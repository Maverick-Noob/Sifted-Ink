"""
Story naming engine — rule-based candidate generation + LLM scoring.

Flow:
  1. Extract keywords from story config and generated text
  2. Select naming style (user-chosen or LLM-auto-detected)
  3. Generate 10 candidates using style-specific templates + keywords
  4. LLM scores candidates and picks the best one
"""

import json
import os
import random
import re
from dataclasses import dataclass, field
from typing import Optional

from .utils import logger


# ═══════════════════════════════════════════════════════════════════════
# Naming style loading
# ═══════════════════════════════════════════════════════════════════════

def load_naming_styles() -> list[dict]:
    """Load naming styles from the bundled JSON file."""
    path = os.path.join(os.path.dirname(__file__), "novel_naming_styles.json")
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("naming_styles", [])


# ═══════════════════════════════════════════════════════════════════════
# Keyword extraction (rule-based — no LLM)
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class StoryKeywords:
    protagonist: str = ""
    locations: list[str] = field(default_factory=list)
    items: list[str] = field(default_factory=list)
    themes: list[str] = field(default_factory=list)
    key_events: list[str] = field(default_factory=list)
    emotions: list[str] = field(default_factory=list)


def extract_keywords(config, story_text: str) -> StoryKeywords:
    """
    Extract keywords from story config and generated text.
    Uses regex patterns and config fields — no LLM call.
    """
    kw = StoryKeywords()

    # From config
    kw.protagonist = config.protagonist_name

    # From story text: find capitalized/quoted items
    # Pattern: 《...》 or "..." or 「...」
    quoted = re.findall(r'[《「](.+?)[》」]', story_text)
    kw.items = list(dict.fromkeys(quoted))[:5]  # deduplicate, max 5

    # Locations: look for 谷/城/国/殿/林/山/海 patterns
    loc_patterns = re.findall(
        r'([\w一-鿿]{1,4}(?:谷|城|国|殿|林|山|海|镇|村|堡|岛|原|境|界))',
        story_text,
    )
    kw.locations = list(dict.fromkeys(loc_patterns))[:5]

    # Themes: keyword matching
    theme_keywords = {
        "复仇": ["复仇", "血仇", "灭门", "雪恨", "报仇"],
        "成长": ["成长", "觉醒", "突破", "试炼", "修炼"],
        "守护": ["守护", "保护", "捍卫", "守卫", "镇守"],
        "冒险": ["冒险", "探索", "旅途", "征程", "远征"],
        "爱情": ["爱情", "恋人", "思念", "牵挂", "相思"],
        "权力": ["权力", "王位", "争霸", "权谋", "篡位"],
        "救赎": ["救赎", "赎罪", "原谅", "宽恕", "忏悔"],
        "命运": ["命运", "宿命", "轮回", "注定", "天意"],
    }
    found_themes = []
    for theme, keywords in theme_keywords.items():
        if any(kw in story_text for kw in keywords):
            found_themes.append(theme)
    kw.themes = found_themes[:4]

    # Key events: look for narrative markers
    event_patterns = re.findall(
        r'(?:发现|击败|获得|失去|觉醒|封印|解开|打破|穿越)(?:了)?'
        r'[一-鿿]{2,12}',
        story_text,
    )
    kw.key_events = list(dict.fromkeys(event_patterns))[:4]

    # Emotions
    emotion_words = ["热血", "悲壮", "温暖", "冷酷", "孤独", "希望", "绝望", "坚定"]
    kw.emotions = [e for e in emotion_words if e in story_text][:3]

    return kw


# ═══════════════════════════════════════════════════════════════════════
# Candidate name generation (template-based — no LLM)
# ═══════════════════════════════════════════════════════════════════════

def _pick(items: list, default: str = "") -> str:
    """Pick a random item from list or return default."""
    return random.choice(items) if items else default


def _random_pick(items: list, default: str) -> str:
    """Pick a random item, returns a new value each call."""
    return random.choice(items) if items else default


