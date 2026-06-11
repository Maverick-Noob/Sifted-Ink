"""
Configuration loading — from YAML file, environment variables, or interactive input.
"""

import os
import yaml
from .models import StoryConfig, UserNPC
from .agents import PROVIDER_REGISTRY, list_providers, resolve_api_key


def _detect_provider(model: str, explicit_provider: str = "") -> str:
    """
    Auto-detect the API provider from the model name prefix.
    If an explicit provider is given and valid, use it.
    """
    if explicit_provider and explicit_provider in PROVIDER_REGISTRY:
        return explicit_provider

    model_lower = model.lower()

    # Match by model name prefix patterns
    patterns = [
        (["claude"], "anthropic"),
        (["gpt-", "o1", "o3", "o4"], "openai"),
        (["gemini"], "google"),
        (["deepseek"], "deepseek"),
        (["moonshot"], "moonshot"),
        (["glm-", "chatglm"], "zhipu"),
        (["qwen", "tongyi"], "qwen"),
        (["baichuan"], "baichuan"),
        (["abab"], "minimax"),
        (["grok"], "grok"),
        (["mistral"], "mistral"),
        (["command"], "cohere"),
    ]

    for prefixes, provider in patterns:
        if any(model_lower.startswith(p) for p in prefixes):
            return provider

    # Fallback: keep explicit provider, or default to anthropic
    return explicit_provider or "anthropic"


