#!/usr/bin/env python3
"""
M0 · Q2 验证工具 —— 「手法规格」vs「直接模仿作家」的盲评样本生成

生成三组同源章节，只有**风格指令**不同，其余（故事设定、章节简报、模型、参数、
随机种子策略）完全一致，从而隔离出唯一变量：

    A 组  旧写法：提示词注入「请模仿 **{作家}** 的写作风格」+ 代表作
    B 组  新写法：注入 narrative_techniques.json 的可执行手法规格
    C 组  不指定：默认叙事

A 组刻意选用**已故 50 年以上的公版作家**（鲁迅，1936 年逝世，作品 1987 年起进入
公有领域）作为基线，避免在测试中生成模仿在世作家的内容；结论对公版作家同样成立。

用法
----
    export ANTHROPIC_API_KEY=...            # 或 SIFTED_INK_API_KEY
    python tools/m0_ab.py --model claude-sonnet-4-6 --chapters 3
    python tools/m0_ab.py --dry-run          # 只打印提示词，不花钱

产出
----
    m0_output/
      A/  chapter_01.txt ...        ← 给盲评者看的（不含任何标识）
      B/  chapter_01.txt ...
      C/  chapter_01.txt ...
      blind_key.json                ← 揭盲用，**评审时不要给盲评者看**
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from novel_preactor.agents import LLMClient  # noqa: E402
from novel_preactor.models import StoryConfig  # noqa: E402
from novel_preactor.utils import build_technique_prompt  # noqa: E402
from novel_preactor.agents import NarrativeWriter  # noqa: E402

# ── A 组基线：公版作家（鲁迅，1936 年逝世，1987 年起进入公有领域）──────────
# 保留旧版的提示词格式，用于复现"直接模仿"的读感基线。
BASELINE_AUTHOR = {
    "name": "鲁迅",
    "style": (
        "中国现代文学奠基人。以冷峻犀利的笔触解剖国民性，将西方现代小说技巧与"
        "本土批判精神融合，开创了中国白话小说的现实主义传统。"
    ),
    "works": ["《狂人日记》", "《阿Q正传》"],
}


def baseline_style_prompt() -> str:
    """旧版「模仿作家」提示词格式（原样复现，用于基线对比）。"""
    works = "、".join(BASELINE_AUTHOR["works"][:2])
    return f"""
## 写作风格要求
请模仿 **{BASELINE_AUTHOR['name']}** 的写作风格进行创作：
- {BASELINE_AUTHOR['style']}
- 代表作品：{works}

在叙事中体现这位作家的语言特色、叙事节奏和审美取向，但不要直接抄袭其作品内容。
"""


# ── 三组共用的章节简报（必须完全一致）──────────────────────────────────

CHAPTER_BRIEF = """请写第 {chapter_no} 章。

## 故事设定
- 主角：林远，20 岁，勇敢但冲动，渴望为家族复仇；擅长剑术，具备初级火系魔法
- 世界：架空奇幻"苍澜大陆"，中世纪文明，四元素魔法体系，人类与精灵、矮人三族共存
- 起因：深夜，林远在家族废墟挖掘父亲遗物时，发现一块刻有火焰纹章的石板，
  石板浮现文字"炎之心，藏于龙眠谷"；此时外面传来脚步声，有人正在接近废墟
- 目标结局：林远找到炎之心，击败幕后黑手（王国宰相莫里斯），成为新一代火焰守护者

## 本章要写什么
- 林远刚读完石板上的字，脚步声逼近；他必须在"带走石板"和"先看清来人"之间做选择
- 本章要交代清楚：他叫不上来那个人的名字，只记得对方左手少了半截小指
- 结尾要落在一个具体的画面上，不要用总结句收尾

## 硬性要求
- 第三人称限知视角，不要写林远视野之外的事
- 目标 {word_target} 字左右
- 不要出现"第X章"这样的标题文字
"""

WORD_TARGET = 900


def build_prompts(technique_id: str) -> dict[str, tuple[str, str]]:
    """返回 {组名: (系统提示, 用户提示)}，三组的用户提示完全相同。"""
    base_system = NarrativeWriter.WRITER_SYSTEM_PROMPT

    variants = {
        "A": base_system + "\n" + baseline_style_prompt(),
        "B": base_system + "\n" + build_technique_prompt(technique_id),
        "C": base_system,
    }
    return {k: (v, "") for k, v in variants.items()}


def main() -> int:
    ap = argparse.ArgumentParser(description="M0 Q2 盲评样本生成")
    ap.add_argument("--model", default="claude-sonnet-4-6")
    ap.add_argument("--provider", default="anthropic")
    ap.add_argument("--chapters", type=int, default=3, help="每组生成几章")
    ap.add_argument("--technique", default="fast-climax", help="B 组使用的手法 id")
    ap.add_argument("--out", type=Path, default=Path("m0_output"))
    ap.add_argument("--dry-run", action="store_true", help="只打印提示词，不调用 API")
    args = ap.parse_args()

    config = StoryConfig(
        protagonist_name="林远",
        protagonist_traits="勇敢但冲动",
        world_setting="苍澜大陆",
        story_start="深夜的家族废墟",
        story_end="找到炎之心",
        model=args.model,
        api_provider=args.provider,
        api_key=os.environ.get("SIFTED_INK_API_KEY", "") or os.environ.get("ANTHROPIC_API_KEY", ""),
        max_tokens_per_call=4000,
    )

    variants = build_prompts(args.technique)

    if args.dry_run:
        for key in ("A", "B", "C"):
            system, _ = variants[key]
            print("=" * 70)
            print(f"### {key} 组 · 系统提示尾部 600 字")
            print("=" * 70)
            print(system[-600:])
            print()
        print("### 三组共用的用户提示")
        print(CHAPTER_BRIEF.format(chapter_no=1, word_target=WORD_TARGET))
        return 0

    client = LLMClient(config)
    blind_key: dict[str, dict] = {}

    for key, (system, _) in variants.items():
        out_dir = args.out / key
        out_dir.mkdir(parents=True, exist_ok=True)
        for ch in range(1, args.chapters + 1):
            user = CHAPTER_BRIEF.format(chapter_no=ch, word_target=WORD_TARGET)
            print(f"[{key}] 生成第 {ch}/{args.chapters} 章 …")
            text, tokens = client.call(system, user, max_tokens=2500, temperature=0.8)
            path = out_dir / f"chapter_{ch:02d}.txt"
            path.write_text(text, encoding="utf-8")
            blind_key.setdefault(key, {})[path.name] = {"tokens": tokens}
            print(f"    → {path}  ({len(text)} 字, {tokens} tokens)")

    (args.out / "blind_key.json").write_text(
        json.dumps(
            {"note": "揭盲用；盲评阶段不要把这个文件交给评审者",
             "variants": {"A": "旧写法：模仿公版作家", "B": f"新手法规格：{args.technique}",
                          "C": "不指定（默认叙事）"},
             "files": blind_key},
            ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n完成。样本在 {args.out}/A|B|C/，揭盲表在 {args.out}/blind_key.json")
    print("下一步：把 A/B/C 三个目录（不含 blind_key.json）交给 5 位盲评者打分。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
