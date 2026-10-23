"""
Tests for the M0 validation tools (tools/m0_ab.py, tools/m0_benchmark.py).

They are scripts rather than package modules, so they are loaded by path.
Nothing here calls the network or the LLM.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_TOOLS = _ROOT / "tools"


def _load(name: str):
    path = _TOOLS / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"_m0_{name}", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


m0_ab = _load("m0_ab")
m0_benchmark = _load("m0_benchmark")


# ── m0_ab ───────────────────────────────────────────────────────────────

def test_ab_variants_differ_only_in_the_style_instruction():
    variants = m0_ab.build_prompts("fast-climax")
    assert set(variants) == {"A", "B", "C"}
    a, b, c = (variants[k][0] for k in ("A", "B", "C"))
    assert "请模仿" in a and "鲁迅" in a          # A = 旧写法
    assert "请模仿" not in b                      # B = 手法规格，不得要求模仿
    assert "叙事手法" in b
    assert "请模仿" not in c                      # C = 默认


def test_ab_uses_only_a_public_domain_author():
    """A 组基线必须用公版作家，避免测试中生成模仿在世作家的内容。"""
    author = m0_ab.BASELINE_AUTHOR
    assert author["name"] == "鲁迅"
    assert 1936 + 50 < 2026, "the baseline author must be in the public domain"


def test_ab_chapter_brief_is_identical_across_variants():
    """用户提示三组共用，变量只应是风格指令。"""
    v = m0_ab.build_prompts("fast-climax")
    assert v["A"][1] == v["B"][1] == v["C"][1] == ""


def test_ab_brief_renders():
    text = m0_ab.CHAPTER_BRIEF.format(chapter_no=2, word_target=900)
    assert "第 2 章" in text
    assert "900" in text


# ── m0_benchmark ────────────────────────────────────────────────────────

def test_spearman_is_monotonic():
    assert m0_benchmark.spearman([1, 2, 3, 4], [1, 2, 3, 4]) == pytest.approx(1.0)
    assert m0_benchmark.spearman([1, 2, 3, 4], [4, 3, 2, 1]) == pytest.approx(-1.0)


def test_spearman_handles_ties():
    r = m0_benchmark.spearman([1, 1, 2, 2], [1, 1, 2, 2])
    assert r == pytest.approx(1.0)


def test_rank_uses_average_ranks():
    assert m0_benchmark.rank([10, 20, 20, 30]) == [1.0, 2.5, 2.5, 4.0]


def test_percentile():
    vals = list(range(1, 11))
    assert m0_benchmark.percentile(vals, 0.0) == 1
    assert m0_benchmark.percentile(vals, 1.0) == 10
    assert m0_benchmark.percentile(vals, 0.5) == pytest.approx(5.5)


def test_benchmark_end_to_end_on_synthetic_corpus(tmp_path, capsys):
    """用人工构造的语料跑一遍完整流程：分数与标签应当正相关。"""
    corpus_dir = tmp_path / "corpus"
    corpus_dir.mkdir()

    # "AI 味重" = 高度模板化的短句堆叠
    flat = "他很高兴。他很生气。他很累。他很困。他站起来。他坐下。他走了。他回来了。他又走了。他又回来了。"
    # "味轻" = 长短交错、对话密集、意象具体
    varied = (
        "老周蹲下去，用镊子夹起地上一根毛发。毛是白的。\n\n"
        "他抬头看了看六号房的门牌，又看了看自己的手。指甲缝里也有白的。\n\n"
        "“你昨天来过？”他问。\n\n"
        "女人没回答。她把伞收了，水珠顺着伞骨滴在地板上，一下，两下，然后就没有了。\n\n"
        "老周等了很久。他决定不问第二遍。有些事情，问出来就得处理，"
        "不问就还能再拖一个礼拜。\n\n"
        "她把外套搭在椅背上，走过去把灯关了一半。\n\n"
        "“六号房空着。”\n\n"
        "“我知道。”"
    )

    names, labels = [], []
    for i in range(4):
        n = f"flat_{i:02d}.txt"
        (corpus_dir / n).write_text(flat * 3, encoding="utf-8")
        names.append(n)
        labels.append("2")
    for i in range(4):
        n = f"varied_{i:02d}.txt"
        (corpus_dir / n).write_text(varied * 3, encoding="utf-8")
        names.append(n)
        labels.append("0")

    label_file = tmp_path / "labels.csv"
    label_file.write_text(
        "file,label\n" + "\n".join(f"{n},{l}" for n, l in zip(names, labels)) + "\n",
        encoding="utf-8",
    )

    argv = sys.argv
    sys.argv = ["m0_benchmark.py", str(corpus_dir), "--labels", str(label_file)]
    try:
        rc = m0_benchmark.main()
    finally:
        sys.argv = argv

    assert rc == 0
    out = capsys.readouterr().out
    assert "Spearman" in out
    # AI 味指数与「AI 味」标签必须正相关（模板文本指数高、标签也高）
    assert "Spearman = +1.000" in out


def test_benchmark_reports_too_few_samples(tmp_path, capsys):
    corpus_dir = tmp_path / "c"
    corpus_dir.mkdir()
    (corpus_dir / "a.txt").write_text("只有一份。", encoding="utf-8")
    label_file = tmp_path / "l.csv"
    label_file.write_text("file,label\na.txt,1\n", encoding="utf-8")

    argv = sys.argv
    sys.argv = ["m0_benchmark.py", str(corpus_dir), "--labels", str(label_file)]
    try:
        rc = m0_benchmark.main()
    finally:
        sys.argv = argv
    assert rc == 1
    assert "样本不足" in capsys.readouterr().out