def load_config_from_yaml(filepath: str) -> StoryConfig:
    """Load story configuration from a YAML file."""
    with open(filepath, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not data:
        raise ValueError(f"配置文件 {filepath} 为空")

    # Resolve API key: file > env var
    api_key = data.get("api_key", "") or os.environ.get("SIFTED_INK_API_KEY", "")

    # Resolve token budget: 0 or missing = unlimited
    raw_budget = data.get("total_token_budget", 0)
    token_budget = raw_budget if raw_budget and raw_budget > 0 else None

    config = StoryConfig(
        protagonist_name=data.get("protagonist_name", ""),
        protagonist_traits=data.get("protagonist_traits", ""),
        world_setting=data.get("world_setting", ""),
        story_start=data.get("story_start", ""),
        story_end=data.get("story_end", ""),
        target_word_count=data.get("target_word_count", 8000),
        writing_style=data.get("writing_style", ""),
        npc_name_style=data.get("npc_name_style", "default"),
        protagonist_mode=data.get("protagonist_mode", "spotlight"),
        protagonist_count=data.get("protagonist_count", 1),
        protagonist_order=data.get("protagonist_order", ""),
        npc_mode=data.get("npc_mode", "parallel"),
        quality_mode=data.get("quality_mode", "balanced"),
        naming_style=data.get("naming_style", ""),
        user_npcs=[UserNPC(**n) for n in data.get("user_npcs", [])],
        front_matter=data.get("front_matter", []),
        api_key=api_key,
        model=data.get("model", "claude-sonnet-4-6"),
        api_provider=data.get("api_provider", "anthropic"),
        api_base_url=data.get("api_base_url", ""),
        max_npcs=data.get("max_npcs", 30),
        total_token_budget=token_budget,
        num_versions=data.get("num_versions", 3),
        max_chapters=data.get("max_chapters", 30),
        version_timeout_seconds=data.get("version_timeout_seconds", 1800),
        max_tokens_per_call=data.get("max_tokens_per_call", 4000),
        repeat_similarity_threshold=data.get("repeat_similarity_threshold", 0.9),
    )

    # Auto-detect API provider from model name prefix
    config.api_provider = _detect_provider(config.model, config.api_provider)

    errors = config.validate()
    if errors:
        raise ValueError("配置验证失败:\n" + "\n".join(f"  - {e}" for e in errors))

    return config


def load_config_interactive() -> StoryConfig:
    """Interactively prompt user for story configuration."""
    print("\n" + "=" * 60)
    print("  选墨集（Sifted-Ink）— 交互式配置")
    print("=" * 60 + "\n")

    protagonist_name = _prompt("主角姓名", "林远")
    protagonist_traits = _prompt_multiline(
        "主角性格、动机、初始能力",
        "勇敢但冲动，渴望为家族复仇，擅长剑术，具备初级火系魔法"
    )
    world_setting = _prompt_multiline(
        "世界背景（时代、规则、魔法/科技水平）",
        "架空奇幻世界，中世纪水平，存在元素魔法体系，人类与精灵、矮人共存"
    )
    story_start = _prompt_multiline(
        "故事开头（初始场景或事件）",
        "深夜，林远在家族废墟中发现了一封父亲留下的密信，信中提到了一件传说中的神器——'炎之心'。"
    )
    story_end = _prompt_multiline(
        "故事结尾（留空则由 AI 自动设计结局）",
        "林远找到炎之心，击败幕后黑手，成为新一代的火焰守护者。"
    )
    if not story_end.strip():
        print("  (将自动生成戏剧性结局)")

    target_word_count = int(_prompt("目标总字数", "8000"))
    num_versions = int(_prompt("并行预演版本数 (1-500，推荐 3~10)", "3"))
    max_npcs = int(_prompt("NPC 数量上限", "30"))
    budget_input = _prompt("总 token 预算（0=不限制）", "0")
    total_token_budget = int(budget_input) if int(budget_input) > 0 else None

    model = _prompt("模型名称", "claude-sonnet-4-6")
    api_provider = _prompt(
        "API 提供商\n"
        "  anthropic/openai/google/deepseek/moonshot/zhipu/qwen/baichuan/minimax/grok/mistral/cohere/custom",
        "anthropic"
    )
    api_key = _prompt(
        f"API Key（留空则使用环境变量 {PROVIDER_REGISTRY.get(api_provider, {}).get('api_key_env', 'SIFTED_INK_API_KEY')}）",
        ""
    )
    # Resolve API key from provider-specific env var
    resolved_key = api_key or resolve_api_key(api_provider, "")

    # Auto-detect provider from model if not explicitly set
    api_provider = _detect_provider(model, api_provider)

    config = StoryConfig(
        protagonist_name=protagonist_name,
        protagonist_traits=protagonist_traits,
        world_setting=world_setting,
        story_start=story_start,
        story_end=story_end,
        target_word_count=target_word_count,
        api_key=resolved_key,
        model=model,
        api_provider=api_provider,
        max_npcs=max_npcs,
        total_token_budget=total_token_budget,
        num_versions=num_versions,
    )

    errors = config.validate()
    if errors:
        raise ValueError("配置验证失败:\n" + "\n".join(f"  - {e}" for e in errors))

    return config


def _prompt(label: str, default: str = "") -> str:
    """Prompt for a single-line input."""
    if default:
        value = input(f"  {label} [{default}]: ").strip()
        return value if value else default
    else:
        while True:
            value = input(f"  {label}: ").strip()
            if value:
                return value
            print("  (此项不能为空)")


def _prompt_multiline(label: str, default: str = "") -> str:
    """Prompt for multi-line input. Enter empty line to finish."""
    print(f"  {label}:")
    if default:
        print(f"  (默认: {default[:60]}...)")
        print(f"  输入 '.' 使用默认值，输入多行内容后空行结束：")
    else:
        print(f"  输入多行内容后空行结束：")

    lines = []
    while True:
        line = input()
        if line == ".":
            return default
        if line == "":
            if lines:
                break
            elif default:
                return default
        else:
            lines.append(line)

    return "\n".join(lines)


def ask_token_budget(default: int | None = None) -> int | None:
    """Ask user whether to set a total token budget. Returns None for unlimited."""
    default_label = f"{default}" if default else "不限制"
    print(f"\n  当前总 token 预算: {default_label}")
    answer = input("  是否设置 token 预算上限？(输入数字/n=不限制): ").strip().lower()
    if answer == "n" or answer == "":
        return None  # unlimited
    else:
        try:
            val = int(answer)
            return val if val > 0 else None
        except ValueError:
            print(f"  输入无效，不限制 token 预算")
            return None
