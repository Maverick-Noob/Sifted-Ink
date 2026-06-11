"""
FastAPI Web UI for 选墨集 / Sifted-Ink — Multi-Agent Story Engine.

Provides:
  - Dark-themed config form (GET /)
  - Async story generation with SSE progress streaming
  - Result viewing and file downloads
"""

import asyncio
import json
import logging
import re
import uuid
import time
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from ..models import StoryConfig, PreActorResult
from ..config import load_config_from_yaml, _detect_provider
from ..agents import PROVIDER_REGISTRY, resolve_api_key
from ..constraints import ShutdownHandler
from ..preactor import run_pre_actor
from ..evaluator import evaluate_versions
from ..writer import generate_novel, generate_novel_for_version, generate_eval_log, generate_front_matter
from ..exporter import export_novel, FORMATS
from ..agents import LLMClient
from ..naming import NamingEngine
from ..utils import logger as app_logger, load_writing_styles, get_regions, get_writers_by_region


# ── Log streaming: capture console logs per run ───────────────────────

class RunLogHandler(logging.Handler):
    """Custom handler that emits SSE events for each log record."""

    def __init__(self, run_id: str):
        super().__init__()
        self.run_id = run_id
        self.setLevel(logging.DEBUG)
        self.setFormatter(logging.Formatter("%(levelname)-7s %(message)s"))

    def emit(self, record: logging.LogRecord):
        try:
            msg = self.format(record)
            level = record.levelname.lower()
            _emit(self.run_id, "log", {
                "level": level,
                "message": msg,
                "time": time.strftime("%H:%M:%S", time.localtime(record.created)),
            })
        except Exception:
            pass  # never let logging break the app

# ── App setup ──────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(
    title="选墨集 / Sifted-Ink",
    description="多 Agent 预演故事生成器 Web UI",
    version="1.0.0",
)

app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# ── In-memory run storage ──────────────────────────────────────────────

runs: dict[str, dict] = {}  # run_id → {state, result, events, ...}


def _create_run() -> str:
    run_id = uuid.uuid4().hex[:12]
    runs[run_id] = {
        "status": "configuring",
        "progress": 0,
        "message": "",
        "events": [],
        "result": None,
        "config": None,
        "shutdown": None,
        "task": None,
        "start_time": None,
        "output_dir": "",
        "log_handler": None,  # RunLogHandler — attached during generation
    }
    return run_id


def _emit(run_id: str, event_type: str, data: dict):
    """Emit an SSE event to a run's event queue."""
    if run_id not in runs:
        return
    payload = json.dumps(data, ensure_ascii=False)
    runs[run_id]["events"].append(f"event: {event_type}\ndata: {payload}\n\n")


def _update_status(run_id: str, status: str, message: str = "", progress: int = -1):
    """Update run status and emit a status event."""
    if run_id not in runs:
        return
    run = runs[run_id]
    run["status"] = status
    if message:
        run["message"] = message
    if progress >= 0:
        run["progress"] = progress
    _emit(run_id, "status", {
        "status": status,
        "message": message,
        "progress": run["progress"],
    })


# ── Background generation task ─────────────────────────────────────────

