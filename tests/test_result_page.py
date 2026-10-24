"""
Tests for the result page — mainly that the branch tree renders.

A template error would only show up when a user opens the result page, which
is the worst possible time to find out. These tests render it directly.
"""

import jinja2
from pathlib import Path

from novel_preactor.models import (
    BranchDecision, BranchOption, Chapter, PreActorResult, StoryConfig, StoryState,
)

_TEMPLATES = jinja2.Environment(
    loader=jinja2.FileSystemLoader(
        str(Path(__file__).resolve().parent.parent / "webui" / "templates")
    ),
    autoescape=True,
)


def _cfg() -> StoryConfig:
    return StoryConfig(
        protagonist_name="林远", protagonist_traits="冲动", world_setting="苍澜",
        story_start="废墟", story_end="炎之心", api_key="dummy",
    )


def _result_with_branch() -> PreActorResult:
    cfg = _cfg()
    state = StoryState(version_id=1, config=cfg)
    state.chapters.append(Chapter(number=1, content="第一章正文。"))
    options = [
        BranchOption(
            id="A", title="先下手", description="林远主动出手",
            payoff="抢到先机", cost="暴露身份", conflict="与师父约定冲突",
            hook="对方喊出了他的名字", risk="high", risk_reason="敌人比预想强",
        ),
        BranchOption(id="B", title="再等等", description="按兵不动", risk="low"),
    ]
    state.branch_history.append(BranchDecision(
        chapter=1, options=options, chosen_id="A", chosen=options[0],
    ))
    return PreActorResult(
        versions=[state],
        config=cfg,
        winning_version_id=1,
        evaluations=[],
        total_tokens_used=1234,
        time_elapsed_seconds=12.3,
    )


def test_result_page_renders_branch_tree():
    tmpl = _TEMPLATES.get_template("result.html")
    html = tmpl.render(
        request=None, run_id="r1", novel_text="## 第一章\n正文",
        eval_log={"versions": []}, result=_result_with_branch(),
        story_name="测试书名", story_meta={},
    )
    assert "走向树" in html
    assert "先下手" in html
    assert "抢到先机" in html
    assert "暴露身份" in html
    assert "与师父约定冲突" in html
    assert "对方喊出了他的名字" in html
    assert "已选" in html
    # the option that was NOT taken should also be listed
    assert "再等等" in html


def test_result_page_handles_a_run_without_branches():
    cfg = _cfg()
    state = StoryState(version_id=1, config=cfg)
    result = PreActorResult(
        versions=[state], config=cfg, winning_version_id=1, evaluations=[],
        total_tokens_used=0, time_elapsed_seconds=0.0,
    )
    tmpl = _TEMPLATES.get_template("result.html")
    html = tmpl.render(
        request=None, run_id="r1", novel_text="正文", eval_log={},
        result=result, story_name="", story_meta={},
    )
    assert "走向树" in html
    assert "没有记录到走向决策点" in html


def test_eval_log_contains_the_branch_tree():
    from novel_preactor.writer import generate_eval_log

    log = generate_eval_log(_result_with_branch())
    tree = log["versions"][0]["branch_tree"]
    assert len(tree) == 1
    assert tree[0]["chosen_id"] == "A"
    assert tree[0]["chosen"]["title"] == "先下手"
    assert len(tree[0]["options"]) == 2
