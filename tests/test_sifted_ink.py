"""
Smoke / regression tests — no network, no LLM calls, no token cost.

Covers the areas changed in the 2026-10-21 refactor:
  * the narrative-technique library replaces the writer-imitation feature
  * the legacy ``writing_style`` key is ignored with a warning
  * provider auto-detection works from the model name
  * the cost estimator and the diversity diagnostic behave sanely
"""

from types import SimpleNamespace

import pytest

from novel_preactor.config import _detect_provider, load_config_from_yaml
from novel_preactor.diversity import analyze_text, diagnose
from novel_preactor.estimation import estimate_run
from novel_preactor.models import StoryConfig
from novel_preactor.utils import (
    build_technique_prompt,
    get_technique_by_id,
    load_narrative_techniques,
    load_user_techniques,
)

FLAT_TEXT = "他很高兴。他很生气。他很累。他很困。他站起来。他坐下。他走了。他回来了。他又走了。"
VARIED_TEXT = (
    "老周蹲下去，用镊子夹起地上一根毛发。毛是白的。\n\n"
    "他抬头看了看六号房的门牌，又看了看自己的手。指甲缝里也有白的。\n\n"
    "“你昨天来过？”他问。\n\n"
    "女人没回答。她把伞收了，水珠顺着伞骨滴在地板上，一下，两下，然后就没有了。\n\n"
    "老周等了很久。他决定不问第二遍。有些事情，问出来就得处理，"
    "不问就还能再拖一个礼拜。"
)


# ── Narrative technique library ────────────────────────────────────────

def test_technique_library_is_not_empty_and_well_formed():
    techs = load_narrative_techniques()
    assert techs, "narrative_techniques.json should not be empty"
    ids = [t["id"] for t in techs]
    assert len(ids) == len(set(ids)), "technique ids must be unique"
    for t in techs:
        assert t.get("name"), f"{t.get('id')} has no name"
        assert t.get("summary"), f"{t.get('id')} has no summary"
        assert t.get("sample_paragraph"), f"{t.get('id')} has no sample paragraph"
        spec = t.get("spec", {})
        for key in ("narrative_person", "dialogue_ratio", "sentence_length_p50",
                    "forbidden"):
            assert key in spec, f"{t.get('id')}.spec is missing {key}"


def test_no_technique_names_a_real_author():
    """A technique must not name a writer or a work — that is the whole point."""
    banned = ["鲁迅", "张爱玲", "老舍", "海明威", "村上春树", "猫腻", "辰东",
              "古龙", "金庸", "托尔金", "陀思妥耶夫斯基", "《"]
    blob = "\n".join(
        t.get("name", "") + t.get("summary", "") + str(t.get("spec", {}))
        for t in load_narrative_techniques()
    )
    for word in banned:
        assert word not in blob, f"technique library still references {word}"


def test_build_technique_prompt_never_asks_to_imitate():
    t = load_narrative_techniques()[0]
    prompt = build_technique_prompt(t["id"])
    assert prompt
    assert "模仿" not in prompt
    assert "代表作" not in prompt


def test_build_technique_prompt_for_custom_description():
    prompt = build_technique_prompt("custom:短句，每段不超过两行")
    assert "短句，每段不超过两行" in prompt
    # it may *forbid* imitation, but must never instruct it
    assert "请模仿" not in prompt
    assert "模仿任何特定在世或已故作家" in prompt


def test_build_technique_prompt_is_empty_for_unknown_id():
    assert build_technique_prompt("no-such-technique") == ""
    assert build_technique_prompt("") == ""


def test_get_technique_by_id():
    assert get_technique_by_id("cold-realism") is not None
    assert get_technique_by_id("nope") is None


def test_user_techniques_start_empty_and_round_trip():
    assert isinstance(load_user_techniques(), list)


# ── Config ─────────────────────────────────────────────────────────────

def test_legacy_writing_style_key_is_ignored(capsys, tmp_path):
    legacy = {
        "protagonist_name": "林远",
        "protagonist_traits": "勇敢",
        "world_setting": "奇幻",
        "story_start": "开头",
        "story_end": "结局",
        "writing_style": "鲁迅",
        "api_key": "dummy",
    }
    p = tmp_path / "legacy.yaml"
    p.write_text(
        "\n".join(f"{k}: '{v}'" for k, v in legacy.items()), encoding="utf-8"
    )
    cfg = load_config_from_yaml(str(p))
    assert cfg.narrative_technique == ""
    assert "writing_style" in capsys.readouterr().out


def test_provider_autodetection_from_model_name():
    cases = {
        "gpt-4o": "openai",
        "deepseek-chat": "deepseek",
        "qwen-plus": "qwen",
        "gemini-2.5-flash": "google",
        "claude-sonnet-4-6": "anthropic",
        "glm-4-plus": "zhipu",
    }
    for model, expected in cases.items():
        assert _detect_provider(model, "") == expected, model


