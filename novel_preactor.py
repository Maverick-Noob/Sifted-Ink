#!/usr/bin/env python3
"""
选墨集 / Sifted-Ink — Multi-Agent Pre-rehearsal Novel Generator CLI.

Usage:
    python -m novel_preactor --config story_config.yaml
    python -m novel_preactor --interactive
    python -m novel_preactor --web
    python -m novel_preactor --config story_config.yaml --budget 200000 --output ./output
"""

import argparse
import asyncio
import os
import re
import sys
import time
from pathlib import Path

from .config import load_config_from_yaml, load_config_interactive, ask_token_budget
from .constraints import ShutdownHandler
from .preactor import run_pre_actor
from .evaluator import evaluate_versions
from .writer import save_novel, save_eval_log, generate_novel
import yaml
from .agents import LLMClient
from .naming import NamingEngine
from .utils import logger


def parse_args():
    parser = argparse.ArgumentParser(
        description="选墨集 / Sifted-Ink — 多 Agent 预演故事生成器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python -m novel_preactor --web
  python -m novel_preactor --config story_config.yaml
  python -m novel_preactor --interactive
  python -m novel_preactor --config story.yaml --budget 200000 --output ./output
        """,
    )

    parser.add_argument(
        "--config", "-c",
        type=str,
        help="YAML 配置文件路径",
    )
    parser.add_argument(
        "--interactive", "-i",
        action="store_true",
        help="交互式配置模式",
    )
    parser.add_argument(
        "--budget", "-b",
        type=int,
        default=None,
        help="总 token 预算（覆盖配置文件中的值）",
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        default=".",
        help="输出目录（默认当前目录）",
    )
    parser.add_argument(
        "--web", "-w",
        action="store_true",
        help="启动 Web UI 界面",
    )
    parser.add_argument(
        "--port", "-p",
        type=int,
        default=8000,
        help="Web UI 端口 (默认 8000)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="详细日志输出",
    )

    return parser.parse_args()


BANNER = r"""
   ███████╗ ██╗ ███████╗ ████████╗ ███████╗ ██████╗        ██╗ ███╗   ██╗ ██╗  ██╗
   ██╔════╝ ██║ ██╔════╝ ╚══██╔══╝ ██╔════╝ ██╔══██╗       ██║ ████╗  ██║ ██║ ██╔╝
   ███████╗ ██║ █████╗      ██║    █████╗   ██║  ██║       ██║ ██╔██╗ ██║ █████╔╝
   ╚════██║ ██║ ██╔══╝      ██║    ██╔══╝   ██║  ██║       ██║ ██║╚██╗██║ ██╔═██╗
   ███████║ ██║ ██║         ██║    ███████╗ ██████╔╝       ██║ ██║ ╚████║ ██║  ██╗
   ╚══════╝ ╚═╝ ╚═╝         ╚═╝    ╚══════╝ ╚═════╝        ╚═╝ ╚═╝  ╚═══╝ ╚═╝  ╚═╝

          ███████╗ ██╗ ███████╗ ████████╗ ███████╗ ██████╗
          ██╔════╝ ██║ ██╔════╝ ╚══██╔══╝ ██╔════╝ ██╔══██╗
          ███████╗ ██║ █████╗      ██║    █████╗   ██║  ██║
          ╚════██║ ██║ ██╔══╝      ██║    ██╔══╝   ██║  ██║
          ███████║ ██║ ██║         ██║    ███████╗ ██████╔╝
          ╚══════╝ ╚═╝ ╚═╝         ╚═╝    ╚══════╝ ╚═════╝

                    选墨集 / Sifted-Ink  v1.0
          千墨选一，落纸成书 — Selected ink, eternal story.
"""


def _show_banner():
    """Print the project banner to stdout."""
    # Use print for raw output, not through logger
    sys.stdout.write(BANNER + "\n\n")
    sys.stdout.flush()


async def main_async(args):
    """Async main entry point."""
    _show_banner()

    # --- Web UI mode ---
    if args.web:
        from .webui.app import app
        import uvicorn

        # Print a clickable URL before uvicorn takes over
        sys.stdout.write(f"\n  🌐 Web UI → http://localhost:{args.port}\n\n")
        sys.stdout.flush()

        config = uvicorn.Config(app, host="0.0.0.0", port=args.port, log_level="info")
        server = uvicorn.Server(config)
        await server.serve()
        return

    # --- Load configuration ---
    if args.config:
        config_path = Path(args.config)
        if not config_path.exists():
            logger.error(f"配置文件不存在: {args.config}")
            sys.exit(1)
        logger.info(f"从配置文件加载: {args.config}")
        config = load_config_from_yaml(str(config_path))
    elif args.interactive:
        config = load_config_interactive()
    else:
        # Default: interactive
        logger.info("未指定配置，进入交互模式")
        config = load_config_interactive()

    # --- Override budget if specified ---
    if args.budget is not None:
        config.total_token_budget = args.budget if args.budget > 0 else None
        logger.info(f"Token 预算已覆盖: {config.total_token_budget or '不限制'}")

    # --- Ensure output directory exists ---
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    # --- Validate ---
    errors = config.validate()
    if errors:
        logger.error("配置验证失败:")
        for e in errors:
            logger.error(f"  - {e}")
        sys.exit(1)

    # --- Display summary ---
    logger.info("")
    logger.info("=" * 50)
    logger.info(f"  主角: {config.protagonist_name}")
    logger.info(f"  世界观: {config.world_setting[:60]}...")
    logger.info(f"  目标结局: {config.story_end[:60]}...")
    logger.info(f"  目标字数: {config.target_word_count}")
    logger.info(f"  并行版本: {config.num_versions}")
    logger.info(f"  Token 预算: {config.total_token_budget or '无限制'}")
    logger.info(f"  模型: {config.model} ({config.api_provider})")
    logger.info(f"  输出目录: {output_dir.absolute()}")
    logger.info("=" * 50)
    logger.info("")

    # --- Confirm before starting ---
    if not args.config:
        # For interactive mode, already confirmed via prompts
        pass
    else:
        response = input("  开始预演？(y/n): ").strip().lower()
        if response not in ("y", "yes", ""):
            logger.info("用户取消。")
            return

    # --- Setup shutdown handler ---
    shutdown = ShutdownHandler().install()
    result = None  # initialize for safe KeyboardInterrupt handling

    try:
        # --- Phase 1: Pre-rehearsal ---
        logger.info("\n📝 阶段 1/3: 并行预演中...\n")
        result = await run_pre_actor(config, shutdown)

        if shutdown.shutdown_requested:
            logger.warning("\n⚠ 用户中断 — 保存已完成版本...")
            _save_intermediate_result(result, str(output_dir))
            return

        # --- Phase 2: Evaluation ---
        logger.info("\n📊 阶段 2/3: 评估版本中...\n")
        result = await evaluate_versions(result, shutdown)

        if shutdown.shutdown_requested:
            logger.warning("\n⚠ 用户中断 — 保存已完成版本...")
            _save_intermediate_result(result, str(output_dir))
            return

        # --- Phase 3: Naming & summarization ---
        logger.info("\n📖 阶段 3/4: 情节总结与起名...\n")

        novel_text = generate_novel(result)
        story_name = f"{config.protagonist_name}的传奇"
        story_meta = {}

        has_content = any(v.chapter_count > 0 for v in result.versions)
        if has_content and novel_text and len(novel_text.strip()) > 200:
            try:
                client = LLMClient(config)
                engine = NamingEngine(client)
                naming_data = await engine.name_story(
                    config, novel_text,
                    style_name=config.naming_style,
                )
                story_name = naming_data.get("best_name", story_name)
                story_meta = {
                    "story_name": story_name,
                    "plot_summary": naming_data.get("summary", ""),
                    "candidate_names": naming_data.get("candidates", []),
                    "best_name_reason": f"命名风格: {naming_data.get('style', '默认')}",
                    "style_tags": [],
                }
            except Exception as e:
                logger.warning(f"故事命名失败: {e}")

        # --- Phase 4: Save output ---
        logger.info("\n💾 阶段 4/4: 保存文件...\n")

        novel_path = save_novel(result, str(output_dir), story_name=story_name)
        eval_path = save_eval_log(result, str(output_dir), story_name=story_name, story_meta=story_meta)

        # Save generation parameters
        from datetime import datetime as _dt
        ts = _dt.now().strftime("%Y%m%d_%H%M%S")
        safe_name = re.sub(r'[\\/*?:"<>|]', '_', story_name)[:30]
        params_path = os.path.join(
            str(output_dir), f"{safe_name}_{ts}_v{result.winning_version_id}_params.yaml",
        )
        params_data = {
            "protagonist_name": config.protagonist_name,
            "protagonist_traits": config.protagonist_traits,
            "world_setting": config.world_setting,
            "story_start": config.story_start,
            "story_end": config.story_end,
            "target_word_count": config.target_word_count,
            "num_versions": config.num_versions,
            "max_npcs": config.max_npcs,
            "max_chapters": config.max_chapters,
            "writing_style": config.writing_style or "默认",
            "naming_style": config.naming_style or "自动",
            "npc_name_style": config.npc_name_style,
            "front_matter": config.front_matter,
            "model": config.model,
            "api_provider": config.api_provider,
            "generation_result": {
                "story_name": story_name,
                "winning_version": result.winning_version_id,
                "total_tokens": result.total_tokens_used,
                "time_elapsed": round(result.time_elapsed_seconds, 1),
            },
        }
        with open(params_path, "w", encoding="utf-8") as f:
            yaml.dump(params_data, f, allow_unicode=True, default_flow_style=False)
        logger.info(f"⚙️ 生成参数已保存至: {params_path}")

        # --- Final summary ---
        logger.info("")
        logger.info("=" * 60)
        logger.info("  ✅ 小说生成完成！")
        logger.info(f"  📖 书名: 《{story_name}》")
        logger.info(f"  📝 摘要: {story_meta.get('plot_summary', '')[:100]}...")
        logger.info(f"  📖 小说文件: {novel_path}")
        logger.info(f"  📊 评估日志: {eval_path}")
        logger.info(f"  🏆 最佳版本: {result.winning_version_id}")
        logger.info(f"  ⏱ 总耗时: {result.time_elapsed_seconds:.1f}秒")
        logger.info(f"  🔢 总 Token: {result.total_tokens_used}")
        logger.info("=" * 60)

    except KeyboardInterrupt:
        logger.warning("\n⚠ Ctrl+C 收到，保存当前进度...")
        if result is not None:
            _save_intermediate_result(result, str(output_dir))

    finally:
        shutdown.uninstall()


def _save_intermediate_result(result, output_dir: str):
    """Save whatever progress we have on interrupt."""
    if result is None:
        logger.warning("没有可保存的进度。")
        return

    try:
        completed = [v for v in result.versions if v.reached_ending]
        if completed:
            # Pick best completed version
            best = max(completed, key=lambda v: v.total_words)
            result.winning_version_id = best.version_id
            save_novel(result, output_dir)

        save_eval_log(result, output_dir)
        logger.info(f"进度已保存至: {output_dir}")
    except Exception as e:
        logger.error(f"保存进度时出错: {e}")


def main():
    """Synchronous entry point."""
    args = parse_args()

    if args.verbose:
        logger.setLevel(10)  # DEBUG

    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
