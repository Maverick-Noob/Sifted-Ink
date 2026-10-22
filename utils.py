"""
Utility functions: edit distance, JSON extraction, logging, content moderation.
"""

import json
import difflib
import logging
import re
import sys
from typing import Optional


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def setup_logger(name: str = "narrative_prism", level: int = logging.INFO) -> logging.Logger:
    """Create a logger with console + file handlers."""
    logger = logging.getLogger(name)
    logger.setLevel(level)

    if not logger.handlers:
        # Console handler
        console = logging.StreamHandler(sys.stdout)
        console.setLevel(level)
        fmt = logging.Formatter(
            "[%(asctime)s] %(levelname)-7s %(message)s",
            datefmt="%H:%M:%S",
        )
        console.setFormatter(fmt)
        logger.addHandler(console)

        # File handler — save to logs/ directory
        try:
            import os as _os
            from datetime import datetime as _dt
            log_dir = _os.path.join(_os.getcwd(), "logs")
            _os.makedirs(log_dir, exist_ok=True)
            log_file = _os.path.join(
                log_dir,
                f"sifted_ink_{_dt.now().strftime('%Y%m%d_%H%M%S')}.log",
            )
            file_handler = logging.FileHandler(log_file, encoding="utf-8")
            file_handler.setLevel(logging.DEBUG)
            file_fmt = logging.Formatter(
                "[%(asctime)s] %(levelname)-7s [%(name)s] %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
            file_handler.setFormatter(file_fmt)
            logger.addHandler(file_handler)
            # Log file path at debug level so it's visible in file but not on console
            logger.debug(f"日志文件: {log_file}")
        except Exception:
            pass  # never let file logging break the app

    return logger


logger = setup_logger()


# ---------------------------------------------------------------------------
# Text similarity (for repeat-action detection)
# ---------------------------------------------------------------------------

def text_similarity(text_a: str, text_b: str) -> float:
    """
    Calculate similarity between two text strings using SequenceMatcher.
    Returns a float between 0 (completely different) and 1 (identical).
    """
    if not text_a and not text_b:
        return 1.0
    if not text_a or not text_b:
        return 0.0
    return difflib.SequenceMatcher(None, text_a, text_b).ratio()


def detect_repeated_action(
    actions: list, text_getter, threshold: float = 0.9, window: int = 3
) -> bool:
    """
    Check if the last `window` actions are too similar (above `threshold`).

    Args:
        actions: list of recent actions
        text_getter: function to extract the comparison text from an action
        threshold: similarity threshold (default 0.9)
        window: how many recent actions to compare (default 3)

    Returns True if repetition is detected.
    """
    if len(actions) < window:
        return False

    recent = actions[-window:]
    texts = [text_getter(a) for a in recent]

    similar_count = 0
    for i in range(len(texts)):
        for j in range(i + 1, len(texts)):
            if text_similarity(texts[i], texts[j]) > threshold:
                similar_count += 1

    # If all pairs are similar (everyone looks like everyone else)
    total_pairs = window * (window - 1) / 2
    return similar_count >= total_pairs * 0.5


# ---------------------------------------------------------------------------
# JSON extraction from LLM output
# ---------------------------------------------------------------------------

def _repair_json(text: str) -> Optional[str]:
    """
    Attempt to repair common JSON formatting errors from LLM output:
      1. Trailing commas: {"a": 1,} → {"a": 1}
      2. Missing quotes on keys: {a: 1} → {"a": 1}
      3. Single-quoted values: {'a': 'hello'} → {"a": "hello"}
      4. // or # comment lines
      5. Extra text after the closing brace
      6. Unescaped double quotes inside string values (LLM dialogue)
    """
    import re as _re

    # Remove single-line comments
    text = _re.sub(r'//[^\n]*', '', text)
    text = _re.sub(r'#[^\n]*', '', text)

    # Fix single-quoted keys and values
    text = _re.sub(r"'([^']+)'\s*:", r'"\1":', text)
    text = _re.sub(r":\s*'([^']*)'", r': "\1"', text)

    # Fix unquoted keys
    text = _re.sub(r'(?<![{"\s])(\w+)(?=\s*:)', r'"\1"', text)

    # Remove trailing commas
    text = _re.sub(r',\s*}', '}', text)
    text = _re.sub(r',\s*]', ']', text)

    # Fix unescaped double-quotes inside string values.
    # LLMs often output dialogue like: "content": "他说："你好！"再见"
    # We find the value portion of each key-value pair and escape inner quotes.
    text = _fix_unescaped_quotes(text)

    return text


def _fix_unescaped_quotes(text: str) -> str:
    """
    Find unescaped double-quotes inside JSON string values and escape them.
    Handles patterns like: "key": "value with "inner quotes" inside"
    """
    import re as _re

    # Strategy: iterate through string, tracking whether we're inside a JSON
    # string value. When inside a value, unescaped " should become \".
    # A " opens/closes a JSON string unless preceded by \.

    result = []
    i = 0
    in_key = False
    in_value = False
    depth = 0  # brace/bracket nesting

    while i < len(text):
        ch = text[i]

        # Track braces
        if ch == '{' or ch == '[':
            depth += 1
            result.append(ch)
            i += 1
            continue
        elif ch == '}' or ch == ']':
            depth -= 1
            result.append(ch)
            i += 1
            continue

        # Track whether we just passed a key followed by :
        if not in_value and ch == '"':
            # Check if this is preceded by : (i.e., start of a value string)
            # Look back for : possibly with whitespace
            before = text[max(0, i-20):i].rstrip()
            if before.endswith(':'):
                in_value = True
                result.append(ch)
                i += 1
                continue
            elif not in_key and not in_value:
                in_key = True
                result.append(ch)
                i += 1
                continue

        # If we're inside a value string and hit an unescaped "
        if in_value and ch == '"' and (i == 0 or text[i-1] != '\\'):
            # Check if this " is followed by , or } or whitespace+newline → end of value
            after = text[i+1:i+30].lstrip()
            if after and (after[0] in ',}' or after.startswith('\n')):
                # This is the closing quote of the value
                in_value = False
                result.append(ch)
                i += 1
                continue
            else:
                # This is an inner quote — escape it
                result.append('\\"')
                i += 1
                continue

        # End of key string
        if in_key and ch == '"' and (i == 0 or text[i-1] != '\\'):
            in_key = False

        result.append(ch)
        i += 1

    return ''.join(result)


def _safe_parse_json(text: str) -> Optional[dict]:
    """
    Parse text as JSON. Uses json5 for maximum leniency with LLM output.
    Pre-processes to fix unescaped quotes inside string values.
    Returns None for empty/malformed input instead of raising.
    """
    if not text or not text.strip():
        return None

    # Pre-fix unescaped quotes (LLM dialogue in JSON values)
    text = _fix_unescaped_quotes(text)

    try:
        import json5
        parsed = json5.loads(text)
    except ImportError:
        try:
            parsed = json.loads(text)
        except Exception:
            return None
    except Exception:
        try:
            parsed = json.loads(text)
        except Exception:
            return None

    if isinstance(parsed, dict):
        return parsed
    return None


def extract_json(text: str) -> Optional[dict]:
    """
    Extract a JSON object from LLM response text using json5 for maximum
    tolerance. Tries multiple strategies:
      1. Direct parse with json5
      2. Strip markdown code fences ```json ... ```
      3. Find outermost { ... } with brace matching
      4. Repair common formatting errors and retry

    Only returns dict objects — never lists, strings, or other JSON types.
    """
    if not text:
        return None

    original = text

    # ── Strategy 1: Direct parse with json5 ──
    result = _safe_parse_json(text.strip())
    if result is not None:
        return result

    # ── Strategy 2: Remove markdown code fences ──
    for pattern in [
        r"```json\s*\n?(.*?)```",
        r"```\s*\n?(.*?)```",
    ]:
        match = re.search(pattern, text, re.DOTALL)
        if match:
            inner = match.group(1).strip()
            result = _safe_parse_json(inner)
            if result is not None:
                return result
            # Try repair + parse
            try:
                repaired = _repair_json(inner)
                result = _safe_parse_json(repaired)
                if result is not None:
                    return result
            except Exception:
                pass
            text = inner
            break

    # ── Strategy 3: Find outermost { ... } with brace matching ──
    brace_start = text.find("{")
    if brace_start == -1:
        return None

    depth = 0
    brace_end = -1
    for i, ch in enumerate(text[brace_start:], start=brace_start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                brace_end = i
                break

    if brace_end == -1:
        return None

    json_candidate = text[brace_start:brace_end + 1]
    result = _safe_parse_json(json_candidate)
    if result is not None:
        return result

    # ── Strategy 4: Repair and retry ──
    try:
        repaired = _repair_json(json_candidate)
        result = _safe_parse_json(repaired)
        if result is not None:
            return result
    except Exception:
        pass

    # ── Strategy 5: Original with repair ──
    try:
        repaired = _repair_json(original)
        s = repaired.find("{")
        e = repaired.rfind("}")
        if s != -1 and e != -1 and e > s:
            result = _safe_parse_json(repaired[s:e + 1])
            if result is not None:
                return result
    except Exception:
        pass

    return None


# ---------------------------------------------------------------------------
# Word count for Chinese text
# ---------------------------------------------------------------------------

def count_chinese_chars(text: str) -> int:
    """Count Chinese characters (and other meaningful units) in text."""
    # Remove whitespace and punctuation for a rough word count
    # Chinese: each character ~= one word
    # English: count whitespace-separated tokens
    chinese_chars = len(re.findall(r"[一-鿿]", text))
    english_words = len(re.findall(r"[a-zA-Z]+", text))
    return chinese_chars + english_words


# ---------------------------------------------------------------------------
# Safe filename generation
# ---------------------------------------------------------------------------

def safe_filename(name: str, max_len: int = 50) -> str:
    """Convert a string to a safe filename."""
    safe = re.sub(r"[^\w\s-]", "", name)
    safe = re.sub(r"[-\s]+", "_", safe)
    return safe[:max_len].strip("_")


# ---------------------------------------------------------------------------
# Narrative technique loading
#
# NOTE: the former "pick a writer to imitate" feature was removed on
# 2026-10-21. Imitating a named author is a copyright risk (171 of the 183
# entries were NOT in the public domain), and the write prompt used to inject
# the author's name plus their works verbatim. What remains is a library of
# *techniques* — executable style specs with no author attached. A technique
# is a method; copyright protects expression, not methods.
# ---------------------------------------------------------------------------

_NARRATIVE_TECHNIQUES: list[dict] | None = None


def load_narrative_techniques() -> list[dict]:
    """Load narrative techniques from the bundled JSON file. Cached after first call."""
    global _NARRATIVE_TECHNIQUES
    if _NARRATIVE_TECHNIQUES is not None:
        return _NARRATIVE_TECHNIQUES

    import os as _os
    json_path = _os.path.join(_os.path.dirname(__file__), "narrative_techniques.json")
    if not _os.path.exists(json_path):
        logger.warning(f"叙事手法库未找到: {json_path}")
        _NARRATIVE_TECHNIQUES = []
        return _NARRATIVE_TECHNIQUES

    with open(json_path, "r", encoding="utf-8") as f:
        _NARRATIVE_TECHNIQUES = json.load(f)
    return _NARRATIVE_TECHNIQUES


def get_technique_by_id(technique_id: str) -> dict | None:
    """Get a single technique spec by its id (built-in or user-defined)."""
    for t in load_narrative_techniques():
        if t.get("id") == technique_id:
            return t
    for t in load_user_techniques():
        if t.get("id") == technique_id:
            return t
    return None


def get_technique_categories() -> list[str]:
    """Sorted list of unique technique categories."""
    cats = set(t.get("category", "其他") for t in load_narrative_techniques())
    cats.update(t.get("category", "其他") for t in load_user_techniques())
    return sorted(cats)


def get_techniques_by_category(category: str | None = None) -> list[dict]:
    """Get techniques, optionally filtered by category (built-in + user-defined)."""
    techs = load_narrative_techniques() + load_user_techniques()
    if category:
        return [t for t in techs if t.get("category") == category]
    return techs


# ── User-defined techniques ──────────────────────────────────────────────
# A user technique is a free-text description of the author's OWN style.
# Ids are "user:<slug>". No third-party names are ever stored here.

_USER_TECHNIQUES: list[dict] | None = None


def _user_techniques_path() -> str:
    import os as _os
    return _os.path.join(_os.path.dirname(__file__), "user_techniques.json")


def load_user_techniques() -> list[dict]:
    """Load user-defined techniques from user_techniques.json. Cached after first call."""
    global _USER_TECHNIQUES
    if _USER_TECHNIQUES is not None:
        return _USER_TECHNIQUES

    import os as _os
    path = _user_techniques_path()
    if not _os.path.exists(path):
        _USER_TECHNIQUES = []
        return _USER_TECHNIQUES

    try:
        with open(path, "r", encoding="utf-8") as f:
            _USER_TECHNIQUES = json.load(f)
    except Exception as e:  # a broken user file must not break startup
        logger.warning(f"用户自定义叙事手法文件读取失败: {e}")
        _USER_TECHNIQUES = []
    return _USER_TECHNIQUES


def save_user_techniques(techniques: list[dict]) -> None:
    """Persist user-defined techniques."""
    with open(_user_techniques_path(), "w", encoding="utf-8") as f:
        json.dump(techniques, f, ensure_ascii=False, indent=2)
    global _USER_TECHNIQUES
    _USER_TECHNIQUES = techniques


def slugify_technique(name: str) -> str:
    """Build an id-safe slug from a technique name."""
    import re as _re
    slug = _re.sub(r"[^\w一-鿿-]+", "-", name.strip().lower())
    slug = _re.sub(r"-+", "-", slug).strip("-")
    return slug or "technique"


def _custom_technique_block(desc: str, name: str = "") -> str:
    """Prompt block for a user-supplied technique description."""
    label = f"**{name}**" if name else "用户自定义"
    return f"""
## 叙事手法要求
本故事使用 {label} 这一套叙事手法。

{desc}

要求：把上述描述转成**可执行的写作约束**（人称、句长、对话率、描写与心理的配比、禁用词），
不要照抄用户原文的措辞，也不要模仿任何特定在世或已故作家的可识别风格。
"""


def build_technique_prompt(technique_id: str) -> str:
    """
    Build a narrative-technique instruction for the writer prompt.

    `technique_id` may be:
      - an id from narrative_techniques.json
      - "user:<slug>" for a technique saved by the user
      - "custom:<free text>" for an inline description of the user's own style
    Returns an empty string when nothing is selected.
    """
    if not technique_id:
        return ""

    # A technique saved by the user (their own words, no third-party rights)
    if technique_id.startswith("user:"):
        for t in load_user_techniques():
            if t.get("id") == technique_id:
                return _custom_technique_block(t.get("summary", ""), t.get("name", ""))
        logger.warning(f"未知的用户自定义叙事手法 id: {technique_id}（已忽略）")
        return ""

    # Inline free-text description
    if technique_id.startswith("custom:"):
        desc = technique_id[len("custom:"):].strip()
        if not desc:
            return ""
        return _custom_technique_block(desc)

    technique = get_technique_by_id(technique_id)
    if not technique:
        logger.warning(f"未知的叙事手法 id: {technique_id}（已忽略）")
        return ""

    spec = technique.get("spec", {})
    forbidden = spec.get("forbidden", [])
    forbidden_text = "、".join(forbidden) if forbidden else "无"

    return f"""
## 叙事手法要求
本故事使用 **{technique['name']}** 这一套叙事手法（{technique.get('category', '')}）。

{technique.get('summary', '')}

### 可执行规格（必须逐条遵守）
- **叙事人称**：{spec.get('narrative_person', '第三人称限知')}
- **视角距离**：{spec.get('viewpoint_distance', '中')}
- **句长**：中位约 {spec.get('sentence_length_p50', 15)} 字，长句不超过 {spec.get('sentence_length_p90', 30)} 字
- **单段最多**：{spec.get('paragraph_max_sentences', 3)} 句
- **对话占比**：约 {int(float(spec.get('dialogue_ratio', 0.3)) * 100)}%
- **描写占比**：约 {int(float(spec.get('description_ratio', 0.3)) * 100)}%
- **心理活动占比**：约 {int(float(spec.get('psychology_ratio', 0.15)) * 100)}%
- **用词**：{spec.get('vocabulary', '')}
- **意象取材**：{spec.get('imagery', '')}
- **语体**：{spec.get('register', '')}
- **节奏**：{spec.get('rhythm', '')}

### 禁用表达（命中即视为不合格）
{forbidden_text}

### 参考样例（学习节奏与质感，**不要复用其中任何词句**）
{technique.get('sample_paragraph', '')}
"""



# ---------------------------------------------------------------------------
# Content moderation
# ---------------------------------------------------------------------------

SENSITIVE_WORDS = [
    # Violence / gore
    "血腥肢解", "虐杀", "碎尸", "奸杀", "凌迟",
    # Explicit sexual content
    "性交", "做爱", "交媾", "淫穴", "肉棒", "巨乳", "爆乳",
    "强奸", "轮奸", "迷奸", "猥亵", "淫秽",
    # Illegal activities
    "制毒配方", "炸弹制作", "恐怖袭击教程",
    # Hate speech
    "种族灭绝", "屠杀华人",
    # Self-harm promotion
    "自杀教程", "自残方法",
]

def moderate_content(text: str) -> dict:
    """
    Scan generated content for sensitive words.
    Returns: {"flagged": bool, "hits": list[str], "clean": bool}
    """
    hits = []
    for word in SENSITIVE_WORDS:
        if word in text:
            hits.append(word)
    return {
        "flagged": len(hits) > 0,
        "hits": hits,
        "clean": len(hits) == 0,
    }


# ---------------------------------------------------------------------------
# NPC name banks by region
# ---------------------------------------------------------------------------

NPC_NAME_BANKS = {
    "chinese": {
        "label": "中文",
        "surnames": ["林", "王", "李", "张", "刘", "陈", "杨", "赵", "黄", "周",
                      "吴", "徐", "孙", "马", "朱", "胡", "郭", "何", "高", "郑",
                      "叶", "沈", "韩", "唐", "冯", "于", "董", "萧", "程", "曹"],
        "given_male": ["远", "天", "明", "宇", "浩", "然", "逸", "风", "辰", "阳",
                       "轩", "文", "博", "毅", "恒", "泽", "铭", "哲", "翰", "皓"],
        "given_female": ["雪", "月", "瑶", "兰", "婉", "清", "云", "雨", "诗", "萱",
                         "琳", "玉", "嫣", "琴", "韵", "蓉", "薇", "静", "柔", "芳"],
    },
    "japanese": {
        "label": "日文",
        "surnames": ["佐藤", "鈴木", "高橋", "田中", "渡辺", "伊藤", "山本", "中村", "小林", "加藤",
                      "吉田", "山田", "佐々木", "山口", "松本", "井上", "木村", "林", "清水", "斉藤"],
        "given_male": ["翔太", "蓮", "大輝", "悠真", "颯太", "陽翔", "湊", "蒼", "大和", "樹",
                       "健太", "拓海", "亮", "達也", "直樹", "誠", "浩二", "隆", "徹", "駿"],
        "given_female": ["桜", "陽菜", "葵", "結衣", "美咲", "凛", "花子", "由美", "真由", "恵",
                         "愛", "優子", "香織", "明美", "直子", "智子", "麻衣", "彩", "優花", "芽衣"],
    },
    "western": {
        "label": "西方",
        "given_male": ["Arthur", "Cedric", "Dorian", "Edmund", "Felix", "Gareth", "Hugo",
                       "Ivan", "Jasper", "Klaus", "Leo", "Marcus", "Nikolai", "Oscar",
                       "Percival", "Quentin", "Roland", "Sebastian", "Theodore", "Victor",
                       "Aldric", "Brom", "Corwin", "Duncan", "Elara"],
        "given_female": ["Alice", "Beatrice", "Clara", "Diana", "Eleanor", "Fiona", "Gwen",
                         "Helena", "Isabel", "Julia", "Katherine", "Lucia", "Margot", "Nora",
                         "Ophelia", "Pearl", "Rosalind", "Sylvia", "Tessa", "Vera"],
        "surnames": ["Ashworth", "Blackwood", "Croft", "Davenport", "Everard", "Fairfax",
                     "Grey", "Hawthorne", "Irons", "Kingsley", "Lancaster", "Montague",
                     "Northam", "Oakley", "Pendleton", "Ravenscroft", "Stirling",
                     "Thorne", "Underwood", "Vance", "Whitmore", "York"],
    },
    "russian": {
        "label": "俄式",
        "given_male": ["Alexei", "Boris", "Dmitri", "Fyodor", "Grigory", "Igor",
                       "Konstantin", "Leonid", "Maxim", "Nikolai", "Oleg", "Pavel",
                       "Roman", "Sergei", "Viktor", "Yuri", "Andrei"],
        "given_female": ["Anastasia", "Darya", "Ekaterina", "Irina", "Ksenia", "Ludmila",
                         "Marina", "Natalia", "Olga", "Polina", "Svetlana", "Tatiana",
                         "Valentina", "Yelena", "Zoya"],
        "surnames": ["Abramov", "Belov", "Chernov", "Durov", "Frolov", "Golubev",
                     "Ivanov", "Kozlov", "Lebedev", "Morozov", "Novikov", "Orlov",
                     "Petrov", "Romanov", "Sokolov", "Titov", "Volkov", "Zaitsev"],
    },
}

NPC_NAME_STYLES = {
    "default": {"label": "默认（导演自由命名）", "regions": []},
    "chinese": {"label": "中文人名", "regions": ["chinese"]},
    "japanese": {"label": "日文人名", "regions": ["japanese"]},
    "western": {"label": "西方人名", "regions": ["western"]},
    "russian": {"label": "俄式人名", "regions": ["russian"]},
    "mixed": {"label": "混合风格", "regions": ["chinese", "japanese", "western", "russian"]},
}


def build_npc_name_instruction(style_key: str) -> str:
    """
    Build a prompt instruction for NPC naming based on the selected style.
    Returns empty string for default (director decides freely).
    """
    if style_key == "default" or style_key not in NPC_NAME_STYLES:
        return ""

    style_info = NPC_NAME_STYLES[style_key]
    regions = style_info["regions"]

    if not regions:
        return ""

    lines = [f"\n## NPC 命名规则\n"]
    lines.append(f"请从以下名字库中为新引入的 NPC 选择或参考命名（{style_info['label']}）：\n")

    for region in regions:
        bank = NPC_NAME_BANKS.get(region)
        if not bank:
            continue
        lines.append(f"### {bank['label']}风格")
        lines.append(f"- 姓氏: {', '.join(bank['surnames'][:12])}...")
        if "given_male" in bank:
            lines.append(f"- 男性名: {', '.join(bank['given_male'][:10])}...")
        if "given_female" in bank:
            lines.append(f"- 女性名: {', '.join(bank['given_female'][:10])}...")
        lines.append("")

    lines.append("请从以上名字库中选取或参考命名，确保 NPC 名字与所选风格一致。")
    return "\n".join(lines)