async def _run_generation(run_id: str, config: StoryConfig, output_dir: str):
    """Run the full preactor pipeline in background, emitting SSE events."""
    # Attach log handler so console output streams to web UI
    log_handler = RunLogHandler(run_id)
    root_logger = logging.getLogger()
    root_logger.addHandler(log_handler)
    runs[run_id]["log_handler"] = log_handler

    try:
        shutdown = ShutdownHandler().install()
        runs[run_id]["shutdown"] = shutdown
        runs[run_id]["start_time"] = time.time()

        _update_status(run_id, "running", "预演开始...", 5)

        # Phase 1: Pre-rehearsal
        _emit(run_id, "phase", {"phase": 1, "label": "并行预演中"})

        # Per-chapter progress callback
        version_chapters = {}  # version_id -> max_chapter_seen
        total_chapters_estimate = config.max_chapters

        async def on_chapter(version_id: int, chapter_num: int, total_ch: int):
            nonlocal total_chapters_estimate
            total_chapters_estimate = max(total_chapters_estimate, total_ch)
            version_chapters[version_id] = max(
                version_chapters.get(version_id, 0), chapter_num
            )
            # Average progress across all versions (scale 5% → 55%)
            avg_ch = sum(version_chapters.values()) / max(len(version_chapters), 1)
            pct = 5 + int((avg_ch / total_chapters_estimate) * 50)
            pct = min(55, pct)
            _update_status(run_id, "running", f"预演中... (各版本平均 {avg_ch:.1f} 章)", pct)

        result = await run_pre_actor(config, shutdown, progress_callback=on_chapter)

        if shutdown.shutdown_requested:
            _update_status(run_id, "cancelled", "用户取消", 50)
            runs[run_id]["result"] = result
            return

        _update_status(run_id, "running", "评估版本中...", 60)

        # Phase 2: Evaluation
        _emit(run_id, "phase", {"phase": 2, "label": "评估版本中"})
        result = await evaluate_versions(result, shutdown, interactive=False)

        if shutdown.shutdown_requested:
            _update_status(run_id, "cancelled", "用户取消", 80)
            runs[run_id]["result"] = result
            return

        _update_status(run_id, "running", "起名中...", 85)

        # Phase 3: Story naming & summarization
        _emit(run_id, "phase", {"phase": 3, "label": "情节总结与起名"})

        novel_text = generate_novel(result)
        story_name = f"{config.protagonist_name}的传奇"
        story_meta = {}

        # Story naming: rule-based candidates + LLM scoring
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
                app_logger.warning(f"故事命名失败: {e}")

        _update_status(run_id, "running", "生成前附文...", 93)

        # Phase 3.5: Front matter generation
        if config.front_matter:
            try:
                client2 = LLMClient(config)
                fm_text = await generate_front_matter(
                    config, story_name, novel_text,
                    llm_client=client2,
                )
                if fm_text:
                    # Insert front matter after title but before chapters
                    # Find first ## heading
                    first_ch = novel_text.find("\n## ")
                    if first_ch > 0:
                        novel_text = novel_text[:first_ch] + "\n" + fm_text + novel_text[first_ch:]
                    else:
                        novel_text = fm_text + novel_text
            except Exception as e:
                app_logger.warning(f"前附文生成失败: {e}")

        _update_status(run_id, "running", "保存文件...", 95)

        # Phase 4: Save output files
        _emit(run_id, "phase", {"phase": 4, "label": "保存文件"})

        out_path = Path(output_dir)
        out_path.mkdir(parents=True, exist_ok=True)

        # Use story name + timestamp + version for filenames
        from datetime import datetime
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_name = re.sub(r'[\\/*?:"<>|]', '_', story_name)[:30]
        vtag = f"v{result.winning_version_id}"
        file_base = f"{safe_name}_{ts}_{vtag}"

        novel_path = out_path / f"{file_base}.md"
        novel_path.write_text(novel_text, encoding="utf-8")

        # Save generation parameters as YAML
        import yaml
        params_path = out_path / f"{file_base}_params.yaml"
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
                "completed_versions": sum(1 for v in result.versions if v.reached_ending),
                "total_versions": len(result.versions),
            },
        }
        params_path.write_text(
            yaml.dump(params_data, allow_unicode=True, default_flow_style=False),
            encoding="utf-8",
        )

        eval_log = generate_eval_log(result, story_meta)
        # Save eval with fixed name for reliable downloads
        eval_path = out_path / "eval_log.json"
        eval_path.write_text(json.dumps(eval_log, ensure_ascii=False, indent=2), encoding="utf-8")
        runs[run_id]["eval_path"] = str(eval_path)

        # Generate novels for ALL completed versions (not just winner)
        version_files = {}
        for v in result.versions:
            if v.reached_ending and not v.terminated_early:
                vtag = f"v{v.version_id}"
                v_base = f"{safe_name}_{ts}_{vtag}"
                v_novel = generate_novel_for_version(result, v)
                v_novel_path = out_path / f"{v_base}.md"
                v_novel_path.write_text(v_novel, encoding="utf-8")
                version_files[v.version_id] = {"file_base": v_base, "words": v.total_words}
                if v.version_id == result.winning_version_id:
                    # Already saved above, just track
                    pass
                else:
                    app_logger.info(f"  📄 版本 {v.version_id} 小说已保存: {v_base}.md")

        runs[run_id]["result"] = result
        runs[run_id]["output_dir"] = str(out_path)
        runs[run_id]["story_name"] = story_name
        runs[run_id]["story_meta"] = story_meta
        runs[run_id]["file_base"] = file_base
        runs[run_id]["version_files"] = version_files

        # Emit version summaries
        for v in result.versions:
            ev = next((e for e in result.evaluations if e.version_id == v.version_id), None)
            _emit(run_id, "version", {
                "version_id": v.version_id,
                "chapters": v.chapter_count,
                "words": v.total_words,
                "reached_ending": v.reached_ending,
                "score": ev.total_score if ev else 0,
                "is_winner": v.version_id == result.winning_version_id,
            })

        _update_status(run_id, "done", "生成完成！", 100)
        _emit(run_id, "result_ready", {
            "story_name": story_name,
            "plot_summary": story_meta.get("plot_summary", ""),
            "candidate_names": story_meta.get("candidate_names", []),
            "novel_url": f"/download/{run_id}/md",
            "eval_url": f"/download/{run_id}/eval",
            "winning_version": result.winning_version_id,
            "total_tokens": result.total_tokens_used,
            "time_elapsed": round(result.time_elapsed_seconds, 1),
        })

    except asyncio.CancelledError:
        _update_status(run_id, "cancelled", "任务被取消", 50)
    except Exception as e:
        app_logger.error(f"Run {run_id} failed: {e}", exc_info=True)
        _update_status(run_id, "error", f"出错: {str(e)}", 50)
        _emit(run_id, "error", {"message": str(e)})
    finally:
        if runs[run_id].get("shutdown"):
            runs[run_id]["shutdown"].uninstall()
        # Detach log handler
        handler = runs[run_id].get("log_handler")
        if handler:
            root_logger = logging.getLogger()
            root_logger.removeHandler(handler)
            runs[run_id]["log_handler"] = None
        # Signal SSE to close
        _emit(run_id, "close", {})