def test_explicit_provider_still_wins():
    assert _detect_provider("gpt-4o", "openai") == "openai"
    assert _detect_provider("claude-sonnet-4-6", "anthropic") == "anthropic"


def test_story_config_has_no_writer_field():
    fields = StoryConfig.__dataclass_fields__
    assert "writing_style" not in fields
    assert "narrative_technique" in fields


def test_num_versions_defaults_to_one():
    assert StoryConfig(
        protagonist_name="a", protagonist_traits="b", world_setting="c",
        story_start="d",
    ).num_versions == 1


# ── Estimation ─────────────────────────────────────────────────────────

def _cfg(**kw):
    base = dict(
        target_word_count=8000, max_chapters=30, num_versions=1,
        max_tokens_per_call=4000, npc_mode="parallel", quality_mode="balanced",
        model="claude-sonnet-4-6", story_end="结局", front_matter=[],
    )
    base.update(kw)
    return SimpleNamespace(**base)


def test_estimate_scales_with_versions():
    one = estimate_run(_cfg(num_versions=1))
    three = estimate_run(_cfg(num_versions=3))
    assert three["llm_calls"] > one["llm_calls"]
    assert three["tokens_total"] > one["tokens_total"]
    assert three["cost_usd"] > one["cost_usd"]
    # versions run in parallel, so the wall clock does not scale the same way
    assert three["wall_minutes"] == pytest.approx(one["wall_minutes"], rel=0.2)


def test_estimate_flags_unreachable_word_target():
    est = estimate_run(_cfg(target_word_count=300000))
    assert any("超过" in n for n in est["notes"])


def test_estimate_warns_on_batch_generation():
    est = estimate_run(_cfg(num_versions=5))
    assert any("批量生成" in n for n in est["notes"])


def test_estimate_narrator_mode_costs_less():
    parallel = estimate_run(_cfg(npc_mode="parallel"))
    narrator = estimate_run(_cfg(npc_mode="narrator"))
    assert narrator["tokens_total"] < parallel["tokens_total"]


# ── Diversity diagnostic ───────────────────────────────────────────────

def test_analyze_text_returns_all_metrics():
    m = analyze_text(VARIED_TEXT)["metrics"]
    for key in ("phrase_repetition", "trigram_repetition", "sentence_length",
                "lexical_diversity", "punctuation_rhythm", "dialogue_ratio",
                "emotion_density", "semantic_smoothness"):
        assert key in m


def test_flat_text_scores_lower_than_varied_text():
    flat = diagnose(FLAT_TEXT)
    varied = diagnose(VARIED_TEXT)
    assert varied["score"] > flat["score"]


def test_flat_text_is_flagged_as_monotonous():
    report = diagnose(FLAT_TEXT)
    joined = " ".join(report["findings"])
    assert "模板" in joined or "σ" in joined or "一致" in joined


def test_diagnose_reports_forbidden_hits():
    text = "他眼中闪过一丝犹豫，嘴角勾起一抹笑。"
    report = diagnose(text, forbidden=["眼中闪过一丝", "嘴角勾起"])
    assert set(report["forbidden_hits"]) == {"眼中闪过一丝", "嘴角勾起"}


def test_diagnose_with_baseline_uses_drift():
    base = analyze_text(VARIED_TEXT)["metrics"]
    report = diagnose(VARIED_TEXT, baseline=base)
    assert 0 <= report["score"] <= 100


# ── Web API surface ────────────────────────────────────────────────────

def test_web_routes_expose_techniques_and_estimate():
    from novel_preactor.webui.app import app

    paths = {r.path for r in app.routes}
    assert "/api/techniques" in paths
    assert "/api/estimate" in paths
    # the writer-imitation endpoints are gone
    assert "/api/styles" not in paths
    assert "/api/styles/custom" not in paths


def test_estimate_endpoint_returns_a_usable_payload():
    from fastapi.testclient import TestClient
    from novel_preactor.webui.app import app

    with TestClient(app) as client:
        resp = client.post("/api/estimate", json={
            "target_word_count": 8000,
            "num_versions": 1,
            "max_chapters": 30,
            "model": "claude-sonnet-4-6",
        })
        assert resp.status_code == 200
        data = resp.json()
        for key in ("chapters", "llm_calls", "tokens_total", "wall_minutes",
                    "cost_usd", "cost_cny", "notes"):
            assert key in data


def test_techniques_endpoint_returns_the_library():
    from fastapi.testclient import TestClient
    from novel_preactor.webui.app import app

    with TestClient(app) as client:
        resp = client.get("/api/techniques")
        assert resp.status_code == 200
        data = resp.json()
        assert data["techniques"]
        assert "categories" in data
        first = data["techniques"][0]
        for key in ("id", "name", "category", "summary"):
            assert key in first
