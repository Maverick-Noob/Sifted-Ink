"""
运行前成本 / 时长预估。

设计原则
--------
1. **不拍脑袋**：估算基于本项目真实的 LLM 调用结构（见下方各阶段的调用次数与
   上下文字符数），而不是"大概是这么多次"。
2. **可反标定**：首次上线后请用 ``eval_log`` / ``params.yaml`` 里的真实
   ``total_tokens_used`` 与本估算对比，修正下方的 ``_PHASE_*`` 常量。
3. **价格只是参考**：价格表为公开挂牌价的快照（单位：美元 / 百万 token），
   随时可能变动，**以服务商账单为准**。若要覆盖当前模型的单价，请设置环境变量
   ``SIFTED_INK_INPUT_PRICE_PER_MILLION`` / ``SIFTED_INK_OUTPUT_PRICE_PER_MILLION``
   （美元 / 百万 token），设置后内置价格表不再生效。
4. **不承诺精确**：输出是"量级"而非"账单"，UI 上会显示区间与误差来源说明。

调用结构（每个版本）
--------------------
    固定阶段   结局生成(可选) + 3 份大纲 + 1 次大纲评估
    每章阶段   导演 1 + 主角 1 + NPC 0~3 + 写手 1 + 记忆抽取 1
    全局阶段   起名与摘要 1 + 前附文 0~4（全书一次）
"""

from __future__ import annotations

import math
import os
from typing import Any

# ── 每阶段的调用与上下文规模 ───────────────────────────────────────────
# 单位：输入/输出 token 数（输入含系统提示 + 上下文，输出为生成内容）

_PHASE_OUTLINE = {"calls": 3, "in": 3000, "out": 1200}       # 3 份不同角度的大纲
_PHASE_OUTLINE_EVAL = {"calls": 1, "in": 9000, "out": 800}   # 评估并选最优
_PHASE_ENDING = {"calls": 1, "in": 2000, "out": 300}          # 自动生成结局
_PHASE_DIRECTOR = {"calls": 1, "in": 3200, "out": 600}        # 每章导演决策
_PHASE_PROTAGONIST = {"calls": 1, "in": 2400, "out": 400}     # 每章主角行动
_PHASE_NPC = {"calls": 1, "in": 1800, "out": 300}             # 每章每个 NPC
_PHASE_WRITER = {"calls": 1, "in": 3200, "out": 0}            # 每章正文（输出随字数变）
_PHASE_MEMORY = {"calls": 1, "in": 1800, "out": 500}          # 每章记忆抽取
_PHASE_NAMING = {"calls": 1, "in": 5000, "out": 800}           # 情节摘要 + 候选书名
_PHASE_FRONT_MATTER = {"calls": 1, "in": 12000, "out": 1500}  # 每个前附文条目

# 中文按 1 字 ≈ 0.7 token 估（经验值）
_TOKENS_PER_CHINESE_CHAR = 0.7

# 单次 LLM 调用的墙钟耗时（秒），用于串行/并行混合的粗估
_SECONDS_PER_CALL = 9.0

# 公开挂牌价快照（美元 / 百万 token）：(输入, 输出)
PRICE_TABLE: dict[str, tuple[float, float]] = {
    "claude-opus": (15.0, 75.0),
    "claude-sonnet": (3.0, 15.0),
    "claude-haiku": (0.80, 4.0),
    "gpt-4o": (2.50, 10.0),
    "gpt-4o-mini": (0.15, 0.60),
    "gemini-2.5-pro": (1.25, 10.0),
    "gemini-2.5-flash": (0.30, 2.50),
    "deepseek-chat": (0.27, 1.10),
    "deepseek-reasoner": (0.55, 2.19),
    "qwen-plus": (0.40, 1.20),
    "qwen-max": (1.60, 6.40),
    "glm-4-plus": (0.60, 0.60),
    "moonshot": (0.60, 0.60),
    "minimax": (0.40, 1.20),
    "grok": (2.50, 10.0),
    "mistral": (0.25, 1.00),
    "cohere": (2.50, 10.0),
}

_USD_TO_CNY = 7.1


