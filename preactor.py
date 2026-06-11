"""
Pre-rehearsal orchestrator — runs multiple story versions in parallel async coroutines.

Each version runs in its own coroutine with:
  - Chapter loop (Director → Protagonist → NPCs → Writer)
  - Timeout enforcement
  - Token budget tracking
  - Repeat-action detection
  - Graceful shutdown on Ctrl+C
"""

import asyncio
import random
import time
from typing import Optional

from .models import StoryConfig, StoryState, Chapter, NPC, AgentAction, PreActorResult, StoryMilestone, StoryOutline, UserNPC
from .agents import LLMClient, DirectorAgent, ProtagonistAgent, NPCAgent, NarrativeWriter
from .constraints import (
    TokenBudget,
    RepeatDetector,
    VersionConstraints,
    ShutdownHandler,
    TimeoutTracker,
)
from .utils import logger, moderate_content
from .story_memory import StoryMemoryStore, extract_chapter_memory


# =========================================================================
# Single version runner
# =========================================================================

async def run_version(
    version_id: int,
    config: StoryConfig,
    token_budget: TokenBudget,
    shutdown: ShutdownHandler,
    progress_callback=None,  # async callable(version_id, chapter_num, total_chapters)
) -> StoryState:
    """
    Run a single pre-rehearsal version to completion or until a constraint stops it.

    If progress_callback is provided, it's called after each chapter is written.
    """
    state = StoryState(version_id=version_id, config=config)
    state.protagonist_state["location"] = "故事起始地点"

    # Initialize agents for this version
    client = LLMClient(config)
    director = DirectorAgent(client, config)
    protagonist = ProtagonistAgent(client, config)
    npc_agent = NPCAgent(client, config)
    writer = NarrativeWriter(client, config)

    # Initialize constraint trackers
    # Dynamic timeout based on protagonist mode + quality mode
    timeout_seconds = config.version_timeout_seconds
    if config.quality_mode == "quality":
        timeout_seconds = int(timeout_seconds * 1.5)  # 50% more time for quality
    if config.protagonist_mode == "parallel":
        timeout_seconds = max(timeout_seconds, config.protagonist_count * 600)
    elif config.protagonist_mode == "team":
        timeout_seconds = max(timeout_seconds, 2400)
    logger.info(
        f"[版本 {version_id}] 主角模式: {config.protagonist_mode}, "
        f"NPC模式: {config.npc_mode}, 质量: {config.quality_mode}"
        f"{' (超时=' + str(timeout_seconds) + 's)' if timeout_seconds != config.version_timeout_seconds else ''}"
    )

    constraints = VersionConstraints(
        max_chapters=config.max_chapters,
        max_npcs=config.max_npcs,
        max_tokens_per_call=config.max_tokens_per_call,
        repeat_threshold=config.repeat_similarity_threshold,
    )
    repeat_detector = RepeatDetector(
        threshold=config.repeat_similarity_threshold, window=3
    )
    timeout = TimeoutTracker(timeout_seconds)
    memory_store = StoryMemoryStore()  # RAG story memory for chapter coherence

    logger.info(f"[版本 {version_id}] 预演开始")

    timeout.start()

    # ── Step -2: Seed user-defined NPCs ──
    if config.user_npcs:
        for unp in config.user_npcs:
            if not unp.name.strip():
                continue
            npc = NPC(
                name=unp.name.strip(),
                role=unp.role or "未知",
                personality=unp.personality or "暂无描述",
                goal=unp.backstory[:100] if unp.backstory else "推动剧情发展",
                relevance=unp.relevance or "medium",
                intro_chapter=unp.intro_chapter or 0,
                last_active_chapter=unp.intro_chapter or 0,
            )
            if unp.abilities:
                npc.personality += f" 能力: {unp.abilities}"
            state.active_npcs.append(npc)
            logger.info(
                f"[版本 {version_id}] 用户定义 NPC: {npc.name}"
                f" ({npc.role}, 登场: {'第' + str(unp.intro_chapter) + '章' if unp.intro_chapter else '待定'})"
            )

    # ── Step -1: Generate ending if user didn't provide one ──
    if not config.story_end.strip():
        logger.info(f"[版本 {version_id}] 未指定结局，生成戏剧性结局...")
        try:
            generated = await director.generate_ending(state)
            config.story_end = generated
            logger.info(f"[版本 {version_id}] 自动结局: {generated[:100]}...")
        except Exception as e:
            logger.warning(f"[版本 {version_id}] 结局生成失败: {e}")
            config.story_end = f"{config.protagonist_name}完成了命运的考验，在故事的最后找到了属于自己的归宿。"

    # ── Step 0: Generate multiple story outlines, evaluate, select best ──
    try:
        # Generate 3 outlines from different narrative angles
        logger.info(f"[版本 {version_id}] 生成 3 份不同角度的大纲...")
        outline_tasks = [
            director.generate_outline(state, angle)
            for angle in director.OUTLINE_ANGLES
        ]
        raw_outlines = await asyncio.gather(*outline_tasks, return_exceptions=True)

        # Filter out failed generations
        valid_outlines = []
        for i, ol in enumerate(raw_outlines):
            if isinstance(ol, Exception):
                logger.warning(f"[版本 {version_id}] 大纲 {i+1} 生成失败: {ol}")
            else:
                valid_outlines.append(ol)

        if not valid_outlines:
            logger.warning(f"[版本 {version_id}] 所有大纲生成失败，使用默认大纲")
            valid_outlines = [{
                "total_chapters_hint": config.max_chapters,
                "milestones": [
                    {"description": "故事开始，建立世界观和角色", "target_chapter": 5},
                    {"description": "核心冲突浮现", "target_chapter": 12},
                    {"description": "故事高潮", "target_chapter": 22},
                    {"description": f"达成结局: {config.story_end[:60]}", "target_chapter": config.max_chapters},
                ],
                "_angle": "默认",
            }]

        # Evaluate and select the best outline
        best_idx, verdict = await director.evaluate_outlines(state, valid_outlines)
        best_outline = valid_outlines[best_idx]

        logger.info(
            f"[版本 {version_id}] 🏆 最优大纲: #{best_idx+1} "
            f"({best_outline.get('_angle', '?')}) — {verdict[:80]}"
        )

        # Build StoryOutline from the best
        milestones = [
            StoryMilestone(
                description=m.get("description", ""),
                target_chapter=m.get("target_chapter", 0),
            )
            for m in best_outline.get("milestones", [])
        ]
        state.outline = StoryOutline(
            milestones=milestones,
            total_chapters_hint=best_outline.get("total_chapters_hint", config.max_chapters),
        )
        for m in milestones:
            logger.info(f"  - 第{m.target_chapter}章: {m.description[:60]}")

    except Exception as e:
        logger.warning(f"[版本 {version_id}] 大纲生成流程失败，使用默认节奏: {e}")
        # continue without outline — pacing still works via progress % alone

    try:
        while True:
            # --- Check all constraints ---
            if shutdown.shutdown_requested:
                state.terminated_early = True
                state.termination_reason = "用户手动退出 (Ctrl+C)"
                logger.warning(f"[版本 {version_id}] 收到退出信号，停止预演")
                break

            if timeout.is_expired():
                state.terminated_early = True
                state.termination_reason = f"超时 ({config.version_timeout_seconds}秒)"
                logger.warning(f"[版本 {version_id}] 超时，强制结束")
                break

            if not constraints.can_add_chapter(state.chapter_count):
                state.terminated_early = True
                state.termination_reason = f"达到章节上限 ({config.max_chapters}章)"
                logger.warning(f"[版本 {version_id}] 达到章节上限，标记为未完成")
                break

            # Check global token budget
            if token_budget.remaining is not None and token_budget.remaining < 3000:
                logger.warning(f"[版本 {version_id}] Token 预算即将耗尽，停止预演")
                state.terminated_early = True
                state.termination_reason = "总 token 预算不足"
                break

            # --- Check repeat detection ---
            recent_actions = state.get_last_n_protagonist_actions(3)
            if repeat_detector.check_protagonist(recent_actions):
                logger.info(f"[版本 {version_id}] 检测到主角重复动作，强制引入变化")

                # Force scene switch by adding a random event
                force_event = _generate_random_event(config)
                # We'll inject this into the director's decision

            # --- Step 1: Director decides next chapter ---
            logger.debug(f"[版本 {version_id}] 导演决策第 {state.chapter_count + 1} 章...")
            director_decision = await director.direct(state)

            # If repeat was detected, force scene change
            if repeat_detector.check_protagonist(recent_actions):
                director_decision["chapter_summary"] += (
                    f"\n（系统干预：检测到重复模式，强制加入随机事件：{force_event}）"
                )
                director_decision["scene_setting"] = force_event

            # Check if director says the ending is reached
            if director_decision.get("ending_reached", False):
                logger.info(f"[版本 {version_id}] 导演判定已到达结局！")
                logger.info(
                    f"[版本 {version_id}] 原因: {director_decision.get('ending_reached_reason', '未知')}"
                )

            # --- Step 2: Handle NPC management ---
            npc_instructions = director_decision.get("npc_instructions", {})

            # Remove NPCs
            for npc_name in npc_instructions.get("remove", []):
                _remove_npc(state, npc_name)

            # Introduce new NPCs (respecting the cap)
            for npc_data in npc_instructions.get("introduce", []):
                if constraints.can_add_npc(state.npc_count):
                    new_npc = NPC(
                        name=npc_data.get("name", f"路人_{state.npc_count + 1}"),
                        role=npc_data.get("role", "路人"),
                        personality=npc_data.get("personality", "普通"),
                        goal=npc_data.get("goal", "暂无明确目标"),
                        backstory=npc_data.get("backstory", ""),
                        intro_chapter=state.chapter_count + 1,
                        last_active_chapter=state.chapter_count + 1,
                        relevance=npc_data.get("relevance", "medium"),
                    )
                    state.active_npcs.append(new_npc)
                    logger.info(f"[版本 {version_id}] 新 NPC 登场: {new_npc.name} ({new_npc.role}, 相关性:{new_npc.relevance})")
                else:
                    logger.warning(
                        f"[版本 {version_id}] NPC 已达上限 ({config.max_npcs})，"
                        f"无法引入 {npc_data.get('name', '未知')}"
                    )

            # --- Step 3: Protagonist(s) act based on mode ---
            chapter_summary = director_decision.get("chapter_summary", "")
            scene_setting = director_decision.get("scene_setting", "")

            if config.protagonist_mode == "parallel" and config.protagonist_count > 1:
                # Full parallel: all protagonists act simultaneously
                proto_tasks = [
                    protagonist.act(state, chapter_summary, scene_setting)
                    for _ in range(config.protagonist_count)
                ]
                proto_results = await asyncio.gather(*proto_tasks, return_exceptions=True)
                protagonist_action = next(
                    (r for r in proto_results if isinstance(r, AgentAction)),
                    AgentAction(
                        agent_name=config.protagonist_name, agent_type="protagonist",
                        action="observe", content="主角团观察着周围的情况。",
                    ),
                )
                # Store all actions for the writer
                all_proto_actions = [r for r in proto_results if isinstance(r, AgentAction)]
            elif config.protagonist_mode == "team":
                # Team mode: single call covers all protagonists
                protagonist_action = await protagonist.act(state, chapter_summary, scene_setting)
                all_proto_actions = [protagonist_action]
            else:
                # Spotlight mode (default): one protagonist per chapter
                logger.debug(f"[版本 {version_id}] 主角行动中...")
                protagonist_action = await protagonist.act(state, chapter_summary, scene_setting)
                all_proto_actions = [protagonist_action]

            # --- Step 4: NPCs act based on npc_mode ---
            npc_actions: list[AgentAction] = []
            active_npcs = [n for n in state.active_npcs if n.alive and n.active]

            if config.npc_mode == "narrator":
                # Fastest: no NPC agent calls, narrator handles all NPC描写
                npcs_to_act = []
            elif config.npc_mode == "scene_filter":
                # Only NPCs directly referenced in scene_setting
                scene_npcs = [
                    n for n in active_npcs
                    if n.name in scene_setting or n.name in chapter_summary
                ]
                npcs_to_act = scene_npcs[:2]
            else:
                # parallel mode (default): async batch NPC calls
                high_rel = [n for n in active_npcs if n.relevance == "high"]
                med_rel = [n for n in active_npcs if n.relevance == "medium"]
                max_npc = 3 if config.quality_mode == "quality" else 2
                npcs_to_act = high_rel[:2]
                remaining = [n for n in med_rel if n not in npcs_to_act]
                if remaining:
                    npcs_to_act.append(random.choice(remaining))
                npcs_to_act = npcs_to_act[:max_npc]

            if npcs_to_act:
                # Async parallel: all NPCs act simultaneously
                npc_tasks = [
                    npc_agent.act(npc, state, scene_setting, protagonist_action)
                    for npc in npcs_to_act
                ]
                npc_results = await asyncio.gather(*npc_tasks, return_exceptions=True)
                for result in npc_results:
                    if isinstance(result, AgentAction):
                        npc_actions.append(result)
                        # Track activity
                        for npc in npcs_to_act:
                            if npc.name == result.agent_name:
                                npc.last_active_chapter = state.chapter_count + 1
                                if result.metadata.get("willing_to_exit", False):
                                    _remove_npc(state, npc.name)
                                break
            # Auto-prune stale NPCs (runs regardless of npc_mode)
            _auto_prune_npcs(state, version_id, config)

            # --- Step 5: Generate narrative text with dynamic word target ---
            word_target = _calc_word_target(config, state)
            logger.debug(
                f"[版本 {version_id}] 生成第 {state.chapter_count + 1} 章 "
                f"(目标 {word_target} 字, 已写 {state.total_words} / {config.target_word_count})"
            )
            # Build RAG context for the Writer
            active_npc_names = [n.name for n in state.active_npcs if n.alive and n.active]
            rag_context = memory_store.build_context(
                state.chapter_count + 1, active_npc_names,
            )

            narrative_text, write_tokens = await writer.write_chapter(
                state, director_decision, protagonist_action, npc_actions,
                word_target=word_target,
                rag_context=rag_context,
            )
            state.total_tokens_used += write_tokens

            # --- Step 6: Record the chapter ---
            chapter = Chapter(
                number=state.chapter_count + 1,
                content=narrative_text,
                protagonist_action=protagonist_action,
                npc_actions=npc_actions,
                director_notes=chapter_summary,
                npcs_introduced=[
                    NPC(
                        name=d.get("name", ""),
                        role=d.get("role", ""),
                        personality=d.get("personality", ""),
                        goal=d.get("goal", ""),
                        intro_chapter=state.chapter_count + 1,
                    )
                    for d in npc_instructions.get("introduce", [])
                ],
                npcs_exited=npc_instructions.get("remove", []),
                token_cost=write_tokens,
            )
            state.chapters.append(chapter)

            # Extract RAG memory from this chapter for future coherence
            try:
                mem = await extract_chapter_memory(
                    narrative_text, chapter.number, client,
                )
                memory_store.add(mem)
            except Exception:
                pass  # memory extraction should never block generation

            # Content moderation check
            mod_result = moderate_content(narrative_text)
            if mod_result["flagged"]:
                logger.warning(
                    f"[版本 {version_id}] 第{chapter.number}章内容审核: "
                    f"命中 {len(mod_result['hits'])} 个敏感词 — {mod_result['hits'][:3]}"
                )

            # Update protagonist state based on action
            state.protagonist_state["emotional"] = protagonist_action.emotion

            # ── Track milestone progress ──
            milestone_reached = director_decision.get("milestone_reached", "")
            progress_made = False

            if milestone_reached and state.outline:
                for m in state.outline.milestones:
                    if not m.reached and m.description[:30] in milestone_reached:
                        m.reached = True
                        progress_made = True
                        logger.info(
                            f"[版本 {version_id}] 🎯 里程碑达成: {m.description[:60]} "
                            f"(第{chapter.number}章, 目标第{m.target_chapter}章)"
                        )

            # Also check if chapter number passed any milestone targets without explicit marking
            if state.outline:
                for m in state.outline.milestones:
                    if not m.reached and chapter.number >= m.target_chapter:
                        # Auto-mark if the chapter is somewhat close to the target
                        m.reached = True
                        progress_made = True
                        logger.info(
                            f"[版本 {version_id}] 📍 自动达标: {m.description[:60]} "
                            f"(第{chapter.number}章 >= 目标第{m.target_chapter}章)"
                        )

            # Update stagnation counter
            if progress_made:
                state.chapters_without_progress = 0
            else:
                state.chapters_without_progress += 1

            # Update pacing stage based on outline progress
            if state.outline and state.outline.milestones:
                reached = sum(1 for m in state.outline.milestones if m.reached)
                total = len(state.outline.milestones)
                if reached >= total:
                    state.pacing_stage = "resolution"
                elif reached >= total * 0.5:
                    state.pacing_stage = "confrontation"
                else:
                    state.pacing_stage = "setup"

            # Update token budget
            est_chapter_tokens = write_tokens + 500  # rough estimate for other agent calls
            if not await token_budget.consume(est_chapter_tokens):
                state.terminated_early = True
                state.termination_reason = "总 token 预算已耗尽"
                logger.warning(f"[版本 {version_id}] Token 预算已耗尽")
                break

            logger.info(
                f"[版本 {version_id}] 第{chapter.number}章完成 "
                f"({len(narrative_text)}字, 累计{state.total_tokens_used} tokens)"
            )

            # Notify progress callback
            if progress_callback:
                try:
                    estimated_total = (
                        state.outline.total_chapters_hint
                        if state.outline and state.outline.total_chapters_hint
                        else config.max_chapters
                    )
                    await progress_callback(version_id, chapter.number, estimated_total)
                except Exception:
                    pass  # never let callback failure break generation

            # --- Check ending ---
            if director_decision.get("ending_reached", False):
                state.reached_ending = True
                state.completed = True
                logger.info(f"[版本 {version_id}] 故事自然达到结局！共 {state.chapter_count} 章")
                break

    except asyncio.CancelledError:
        state.terminated_early = True
        state.termination_reason = "任务被取消"
        logger.warning(f"[版本 {version_id}] 任务被取消")

    except Exception as e:
        state.terminated_early = True
        # Give a clear message for common API errors
        err_msg = str(e)
        if "403" in err_msg or "forbidden" in err_msg.lower():
            state.termination_reason = "API 权限不足 (403) — 请检查 API Key 是否有权访问该模型"
        elif "401" in err_msg or "unauthorized" in err_msg.lower():
            state.termination_reason = "API 认证失败 (401) — 请检查 API Key 是否正确"
        elif "429" in err_msg or "rate" in err_msg.lower():
            state.termination_reason = "API 速率限制 (429) — 请稍后重试或降低并行版本数"
        elif "timeout" in err_msg.lower():
            state.termination_reason = f"API 请求超时"
        else:
            state.termination_reason = f"异常: {err_msg[:200]}"
        logger.error(f"[版本 {version_id}] 预演出错: {err_msg[:200]}")

    # Final status
    elapsed = timeout.elapsed()
    if state.reached_ending:
        logger.info(
            f"[版本 {version_id}] ✅ 完成 — {state.chapter_count}章, "
            f"{state.total_words}字, {elapsed:.1f}秒"
        )
    else:
        logger.info(
            f"[版本 {version_id}] ❌ 未完成 — {state.chapter_count}章, "
            f"原因: {state.termination_reason}"
        )

    return state