# ── Routes ─────────────────────────────────────────────────────────────

@app.get("/api/styles")
async def get_styles(region: str = ""):
    """Get writing styles, optionally filtered by region."""
    regions = get_regions()
    if region:
        writers = get_writers_by_region(region)
    else:
        writers = load_writing_styles()

    # Load custom styles
    custom = _load_custom_styles()

    return {
        "regions": regions,
        "writers": [
            {
                "name": w["name"],
                "region": w["region"],
                "style": w["style"],
                "works": w.get("representative_works", []),
                "death_year": w.get("death_year"),
                "is_public_domain": w.get("is_public_domain", False),
            }
            for w in writers
        ],
        "custom": custom,
    }


@app.post("/api/styles/custom")
async def add_custom_style(request: Request):
    """Add a custom writing style."""
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    name = data.get("name", "").strip()
    style_desc = data.get("style", "").strip()
    if not name or not style_desc:
        raise HTTPException(status_code=400, detail="Name and style are required")

    custom = _load_custom_styles()
    new_style = {
        "name": name,
        "region": data.get("region", "自定义").strip() or "自定义",
        "style": style_desc,
        "representative_works": data.get("works", []),
    }
    custom.append(new_style)
    _save_custom_styles(custom)

    return {"status": "ok", "custom": custom}


def _custom_styles_path() -> Path:
    return Path(__file__).resolve().parent.parent / "user_styles.json"


def _load_custom_styles() -> list:
    path = _custom_styles_path()
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []


