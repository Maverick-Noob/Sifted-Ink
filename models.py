"""
Core data models for the multi-agent novel pre-rehearsal system.
"""

from dataclasses import dataclass, field
from typing import Optional
import uuid


@dataclass
class UserNPC:
    """User-defined NPC specification (before generation)."""
    name: str                              # required
    role: str = ""                         # friend/enemy/mentor/lover/rival/neutral
    personality: str = ""                  # optional
    backstory: str = ""                    # optional
    relevance: str = "medium"              # high / medium / low
    intro_chapter: int = 0                 # 0 = auto (AI decides)
    exit_chapter: int = 0                  # 0 = auto
    abilities: str = ""                    # optional


@dataclass
class StoryConfig:
    """User-provided story configuration."""
    protagonist_name: str
    protagonist_traits: str       # personality, motivation, abilities (free text)
    world_setting: str             # era, rules, magic/tech level (free text)
    story_start: str               # opening scene or event
    story_end: str = ""            # target ending (auto-generated if empty)
    target_word_count: int = 8000

    # Writing style
    writing_style: str = ""           # selected writer name, empty = default

    # NPC naming
    npc_name_style: str = "default"   # default / chinese / japanese / western / mixed

    # Story naming
    naming_style: str = ""            # empty = auto-detect, or pick from novel_naming_styles.json

    # Front matter
    front_matter: list[str] = field(default_factory=list)  # e.g. ["toc","prologue","characters"]

    # Multi-protagonist mode
    protagonist_mode: str = "spotlight"  # spotlight / team / parallel
    protagonist_count: int = 1           # number of main protagonists (max 10)
    protagonist_order: str = ""          # comma-separated names in appearance order

    # NPC & quality strategy
    npc_mode: str = "parallel"           # parallel / scene_filter / narrator
    quality_mode: str = "balanced"       # balanced / quality

    # User-defined NPCs
    user_npcs: list[UserNPC] = field(default_factory=list)

    # API configuration
    api_key: str = ""
    model: str = "claude-sonnet-4-6"
    api_provider: str = "anthropic"  # "anthropic" or "openai"
    api_base_url: str = ""           # optional custom base URL for OpenAI-compatible

    # Constraint configuration
    max_npcs: int = 30
    total_token_budget: Optional[int] = None  # None = unlimited
    num_versions: int = 3            # number of parallel pre-rehearsal versions (max 500)
    max_chapters: int = 30
    version_timeout_seconds: int = 1800  # 30 minutes per version
    max_tokens_per_call: int = 4000
    repeat_similarity_threshold: float = 0.9

    def validate(self) -> list[str]:
        """Validate configuration, returns list of error messages (empty = valid)."""
        errors = []
        if not self.protagonist_name.strip():
            errors.append("主角姓名不能为空")
        if not self.story_start.strip():
            errors.append("故事开头不能为空")
        # story_end is optional — system auto-generates if empty
        if self.target_word_count < 500:
            errors.append("目标字数不能少于 500")
        if self.max_npcs < 1:
            errors.append("NPC 数量上限至少为 1")
        if self.num_versions < 1 or self.num_versions > 500:
            errors.append("预演版本数应在 1~500 之间")
        if self.protagonist_count < 1 or self.protagonist_count > 10:
            errors.append("主角团人数应在 1~10 之间")
        if self.max_chapters < 1:
            errors.append("章节数上限至少为 1")
        if self.max_tokens_per_call < 100:
            errors.append("单次 API token 数至少为 100")
        if self.model.startswith("claude") and self.api_provider != "anthropic":
            pass  # auto-detect is fine
        if not self.api_key.strip():
            errors.append("API key 不能为空（可通过环境变量 SIFTED_INK_API_KEY 设置）")
        return errors


@dataclass
class AgentAction:
    """Structured output from an agent (protagonist or NPC)."""
    agent_name: str
    agent_type: str            # "protagonist" or "npc"
    action: str                # "speak", "move", "decide", "attack", "observe", "internal_monologue", "exit"
    content: str               # the actual text of the action
    emotion: str = "neutral"
    target: str = ""           # who or what the action is directed at
    metadata: dict = field(default_factory=dict)


