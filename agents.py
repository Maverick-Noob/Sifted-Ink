"""
LLM Agent wrappers — unified interface for all major LLM providers.

Supported providers:
  Anthropic (Claude), OpenAI (GPT-4/GPT-4o), Google (Gemini),
  DeepSeek, Moonshot, Zhipu (GLM), Qwen (Tongyi), Baichuan,
  MiniMax, Grok (xAI), Mistral, Cohere, + any OpenAI-compatible API.

Each agent function:
  1. Builds a system + user prompt from templates
  2. Calls the LLM API via the unified LLMClient
  3. Extracts structured JSON from the response
  4. Returns a typed result (AgentAction, dict, etc.)
"""

import json
import re
from typing import Optional

from .models import StoryConfig, StoryState, AgentAction, NPC, Chapter, EvalResult
from .prompts import (
    DIRECTOR_SYSTEM_PROMPT,
    DIRECTOR_OUTLINE_PROMPT,
    OUTLINE_EVALUATOR_PROMPT,
    STORY_NAMING_PROMPT,
    ENDING_GENERATION_PROMPT,
    PROTAGONIST_SYSTEM_PROMPT,
    NPC_SYSTEM_PROMPT,
    EVALUATOR_SYSTEM_PROMPT,
)
from .utils import extract_json, logger, build_style_prompt, build_npc_name_instruction


# =========================================================================
# Provider Registry — all supported LLM providers
# =========================================================================

PROVIDER_REGISTRY: dict[str, dict] = {
    # ── First-party SDK providers ──
    "anthropic": {
        "name": "Anthropic (Claude)",
        "sdk": "anthropic",
        "default_model": "claude-sonnet-4-6",
        "base_url": None,
        "api_key_env": "ANTHROPIC_API_KEY",
        "models": ["claude-opus-4-8", "claude-sonnet-4-6", "claude-haiku-4-5",
                    "claude-3-5-sonnet-20241022", "claude-3-5-haiku-20241022"],
    },
    "openai": {
        "name": "OpenAI (GPT-4/GPT-4o)",
        "sdk": "openai",
        "default_model": "gpt-4o",
        "base_url": None,
        "api_key_env": "OPENAI_API_KEY",
        "models": ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "o1", "o3-mini"],
    },
    "google": {
        "name": "Google (Gemini)",
        "sdk": "google",
        "default_model": "gemini-2.5-flash",
        "base_url": None,
        "api_key_env": "GOOGLE_API_KEY",
        "models": ["gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.0-flash"],
    },
    # ── OpenAI-compatible providers (use openai SDK with custom base_url) ──
    "deepseek": {
        "name": "DeepSeek",
        "sdk": "openai",
        "default_model": "deepseek-chat",
        "base_url": "https://api.deepseek.com/v1",
        "api_key_env": "DEEPSEEK_API_KEY",
        "models": ["deepseek-chat", "deepseek-reasoner"],
    },
    "moonshot": {
        "name": "Moonshot (Kimi)",
        "sdk": "openai",
        "default_model": "moonshot-v1-8k",
        "base_url": "https://api.moonshot.cn/v1",
        "api_key_env": "MOONSHOT_API_KEY",
        "models": ["moonshot-v1-8k", "moonshot-v1-32k", "moonshot-v1-128k"],
    },
    "zhipu": {
        "name": "智谱 AI (GLM)",
        "sdk": "openai",
        "default_model": "glm-4-plus",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "api_key_env": "ZHIPU_API_KEY",
        "models": ["glm-4-plus", "glm-4-flash", "glm-4-long"],
    },
    "qwen": {
        "name": "阿里通义千问 (Qwen)",
        "sdk": "openai",
        "default_model": "qwen-plus",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "api_key_env": "DASHSCOPE_API_KEY",
        "models": ["qwen-plus", "qwen-max", "qwen-turbo", "qwen3-235b-a22b"],
    },
    "baichuan": {
        "name": "百川 (Baichuan)",
        "sdk": "openai",
        "default_model": "Baichuan4",
        "base_url": "https://api.baichuan-ai.com/v1",
        "api_key_env": "BAICHUAN_API_KEY",
        "models": ["Baichuan4", "Baichuan4-Turbo"],
    },
    "minimax": {
        "name": "MiniMax",
        "sdk": "openai",
        "default_model": "abab6.5s-chat",
        "base_url": "https://api.minimax.chat/v1",
        "api_key_env": "MINIMAX_API_KEY",
        "models": ["abab6.5s-chat", "abab6.5t-chat"],
    },
    "grok": {
        "name": "xAI (Grok)",
        "sdk": "openai",
        "default_model": "grok-3",
        "base_url": "https://api.x.ai/v1",
        "api_key_env": "XAI_API_KEY",
        "models": ["grok-3", "grok-3-mini"],
    },
    "mistral": {
        "name": "Mistral AI",
        "sdk": "openai",
        "default_model": "mistral-large-latest",
        "base_url": "https://api.mistral.ai/v1",
        "api_key_env": "MISTRAL_API_KEY",
        "models": ["mistral-large-latest", "mistral-medium-latest", "mistral-small-latest"],
    },
    "cohere": {
        "name": "Cohere",
        "sdk": "openai",
        "default_model": "command-r-plus",
        "base_url": "https://api.cohere.ai/v1",
        "api_key_env": "COHERE_API_KEY",
        "models": ["command-r-plus", "command-r"],
    },
    "custom": {
        "name": "自定义 OpenAI 兼容接口",
        "sdk": "openai",
        "default_model": "",
        "base_url": "",  # user must specify
        "api_key_env": "",
        "models": [],
    },
}