def _save_custom_styles(styles: list):
    path = _custom_styles_path()
    path.write_text(json.dumps(styles, ensure_ascii=False, indent=2), encoding="utf-8")


@app.get("/terms", response_class=HTMLResponse)
async def terms_page(request: Request):
    """Display terms of use."""
    from pathlib import Path as _Path
    terms_path = _Path(__file__).resolve().parent.parent / "TERMS.md"
    if terms_path.exists():
        content = terms_path.read_text(encoding="utf-8")
        # Simple markdown to HTML conversion
        import re as _re
        html = _re.sub(r'^### (.+)$', r'<h3>\1</h3>', content, flags=_re.MULTILINE)
        html = _re.sub(r'^## (.+)$', r'<h2>\1</h2>', html, flags=_re.MULTILINE)
        html = _re.sub(r'^# (.+)$', r'<h1>\1</h1>', html, flags=_re.MULTILINE)
        html = _re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', html)
        html = _re.sub(r'^- (.+)$', r'<li>\1</li>', html, flags=_re.MULTILINE)
        html = '<div class="novel-preview" style="max-width:800px;margin:2rem auto;">' + html + '</div>'
    else:
        html = '<p>Terms file not found.</p>'

    return HTMLResponse(f"""
    <!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">
    <title>使用条款 — 选墨集 / Sifted-Ink</title>
    <link rel="stylesheet" href="/static/style.css"></head>
    <body><div class="container">{html}
    <p style="text-align:center;margin-top:2rem;"><a href="/">← 返回首页</a></p>
    </div></body></html>
    """)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Main page — story configuration form."""
    return templates.TemplateResponse(request=request, name="index.html", context={"request": request})


@app.post("/api/start")
async def start_generation(
    request: Request,
    protagonist_name: str = Form(""),
    protagonist_traits: str = Form(""),
    world_setting: str = Form(...),
    story_start: str = Form(...),
    story_end: str = Form(""),
    target_word_count: int = Form(8000),
    num_versions: int = Form(3),
    max_npcs: int = Form(30),
    max_chapters: int = Form(30),
    total_token_budget: int = Form(0),
    npc_name_style: str = Form("default"),
    protagonist_mode: str = Form("spotlight"),
    protagonist_count: int = Form(1),
    protagonist_order: str = Form(""),
    npc_mode: str = Form("parallel"),
    quality_mode: str = Form("balanced"),
    naming_style: str = Form(""),
    api_key: str = Form(""),
    model: str = Form("claude-sonnet-4-6"),
    api_provider: str = Form("anthropic"),
    writing_style: str = Form(""),
):
    """Start a generation run. Returns JSON with run_id."""
    # Parse front_matter and user NPCs from multi-value form fields
    form_data = await request.form()
    front_matter_values = form_data.getlist("front_matter")

    # Parse dynamic protagonist fields (protagonist_name_N, protagonist_traits_N, ...)
    import re as _re
    proto_names = []
    proto_traits_parts = []
    proto_order_parts = []
    for key in sorted(form_data.keys()):
        m = _re.match(r"protagonist_name_(\d+)$", key)
        if m:
            idx = m.group(1)
            name = form_data.get(key, "").strip()
            if name:
                proto_names.append(name)
                traits = form_data.get(f"protagonist_traits_{idx}", "").strip()
                proto_traits_parts.append(f"{name}: {traits}" if traits else name)
                role = form_data.get(f"protagonist_role_{idx}", "").strip()
                abilities = form_data.get(f"protagonist_abilities_{idx}", "").strip()
                intro = form_data.get(f"protagonist_intro_{idx}", "0").strip()
                if role or abilities or intro:
                    extras = []
                    if role: extras.append(f"角色: {role}")
                    if abilities: extras.append(f"能力: {abilities}")
                    if intro and intro != "0": extras.append(f"登场: 第{intro}章")
                    if extras:
                        proto_order_parts.append(f"{name}({' / '.join(extras)})")
                    else:
                        proto_order_parts.append(name)

    # Resolve protagonist fields
    if proto_names:
        resolved_protagonist_name = proto_names[0]  # first as main
        resolved_protagonist_traits = "; ".join(proto_traits_parts)
        resolved_protagonist_count = len(proto_names)
        resolved_protagonist_order = ", ".join(proto_order_parts)
    else:
        resolved_protagonist_name = protagonist_name
        resolved_protagonist_traits = protagonist_traits
        resolved_protagonist_count = protagonist_count
        resolved_protagonist_order = protagonist_order.strip()

    # Parse dynamic NPC fields (npc_name_N, npc_role_N, ...)
    from ..models import UserNPC
    user_npcs = []
    npc_indices = set()
    for key in form_data:
        m = _re.match(r"npc_name_(\d+)$", key)
        if m:
            npc_indices.add(int(m.group(1)))
    for idx in sorted(npc_indices):
        name = form_data.get(f"npc_name_{idx}", "").strip()
        if not name:
            continue
        user_npcs.append(UserNPC(
            name=name,
            role=form_data.get(f"npc_role_{idx}", ""),
            personality=form_data.get(f"npc_personality_{idx}", ""),
            backstory=form_data.get(f"npc_backstory_{idx}", ""),
            relevance=form_data.get(f"npc_relevance_{idx}", "medium"),
            intro_chapter=int(form_data.get(f"npc_intro_{idx}", "0") or "0"),
            exit_chapter=int(form_data.get(f"npc_exit_{idx}", "0") or "0"),
            abilities=form_data.get(f"npc_abilities_{idx}", ""),
        ))

    # Auto-detect provider if needed
    resolved_provider = _detect_provider(model, api_provider)

    # Resolve API key: explicit > provider-specific env > generic env
    resolved_key = resolve_api_key(resolved_provider, api_key.strip())
    if not resolved_key:
        info = PROVIDER_REGISTRY.get(resolved_provider, {})
        env_specific = info.get("api_key_env", "")
        checked = f"已检查: 表单输入、环境变量 {env_specific}、SIFTED_INK_API_KEY" if env_specific else \
                   "已检查: 表单输入、环境变量 SIFTED_INK_API_KEY"
        raise HTTPException(
            status_code=400,
            detail=f"未找到有效的 API Key。{checked}。请在表单中填写 API Key 或设置对应的环境变量。"
        )

    # Auto-resolve base URL from provider registry
    info = PROVIDER_REGISTRY.get(resolved_provider, {})
    resolved_url = info.get("base_url") or ""

    # Convert 0 budget to None (unlimited)
    resolved_budget = total_token_budget if total_token_budget > 0 else None

    config = StoryConfig(
        protagonist_name=resolved_protagonist_name,
        protagonist_traits=resolved_protagonist_traits,
        world_setting=world_setting,
        story_start=story_start,
        story_end=story_end,
        writing_style=writing_style.strip(),
        npc_name_style=npc_name_style,
        protagonist_mode=protagonist_mode,
        protagonist_count=resolved_protagonist_count,
        protagonist_order=resolved_protagonist_order,
        npc_mode=npc_mode,
        quality_mode=quality_mode,
        naming_style=naming_style.strip(),
        front_matter=list(front_matter_values),
        user_npcs=user_npcs,
        target_word_count=target_word_count,
        num_versions=num_versions,
        max_npcs=max_npcs,
        max_chapters=max_chapters,
        total_token_budget=resolved_budget,
        api_key=resolved_key,
        model=model,
        api_provider=resolved_provider,
        api_base_url=resolved_url,
    )

    errors = config.validate()
    if errors:
        raise HTTPException(status_code=400, detail="; ".join(errors))

    run_id = _create_run()
    runs[run_id]["config"] = config

    output_dir = str(Path.cwd() / "output" / run_id)
    runs[run_id]["output_dir"] = output_dir

    task = asyncio.create_task(_run_generation(run_id, config, output_dir))
    runs[run_id]["task"] = task

    return {"run_id": run_id}


@app.get("/api/stream/{run_id}")
async def stream_progress(run_id: str, request: Request):
    """SSE endpoint for real-time progress updates."""
    if run_id not in runs:
        raise HTTPException(status_code=404, detail="Run not found")

    async def event_generator():
        # Send existing events first
        for event_str in runs[run_id]["events"]:
            if await request.is_disconnected():
                break
            yield event_str

        # Send new events as they arrive
        last_idx = len(runs[run_id]["events"])
        while True:
            if await request.is_disconnected():
                break

            current_events = runs[run_id]["events"]
            while last_idx < len(current_events):
                yield current_events[last_idx]
                last_idx += 1

            # Check if run is in terminal state
            if runs[run_id]["status"] in ("done", "error", "cancelled"):
                yield "event: close\ndata: {}\n\n"
                break

            await asyncio.sleep(0.3)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/status/{run_id}")
async def get_status(run_id: str):
    """Get current status of a run."""
    if run_id not in runs:
        raise HTTPException(status_code=404, detail="Run not found")

    run = runs[run_id]
    result = run.get("result")

    return {
        "run_id": run_id,
        "status": run["status"],
        "progress": run["progress"],
        "message": run["message"],
        "versions": [
            {
                "version_id": v.version_id,
                "chapters": v.chapter_count,
                "words": v.total_words,
                "reached_ending": v.reached_ending,
                "terminated_early": v.terminated_early,
                "termination_reason": v.termination_reason,
            }
            for v in result.versions
        ] if result else [],
        "evaluations": [
            {
                "version_id": e.version_id,
                "total_score": e.total_score,
                "dramatic_tension": e.dramatic_tension,
                "character_growth": e.character_growth,
                "logic_consistency": e.logic_consistency,
                "ending_alignment": e.ending_alignment,
            }
            for e in result.evaluations
        ] if result else [],
    }


@app.post("/api/cancel/{run_id}")
async def cancel_run(run_id: str):
    """Cancel a running generation."""
    if run_id not in runs:
        raise HTTPException(status_code=404, detail="Run not found")

    run = runs[run_id]
    if run.get("shutdown"):
        run["shutdown"].shutdown_requested = True

    if run.get("task"):
        run["task"].cancel()

    _update_status(run_id, "cancelled", "用户取消")
    return {"status": "cancelled"}


@app.get("/progress/{run_id}", response_class=HTMLResponse)
async def progress_page(request: Request, run_id: str):
    """Progress page with real-time updates."""
    if run_id not in runs:
        raise HTTPException(status_code=404, detail="Run not found")
    return templates.TemplateResponse(
        request=request, name="progress.html",
        context={"request": request, "run_id": run_id},
    )


@app.get("/result/{run_id}", response_class=HTMLResponse)
async def result_page(request: Request, run_id: str):
    """Result page showing the generated novel and eval data."""
    if run_id not in runs:
        raise HTTPException(status_code=404, detail="Run not found")

    run = runs[run_id]
    result = run.get("result")

    if not result or run["status"] != "done":
        raise HTTPException(status_code=404, detail="Result not ready")

    novel_text = generate_novel(result)
    eval_log = generate_eval_log(result, run.get("story_meta"))

    return templates.TemplateResponse(
        request=request, name="result.html",
        context={
            "request": request,
            "run_id": run_id,
            "novel_text": novel_text,
            "eval_log": eval_log,
            "result": result,
            "story_name": run.get("story_name", ""),
            "story_meta": run.get("story_meta", {}),
        },
    )


@app.get("/download/{run_id}/{format}/{version_id}")
async def download_version_novel(run_id: str, format: str, version_id: int):
    """Download a specific version's novel."""
    if run_id not in runs:
        raise HTTPException(status_code=404, detail="Run not found")
    if format not in FORMATS:
        raise HTTPException(status_code=400, detail=f"Unsupported format: {format}")

    run = runs[run_id]
    output_dir = Path(run.get("output_dir", ""))
    version_files = run.get("version_files", {})

    vkey = version_id
    vinfo = version_files.get(vkey)
    if not vinfo:
        raise HTTPException(status_code=404, detail=f"Version {version_id} not found or not completed")

    v_base = vinfo["file_base"]
    file_ext = FORMATS[format]["ext"]
    file_path = output_dir / f"{v_base}{file_ext}"

    if not file_path.exists():
        # Generate non-MD format on demand
        result = run.get("result")
        if not result:
            raise HTTPException(status_code=404, detail="Result not found")
        version = next((v for v in result.versions if v.version_id == version_id), None)
        if not version:
            raise HTTPException(status_code=404, detail="Version not found")

        novel_text = generate_novel_for_version(result, version)
        title = run.get("story_name", f"{result.config.protagonist_name}的传奇")
        file_path_str = export_novel(novel_text, str(output_dir), format, title=title)
        exported = Path(file_path_str)
        target = output_dir / f"{v_base}{file_ext}"
        if exported != target:
            exported.rename(target)
        file_path = target

    return FileResponse(
        str(file_path),
        media_type=FORMATS[format]["mime"],
        filename=f"{v_base}{file_ext}",
    )