def _calc_word_target(config: StoryConfig, state: StoryState) -> int:
    """
    Calculate the dynamic per-chapter word target based on:
      - Target total word count
      - Words written so far
      - Estimated chapters remaining (from outline or max_chapters)
    Returns a suggested word count for the next chapter (300~1500 range).
    """
    target_total = config.target_word_count
    written = state.total_words
    current_ch = state.chapter_count
    words_remaining = max(0, target_total - written)

    # Estimate total chapters: prefer outline hint, fallback to max_chapters
    if state.outline and state.outline.total_chapters_hint:
        estimated_total = state.outline.total_chapters_hint
    else:
        estimated_total = config.max_chapters

    chapters_done = current_ch
    chapters_left = max(1, estimated_total - chapters_done)

    # Dynamic target: distribute remaining words evenly
    per_chapter = words_remaining // chapters_left

    # Floor at 300, ceiling at 1500 (Chinese chars per chapter)
    per_chapter = max(300, min(1500, per_chapter))

    # If the story is almost done (last 3 chapters), tighten the range
    if chapters_left <= 3 and words_remaining > 0:
        per_chapter = max(200, words_remaining // chapters_left)

    return per_chapter


def _remove_npc(state: StoryState, npc_name: str):
    """Remove an NPC from the active list and move to graveyard."""
    for npc in state.active_npcs:
        if npc.name == npc_name and npc.alive:
            npc.alive = False
            npc.active = False
            npc.exit_chapter = state.chapter_count + 1
            state.npc_graveyard.append(npc)
            state.active_npcs.remove(npc)
            logger.info(f"  NPC 退场: {npc.name}")
            return

    # Try matching by ID
    for npc in state.active_npcs:
        if npc.id == npc_name:
            npc.alive = False
            npc.active = False
            npc.exit_chapter = state.chapter_count + 1
            state.npc_graveyard.append(npc)
            state.active_npcs.remove(npc)
            logger.info(f"  NPC 退场: {npc.name}")
            return


def _auto_prune_npcs(state: StoryState, version_id: int, config: StoryConfig):
    """
    Automatically remove NPCs that are no longer relevant to the plot.

    Pruning rules:
      - NPCs inactive for > 3 chapters (not acted or mentioned)
      - NPCs with relevance='low' that haven't acted in 2+ chapters
      - Always keep at least 2 NPCs to maintain story richness
    """
    current_chapter = state.chapter_count
    inactive_threshold = 3  # chapters

    candidates = []
    for npc in state.active_npcs:
        if not npc.alive or not npc.active:
            continue
        chapters_inactive = current_chapter - npc.last_active_chapter

        if chapters_inactive > inactive_threshold:
            candidates.append((npc, f"已 {chapters_inactive} 章未活跃"))
        elif npc.relevance == "low" and chapters_inactive >= 2:
            candidates.append((npc, f"低相关性 NPC，{chapters_inactive} 章未活跃"))

    # Keep at least 2 NPCs (unless there are fewer)
    min_keep = min(2, len(state.active_npcs))
    while len(candidates) > 0 and len(state.active_npcs) - len([c for c, _ in candidates]) < min_keep:
        candidates.pop()

    for npc, reason in candidates:
        logger.info(
            f"[版本 {version_id}] 🔄 自动清理 NPC: {npc.name} "
            f"({npc.role}, {reason})"
        )
        npc.exit_chapter = current_chapter
        npc.alive = True   # not dead, just exited the story
        npc.active = False
        state.npc_graveyard.append(npc)
        state.active_npcs.remove(npc)

    if candidates:
        logger.info(
            f"[版本 {version_id}] NPC 阵容: {state.npc_count} 活跃 "
            f"(本次清理 {len(candidates)} 人)"
        )


def _generate_random_event(config: StoryConfig) -> str:
    """Generate a random event to break repetition."""
    events = [
        "突然，一道闪电劈开了天空，暴雨倾盆而下，迫使所有人寻找避难所。",
        "远处传来一声巨响，地面开始震动——有什么巨大的东西正在接近。",
        "一个陌生的信使出现在面前，手中拿着一封火漆密封的信件。",
        "主角突然感到一阵眩晕，一段被遗忘的记忆在脑海中闪现。",
        "一队全副武装的士兵突然出现，封锁了前方的道路。",
        "空气中弥漫起一股奇异的香味，让人感到昏昏欲睡。",
        "一个孩子的尖叫声打破了平静，声音中充满了恐惧。",
    ]
    return random.choice(events)


# =========================================================================
# Orchestrator — manages all parallel versions
# =========================================================================

async def run_pre_actor(config: StoryConfig, shutdown: ShutdownHandler,
                        progress_callback=None) -> PreActorResult:
    """
    Run all pre-rehearsal versions in parallel.

    Returns a PreActorResult with all version states.
    """
    token_budget = TokenBudget(config.total_token_budget)
    start_time = time.time()

    logger.info("=" * 60)
    logger.info(f"  多 Agent 故事预演开始")
    logger.info(f"  并行版本数: {config.num_versions}")
    if config.num_versions > 50:
        logger.warning(
            f"  ⚠️ 高并发模式 ({config.num_versions} 个版本) — "
            f"注意 API 速率限制和 Token 消耗"
        )
    logger.info(f"  总 Token 预算: {config.total_token_budget or '无限制'}")
    logger.info(f"  每版本超时: {config.version_timeout_seconds}秒")
    logger.info(f"  章节上限: {config.max_chapters}章")
    logger.info(f"  NPC 上限: {config.max_npcs}")
    logger.info("=" * 60)

    # Run all versions concurrently
    tasks = []
    for i in range(config.num_versions):
        task = asyncio.create_task(
            run_version(i + 1, config, token_budget, shutdown, progress_callback)
        )
        tasks.append(task)

    # Wait for all to complete (with individual timeouts handled internally)
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Process results
    versions: list[StoryState] = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            logger.error(f"版本 {i + 1} 抛出异常: {result}")
            # Create a failed state
            failed_state = StoryState(version_id=i + 1, config=config)
            failed_state.terminated_early = True
            failed_state.termination_reason = f"异常: {str(result)}"
            versions.append(failed_state)
        else:
            versions.append(result)

    elapsed = time.time() - start_time
    total_tokens = await token_budget.get_used()

    logger.info("=" * 60)
    logger.info(f"  预演完成 — {elapsed:.1f}秒, {total_tokens} tokens")
    completed = sum(1 for v in versions if v.reached_ending)
    logger.info(f"  成功达到结局: {completed}/{len(versions)}")
    logger.info("=" * 60)

    return PreActorResult(
        config=config,
        versions=versions,
        evaluations=[],  # filled in by evaluator
        winning_version_id=-1,  # filled in by evaluator
        total_tokens_used=total_tokens,
        time_elapsed_seconds=elapsed,
    )