def generate_candidates(kw: StoryKeywords, style: dict, count: int = 10) -> list[str]:
    """
    Generate candidate book titles using style-specific templates and extracted keywords.
    Each template is re-evaluated with fresh random picks to ensure diversity.
    Returns a list of unique candidate names.
    """
    style_name = style.get("style", "")
    names = set()

    # Template factories: lambdas that produce a fresh name each call
    def p(): return kw.protagonist or "主角"
    def loc(): return _random_pick(kw.locations, "远方")
    def item(): return _random_pick(kw.items, "信物")
    def theme(): return _random_pick(kw.themes, "命运")
    def event(): return _random_pick(kw.key_events, "冒险")
    def emotion(): return _random_pick(kw.emotions, "")
    def r_pick(opts, default): return _random_pick(opts, default)

    # Template banks per style — lambdas for fresh random picks each time
    templates = {
        "直白陈述型": [
            lambda: f"{p()}的{theme()}之路",
            lambda: f"{event()}记",
            lambda: f"关于{theme()}的故事",
            lambda: f"{p()}：{theme()}与救赎",
            lambda: f"从{loc()}到{loc()}",
            lambda: f"{theme()}者{p()}",
            lambda: f"{loc()}往事",
            lambda: f"当{event()}时",
            lambda: f"{p()}的最后{r_pick(['旅程','战斗','选择','秘密'],'旅程')}",
            lambda: f"{theme()}年代记",
            lambda: f"{p()}传",
            lambda: f"{event()}录",
        ],
        "诗意意境型": [
            lambda: f"{loc()}的{r_pick(['风','雨','雪','月','夜','梦'],'梦')}",
            lambda: f"且听{r_pick(['风吟','蝉鸣','雪落','潮声'],'风吟')}",
            lambda: f"{emotion() or '孤独'}的{r_pick(['旅人','歌者','守望者'],'旅人')}",
            lambda: f"雾锁{loc()}",
            lambda: f"当{r_pick(['星辰坠落','繁花盛开','长夜将尽'],'星辰坠落')}",
            lambda: f"在{loc()}等{r_pick(['你','风','春天','光'],'风')}",
            lambda: f"{r_pick(['春','夏','秋','冬'],'春')}之{r_pick(['歌','梦','诗','祭'],'歌')}",
            lambda: f"落日{loc()}",
        ],
        "悬念钩子型": [
            lambda: f"谁{r_pick(['杀了','偷走了','召唤了','唤醒了'],'杀了')}{p()}？",
            lambda: f"{loc()}的{random.randint(3,13)}个{r_pick(['秘密','谜题','幽灵','诅咒'],'秘密')}",
            lambda: f"不要{r_pick(['打开那扇门','相信任何人','回头','忘记我'],'打开那扇门')}",
            lambda: f"如果{event()}，请{r_pick(['快跑','忘了我','继续读'],'快跑')}",
            lambda: f"最后{random.randint(1,99)}天",
            lambda: f"{p()}必须死",
            lambda: f"你确定要打开{item()}吗？",
        ],
        "人物标签型": [
            lambda: f"{p()}传",
            lambda: f"{p()}与{item()}",
            lambda: f"{p()}的{random.randint(1,7)}次{r_pick(['选择','重生','背叛','觉醒'],'选择')}",
            lambda: f"我叫{p()}，{r_pick(['这是我的故事','我来自未来','我可以穿越时间'],'这是我的故事')}",
            lambda: f"{p()}：{theme()}纪元",
            lambda: f"最后的{p()}",
            lambda: f"少年{p()}之{r_pick(['烦恼','冒险','逆袭','修行'],'冒险')}",
        ],
        "物件意象型": [
            lambda: f"{item()}",
            lambda: f"{item()}之歌",
            lambda: f"寻找{item()}",
            lambda: f"{item()}与{p()}",
            lambda: f"遗失的{item()}",
            lambda: f"{item()}的秘密",
            lambda: f"守护{item()}",
            lambda: f"当{item()}绽放时",
        ],
        "时间/地点锚定型": [
            lambda: f"{loc()}的{random.randint(1800,2025)}年",
            lambda: f"在{loc()}",
            lambda: f"从{loc()}出发",
            lambda: f"{loc()}往事",
            lambda: f"回到{loc()}",
            lambda: f"{loc()}来信",
            lambda: f"夜访{loc()}",
        ],
        "对话/金句型": [
            lambda: f"「{r_pick(['你好，','再见了，','别了，','等着我，'],'你好，')}{loc()}」",
            lambda: f"「{theme()}是一种{r_pick(['病','选择','信仰','本能'],'选择')}」",
            lambda: f"「如果还有明天」",
            lambda: f"「{p()}，{r_pick(['活下去','不要死','记住我','原谅我'],'活下去')}」",
            lambda: f"「这个世界{r_pick(['疯了','是假的','不属于我们','会好的'],'疯了')}」",
        ],
    }

    # Get templates for this style
    style_templates = templates.get(style_name, templates["直白陈述型"])

    # Generate candidates (call lambdas for fresh values each time)
    attempts = 0
    while len(names) < count and attempts < count * 5:
        tpl = random.choice(style_templates)
        name = tpl().strip()  # call lambda for fresh random picks
        if 2 <= len(name) <= 30 and name not in names:
            names.add(name)
        attempts += 1

    # If still short, add protagonist-based fallbacks
    fallbacks = [
        f"{p}的传奇", f"{p}战记", f"{p}：{theme}",
        f"{loc}故事", f"{event}", f"{p}与{loc}",
    ]
    for fb in fallbacks:
        if len(names) >= count:
            break
        names.add(fb)

    return list(names)[:count]


