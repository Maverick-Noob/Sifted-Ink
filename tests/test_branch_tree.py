"""
Tests for the branch tree (走向树 + 后果推演).

The point of these tests is not "the JSON parses" but "the branch actually
constrains the next chapter" — that is what the feature promises.
"""

from novel_preactor.agents import DirectorAgent
from novel_preactor.models import (
    BranchDecision, BranchOption, Chapter, StoryConfig, StoryState,
)


def _state() -> StoryState:
    cfg = StoryConfig(
        protagonist_name="林远", protagonist_traits="冲动", world_setting="苍澜",
        story_start="废墟", story_end="找到炎之心", api_key="dummy",
    )
    return StoryState(version_id=1, config=cfg)


def _agent() -> DirectorAgent:
    """A DirectorAgent with a stub client — no network, no LLM."""
    agent = DirectorAgent.__new__(DirectorAgent)
    agent.config = _state().config
    return agent


# ── 解析 ────────────────────────────────────────────────────────────────

def test_parse_new_format():
    opts = DirectorAgent._parse_branch_options([
        {
            "id": "A", "title": "先下手", "description": "林远主动出手",
            "payoff": "抢到先机", "cost": "暴露身份", "conflict": "与师父约定冲突",
            "hook": "对方喊出了他的名字", "risk": "high", "risk_reason": "敌人比预想强",
        },
        {"id": "B", "title": "再等等", "description": "按兵不动", "risk": "low"},
    ])
    assert len(opts) == 2
    a = opts[0]
    assert a.title == "先下手"
    assert a.payoff == "抢到先机"
    assert a.cost == "暴露身份"
    assert a.conflict == "与师父约定冲突"
    assert a.hook == "对方喊出了他的名字"
    assert a.risk == "high"
    assert a.risk_reason == "敌人比预想强"
    assert opts[1].risk == "low"


def test_parse_tolerates_old_flat_format():
    """The old format was {"id", "description"} only."""
    opts = DirectorAgent._parse_branch_options([
        {"id": "A", "description": "分支A的走向描述"},
        {"id": "B", "description": "分支B的走向描述"},
    ])
    assert len(opts) == 2
    assert opts[0].description == "分支A的走向描述"
    assert opts[0].risk == "mid"      # default
    assert opts[0].payoff == ""


def test_parse_ignores_junk():
    opts = DirectorAgent._parse_branch_options([
        {"description": "没有 id"},            # no id → dropped
        "not a dict",                        # wrong type → dropped
        {"id": "  ", "description": "空 id"},  # blank id → dropped
        {"id": "C", "description": "好的"},     # kept
    ])
    assert len(opts) == 1
    assert opts[0].id == "C"


def test_parse_rejects_unknown_risk_value():
    opts = DirectorAgent._parse_branch_options([{"id": "A", "risk": "极度危险"}])
    assert opts[0].risk == "mid"


def test_parse_non_list_gives_empty():
    assert DirectorAgent._parse_branch_options(None) == []
    assert DirectorAgent._parse_branch_options("nope") == []


# ── 选定与记录 ──────────────────────────────────────────────────────────

def test_record_branch_picks_the_named_option():
    state = _state()
    agent = _agent()
    result = {
        "chapter_summary": "摘要",
        "branch_choice": "B",
        "branch_options": [
            {"id": "A", "title": "甲", "description": "走A"},
            {"id": "B", "title": "乙", "description": "走B", "risk": "low"},
        ],
    }
    dec = agent._record_branch(state, result)
    assert dec is not None
    assert dec.chosen_id == "B"
    assert dec.chosen.title == "乙"
    assert dec.chapter == 1
    assert len(state.branch_history) == 1


def test_record_branch_falls_back_when_choice_is_invalid():
    state = _state()
    agent = _agent()
    result = {
        "branch_choice": "Z",   # not on the list
        "branch_options": [
            {"id": "A", "title": "甲", "description": "走A"},
            {"id": "B", "title": "乙", "description": "走B"},
        ],
    }
    dec = agent._record_branch(state, result)
    assert dec is not None
    assert dec.chosen_id == "A"       # fell back to the first option
    assert len(state.branch_history) == 1


def test_record_branch_returns_none_without_options():
    state = _state()
    agent = _agent()
    assert agent._record_branch(state, {"branch_choice": "A"}) is None
    assert state.branch_history == []


def test_branch_history_accumulates():
    state = _state()
    agent = _agent()
    for i in range(3):
        agent._record_branch(state, {
            "branch_choice": "A",
            "branch_options": [{"id": "A", "title": f"第{i}章走向"}],
        })
        # 真实流程里，章节在写完后才追加到 state.chapters
        state.chapters.append(Chapter(number=i + 1, content="正文"))
    assert len(state.branch_history) == 3
    assert [d.chapter for d in state.branch_history] == [1, 2, 3]


# ── 真正的约束：下一章必须看到已选走向 ─────────────────────────────────

def test_next_director_prompt_contains_the_chosen_branch():
    """这是整个特性的核心：已选走向必须出现在下一章的导演提示里。"""
    state = _state()
    agent = _agent()
    agent._record_branch(state, {
        "branch_choice": "A",
        "branch_options": [{
            "id": "A", "title": "先下手", "description": "林远主动出手",
            "payoff": "抢到先机", "cost": "暴露身份", "conflict": "与师父约定冲突",
        }],
    })
    msg = agent._build_user_message(state)
    assert "已选走向" in msg
    assert "先下手" in msg
    assert "林远主动出手" in msg
    assert "已兑现" in msg and "抢到先机" in msg
    assert "已付出" in msg and "暴露身份" in msg
    assert "遗留冲突" in msg and "与师父约定冲突" in msg


def test_no_branch_history_means_no_branch_section():
    state = _state()
    agent = _agent()
    msg = agent._build_user_message(state)
    assert "已选走向" not in msg


# ── 数据模型 ────────────────────────────────────────────────────────────

def test_branch_option_round_trips_to_dict():
    o = BranchOption(id="A", title="甲", description="走A", risk="high")
    d = o.to_dict()
    assert d["id"] == "A"
    assert d["risk"] == "high"
    assert "甲" in o.summary_line()
    assert "high" in o.summary_line()


def test_branch_decision_to_dict_includes_options():
    o = BranchOption(id="A", title="甲")
    dec = BranchDecision(chapter=3, options=[o], chosen_id="A", chosen=o)
    d = dec.to_dict()
    assert d["chapter"] == 3
    assert d["chosen_id"] == "A"
    assert d["chosen"]["title"] == "甲"
    assert len(d["options"]) == 1
