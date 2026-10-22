"""
文本多样性诊断仪。

定位说明（重要）
----------------
本模块**不预测也不承诺**"AI 率"。它测量的是**文本本身的多样性与节奏**——
句长波动、短语重复、对话密度、标点节奏、情绪密度等。
这些指标与作者是不是人无关、与有没有用 AI 无关，只与**这一段写得好不好、
读起来平不平**有关。

检测器所用的技术原理（困惑度 Perplexity / 突发性 Burstiness）本质上也是
"文本多样性"的某种度量；把同一批指标用于**写作质量诊断**，比包装成
"降 AI 率"要可靠得多，也不会随着检测器升级而失效。

用法
----
    from diversity import analyze_text, diagnose

    metrics = analyze_text(chapter_text)
    report  = diagnose(chapter_text, baseline_metrics=metrics_of_first_20_chapters)

所有函数都是纯函数，无 LLM 调用、无网络、无 token 消耗。
"""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any

# ── 基础切分 ───────────────────────────────────────────────────────────

_SENTENCE_SPLIT = re.compile(r"[。！？!?；;…]+|\n+")
_CJK = re.compile(r"[一-鿿]")
_LATIN_WORD = re.compile(r"[A-Za-z]+")
_DIGIT = re.compile(r"\d+")
# 对话引号内的内容（中文直角/弯引号 + 英文引号）
_DIALOGUE = re.compile(r"[「『“\"]([^「『“\"”』]{0,400})[」』”\"]")

# 情绪词表（通用情绪词，不含任何作者名或作品名）
_EMOTION_WORDS = [
    "怒", "恨", "怕", "惊", "喜", "悲", "哀", "慌", "急", "痛", "暖", "酸", "甜",
    "兴奋", "恐惧", "愤怒", "悲伤", "喜悦", "惊讶", "绝望", "希望", "疑惑", "不安",
    "欣慰", "羞愧", "嫉妒", "心疼", "激动", "紧张", "释然", "委屈", "委屈", "愤怒",
    "委屈", "心酸", "发慌", "发怵", "冷笑", "苦笑", "大笑", "轻笑", "沉默", "叹",
]

_PUNCT_NAMES = {
    "，": "逗号", "。": "句号", "、": "顿号", "；": "分号", "：": "冒号",
    "？": "问号", "！": "感叹号", "—": "破折号", "…": "省略号",
    "「": "左引号", "」": "右引号", "“": "左双引号", "”": "右双引号",
    "(": "左括号", ")": "右括号",
}


def _content_chars(text: str) -> str:
    """Keep only content characters (CJK, latin letters, digits)."""
    return "".join(_CJK.findall(text)) + "".join(_LATIN_WORD.findall(text)) + "".join(_DIGIT.findall(text))


def _sentences(text: str) -> list[str]:
    parts = [p.strip() for p in _SENTENCE_SPLIT.split(text) if p and p.strip()]
    return [p for p in parts if _content_chars(p)]