def get_provider_info(provider: str) -> dict | None:
    """Get provider registry entry."""
    return PROVIDER_REGISTRY.get(provider)


def list_providers() -> list[str]:
    """List all supported provider keys."""
    return list(PROVIDER_REGISTRY.keys())


def resolve_api_key(provider: str, explicit_key: str = "") -> str:
    """
    Resolve API key: explicit > provider-specific env var > SIFTED_INK_API_KEY.
    """
    import os
    if explicit_key:
        return explicit_key
    info = PROVIDER_REGISTRY.get(provider, {})
    env_var = info.get("api_key_env", "")
    if env_var:
        key = os.environ.get(env_var, "")
        if key:
            return key
    return os.environ.get("SIFTED_INK_API_KEY", "")


# =========================================================================
# Unified API Client
# =========================================================================

class LLMClient:
    """Unified LLM client that supports all major providers via provider registry."""

    def __init__(self, config: StoryConfig):
        self.config = config
        self.provider = config.api_provider
        self.max_tokens_per_call = config.max_tokens_per_call

        # Resolve provider info from registry
        info = get_provider_info(self.provider)
        if info is None:
            raise ValueError(
                f"不支持的 API 提供商: {self.provider}\n"
                f"支持的提供商: {', '.join(list_providers())}"
            )
        self._provider_info = info

        # Resolve API key: explicit > provider env > generic env
        self.api_key = resolve_api_key(self.provider, config.api_key)

        # Resolve model
        self.model = config.model or info.get("default_model", "")
        if not self.model:
            raise ValueError(f"提供商 '{self.provider}' 需要指定 model")

        # Resolve base URL
        self.base_url = config.api_base_url or info.get("base_url") or ""

        # Lazy-init
        self._client = None

    @property
    def provider_name(self) -> str:
        return self._provider_info.get("name", self.provider)

    @property
    def sdk_type(self) -> str:
        return self._provider_info.get("sdk", "openai")

    def _ensure_client(self):
        """Lazy-init the API client based on SDK type."""
        if self._client is not None:
            return

        sdk = self.sdk_type

        if sdk == "anthropic":
            try:
                import anthropic
            except ImportError:
                raise ImportError("需要安装 anthropic: pip install anthropic")
            self._client = anthropic.Anthropic(api_key=self.api_key)

        elif sdk == "openai":
            try:
                import openai
            except ImportError:
                raise ImportError("需要安装 openai: pip install openai")
            kwargs = {"api_key": self.api_key}
            if self.base_url:
                kwargs["base_url"] = self.base_url
            self._client = openai.OpenAI(**kwargs)

        elif sdk == "google":
            try:
                import google.generativeai as genai
            except ImportError:
                raise ImportError(
                    "需要安装 google-generativeai: pip install google-generativeai"
                )
            genai.configure(api_key=self.api_key)
            self._client = genai

        else:
            raise ValueError(f"未知的 SDK 类型: {sdk}")

    async def call(
        self,
        system_prompt: str,
        user_message: str,
        max_tokens: Optional[int] = None,
        temperature: float = 0.8,
    ) -> tuple[str, int]:
        """Call the LLM API. Returns (response_text, tokens_used)."""
        self._ensure_client()
        max_tok = min(max_tokens or self.max_tokens_per_call, self.max_tokens_per_call)

        sdk = self.sdk_type
        if sdk == "anthropic":
            return await self._call_anthropic(system_prompt, user_message, max_tok, temperature)
        elif sdk == "openai":
            return await self._call_openai(system_prompt, user_message, max_tok, temperature)
        elif sdk == "google":
            return await self._call_google(system_prompt, user_message, max_tok, temperature)
        else:
            raise RuntimeError(f"未实现的 SDK: {sdk}")

    async def _call_anthropic(
        self, system_prompt: str, user_message: str, max_tokens: int, temperature: float
    ) -> tuple[str, int]:
        """Call Anthropic Claude API."""
        import asyncio

        def _sync_call():
            response = self._client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                temperature=temperature,
                system=system_prompt,
                messages=[{"role": "user", "content": user_message}],
            )
            return response

        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(None, _sync_call)

        try:
            text = response.content[0].text
        except (IndexError, AttributeError):
            text = ""
        try:
            tokens = response.usage.input_tokens + response.usage.output_tokens
        except AttributeError:
            tokens = 0
        return text, tokens

    async def _call_openai(
        self, system_prompt: str, user_message: str, max_tokens: int, temperature: float
    ) -> tuple[str, int]:
        """Call OpenAI-compatible API (OpenAI, DeepSeek, Moonshot, Zhipu, Qwen, etc.)."""
        import asyncio

        def _sync_call():
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ]
            response = self._client.chat.completions.create(
                model=self.model,
                max_tokens=max_tokens,
                temperature=temperature,
                messages=messages,
            )
            return response

        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(None, _sync_call)

        try:
            text = response.choices[0].message.content or ""
        except (IndexError, AttributeError):
            text = ""
        try:
            tokens = response.usage.total_tokens
        except AttributeError:
            tokens = 0
        return text, tokens

    async def _call_google(
        self, system_prompt: str, user_message: str, max_tokens: int, temperature: float
    ) -> tuple[str, int]:
        """Call Google Gemini API."""
        import asyncio

        def _sync_call():
            # Combine system prompt into user message (Gemini convention)
            combined = f"[System Instructions]\n{system_prompt}\n\n[User Message]\n{user_message}"

            model = self._client.GenerativeModel(
                model_name=self.model,
                generation_config={
                    "temperature": temperature,
                    "max_output_tokens": max_tokens,
                },
            )
            response = model.generate_content(combined)
            return response

        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(None, _sync_call)

        try:
            text = response.text or ""
        except (AttributeError, ValueError):
            text = ""
        try:
            tokens = response.usage_metadata.total_token_count
        except AttributeError:
            tokens = max(len(text) // 2, 1) if text else 0
        return text, tokens


# =========================================================================
# Director Agent
# =========================================================================

class DirectorAgent:
    """叙事导演 — orchestrates chapter flow and NPC management with pacing."""

    def __init__(self, client: LLMClient, config: StoryConfig):
        self.client = client
        self.config = config

    # ── Outline generation ────────────────────────────────────────────

    # Diversity seeds for generating different outline perspectives
    OUTLINE_ANGLES = [
        {"angle": "角色驱动", "hint": "从主角的内心成长和情感变化出发来设计情节节点"},
        {"angle": "悬念反转", "hint": "侧重设计出人意料的情节反转和悬疑推进"},
        {"angle": "史诗冒险", "hint": "强调宏大的世界观探索和史诗级的冲突对抗"},
    ]

    async def generate_outline(self, state: StoryState, angle: dict | None = None) -> dict:
        """
        Generate a story outline before the first chapter.
        If `angle` is provided, use it to bias the outline toward a specific style.
        """
        system = DIRECTOR_OUTLINE_PROMPT.format(
            max_chapters=self.config.max_chapters,
            story_end=self.config.story_end,
            story_end_short=self.config.story_end[:80],
        )

        angle_hint = ""
        if angle:
            angle_hint = f"\n## 叙事角度偏好\n请从「{angle['angle']}」的角度来设计大纲：{angle['hint']}"

        user = f"""## 故事信息
- 主角: {self.config.protagonist_name} ({self.config.protagonist_traits})
- 世界背景: {self.config.world_setting}
- 故事开头: {self.config.story_start}
- 目标结局: {self.config.story_end}
- 章节预算: {self.config.max_chapters} 章
{angle_hint}
请为这个故事生成一份 4~6 个节点的情节大纲。"""

        text, tokens = await self.client.call(
            system, user, temperature=0.8 if angle else 0.7,
        )
        state.total_tokens_used += tokens

        outline_data = extract_json(text)
        if outline_data is None:
            logger.warning(f"大纲生成失败，使用默认大纲" +
                          (f" (角度: {angle['angle']})" if angle else ""))
            outline_data = {
                "total_chapters_hint": self.config.max_chapters,
                "milestones": [
                    {"description": "故事开始，建立世界观和角色", "target_chapter": 5},
                    {"description": "核心冲突浮现", "target_chapter": 12},
                    {"description": "故事高潮", "target_chapter": 22},
                    {"description": f"达成结局: {self.config.story_end[:60]}", "target_chapter": self.config.max_chapters},
                ],
            }

        outline_data["_angle"] = angle["angle"] if angle else "default"
        return outline_data

    # ── Outline evaluation ────────────────────────────────────────────

    async def evaluate_outlines(
        self, state: StoryState, outlines: list[dict],
    ) -> tuple[int, str]:
        """
        Score multiple outlines and select the best one.
        Returns (best_index, verdict_text).
        """
        if len(outlines) <= 1:
            return 0, "仅有一份大纲，自动选择。"

        # Format outlines for evaluation
        outlines_text = ""
        for i, ol in enumerate(outlines):
            angle_tag = ol.get("_angle", f"版本{i+1}")
            outlines_text += f"\n### 大纲 {i+1}（{angle_tag}）\n"
            outlines_text += f"规划章数: {ol.get('total_chapters_hint', '?')}\n"
            for j, m in enumerate(ol.get("milestones", [])):
                outlines_text += f"  节点{j+1}（第{m.get('target_chapter', '?')}章）: {m.get('description', '?')}\n"

        system = OUTLINE_EVALUATOR_PROMPT.format(
            protagonist_name=self.config.protagonist_name,
            protagonist_traits=self.config.protagonist_traits,
            story_end=self.config.story_end,
            outlines_text=outlines_text,
        )

        user = f"请从以上 {len(outlines)} 份大纲中选出最优的一份。"

        text, tokens = await self.client.call(system, user, temperature=0.3)
        state.total_tokens_used += tokens

        result = extract_json(text)
        if result is None:
            logger.warning("大纲评估失败，使用第一份大纲")
            return 0, "评估失败，默认选择第一份。"

        best_idx = result.get("best_index", 0)
        verdict = result.get("overall_verdict", "")

        # Log rankings
        for r in result.get("rankings", []):
            logger.info(
                f"  大纲 {r.get('index', '?')+1}: "
                f"连贯性{r.get('coherence', 0):.1f} "
                f"可达性{r.get('reachability', 0):.1f} "
                f"戏剧性{r.get('drama', 0):.1f} "
                f"角色弧{r.get('character_arc', 0):.1f} "
                f"— {r.get('reason', '')}"
            )

        return best_idx, verdict

    # ── Story naming & summarization ─────────────────────────────────

    async def name_and_summarize(
        self, state: StoryState, story_text: str,
    ) -> dict:
        """
        After the story is complete: generate a plot summary, 10 candidate
        names, and select the best one. Always returns a dict.
        """
        protagonist = self.config.protagonist_name
        default_result = {
            "best_name": f"{protagonist}的传奇",
            "plot_summary": "",
            "candidate_names": [],
            "best_name_reason": "",
            "style_tags": [],
        }

        # Guard: skip if story text too short
        if not story_text or len(story_text.strip()) < 100:
            logger.warning("小说文本过短，跳过 AI 命名")
            return default_result

        # Truncate story if too long
        if len(story_text) > 8000:
            story_snippet = story_text[:4000] + "\n\n...\n\n" + story_text[-4000:]
        else:
            story_snippet = story_text

        system = STORY_NAMING_PROMPT.format(
            protagonist_name=protagonist,
            world_setting=self.config.world_setting,
            story_end=self.config.story_end,
            story_text=story_snippet,
        )
        user = "请为这部小说生成情节摘要、10 个候选书名，并选出最佳。"

        content = ""  # initialized for error logging
        try:
            text, tokens = await self.client.call(system, user, temperature=0.85)
            state.total_tokens_used += tokens
            content = text  # save for error logging

            # Parse response — extract_json handles json5 and markdown fences
            result = extract_json(text)
            if not isinstance(result, dict):
                logger.warning(
                    f"命名 API 返回非字典类型: {type(result).__name__}，使用默认值"
                )
                return default_result

            # Build safe result with type guards on every field
            best = result.get("best_name", default_result["best_name"])
            if not isinstance(best, str) or not best.strip():
                best = default_result["best_name"]
            best = re.sub(r'[\\/*?:"<>|]', '_', str(best))[:50]

            plot = result.get("plot_summary", "")
            if not isinstance(plot, str):
                plot = ""

            names = result.get("candidate_names", [])
            if not isinstance(names, list):
                names = []
            names = [str(n) for n in names if isinstance(n, str)][:10]

            reason = result.get("best_name_reason", "")
            if not isinstance(reason, str):
                reason = ""

            tags = result.get("style_tags", [])
            if not isinstance(tags, list):
                tags = []

            logger.info(f"📖 故事命名: 《{best}》")
            if names:
                logger.info(f"   候选: {', '.join(names[:5])}")

            return {
                "best_name": best,
                "plot_summary": plot,
                "candidate_names": names,
                "best_name_reason": reason,
                "style_tags": tags,
            }

        except Exception as e:
            preview = content[:200] if content else "N/A"
            logger.warning(f"故事命名失败: {e} (content_preview={preview})")
            return default_result

    # ── Ending generation ────────────────────────────────────────────

    async def generate_ending(self, state: StoryState) -> str:
        """
        Auto-generate a dramatic ending when the user didn't specify one.
        Returns the generated ending text.
        """
        system = ENDING_GENERATION_PROMPT.format(
            protagonist_name=self.config.protagonist_name,
            protagonist_traits=self.config.protagonist_traits,
            world_setting=self.config.world_setting,
            story_start=self.config.story_start,
        )

        user = "请为这个故事设计一个有戏剧性的结局。"

        text, tokens = await self.client.call(system, user, temperature=0.9)
        state.total_tokens_used += tokens

        result = extract_json(text)
        if result is None or not isinstance(result, dict):
            logger.warning("结局生成失败，使用默认结局")
            return f"{self.config.protagonist_name}最终完成了自己的使命，在经历了重重考验后迎来了命运的转折。"

        ending = result.get("generated_ending", "")
        style = result.get("ending_style", "未知")
        reason = result.get("reason", "")

        logger.info(f"🎭 自动生成结局（{style}）: {ending[:100]}...")
        if reason:
            logger.info(f"   理由: {reason[:80]}")

        return ending

    # ── Pacing calculation ────────────────────────────────────────────

    def _calc_pacing(self, state: StoryState) -> dict:
        """Calculate pacing metadata for the current chapter."""
        chapter = state.chapter_count + 1  # next chapter
        max_ch = self.config.max_chapters
        progress = chapter / max_ch

        # Determine pacing stage and pressure
        if progress < 0.30:
            stage = "铺垫期"
            guidance = "自由展开故事，建立世界观和角色关系，为后续冲突埋下伏笔"
            pressure_label = "低压 — 正常推进"
            pressure_emoji = "🟢"
        elif progress < 0.50:
            stage = "发展期"
            guidance = "必须引入核心矛盾，加速主线推进，开始收束不必要的支线"
            pressure_label = "中压 — 需要推进主线"
            pressure_emoji = "🟡"
        elif progress < 0.75:
            stage = "高潮期"
            guidance = "全力向结局冲刺！禁止开新支线，每个场景都必须推动主线向结局前进"
            pressure_label = "高压 — 必须加速！"
            pressure_emoji = "🟠"
        else:
            stage = "收束期"
            guidance = "🚨 只写结局必要的场景！禁止新角色！禁止新支线！每章都必须大幅推进结局！"
            pressure_label = "临界 — 立即向结局冲刺！！"
            pressure_emoji = "🔴"

        chapters_remaining = max_ch - chapter + 1

        # Word budget awareness
        word_budget_hint = ""
        if self.config.target_word_count <= 5000:
            written = state.total_words
            remaining_words = max(0, self.config.target_word_count - written)
            word_budget_hint = (
                f"\n**字数预算**：目标 {self.config.target_word_count} 字，"
                f"已写 {written} 字，剩余 {remaining_words} 字。"
                f"请紧缩篇幅，每章控制在 {max(100, remaining_words // max(chapters_remaining, 1))} 字以内。"
            )

        # Next milestone
        next_milestone_text = "（无大纲）"
        if state.outline and state.outline.milestones:
            for m in state.outline.milestones:
                if not m.reached:
                    next_milestone_text = (
                        f"**下一个必须达成的节点**（预计第 {m.target_chapter} 章）：{m.description}\n"
                        f"你当前在第 {chapter} 章，{'已经超过预期章数，请加速！' if chapter > m.target_chapter else f'还有 {m.target_chapter - chapter} 章到达此节点'}"
                    )
                    break

        # Stagnation warning
        stagnation_warning = ""
        if state.chapters_without_progress >= 3:
            stagnation_warning = (
                f"⚠️ 警告：已连续 {state.chapters_without_progress} 章没有达到任何里程碑！"
                f"本章必须发生一个重大事件来推动故事！"
            )

        return {
            "max_npcs": self.config.max_npcs,
            "current_chapter": chapter,
            "max_chapters": max_ch,
            "chapters_remaining": chapters_remaining,
            "progress_pct": f"{progress:.0%}",
            "pacing_stage": stage,
            "pacing_guidance": guidance,
            "pressure_label": pressure_label,
            "pressure_emoji": pressure_emoji,
            "next_milestone_text": next_milestone_text,
            "stagnation_warning": stagnation_warning,
            "word_budget_hint": word_budget_hint,
        }

    # ── Prompt builders ───────────────────────────────────────────────

    def _build_system_prompt(self, pacing: dict) -> str:
        # Multi-protagonist guidance
        if self.config.protagonist_count > 1:
            order_hint = ""
            if self.config.protagonist_order:
                names = [n.strip() for n in self.config.protagonist_order.split(",") if n.strip()]
                if names:
                    order_hint = f" 登场顺序: {' → '.join(names)}。"

            if self.config.protagonist_mode == "spotlight":
                multi_guidance = (
                    f"本故事有 {self.config.protagonist_count} 位主角。"
                    f"每章选择 2-3 位作为焦点，其余主角作为背景。"
                    f"章间轮换焦点以确保每位主角都有发展弧线。"
                    f"{order_hint}"
                )
            elif self.config.protagonist_mode == "team":
                multi_guidance = (
                    f"本故事有 {self.config.protagonist_count} 位主角组成的团队。"
                    f"每章以团队整体行动为主，通过对话和互动展现各角色特点。"
                )
            else:
                multi_guidance = (
                    f"本故事有 {self.config.protagonist_count} 位主角。"
                    f"确保每位主角在每章都有独立的行动和对话。"
                )
        else:
            multi_guidance = ""
        pacing["multi_protagonist_guidance"] = multi_guidance

        prompt = DIRECTOR_SYSTEM_PROMPT.format(**pacing)
        # Append NPC name style instruction if configured
        name_instruction = build_npc_name_instruction(self.config.npc_name_style)
        if name_instruction:
            prompt += "\n" + name_instruction
        return prompt

    def _build_user_message(self, state: StoryState) -> str:
        """Build the user message describing current story state."""
        prev_chapters = ""
        for ch in state.chapters[-3:]:
            # Show chapter ENDING (last 200 chars) so Director knows where story left off
            ending = ch.content[-200:] if ch.content else ""
            prev_chapters += f"第{ch.number}章结尾: {ending}\n"

        # Separate user-defined NPCs for special highlighting
        user_npc_names = {unp.name.strip() for unp in self.config.user_npcs if unp.name.strip()}
        npc_list = ", ".join(
            f"{n.name}({n.role}, 目标:{n.goal}"
            f"{' [用户指定]' if n.name in user_npc_names else ''})"
            for n in state.active_npcs if n.alive and n.active
        ) or "无"

        # Outline context
        outline_text = ""
        if state.outline and state.outline.milestones:
            outline_text = "## 故事大纲\n"
            for m in state.outline.milestones:
                status = "✅" if m.reached else "⬜"
                outline_text += f"- {status} 第{m.target_chapter}章: {m.description}\n"

        return f"""## 故事全局信息
- 主角: {self.config.protagonist_name} ({self.config.protagonist_traits})
- 世界背景: {self.config.world_setting}
- 故事开头: {self.config.story_start}
- 目标结局: {self.config.story_end}

{outline_text}
## 当前进度
- 当前主角状态: {json.dumps(state.protagonist_state, ensure_ascii=False)}
- 当前活动 NPC: {npc_list}
- NPC 总数: {state.npc_count} / {self.config.max_npcs}

## 最近章节摘要
{prev_chapters or "（尚无章节，这是故事开始）"}

## 上一章内容
{state.chapters[-1].content if state.chapters else state.config.story_start}

请基于以上信息，为第 {state.chapter_count + 1} 章做出导演决策。"""

    async def direct(self, state: StoryState) -> dict:
        """Make a directing decision for the next chapter."""
        pacing = self._calc_pacing(state)
        system = self._build_system_prompt(pacing)
        user = self._build_user_message(state)

        text, tokens = await self.client.call(system, user, temperature=0.9)
        state.total_tokens_used += tokens

        result = extract_json(text)
        if result is None:
            logger.warning(f"导演 Agent 返回了无法解析的 JSON，使用默认决策。原文: {text[:200]}")
            result = {
                "chapter_summary": "故事继续推进，主角面对新的挑战。",
                "scene_setting": "未知场景",
                "branch_choice": "A",
                "branch_options": [{"id": "A", "description": "继续当前主线"}],
                "npc_instructions": {"introduce": [], "remove": []},
                "ending_reached": False,
                "ending_reached_reason": "",
                "milestone_reached": "",
            }

        return result


# =========================================================================
# Protagonist Agent
# =========================================================================

class ProtagonistAgent:
    """主角 Agent — makes autonomous decisions and dialogue."""

    def __init__(self, client: LLMClient, config: StoryConfig):
        self.client = client
        self.config = config

    def _build_system_prompt(self, state: StoryState, scene_setting: str) -> str:
        # Build story context from recent chapters
        context = ""
        for ch in state.chapters[-2:]:
            context += f"第{ch.number}章摘要: {ch.director_notes or ch.content[:150]}\n"

        return PROTAGONIST_SYSTEM_PROMPT.format(
            protagonist_traits=f"姓名: {self.config.protagonist_name}\n{self.config.protagonist_traits}",
            world_setting=self.config.world_setting,
            story_end=self.config.story_end,
            story_context=context or "故事刚刚开始",
            scene_setting=scene_setting,
        )

    def _build_user_message(self, state: StoryState, chapter_summary: str, scene_setting: str) -> str:
        return f"""## 本章导演指示
{chapter_summary}

## 当前场景
{scene_setting}

## 你的当前状态
- 情绪: {state.protagonist_state.get('emotional', 'neutral')}
- 体力: {state.protagonist_state.get('physical', 'healthy')}
- 位置: {state.protagonist_state.get('location', '未知')}
- 能力: {', '.join(state.protagonist_state.get('abilities_gained', [])) or '初始能力'}
- 重要物品: {', '.join(state.protagonist_state.get('key_items', [])) or '无'}

## 场景中的其他角色
{self._format_npcs(state)}

请做出你的行动选择。"""

    def _format_npcs(self, state: StoryState) -> str:
        active = [n for n in state.active_npcs if n.alive and n.active]
        if not active:
            return "当前场景中没有其他角色。"
        lines = []
        for n in active:
            lines.append(f"- {n.name}（{n.role}，性格：{n.personality}，目标：{n.goal}）")
        return "\n".join(lines)

    async def act(self, state: StoryState, chapter_summary: str, scene_setting: str) -> AgentAction:
        """Protagonist makes an action decision."""
        system = self._build_system_prompt(state, scene_setting)
        user = self._build_user_message(state, chapter_summary, scene_setting)

        text, tokens = await self.client.call(system, user, temperature=0.85)
        state.total_tokens_used += tokens

        result = extract_json(text)
        if result is None:
            logger.warning(f"主角 Agent 返回了无法解析的 JSON。原文: {text[:200]}")
            result = {
                "action": "internal_monologue",
                "content": "面对着未知的局面，心中思绪万千。",
                "emotion": "neutral",
                "target": "",
                "inner_thought": "接下来该怎么办？",
            }

        return AgentAction(
            agent_name=self.config.protagonist_name,
            agent_type="protagonist",
            action=result.get("action", "observe"),
            content=result.get("content", ""),
            emotion=result.get("emotion", "neutral"),
            target=result.get("target", ""),
            metadata={"inner_thought": result.get("inner_thought", "")},
        )


# =========================================================================
# NPC Agent
# =========================================================================

class NPCAgent:
    """NPC Agent — situational behavior for a non-player character."""

    def __init__(self, client: LLMClient, config: StoryConfig):
        self.client = client
        self.config = config

    async def act(
        self,
        npc: NPC,
        state: StoryState,
        scene_context: str,
        protagonist_action: Optional[AgentAction] = None,
    ) -> AgentAction:
        """NPC makes an action decision."""
        system = NPC_SYSTEM_PROMPT.format(
            npc_name=npc.name,
            npc_role=npc.role,
            npc_personality=npc.personality,
            npc_goal=npc.goal,
            world_setting=self.config.world_setting,
            scene_context=scene_context,
        )

        proto_info = ""
        if protagonist_action:
            proto_info = f"\n主角刚才的行动: {protagonist_action.action} - {protagonist_action.content}"

        user = f"""## 当前场景
{scene_context}{proto_info}

## NPC 状态
- 已活跃章节数: {state.chapter_count - npc.intro_chapter}
- 目标完成进度: 未知（根据场景判断）

请做出你的行动选择。"""

        text, tokens = await self.client.call(system, user, temperature=0.8, max_tokens=800)
        state.total_tokens_used += tokens

        result = extract_json(text)
        if result is None:
            logger.warning(f"NPC [{npc.name}] 返回了无法解析的 JSON。原文: {text[:200]}")
            result = {
                "action": "observe",
                "content": f"{npc.name} 静静地观察着周围的一切。",
                "emotion": "neutral",
                "target": self.config.protagonist_name,
                "willing_to_exit": False,
            }

        return AgentAction(
            agent_name=npc.name,
            agent_type="npc",
            action=result.get("action", "observe"),
            content=result.get("content", ""),
            emotion=result.get("emotion", "neutral"),
            target=result.get("target", ""),
            metadata={"willing_to_exit": result.get("willing_to_exit", False)},
        )


# =========================================================================
# Evaluator Agent
# =========================================================================

class EvaluatorAgent:
    """评估 Agent — scores a completed version on 4 dimensions."""

    def __init__(self, client: LLMClient, config: StoryConfig):
        self.client = client
        self.config = config

    async def evaluate(self, state: StoryState) -> EvalResult:
        """Score a completed pre-rehearsal version."""
        # Assemble full story text
        story_text = ""
        for ch in state.chapters:
            story_text += f"\n## 第{ch.number}章\n{ch.content}\n"

        system = EVALUATOR_SYSTEM_PROMPT.format(
            required_ending=self.config.story_end,
            story_text=story_text,
        )

        user = f"""## 版本信息
- 版本 ID: {state.version_id}
- 总章节数: {state.chapter_count}
- 是否到达结局: {state.reached_ending}
- 提前终止: {state.terminated_early}

## 主角设定
{self.config.protagonist_name}: {self.config.protagonist_traits}

请对上述故事版本进行四维度评估。"""

        text, tokens = await self.client.call(system, user, temperature=0.3)
        # Note: evaluator token usage is tracked separately or on the main budget
        # We don't add to state.total_tokens_used since state is per version

        result = extract_json(text)
        if result is None:
            logger.warning(f"评估 Agent 返回了无法解析的 JSON。原文: {text[:200]}")
            result = {
                "dramatic_tension": 5.0,
                "character_growth": 5.0,
                "logic_consistency": 5.0,
                "ending_alignment": 5.0,
                "overall_assessment": "无法自动评估",
                "strengths": [],
                "weaknesses": ["评估失败"],
            }

        total = (
            result.get("dramatic_tension", 5.0)
            + result.get("character_growth", 5.0)
            + result.get("logic_consistency", 5.0)
            + result.get("ending_alignment", 5.0)
        ) / 4.0

        return EvalResult(
            version_id=state.version_id,
            dramatic_tension=result.get("dramatic_tension", 5.0),
            character_growth=result.get("character_growth", 5.0),
            logic_consistency=result.get("logic_consistency", 5.0),
            ending_alignment=result.get("ending_alignment", 5.0),
            total_score=round(total, 2),
            evaluator_notes=result.get("overall_assessment", ""),
            is_complete=state.reached_ending and not state.terminated_early,
        )


# =========================================================================
# Narrative Writer Agent — generates actual chapter narrative text
# =========================================================================

def _build_npc_profiles(state) -> str:
    """Build a summary of active NPC profiles for the NarrativeWriter."""
    active = [n for n in state.active_npcs if n.alive and n.active]
    if not active:
        return "无"
    lines = []
    for n in active[:6]:  # max 6 for token efficiency
        is_new = n.intro_chapter == state.chapter_count + 1
        tag = " [首次出场]" if is_new else ""
        backstory = getattr(n, 'backstory', '') or ''
        lines.append(
            f"- {n.name}（{n.role}）性格:{n.personality} 目标:{n.goal}"
            f"{' 背景:' + backstory if backstory else ''}{tag}"
        )
    return "\n".join(lines)


class NarrativeWriter:
    """
    Generates the actual narrative prose for a chapter based on agent actions.
    This is called after Director, Protagonist, and NPC agents have decided
    what happens in the chapter.
    """

    WRITER_SYSTEM_PROMPT = """你是一位才华横溢的小说家。根据导演的指示和角色的行动，将本章内容写成生动流畅的叙事文字。

## 写作要求
1. 用中文写作，文笔流畅，描写生动。
2. 从第三人称有限视角叙述（以主角的视角为主）。
3. 包含适当的场景描写、动作描写、对话和心理活动。
4. 字数控制在 500-800 字。
5. 保持与前文章节风格一致。
6. **场景连续性**：章节开头必须交代角色的当前位置。如果场景与上章结尾不同，用一两句话描述角色是如何到达新场景的（旅行、时间流逝、突发事件等）。禁止角色位置突然跳跃。
7. **角色引入**：如果本章有首次出场的新角色，通过动作或简短描写自然交代其身份特征，避免毫无铺垫地突然出现。

## 输出格式
直接输出叙事文字，不需要 JSON 格式。不要添加"第X章"标题（标题由程序添加）。"""

    def __init__(self, client: LLMClient, config: StoryConfig):
        self.client = client
        self.config = config
        # Build style instruction once
        self._style_instruction = build_style_prompt(config.writing_style)

    def _build_system_prompt(self) -> str:
        """System prompt with optional style instruction."""
        prompt = self.WRITER_SYSTEM_PROMPT
        if self._style_instruction:
            prompt += "\n" + self._style_instruction
        return prompt

    async def write_chapter(
        self,
        state: StoryState,
        director_decision: dict,
        protagonist_action: AgentAction,
        npc_actions: list[AgentAction],
        word_target: int = 650,
        rag_context: str = "",
    ) -> tuple[str, int]:
        """Generate the narrative text for a chapter with dynamic word target and RAG context."""
        # Use RAG context when available, fall back to raw text
        if rag_context:
            prev_context = rag_context
        else:
            prev_text = ""
            for ch in state.chapters[-2:]:
                prev_text += ch.content[-500:] + "\n"
            prev_context = f"## 前文章节结尾\n{prev_text or '（故事开始）'}"

        chapter_num = state.chapter_count + 1

        # Use Director-generated title if available (from chapter_title field)
        director_title = director_decision.get("chapter_title", "").strip()
        if director_title and 2 <= len(director_title) <= 20:
            title_hint = f"\n## 本章标题\n{director_title}\n（请在叙事中自然地呼应此标题的意境）"
        else:
            title_hint = ""

        npc_text = ""
        for a in npc_actions:
            npc_text += f"- {a.agent_name} ({a.emotion}): {a.action} → {a.content}\n\n"

        style_note = ""
        if self._style_instruction:
            style_note = f"\n## 风格参考\n本章请模仿 **{self.config.writing_style}** 的风格写作。\n"

        # Build first-appearance NPC warning (at TOP for maximum attention)
        first_appearance_npcs = [
            n for n in state.active_npcs
            if n.alive and n.active and n.intro_chapter == chapter_num
        ]
        npc_intro_warning = ""
        if first_appearance_npcs:
            names = "、".join(n.name for n in first_appearance_npcs)
            npc_intro_warning = (
                f"## ⚠️ 本章首次登场角色（必须在叙事中交代身份！）\n"
                f"以下角色在本章首次出场：**{names}**。\n"
                f"请在叙事中自然地介绍他们的身份、外貌特征和登场原因。\n"
                f"不要让读者猜测'这人是谁'——每个新角色出场时至少用一两句话交代背景。\n\n"
            )

        user = f"""{npc_intro_warning}{prev_context}

## 本章导演指示
{json.dumps(director_decision, ensure_ascii=False, indent=2)}

## 主角行动
- 行动类型: {protagonist_action.action}
- 情绪: {protagonist_action.emotion}
- 内容: {protagonist_action.content}
- 内心想法: {protagonist_action.metadata.get('inner_thought', '')}
{title_hint}
{style_note}
## NPC 行动
{npc_text or "本章无 NPC 参与行动"}

## 活跃 NPC 角色档案
{_build_npc_profiles(state)}

## 写作要求
- 这是第 {chapter_num} 章
- **目标字数: {word_target} 字**（请注意控制篇幅，尽量接近目标字数，允许 ±100 字浮动）
- 自然地衔接前文，流畅推进故事
- 重点描写主角的行动和感受，NPC 行动作为辅助

请写出本章的叙事文字："""

        text, tokens = await self.client.call(
            self._build_system_prompt(), user, max_tokens=3000, temperature=0.9
        )

        # Detect truncation: if output ends mid-sentence, log warning
        if text and len(text) > 50:
            last_char = text.strip()[-1]
            sentence_ends = {'。', '！', '？', '”', '"', '…', '—', '~', '\n'}
            if last_char not in sentence_ends and not text.strip().endswith('...'):
                logger.warning(
                    f"章节可能被截断（结尾字符: '{last_char}'），"
                    f"建议增加 max_tokens 或减少 prompt 长度"
                )

        return text, tokens
