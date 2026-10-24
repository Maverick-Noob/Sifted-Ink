#!/usr/bin/env python3
"""
M0 · Q3 验证工具 —— 诊断仪的判别力标定与参考区间再校准

用法
----
    # 1) 语料目录里放若干 .txt（每段 800~3000 字），文件名即样本 id
    # 2) 人工标签放在 labels.csv：第一列文件名，第二列 AI 味档位
    #        0 = 味轻（读感好）  1 = 中  2 = 味重（机械）
    #        也接受 1~5 的连续分值
    # 3) 运行：
    python tools/m0_benchmark.py corpus/ --labels corpus/labels.csv

产出
----
    * 与人工标签的 Spearman 相关系数（**目标 ≥ 0.6**）
    * 每个指标各自的相关系数（看哪个指标在真正起作用）
    * 按语料重新标定的参考区间建议（可直接回填 diversity.py 的 _REFERENCE）
    * 一份 Markdown 报告

不需要网络、不调用 LLM、不消耗 token。
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
# The repository root IS the package directory, so the PARENT has to be on
# sys.path for `import novel_preactor.xxx` to resolve — otherwise the module
# novel_preactor.py shadows the package directory of the same name.
for _p in (str(_ROOT), str(_ROOT.parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)
if str(_ROOT.parent) in sys.path:
    sys.path.remove(str(_ROOT.parent))
    sys.path.insert(0, str(_ROOT.parent))

from novel_preactor.diversity import analyze_text, diagnose  # noqa: E402

# 被逐一检验的指标路径（与 diversity._REFERENCE 的键一致）
METRIC_PATHS = [
    "phrase_repetition",
    "trigram_repetition",
    "sentence_length.stdev",
    "sentence_length.short_ratio",
    "sentence_length.long_ratio",
    "lexical_diversity.char_ttr",
    "punctuation_rhythm.commas_per_sentence",
    "punctuation_rhythm.kinds",
    "dialogue_ratio",
    "emotion_density",
    "semantic_smoothness",
]


# ── 统计 ────────────────────────────────────────────────────────────────

def rank(values: list[float]) -> list[float]:
    """平均秩（并列取均值）。"""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def pearson(a: list[float], b: list[float]) -> float:
    n = len(a)
    if n < 2:
        return 0.0
    ma, mb = sum(a) / n, sum(b) / n
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    da = sum((x - ma) ** 2 for x in a) ** 0.5
    db = sum((y - mb) ** 2 for y in b) ** 0.5
    return num / (da * db) if da and db else 0.0


def spearman(a: list[float], b: list[float]) -> float:
    """秩相关。"""
    if len(a) < 3:
        return 0.0
    return pearson(rank(a), rank(b))


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    pos = (len(s) - 1) * q
    lo, hi = int(pos), min(int(pos) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def get_path(metrics: dict, path: str) -> float:
    node = metrics
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return 0.0
        node = node[part]
    return float(node) if isinstance(node, (int, float)) else 0.0


# ── 输入 ────────────────────────────────────────────────────────────────

def load_labels(path: Path) -> dict[str, float]:
    labels: dict[str, float] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.reader(f):
            if not row or row[0].strip().lower() in ("", "file", "filename", "文件名"):
                continue
            name = row[0].strip()
            try:
                labels[name] = float(row[1].strip())
            except (ValueError, IndexError):
                continue
    return labels


def load_corpus(corpus_dir: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for p in sorted(corpus_dir.glob("*.txt")):
        out[p.name] = p.read_text(encoding="utf-8", errors="replace")
    return out


# ── 主流程 ──────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description="诊断仪判别力标定")
    ap.add_argument("corpus", type=Path, help="语料目录（*.txt）")
    ap.add_argument("--labels", type=Path, required=True, help="labels.csv")
    ap.add_argument("--out", type=Path, default=None, help="报告输出路径（默认打印到屏幕）")
    args = ap.parse_args()

    corpus = load_corpus(args.corpus)
    labels = load_labels(args.labels)

    common = sorted(set(corpus) & set(labels))
    if len(common) < 6:
        print(f"样本不足：同时有语料和标签的只有 {len(common)} 份，至少需要 6 份。")
        print("提示：labels.csv 第一列必须是文件名（含 .txt），第二列是 AI 味档位。")
        return 1

    print(f"样本：{len(common)} 份（语料 {len(corpus)} 份，标签 {len(labels)} 份）\n")

    scores, gold, per_metric = [], [], {p: [] for p in METRIC_PATHS}
    detail = []

    for name in common:
        text = corpus[name]
        m = analyze_text(text)["metrics"]
        report = diagnose(text)
        # 多样性分越高 = 文本越有变化 = 越不像模板；
        # 人工标签是「AI 味」档位（越高越机械），两者方向相反，
        # 因此统一换算成「AI 味指数」再做相关，正值才代表判别力成立。
        ai_index = 100 - float(report["score"])
        scores.append(ai_index)
        gold.append(labels[name])
        for p in METRIC_PATHS:
            per_metric[p].append(get_path(m, p))
        detail.append((name, report["score"], ai_index, labels[name], report["findings"]))

    overall = spearman(scores, gold)
    print(f"★ AI 味指数 vs 人工标签：Spearman = {overall:+.3f}   （正相关 = 判别力成立）")
    if overall >= 0.75:
        verdict = "可用（可对外作为「节奏体检」）"
    elif overall >= 0.6:
        verdict = "达到 go 判据（≥0.6），进入 M1"
    elif overall >= 0.4:
        verdict = "仅作参考，尚未达到 go 判据（≥0.6）"
    else:
        verdict = "未达判据——参考区间需要用本语料重新标定（见下方建议）"
    print(f"  判定：{verdict}\n")

    print("各指标与人工标签的相关性（正 = 该指标越高越像模板）：")
    rows = []
    for p in METRIC_PATHS:
        r = spearman(per_metric[p], gold)
        rows.append((p, r))
    for p, r in sorted(rows, key=lambda x: -abs(x[1])):
        print(f"  {r:+.3f}  {p}")

    print("\n按语料重新标定的参考区间建议（p10 / p90，回填 diversity._REFERENCE）：")
    print("    _REFERENCE = {")
    for p in METRIC_PATHS:
        vals = per_metric[p]
        lo, hi = percentile(vals, 0.10), percentile(vals, 0.90)
        print(f'        "{p}": {{"low": {round(lo, 4)}, "high": {round(hi, 4)}}},')
    print("    }")

    print("\n逐段明细（多样性分高 = 文本更有变化；AI 味指数高 = 更像模板）：")
    for name, sc, ai, lab, findings in sorted(detail, key=lambda d: -d[1]):
        flag = "味重" if lab >= 2 else ("味中" if lab >= 1 else "味轻")
        print(f"  {name:24s} 多样性={sc:6.1f}  AI味指数={ai:6.1f}  人工={flag}  命中 {len(findings)} 条")

    report = [
        "# M0 · Q3 诊断仪标定报告",
        "",
        f"- 样本量：{len(common)}",
        f"- **AI 味指数 vs 人工标签：Spearman = {overall:+.3f}** — {verdict}",
        "- 说明：多样性分越高 = 越有变化；AI 味指数 = 100 − 多样性分，越高越像模板。"
        "与「AI 味」人工标签应为**正相关**。",
        "",
        "## 各指标相关性（正 = 该指标越高越像模板）",
        "",
        "| 指标 | Spearman |",
        "|---|---|",
    ]
    for p, r in sorted(rows, key=lambda x: -abs(x[1])):
        report.append(f"| `{p}` | {r:+.3f} |")
    report += [
        "",
        "## 重新标定的参考区间",
        "",
        "```python",
        "_REFERENCE = {",
    ]
    for p in METRIC_PATHS:
        vals = per_metric[p]
        lo, hi = percentile(vals, 0.10), percentile(vals, 0.90)
        report.append(f'    "{p}": {{"low": {round(lo, 4)}, "high": {round(hi, 4)}}},')
    report += ["}", "```", "", "## 逐段明细", "",
               "| 文件 | 多样性分 | AI 味指数 | 人工标签 | 命中条数 |", "|---|---|---|---|---|"]
    for name, sc, ai, lab, findings in sorted(detail, key=lambda d: -d[1]):
        report.append(f"| {name} | {sc} | {ai} | {lab} | {len(findings)} |")

    text = "\n".join(report)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
        print(f"\n报告已写入 {args.out}")
    else:
        print("\n(加 --out report.md 可保存报告)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