# ═══════════════════════════════════════════════════════════════════════
# Naming orchestrator
# ═══════════════════════════════════════════════════════════════════════

STYLE_DETECTION_PROMPT = """你是一位资深图书编辑。请根据以下故事信息，从 {style_count} 种命名风格中选择最合适的一种。

## 故事信息
- 主角: {protagonist}（{traits}）
- 世界背景: {world}
- 故事开头: {start}
- 故事摘要: {summary}

## 可选命名风格
{style_list}

## 输出格式
只输出选中风格的名称（一个字都不要多）："""


CANDIDATE_SCORING_PROMPT = """你是一位资深图书编辑。请从以下候选书名中选出最优秀的一个。

## 故事背景
- 主角: {protagonist}
- 风格: {world}
- 核心情节: {summary}

## 候选书名
{candidates_text}

## 评分标准
1. 与故事内容匹配度
2. 文学性和美感
3. 记忆度和传播性
4. 独特性

## 输出格式
只输出最佳书名的完整文字（不要加引号、不要加任何解释）："""


# ═══════════════════════════════════════════════════════════════════════
# Chapter title generation
# ═══════════════════════════════════════════════════════════════════════

CHAPTER_TITLE_TEMPLATES = {
    "直白陈述型": [
        lambda kw: f"{kw.get('event','开端')}",
        lambda kw: f"{kw.get('location','未知之地')}的{kw.get('event','遭遇')}",
        lambda kw: f"{kw.get('event','转折')}之际",
        lambda kw: f"{kw.get('character','主角')}的{kw.get('choice','抉择')}",
        lambda kw: f"{kw.get('location','远方')}来客",
        lambda kw: f"{kw.get('event','真相')}浮现",
    ],
    "诗意意境型": [
        lambda kw: f"{kw.get('location','长夜')}之{random.choice(['歌','梦','诗','祭','舞'])}",
        lambda kw: f"当{kw.get('event','风')}吹过{kw.get('location','山谷')}",
        lambda kw: f"{random.choice(['春','夏','秋','冬'])}{random.choice(['雨','雪','雾','霜','露'])}{kw.get('event','时节')}",
        lambda kw: f"{kw.get('location','月')}下{kw.get('event','独白')}",
        lambda kw: f"且听{kw.get('event','风吟')}",
    ],
    "悬念钩子型": [
        lambda kw: f"谁在{kw.get('location','那里')}？",
        lambda kw: f"{kw.get('character','谁')}的{kw.get('event','秘密')}",
        lambda kw: f"{kw.get('event','危机')}降临",
        lambda kw: f"不可{kw.get('choice','回头')}",
        lambda kw: f"{kw.get('event','陷阱')}",
    ],
    "人物标签型": [
        lambda kw: f"{kw.get('character','他')}的{kw.get('event','选择')}",
        lambda kw: f"{kw.get('character','她')}与{kw.get('event','命运')}",
        lambda kw: f"第{random.randint(1,10)}次{kw.get('event','相遇')}",
        lambda kw: f"{kw.get('character','陌生人')}的{kw.get('event','来信')}",
    ],
    "物件意象型": [
        lambda kw: f"{kw.get('item','信物')}",
        lambda kw: f"遗失的{kw.get('item','钥匙')}",
        lambda kw: f"{kw.get('item','剑')}与{kw.get('event','誓言')}",
        lambda kw: f"{kw.get('item','镜子')}的{kw.get('event','秘密')}",
    ],
    "时间/地点锚定型": [
        lambda kw: f"{kw.get('location','某地')}·{kw.get('event','初见')}",
        lambda kw: f"{kw.get('location','某城')}来信",
        lambda kw: f"夜访{kw.get('location','某处')}",
        lambda kw: f"离开{kw.get('location','故乡')}",
    ],
    "对话/金句型": [
        lambda kw: f"「{kw.get('quote','你好')}」",
        lambda kw: f"「{kw.get('quote','等着我')}」",
        lambda kw: f"「{kw.get('quote','活下去')}」",
        lambda kw: f"「{kw.get('quote','这就是命运')}」",
    ],
}