def _percentile(values: list[float], q: float) -> float:
    """Linear-interpolated percentile of a numeric list."""
    if not values:
        return 0.0
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    pos = (len(s) - 1) * q
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return s[int(pos)]
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def _stdev(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    var = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
    return math.sqrt(var)


def _ngram_repeat_rate(chars: str, n: int) -> float:
    """Fraction of n-grams that are repeats of an earlier n-gram."""
    if len(chars) < n + 1:
        return 0.0
    grams = [chars[i:i + n] for i in range(len(chars) - n + 1)]
    counter = Counter(grams)
    repeated = sum(c - 1 for c in counter.values() if c > 1)
    return repeated / len(grams)


# ── 单项指标 ───────────────────────────────────────────────────────────

def phrase_repetition(text: str, n: int = 4) -> float:
    """Repeated 4-character phrase rate. Lower is more varied."""
    return round(_ngram_repeat_rate(_content_chars(text), n), 4)


def trigram_repetition(text: str) -> float:
    """Repeated 3-character gram rate — the strictest of the repetition checks."""
    return round(_ngram_repeat_rate(_content_chars(text), 3), 4)


def sentence_length_stats(text: str) -> dict[str, float]:
    """Sentence length distribution. Flat distributions read as monotonous."""
    lens = [len(_content_chars(s)) for s in _sentences(text)]
    if not lens:
        return {"count": 0, "mean": 0.0, "stdev": 0.0, "p50": 0.0, "p90": 0.0,
                "max": 0.0, "min": 0.0, "short_ratio": 0.0, "long_ratio": 0.0}
    mean = sum(lens) / len(lens)
    stdev = _stdev([float(x) for x in lens])
    short_ratio = sum(1 for x in lens if x <= max(4, mean * 0.5)) / len(lens)
    long_ratio = sum(1 for x in lens if x >= mean * 1.8) / len(lens)
    return {
        "count": len(lens),
        "mean": round(mean, 2),
        "stdev": round(stdev, 2),
        "p50": round(_percentile([float(x) for x in lens], 0.5), 1),
        "p90": round(_percentile([float(x) for x in lens], 0.9), 1),
        "max": max(lens),
        "min": min(lens),
        "short_ratio": round(short_ratio, 4),
        "long_ratio": round(long_ratio, 4),
    }


def lexical_diversity(text: str) -> dict[str, float]:
    """Type-token ratios at character and word level."""
    content = _content_chars(text)
    if not content:
        return {"char_ttr": 0.0, "word_ttr": 0.0, "unique_chars": 0, "total_chars": 0}
    words = _LATIN_WORD.findall(text) + _CJK.findall(text)
    # Chinese "words" approximated by 2-char shingles for a stable TTR
    shingles = [content[i:i + 2] for i in range(max(0, len(content) - 1))]
    return {
        "char_ttr": round(len(set(content)) / len(content), 4),
        "word_ttr": round(len(set(shingles)) / len(shingles), 4) if shingles else 0.0,
        "unique_chars": len(set(content)),
        "total_chars": len(content),
    }


def punctuation_rhythm(text: str) -> dict[str, Any]:
    """Punctuation habits — a very common tell of machine-flat prose."""
    counts = Counter(ch for ch in text if ch in _PUNCT_NAMES)
    total_content = max(1, len(_content_chars(text)))
    kinds = len(counts)
    comma = counts.get("，", 0)
    sentences = max(1, len(_sentences(text)))
    return {
        "kinds": kinds,
        "comma_density": round(comma / total_content * 1000, 2),   # 每千字逗号数
        "commas_per_sentence": round(comma / sentences, 2),
        "dash_count": counts.get("—", 0),
        "colon_count": counts.get("：", 0),
        "ellipsis_count": counts.get("…", 0),
        "quote_pairs": counts.get("「", 0) + counts.get("“", 0),
        "counts": dict(counts),
    }


def dialogue_ratio(text: str) -> float:
    """Share of characters that sit inside quotation marks."""
    content_len = len(_content_chars(text))
    if not content_len:
        return 0.0
    quoted = sum(len(_content_chars(m)) for m in _DIALOGUE.findall(text))
    return round(min(1.0, quoted / content_len), 4)


def emotion_density(text: str) -> float:
    """Emotional vocabulary per 1,000 characters."""
    content = _content_chars(text)
    if not content:
        return 0.0
    hits = sum(content.count(w) for w in set(_EMOTION_WORDS))
    return round(hits / len(content) * 1000, 2)


def semantic_smoothness(text: str) -> float:
    """
    Average character-bigram overlap between adjacent sentences.

    High = every sentence flows into the next the same way (flat).
    Low  = the prose jumps around (may be vivid, may be incoherent).
    """
    sents = [_content_chars(s) for s in _sentences(text)]
    sents = [s for s in sents if len(s) >= 2]
    if len(sents) < 2:
        return 0.0
    overlaps = []
    for a, b in zip(sents, sents[1:]):
        grams_a = {a[i:i + 2] for i in range(len(a) - 1)}
        grams_b = {b[i:i + 2] for i in range(len(b) - 1)}
        if not grams_a or not grams_b:
            continue
        overlaps.append(len(grams_a & grams_b) / min(len(grams_a), len(grams_b)))
    return round(sum(overlaps) / len(overlaps), 4) if overlaps else 0.0


# ── 汇总 ───────────────────────────────────────────────────────────────

def analyze_text(text: str) -> dict[str, Any]:
    """
    Compute all diversity metrics for a passage.

    Returns a dict with a ``metrics`` block and a ``chars`` count.
    """
    text = text or ""
    sl = sentence_length_stats(text)
    return {
        "chars": len(_content_chars(text)),
        "sentences": sl["count"],
        "metrics": {
            "phrase_repetition": phrase_repetition(text),
            "trigram_repetition": trigram_repetition(text),
            "sentence_length": sl,
            "lexical_diversity": lexical_diversity(text),
            "punctuation_rhythm": punctuation_rhythm(text),
            "dialogue_ratio": dialogue_ratio(text),
            "emotion_density": emotion_density(text),
            "semantic_smoothness": semantic_smoothness(text),
        },
    }


# 参考区间：来自真实中文网文与通用散文的经验值，仅用于给出"偏离"的方向
_REFERENCE = {
    "phrase_repetition": {"low": 0.02, "high": 0.12},
    "trigram_repetition": {"low": 0.01, "high": 0.06},
    "sentence_length.stdev": {"low": 4.0, "high": 14.0},
    "sentence_length.short_ratio": {"low": 0.10, "high": 0.45},
    "sentence_length.long_ratio": {"low": 0.02, "high": 0.15},
    "lexical_diversity.char_ttr": {"low": 0.45, "high": 0.85},
    "punctuation_rhythm.commas_per_sentence": {"low": 0.5, "high": 2.5},
    "punctuation_rhythm.kinds": {"low": 3, "high": 10},
    "dialogue_ratio": {"low": 0.15, "high": 0.65},
    "emotion_density": {"low": 3.0, "high": 30.0},
    "semantic_smoothness": {"low": 0.05, "high": 0.35},
}


def _get_path(metrics: dict, path: str) -> float:
    node: Any = metrics
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return 0.0
        node = node[part]
    return float(node) if isinstance(node, (int, float)) else 0.0


def diagnose(
    text: str,
    baseline: dict[str, Any] | None = None,
    forbidden: list[str] | None = None,
) -> dict[str, Any]:
    """
    Produce a diagnostic card for a passage.

    Args:
        text: the passage
        baseline: metrics dict from ``analyze_text`` of earlier chapters; when
            given, each metric is also compared against the book's own baseline
            rather than a generic reference range
        forbidden: banned expressions to look for (e.g. a technique's ``forbidden``)

    Returns:
        A dict with ``findings`` (list of human-readable strings), ``score``
        (0-100, higher = more varied) and the raw metrics.
    """
    analysis = analyze_text(text)
    metrics = analysis["metrics"]
    findings: list[str] = []

    # ── 禁用表达 ──────────────────────────────────────────────────────
    hits = []
    for w in forbidden or []:
        if w and w in text:
            hits.append(w)
    if hits:
        findings.append(
            f"命中禁用表达 {len(hits)} 处：{'、'.join(hits[:6])}"
            + ("（…）" if len(hits) > 6 else "")
        )

    # ── 与基线/参考区间比较 ───────────────────────────────────────────
    scored = 0
    total = 0
    for path, rng in _REFERENCE.items():
        value = _get_path(metrics, path)
        total += 1
        if path == "sentence_length.stdev":
            # A wider spread is better; the reference band marks "healthy".
            if value < rng["low"]:
                findings.append(f"句长波动偏小（σ={value}，参考 ≥{rng['low']}）——节奏容易发平")
                scored += 0
            elif value > rng["high"]:
                findings.append(f"句长波动偏大（σ={value}，参考 ≤{rng['high']}）——句子长度忽长忽短")
                scored += 0.5
            else:
                scored += 1
            continue

        if baseline is not None:
            base_value = _get_path(baseline, path)
            if base_value:
                drift = value / base_value if base_value else 1.0
                if drift > 1.6 and rng.get("high") is not None:
                    findings.append(
                        f"{path} 明显高于本书基线（{value} vs {base_value}）"
                    )
                    scored += 0.5
                elif drift < 0.6 and rng.get("low") is not None:
                    findings.append(
                        f"{path} 明显低于本书基线（{value} vs {base_value}）"
                    )
                    scored += 0.5
                else:
                    scored += 1
                continue

        low = rng.get("low")
        high = rng.get("high")
        if low is not None and value < low:
            findings.append(f"{path} 偏低（{value}，参考 ≥{low}）")
            scored += 0.5
        elif high is not None and value > high:
            findings.append(f"{path} 偏高（{value}，参考 ≤{high}）")
            scored += 0.5
        else:
            scored += 1

    score = round(100 * scored / total) if total else 0

    # ── 几处硬性提示 ──────────────────────────────────────────────────
    if metrics["dialogue_ratio"] < 0.10 and analysis["chars"] > 500:
        findings.append("对话占比很低（<10%），叙述腔偏重")
    if metrics["punctuation_rhythm"]["commas_per_sentence"] > 3.0:
        findings.append("每句逗号偏多，句读偏碎")
    if metrics["sentence_length"]["count"] >= 5 and metrics["sentence_length"]["stdev"] < 3.0:
        findings.append("句子长度高度一致，读起来像模板")

    return {
        "chars": analysis["chars"],
        "sentences": analysis["sentences"],
        "score": score,
        "findings": findings,
        "forbidden_hits": hits,
        "metrics": metrics,
    }


def format_report(report: dict[str, Any]) -> str:
    """Render a diagnostic card as plain text."""
    lines = [
        f"多样性评分：{report['score']}/100"
        f"（{report['sentences']} 句 / {report['chars']} 字）",
    ]
    if report["findings"]:
        lines.append("发现：")
        lines.extend(f"  · {f}" for f in report["findings"])
    else:
        lines.append("未发现明显问题。")
    m = report["metrics"]
    lines.append(
        f"明细：短语重复 {m['phrase_repetition']}｜3-gram 重复 {m['trigram_repetition']}｜"
        f"句长 σ={m['sentence_length']['stdev']}（p50 {m['sentence_length']['p50']} / "
        f"p90 {m['sentence_length']['p90']}）｜"
        f"对话 {m['dialogue_ratio']}｜标点种类 {m['punctuation_rhythm']['kinds']}｜"
        f"每句逗号 {m['punctuation_rhythm']['commas_per_sentence']}｜"
        f"情绪密度 {m['emotion_density']}/千字｜"
        f"语义平滑 {m['semantic_smoothness']}"
    )
    return "\n".join(lines)
