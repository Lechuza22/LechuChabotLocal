"""Loads tasks from tasks/<id>/task.yaml, runs their pipeline, writes the HTML
report (+ PNG screenshot) under tasks/<id>/runs/, and delivers it to Telegram.
Used by the LechuPasto UI ("run now") and by the background daemon (schedule)."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

import yaml

from core.notify import notify_telegram, notify_telegram_file
from lechupasto import render
from lechupasto.report import build_report_html
from lechupasto.steps import STEP_CATALOG

logger = logging.getLogger(__name__)

TASKS_DIR = Path(__file__).parent / "tasks"
DAY_KEYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
WEEKDAYS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MONTHS = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
          "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
DELIVERY_RETRY = timedelta(minutes=10)

_retry_at: dict[str, datetime] = {}


@dataclass
class Task:
    id: str
    name: str
    description: str
    schedule: dict
    steps: list[dict]
    report: dict
    deliver: dict = field(default_factory=dict)

    @property
    def dir(self) -> Path:
        return TASKS_DIR / self.id

    @property
    def runs_dir(self) -> Path:
        path = self.dir / "runs"
        path.mkdir(parents=True, exist_ok=True)
        return path


@dataclass
class RunResult:
    task_id: str
    run_id: str
    html_path: Path
    png_path: Path | None
    pixel_height: int
    title: str


def load_tasks() -> dict[str, Task]:
    tasks: dict[str, Task] = {}
    for path in sorted(TASKS_DIR.glob("*/task.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        tasks[data["id"]] = Task(
            id=data["id"], name=data["name"], description=data.get("description", ""),
            schedule=data.get("schedule", {}), steps=data["steps"], report=data["report"],
            deliver=data.get("deliver", {}),
        )
    return tasks


def list_runs(task: Task) -> list[str]:
    """Run ids (file stems), newest first."""
    return sorted((p.stem for p in task.runs_dir.glob("*.html")), reverse=True)


def _meta_path(task: Task, run_id: str) -> Path:
    return task.runs_dir / f"{run_id}.json"


def _read_meta(task: Task, run_id: str) -> dict:
    try:
        return json.loads(_meta_path(task, run_id).read_text())
    except (OSError, ValueError):
        return {}


def _write_meta(task: Task, run_id: str, **updates) -> None:
    meta = _read_meta(task, run_id) | updates
    _meta_path(task, run_id).write_text(json.dumps(meta, ensure_ascii=False, indent=2))


def _template_vars(now: datetime, ctx: dict) -> dict:
    counts = {f"{k}_count": len(v) for k, v in ctx.items() if isinstance(v, list)}
    return {"weekday": WEEKDAYS[now.weekday()], "day": now.day, "month": MONTHS[now.month - 1],
            "since": "el fin de semana" if now.weekday() == 0 else "ayer", **counts}


def run_task(task: Task, now: datetime | None = None, scheduled: bool = False) -> RunResult:
    """Run the pipeline and write the report. `scheduled` runs use the plain
    date as run id (one per day); manual runs add the time so they never
    overwrite the scheduled one."""
    now = now or datetime.now()
    run_id = now.strftime("%Y-%m-%d") if scheduled else now.strftime("%Y-%m-%d_%H%M")

    ctx: dict = {}
    for step in task.steps:
        ctx[step["id"]] = STEP_CATALOG[step["type"]](now, step, ctx)
    variables = _template_vars(now, ctx)

    rep = task.report
    sections = [
        {"title": s["title"].format(**variables), "kind": s["kind"], "data": ctx[s["from"]]}
        for s in rep["sections"]
        # `hide_if_empty` sections only appear when there is something to show.
        if not (s.get("hide_if_empty") and not ctx[s["from"]])
    ]
    title = rep["title"].format(**variables)
    html_doc = build_report_html(title, rep.get("subtitle", ""), sections,
                                 f"Generado por LechuPasto · {now.strftime('%d/%m/%Y %H:%M')}")

    html_path = task.runs_dir / f"{run_id}.html"
    html_path.write_text(html_doc, encoding="utf-8")

    png_path, pixel_height = None, 0
    try:
        png_path, pixel_height = render.screenshot(html_path, task.runs_dir / f"{run_id}.png")
    except render.RenderError as exc:
        logger.warning("screenshot failed for %s/%s: %s", task.id, run_id, exc)

    _write_meta(task, run_id, title=title, generated=now.isoformat(timespec="seconds"),
                scheduled=scheduled, delivered=False, pixel_height=pixel_height)
    return RunResult(task.id, run_id, html_path, png_path, pixel_height, title)


def result_from_run(task: Task, run_id: str) -> RunResult:
    meta = _read_meta(task, run_id)
    png = task.runs_dir / f"{run_id}.png"
    return RunResult(task.id, run_id, task.runs_dir / f"{run_id}.html", png if png.exists() else None,
                     meta.get("pixel_height", 0), meta.get("title", task.name))


def run_meta(task: Task, run_id: str) -> dict:
    return _read_meta(task, run_id)


def deliver(task: Task, result: RunResult) -> bool:
    """Telegram delivery: screenshot as photo (document if too tall); falls back
    to a plain-text message when there's no screenshot."""
    if task.deliver.get("telegram") != "image":
        return True
    if result.png_path is None:
        ok = notify_telegram(f"{result.title}\n(no se pudo generar la imagen del reporte)")
    else:
        ok = notify_telegram_file(result.png_path, caption=result.title,
                                  as_document=not render.fits_telegram_photo(result.pixel_height))
    if ok:
        _write_meta(task, result.run_id, delivered=True)
    return ok


def _is_scheduled_today(task: Task, now: datetime) -> bool:
    sched = task.schedule
    if not sched:
        return False
    hour, minute = (int(x) for x in sched.get("time", "09:00").split(":"))
    return DAY_KEYS[now.weekday()] in sched.get("days", DAY_KEYS) and (now.hour, now.minute) >= (hour, minute)


def run_due_tasks(now: datetime | None = None) -> None:
    """Called by the daemon every tick. Runs each scheduled task once per day,
    from its scheduled time on (so a Mac that was asleep catches up on wake);
    a generated-but-undelivered run is re-sent, not regenerated."""
    now = now or datetime.now()
    for task in load_tasks().values():
        if not _is_scheduled_today(task, now):
            continue
        if _retry_at.get(task.id) and now < _retry_at[task.id]:
            continue
        run_id = now.strftime("%Y-%m-%d")
        meta = _read_meta(task, run_id)
        if meta.get("delivered"):
            continue
        try:
            if meta and (task.runs_dir / f"{run_id}.html").exists():
                result = result_from_run(task, run_id)
            else:
                logger.info("running task %s", task.id)
                result = run_task(task, now, scheduled=True)
            if deliver(task, result):
                _retry_at.pop(task.id, None)
                logger.info("task %s delivered", task.id)
            else:
                _retry_at[task.id] = now + DELIVERY_RETRY
                logger.warning("task %s not delivered, retrying at %s", task.id, _retry_at[task.id].strftime("%H:%M"))
        except Exception:  # one broken task must not stop the others
            logger.exception("task %s failed", task.id)
            _retry_at[task.id] = now + DELIVERY_RETRY