@app.get("/download/{run_id}/{format}")
async def download_novel(run_id: str, format: str):
    """Download the generated novel in the specified format."""
    if run_id not in runs:
        raise HTTPException(status_code=404, detail="Run not found")
    if format not in FORMATS:
        raise HTTPException(status_code=400, detail=f"Unsupported format: {format}. Use: {', '.join(FORMATS)}")

    run = runs[run_id]
    output_dir = Path(run.get("output_dir", ""))
    file_base = run.get("file_base", "novel_output")
    file_ext = FORMATS[format]["ext"]
    file_path = output_dir / f"{file_base}{file_ext}"

    # Generate on first request if not already cached
    if not file_path.exists():
        try:
            result = run.get("result")
            if not result:
                raise HTTPException(status_code=404, detail="Generation result not found")

            novel_text = generate_novel(result)
            title = run.get("story_name", f"{result.config.protagonist_name}的传奇")
            file_path_str = export_novel(novel_text, str(output_dir), format, title=title)
            # Rename to match our naming convention
            exported = Path(file_path_str)
            target = output_dir / f"{file_base}{file_ext}"
            if exported != target:
                exported.rename(target)
            file_path = target
        except ImportError as e:
            raise HTTPException(status_code=500, detail=str(e))
        except RuntimeError as e:
            raise HTTPException(status_code=500, detail=str(e))

    download_name = f"{file_base}{file_ext}"
    return FileResponse(
        str(file_path),
        media_type=FORMATS[format]["mime"],
        filename=download_name,
    )


