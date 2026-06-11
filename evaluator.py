"""
Evaluation and version selection — scores each completed pre-rehearsal version
on 4 dimensions and selects the best one (optionally letting user choose if close).
"""

from typing import Optional

from .models import StoryConfig, StoryState, EvalResult, PreActorResult
from .agents import LLMClient, EvaluatorAgent
from .utils import logger


async def evaluate_versions(result: PreActorResult, shutdown, interactive: bool = True) -> PreActorResult:
    """
    Evaluate all completed versions and select the winner.

    If `interactive` is True and scores are close (< 5%), prompt the user
    to choose. Otherwise auto-select the highest-scoring version.
    """
    config = result.config
    client = LLMClient(config)
    evaluator = EvaluatorAgent(client, config)

    completed_versions = [v for v in result.versions if v.reached_ending and not v.terminated_early]
    incomplete_versions = [v for v in result.versions if not v.reached_ending or v.terminated_early]

    logger.info("-" * 40)
    logger.info(f"  评估阶段: {len(completed_versions)} 个完成版本, "
                f"{len(incomplete_versions)} 个未完成版本")
    logger.info("-" * 40)

    evaluations: list[EvalResult] = []

    # Mark incomplete versions
    for v in incomplete_versions:
        eval_result = EvalResult(
            version_id=v.version_id,
            total_score=0.0,
            evaluator_notes=f"未完成: {v.termination_reason}",
            is_complete=False,
        )
        evaluations.append(eval_result)
        logger.info(f"  [版本 {v.version_id}] 跳过评估 — 未完成 ({v.termination_reason})")

    # Evaluate completed versions
    for v in completed_versions:
        if shutdown.shutdown_requested:
            break

        logger.info(f"  [版本 {v.version_id}] 评估中...")
        eval_result = await evaluator.evaluate(v)
        evaluations.append(eval_result)

        logger.info(
            f"  [版本 {v.version_id}] 评分: "
            f"戏剧{ eval_result.dramatic_tension:.1f} "
            f"成长{ eval_result.character_growth:.1f} "
            f"逻辑{ eval_result.logic_consistency:.1f} "
            f"结局{ eval_result.ending_alignment:.1f} "
            f"→ 总分 {eval_result.total_score:.2f}"
        )

    result.evaluations = evaluations

    # Select winner
    if not completed_versions:
        logger.warning("⚠ 没有版本成功达到结局！将选择最接近完成的版本。")
        # Pick the version with most chapters as fallback
        if result.versions:
            best = max(result.versions, key=lambda v: v.chapter_count)
            result.winning_version_id = best.version_id
            result.user_selected = False
        else:
            logger.error("没有可用的版本！")
            result.winning_version_id = -1
        return result

    # Sort by total score
    completed_evals = [e for e in evaluations if e.is_complete]
    completed_evals.sort(key=lambda e: e.total_score, reverse=True)

    if len(completed_evals) == 1:
        result.winning_version_id = completed_evals[0].version_id
        logger.info(f"\n🏆 唯一完成版本 [版本 {result.winning_version_id}] 自动当选！")
        return result

    # Check if top scores are close (< 5% difference)
    top_score = completed_evals[0].total_score
    second_score = completed_evals[1].total_score

    if top_score > 0 and (top_score - second_score) / top_score < 0.05:
        # Scores are close
        if interactive:
            # CLI mode — ask user to choose
            logger.info("\n" + "=" * 40)
            logger.info("  多个版本分数接近，请用户选择：")
            logger.info("=" * 40)

            for i, ev in enumerate(completed_evals[:5], 1):
                v = next(v for v in result.versions if v.version_id == ev.version_id)
                logger.info(
                    f"  [{i}] 版本 {ev.version_id}: 总分 {ev.total_score:.2f} "
                    f"({v.chapter_count}章, {v.total_words}字)"
                )
                logger.info(f"      戏剧{ev.dramatic_tension:.1f} "
                            f"成长{ev.character_growth:.1f} "
                            f"逻辑{ev.logic_consistency:.1f} "
                            f"结局{ev.ending_alignment:.1f}")
                logger.info(f"      摘要: {v.chapters[-1].content[:100] if v.chapters else '无'}...")

            choice = await _user_select(completed_evals, shutdown)
            result.winning_version_id = choice
            result.user_selected = True
        else:
            # Web UI mode — auto-select top scorer, log alternatives
            result.winning_version_id = completed_evals[0].version_id
            result.user_selected = False
            logger.info("\n" + "=" * 40)
            logger.info("  多个版本分数接近，Web 模式自动选择最高分：")
            logger.info("=" * 40)
            for i, ev in enumerate(completed_evals[:3], 1):
                tag = " 🏆" if i == 1 else ""
                logger.info(
                    f"  [{i}] 版本 {ev.version_id}: 总分 {ev.total_score:.2f} "
                    f"(戏剧{ev.dramatic_tension:.1f} 成长{ev.character_growth:.1f} "
                    f"逻辑{ev.logic_consistency:.1f} 结局{ev.ending_alignment:.1f}){tag}"
                )
    else:
        result.winning_version_id = completed_evals[0].version_id
        result.user_selected = False
        logger.info(f"\n🏆 最优版本: [版本 {result.winning_version_id}] "
                    f"总分 {top_score:.2f}")

    return result


async def _user_select(
    ranked_evals: list[EvalResult], shutdown
) -> int:
    """Prompt user to select a version interactively (async-safe)."""
    import asyncio

    while not shutdown.shutdown_requested:
        try:
            choice = input(f"\n  请选择版本 (1-{len(ranked_evals)}): ").strip()
            idx = int(choice) - 1
            if 0 <= idx < len(ranked_evals):
                return ranked_evals[idx].version_id
            print(f"  无效选择，请输入 1-{len(ranked_evals)} 之间的数字")
        except ValueError:
            print(f"  请输入数字")
        except (EOFError, KeyboardInterrupt):
            # If we can't get input, default to top
            return ranked_evals[0].version_id

    return ranked_evals[0].version_id