@dataclass
@dataclass
class NPC:
    """A non-player character in the story."""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = ""
    role: str = ""             # friend, enemy, mentor, stranger, etc.
    personality: str = ""      # brief personality description
    goal: str = ""             # short-term goal in the story
    alive: bool = True
    active: bool = True        # currently in the scene
    intro_chapter: int = 0
    exit_chapter: Optional[int] = None
    last_active_chapter: int = 0  # last chapter where this NPC performed an action
    relevance: str = "medium"    # high / medium / low — how important to the main plot
    backstory: str = ""          # character background (1-2 sentences)


@dataclass
class StoryMilestone:
    """A key plot milestone in the story outline."""
    description: str          # what should happen
    target_chapter: int       # approximate chapter number to reach this
    reached: bool = False     # whether this milestone has been achieved


@dataclass
class StoryOutline:
    """Pre-planned story structure with milestones."""
    milestones: list[StoryMilestone] = field(default_factory=list)
    total_chapters_hint: int = 30        # suggested total chapters
    current_act: str = "setup"           # setup / confrontation / resolution


@dataclass
class Chapter:
    """A single chapter in a pre-rehearsal version."""
    number: int
    content: str                          # narrative text for this chapter
    protagonist_action: Optional[AgentAction] = None
    npc_actions: list[AgentAction] = field(default_factory=list)
    director_notes: str = ""              # Director's reasoning for this chapter
    chapter_title: str = ""               # Director-generated chapter title
    npcs_introduced: list[NPC] = field(default_factory=list)
    npcs_exited: list[str] = field(default_factory=list)  # NPC ids that exited
    token_cost: int = 0                   # tokens consumed for this chapter


@dataclass
class StoryState:
    """Runtime state for a single pre-rehearsal version."""
    version_id: int
    config: StoryConfig
    chapters: list[Chapter] = field(default_factory=list)
    active_npcs: list[NPC] = field(default_factory=list)
    npc_graveyard: list[NPC] = field(default_factory=list)  # exited/dead NPCs
    protagonist_state: dict = field(default_factory=lambda: {
        "emotional": "neutral",
        "physical": "healthy",
        "location": "",
        "relationships": {},
        "abilities_gained": [],
        "key_items": [],
    })
    total_tokens_used: int = 0
    completed: bool = False
    reached_ending: bool = False
    terminated_early: bool = False       # timeout or user interrupt
    termination_reason: str = ""

    # Pacing & outline
    outline: Optional[StoryOutline] = None
    pacing_stage: str = "setup"          # setup / confrontation / resolution
    pacing_pressure: str = "low"         # low / medium / high / critical
    chapters_without_progress: int = 0   # counter for stagnation detection

    @property
    def chapter_count(self) -> int:
        return len(self.chapters)

    @property
    def total_words(self) -> int:
        """Approximate word count (Chinese characters + spaces)."""
        return sum(len(ch.content) for ch in self.chapters)

    @property
    def npc_count(self) -> int:
        return len([n for n in self.active_npcs if n.alive and n.active])

    def get_last_n_protagonist_actions(self, n: int = 3) -> list[AgentAction]:
        """Get the last N protagonist actions for repeat detection."""
        actions = []
        for ch in reversed(self.chapters):
            if ch.protagonist_action:
                actions.append(ch.protagonist_action)
            if len(actions) >= n:
                break
        return list(reversed(actions))


@dataclass
class EvalResult:
    """Evaluation result for a single pre-rehearsal version."""
    version_id: int
    dramatic_tension: float = 0.0    # 0-10: conflicts, stakes, suspense
    character_growth: float = 0.0    # 0-10: protagonist development arc
    logic_consistency: float = 0.0   # 0-10: plot coherence, no contradictions
    ending_alignment: float = 0.0    # 0-10: how well the ending matches requirement
    total_score: float = 0.0
    evaluator_notes: str = ""
    is_complete: bool = True         # False if version was "未完成"


@dataclass
class PreActorResult:
    """Complete result of the pre-rehearsal process."""
    config: StoryConfig
    versions: list[StoryState]
    evaluations: list[EvalResult]
    winning_version_id: int
    total_tokens_used: int
    time_elapsed_seconds: float
    user_selected: bool = False      # True if user had to choose between close scores
