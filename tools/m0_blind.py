#!/usr/bin/env python3
"""
M0 · Q2 盲评分组打包器

把 A/B/C 三组样本打乱并重命名，生成一个**不含任何组别标识**的盲评包，
同时把映射表单独保存（交给盲评者时**不能**包含映射表）。

用法
----
    python tools/m0_blind.py --src m0_output --out m0_blind --seed 20261024

产出
----
    m0_blind/
      samples/sample_01.txt … sample_09.txt   ← 给盲评者
      m0_blind/评分表.md                        ← 打印用（可选拷贝）
      揭盲表_key.json                           ← **不要**给盲评者
"""

from __future__ import annotations

import argparse
import json
import random
import shutil
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(description="M0 盲评分组打包")
    ap.add_argument("--src", type=Path, default=Path("m0_output"))
    ap.add_argument("--out", type=Path, default=Path("m0_blind"))
    ap.add_argument("--seed", type=int, default=20261024, help="随机种子（换种子=换卷）")
    ap.add_argument("--groups", default="ABC")
    args = ap.parse_args()

    files = []
    for g in args.groups:
        for p in sorted((args.src / g).glob("*.txt")):
            if p.read_text(encoding="utf-8").strip():
                files.append((g, p))
    if len(files) < 3:
        print(f"样本不足：只找到 {len(files)} 个非空样本")
        return 1

    rng = random.Random(args.seed)
    rng.shuffle(files)

    samples_dir = args.out / "samples"
    if samples_dir.exists():
        shutil.rmtree(samples_dir)
    samples_dir.mkdir(parents=True, exist_ok=True)

    key = {}
    for i, (g, p) in enumerate(files, start=1):
        name = f"sample_{i:02d}.txt"
        shutil.copy2(p, samples_dir / name)
        key[name] = {"group": g, "source": str(p.relative_to(args.src.parent))}

    (args.out / "揭盲表_key.json").write_text(
        json.dumps(
            {
                "note": "揭盲用。盲评阶段不要把这���文件交给评审者。",
                "seed": args.seed,
                "samples": key,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"盲评包已生成：{samples_dir}")
    print(f"  样本数：{len(files)}")
    print(f"  种子：{args.seed}（换种子可生成不同卷）")
    print()
    print("各组样本数：")
    counts: dict[str, int] = {}
    for name, info in key.items():
        counts[info["group"]] = counts.get(info["group"], 0) + 1
    for g, c in sorted(counts.items()):
        print(f"  {g} 组：{c} 段")
    print()
    print(f"→ 把 {samples_dir} 目录交给盲评者（**不要**给 揭盲表_key.json）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