def _price_for(model: str) -> tuple[float, float]:
    """Resolve (usd_in_per_million, usd_out_per_million) for a model name."""
    env_in = os.environ.get("SIFTED_INK_INPUT_PRICE_PER_MILLION")
    env_out = os.environ.get("SIFTED_INK_OUTPUT_PRICE_PER_MILLION")
    if env_in and env_out:
        try:
            return float(env_in), float(env_out)
        except ValueError:
            pass

    m = (model or "").lower()
    # 长前缀优先匹配
    for key in sorted(PRICE_TABLE, key=len, reverse=True):
        if key in m:
            return PRICE_TABLE[key]
    return (1.0, 3.0)  # 未知模型给一个中间值，并在 notes 里提示自行确认


def chapter_word_bounds(target_total: int) -> tuple[int, int]:
    """
    Per-chapter word floor/ceiling.

    Mirrors ``preactor._calc_word_target`` — keep the two in sync.
    """
    if target_total <= 3000:
        return 100, 800
    elif target_total <= 5000:
        return 150, 1000
    elif target_total <= 10000:
        return 200, 1200
    else:
        return 300, 1500


def adaptive_max_chapters(target_total: int, configured_max: int) -> int:
    """Mirrors ``preactor._adaptive_max_chapters``."""
    if target_total <= 1000:
        return min(configured_max, 5)
    elif target_total <= 3000:
        return min(configured_max, 10)
    elif target_total <= 5000:
        return min(configured_max, 20)
    return configured_max


def _npc_calls_per_chapter(npc_mode: str, quality_mode: str) -> int:
    if npc_mode == "narrator":
        return 0
    if npc_mode == "scene_filter":
        return 1
    return 3 if quality_mode == "quality" else 2