@app.get("/download/{run_id}/eval")
async def download_eval(run_id: str):
    """Download the evaluation log as JSON."""
    if run_id not in runs:
        raise HTTPException(status_code=404, detail="Run not found")

    run = runs[run_id]
    output_dir = Path(run.get("output_dir", ""))

    # Try multiple paths: stored path, then eval_log.json, then any .json eval file
    candidates = [
        Path(run.get("eval_path", "")),
        output_dir / "eval_log.json",
    ]
    # Also search for any eval*.json files
    try:
        for f in output_dir.glob("*eval*.json"):
            if f not in candidates:
                candidates.append(f)
    except Exception:
        pass

    eval_path = None
    for p in candidates:
        if p.exists():
            eval_path = p
            break

    if eval_path is None:
        raise HTTPException(status_code=404, detail="Eval log not found")

    return FileResponse(
        str(eval_path),
        media_type="application/json",
        filename="eval_log.json",
    )


# ── Startup ────────────────────────────────────────────────────────────

def main():
    """Entry point: `python -m novel_preactor --web` or `python -m novel_preactor.webui`."""
    import sys as _sys
    _sys.stdout.write("\n  选墨集 / Sifted-Ink  v1.0\n  千墨选一，落纸成书\n")
    _sys.stdout.write("  🌐 http://localhost:8000\n\n")
    _sys.stdout.flush()
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")


if __name__ == "__main__":
    main()