def generate_chapter_title(
    chapter_summary: str, chapter_num: int, style_name: str = ""
) -> str:
    """
    Generate a creative chapter title using naming style templates.
    Falls back to '第N章' if style unavailable.
    """
    templates = CHAPTER_TITLE_TEMPLATES.get(style_name)
    if not templates:
        return f"第{chapter_num}章"

    # Extract mini-keywords from chapter summary
    kw = {}
    # Location
    loc_match = re.search(r'[\w一-鿿]{1,4}(?:谷|城|国|殿|林|山|海|镇|村|堡|岛)', chapter_summary)
    kw['location'] = loc_match.group(0) if loc_match else "此地"
    # Character
    char_match = re.search(r'(?:林远|艾琳|莫里斯|铁山|[\w一-鿿]{2,3})(?=目睹|来到|决定|发现|说|冲|拔|感到)', chapter_summary)
    kw['character'] = char_match.group(0) if char_match else "他"
    # Event
    event_match = re.search(r'(?:发现|击败|获得|失去|觉醒|封印|揭开|打破|穿越|逃离|对质|告白)[\w一-鿿]{0,6}', chapter_summary)
    kw['event'] = event_match.group(0) if event_match else "抉择"
    # Item
    item_match = re.search(r'[《「]([\w一-鿿]{1,6})[》」]', chapter_summary)
    kw['item'] = item_match.group(1) if item_match else "信物"

    # Pick random template and generate
    tpl = random.choice(templates)
    title = tpl(kw).strip()
    if 2 <= len(title) <= 20:
        return f"第{chapter_num}章 {title}"
    return f"第{chapter_num}章"