def estimate_run(config: Any, front_matter: list[str] | None = None) -> dict[str, Any]:
    """
    Estimate one generation run.

    Args:
        config: a StoryConfig (or any object with the same attributes)
        front_matter: list of front-matter keys (toc/epigraph/prologue/characters)

    Returns a dict with the estimate plus a list of human-readable notes.
    """
    fm = front_matter if front_matter is not None else list(getattr(config, "front_matter", []) or [])

    target_total = int(getattr(config, "target_word_count", 8000))
    max_chapters = int(getattr(config, "max_chapters", 30))
    num_versions = int(getattr(config, "num_versions", 1))
    max_tokens = int(getattr(config, "max_tokens_per_call", 4000))
    npc_mode = getattr(config, "npc_mode", "parallel")
    quality_mode = getattr(config, "quality_mode", "balanced")
    has_ending = bool(str(getattr(config, "story_end", "")).strip())
    model = getattr(config, "model", "")

    notes: list[str] = []

    # ── 章节数 ────────────────────────────────────────────────────────
    effective_max = adaptive_max_chapters(target_total, max_chapters)
    floor, ceiling = chapter_word_bounds(target_total)
    avg_words = max(floor, min(ceiling, target_total // max(1, effective_max)))
    chapters = max(1, min(effective_max, math.ceil(target_total / avg_words)))

    if effective_max != max_chapters:
        notes.append(
            f"目标字数 {target_total} 对应的章节上限已自动调整为 {effective_max}（原 {max_chapters}）"
        )

    # ── 每次调用的 token ──────────────────────────────────────────────
    npc_calls = _npc_calls_per_chapter(npc_mode, quality_mode)
    writer_out = min(int(avg_words * _TOKENS_PER_CHINESE_CHAR) + 200, max_tokens)

    per_chapter_in = (
        _PHASE_DIRECTOR["in"]
        + _PHASE_PROTAGONIST["in"]
        + _PHASE_NPC["in"] * npc_calls
        + _PHASE_WRITER["in"]
        + _PHASE_MEMORY["in"]
    )
    per_chapter_out = (
        _PHASE_DIRECTOR["out"]
        + _PHASE_PROTAGONIST["out"]
        + _PHASE_NPC["out"] * npc_calls
        + writer_out
        + _PHASE_MEMORY["out"]
    )
    per_chapter_calls = (
        _PHASE_DIRECTOR["calls"]
        + _PHASE_PROTAGONIST["calls"]
        + _PHASE_NPC["calls"] * npc_calls
        + _PHASE_WRITER["calls"]
        + _PHASE_MEMORY["calls"]
    )

    per_version_in = (
        per_chapter_in * chapters
        + _PHASE_OUTLINE["in"] * _PHASE_OUTLINE["calls"]
        + _PHASE_OUTLINE_EVAL["in"]
        + (0 if has_ending else _PHASE_ENDING["in"])
    )
    per_version_out = (
        per_chapter_out * chapters
        + _PHASE_OUTLINE["out"] * _PHASE_OUTLINE["calls"]
        + _PHASE_OUTLINE_EVAL["out"]
        + (0 if has_ending else _PHASE_ENDING["out"])
    )
    per_version_calls = (
        per_chapter_calls * chapters
        + _PHASE_OUTLINE["calls"]
        + _PHASE_OUTLINE_EVAL["calls"]
        + (0 if has_ending else _PHASE_ENDING["calls"])
    )

    tokens_in = int(per_version_in * num_versions + _PHASE_NAMING["in"])
    tokens_out = int(per_version_out * num_versions + _PHASE_NAMING["out"])
    llm_calls = int(per_version_calls * num_versions + _PHASE_NAMING["calls"])

    if fm:
        tokens_in += _PHASE_FRONT_MATTER["in"] * len(fm)
        tokens_out += _PHASE_FRONT_MATTER["out"] * len(fm)
        llm_calls += _PHASE_FRONT_MATTER["calls"] * len(fm)

    tokens_total = tokens_in + tokens_out

    # ── 墙钟时长 ──────────────────────────────────────────────────────
    # 单版本内部是串行的（导演→主角→NPC→写手→记忆），版本之间并行。
    serial_calls = per_version_calls + _PHASE_NAMING["calls"]
    wall_seconds = serial_calls * _SECONDS_PER_CALL
    wall_seconds += len(fm) * _PHASE_FRONT_MATTER["calls"] * _SECONDS_PER_CALL
    wall_minutes = wall_seconds / 60.0

    # ── 费用 ──────────────────────────────────────────────────────────
    price_in, price_out = _price_for(model)
    cost_usd = tokens_in / 1e6 * price_in + tokens_out / 1e6 * price_out

    if num_versions > 1:
        notes.append(
            f"并行 {num_versions} 个版本：调用与费用约为单版的 {num_versions} 倍，"
            "但墙钟时长基本不变。"
        )
        notes.append(
            "批量生成是平台治理的判定维度之一（是否批量生成 / 是否严重缺乏原创性），"
            "建议先跑 1 版确认方向。"
        )
    if target_total > chapters * ceiling:
        notes.append(
            f"目标字数 {target_total} 超过单次运行的能力上限：每章上限 {ceiling} 字 × "
            f"{chapters} 章 ≈ {int(chapters * ceiling)} 字，超出的部分不会生成。"
        )
    if fm:
        notes.append("前附文会额外调用 LLM 生成（全书一次）。")
    notes.append("价格为公开挂牌价快照，以服务商账单为准。")

    return {
        "chapters": chapters,
        "chapters_cap": effective_max,
        "words_per_chapter": avg_words,
        "llm_calls": llm_calls,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "tokens_total": tokens_total,
        "wall_minutes": round(wall_minutes, 1),
        "cost_usd": round(cost_usd, 4),
        "cost_cny": round(cost_usd * _USD_TO_CNY, 2),
        "price_in_per_million": price_in,
        "price_out_per_million": price_out,
        "notes": notes,
    }


def format_estimate(est: dict[str, Any]) -> str:
    """Human-readable one-paragraph summary of an estimate."""
    return (
        f"约 {est['chapters']} 章 · {est['llm_calls']} 次模型调用 · "
        f"约 {est['tokens_total']:,} token（输入 {est['tokens_in']:,} / 输出 {est['tokens_out']:,}）· "
        f"约 {est['wall_minutes']} 分钟 · 约 ${est['cost_usd']}（≈¥{est['cost_cny']}）"
    )