class NamingEngine:
    """Orchestrates the rule-based + LLM naming pipeline."""

    def __init__(self, llm_client=None):
        self.client = llm_client  # LLMClient instance (optional)

    # ── Style selection ──────────────────────────────────────────────

    def get_default_style(self) -> dict:
        styles = load_naming_styles()
        return styles[0] if styles else {"style": "直白陈述型"}

    def get_style_by_name(self, name: str) -> Optional[dict]:
        styles = load_naming_styles()
        for s in styles:
            if s["style"] == name:
                return s
        return None

    async def auto_detect_style(
        self, config, story_summary: str,
    ) -> dict:
        """Use LLM to pick the best naming style."""
        styles = load_naming_styles()
        if not styles or not self.client:
            return self.get_default_style()

        style_list = "\n".join(
            f"- {s['style']}: {s['description']}"
            for s in styles
        )

        prompt = STYLE_DETECTION_PROMPT.format(
            style_count=len(styles),
            protagonist=config.protagonist_name,
            traits=config.protagonist_traits[:100],
            world=config.world_setting[:100],
            start=config.story_start[:150],
            summary=story_summary[:300],
            style_list=style_list,
        )

        try:
            text, _ = await self.client.call(
                prompt, "请选择最合适的命名风格。", temperature=0.5, max_tokens=50,
            )
            # Clean response: take first line, strip quotes and whitespace
            detected = text.strip().split("\n")[0].strip().strip("\"'「」《》")
            # Match against known styles
            for s in styles:
                if s["style"] in detected or detected in s["style"]:
                    logger.info(f"[命名] 自动选择风格: {s['style']}")
                    return s
        except Exception as e:
            logger.warning(f"命名风格自动检测失败: {e}")

        return self.get_default_style()

    # ── Candidate scoring ────────────────────────────────────────────

    async def score_and_pick(
        self, candidates: list[str], config, story_summary: str,
    ) -> str:
        """Use LLM to pick the best candidate from the list."""
        if not candidates:
            return f"{config.protagonist_name}的传奇"
        if len(candidates) == 1 or not self.client:
            return candidates[0]

        candidates_text = "\n".join(
            f"{i+1}. {c}" for i, c in enumerate(candidates)
        )

        prompt = CANDIDATE_SCORING_PROMPT.format(
            protagonist=config.protagonist_name,
            world=config.world_setting[:100],
            summary=story_summary[:300],
            candidates_text=candidates_text,
        )

        try:
            text, _ = await self.client.call(
                prompt, "请从以上候选书名中选出最佳的一个。",
                temperature=0.4, max_tokens=50,
            )
            # Clean response
            picked = text.strip().split("\n")[0].strip().strip("\"'「」《》")
            # Remove numbering like "1. " or "1、"
            picked = re.sub(r'^\d+[.、)\s]+', '', picked).strip()

            # Try to match against candidates
            for c in candidates:
                if c == picked or picked in c or c in picked:
                    logger.info(f"[命名] LLM 评选最佳书名: 《{c}》")
                    return c

            # If no match, return the picked text if it looks reasonable
            if 2 <= len(picked) <= 30:
                logger.info(f"📖 LLM 评选最佳书名: 《{picked}》")
                return picked
        except Exception as e:
            logger.warning(f"书名评分失败: {e}")

        # Fallback: first candidate
        return candidates[0]

    # ── Main pipeline ────────────────────────────────────────────────

    async def name_story(
        self, config, story_text: str,
        style_name: str = "",
    ) -> dict:
        """
        Main entry point: generate a story name.
        Returns {"best_name": str, "candidates": list, "style": str, "summary": str}
        """
        protagonist = config.protagonist_name
        fallback = {
            "best_name": f"{protagonist}的传奇",
            "candidates": [f"{protagonist}的传奇"],
            "style": "默认",
            "summary": "",
        }

        if not story_text or len(story_text.strip()) < 100:
            return fallback

        # 1. Extract keywords
        kw = extract_keywords(config, story_text)

        # 2. Select naming style
        if style_name:
            style = self.get_style_by_name(style_name)
            if not style:
                style = self.get_default_style()
        else:
            # Auto-detect with LLM if available, else default
            if self.client:
                story_summary = story_text[:500]
                style = await self.auto_detect_style(config, story_summary)
            else:
                style = self.get_default_style()

        style_label = style.get("style", "默认")

        # 3. Generate candidates
        candidates = generate_candidates(kw, style, count=10)
        logger.info(
            f"[命名] 生成 {len(candidates)} 个候选书名 (风格: {style_label}): "
            f"{', '.join(candidates[:5])}..."
        )

        # 4. Score and pick best
        summary_snippet = story_text[:500]
        if self.client:
            best = await self.score_and_pick(candidates, config, summary_snippet)
        else:
            best = candidates[0]

        return {
            "best_name": best,
            "candidates": candidates,
            "style": style_label,
            "summary": "",
        }
