"""Local, JSON-backed persistence for completed Navigator runs."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any


RUNS_DIRECTORY = Path(__file__).resolve().parent / "data" / "runs"
RUN_ID_PATTERN = re.compile(r"^run_\d{8}_\d{6}_[a-f0-9]{8}$")


def _run_path(run_id: str) -> Path:
    if not RUN_ID_PATTERN.fullmatch(run_id):
        raise ValueError("Invalid run id")
    return RUNS_DIRECTORY / f"{run_id}.json"


def _redact(value: Any) -> Any:
    """Keep environment secrets out of persisted, user-facing run data."""
    secrets = [item for key, item in os.environ.items() if item and any(word in key.upper() for word in ("KEY", "TOKEN", "SECRET", "PASSWORD"))]
    if isinstance(value, str):
        for secret in secrets:
            if len(secret) > 3:
                value = value.replace(secret, "[REDACTED]")
        return value
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, dict):
        return {key: _redact(item) for key, item in value.items()}
    return value


def build_history_record(run: dict[str, Any]) -> dict[str, Any]:
    started_at = run.get("started_at")
    completed_at = run.get("completed_at")
    duration_seconds: int | None = None
    if started_at and completed_at:
        try:
            duration_seconds = max(0, round((datetime.fromisoformat(completed_at) - datetime.fromisoformat(started_at)).total_seconds()))
        except ValueError:
            duration_seconds = None

    constraints = {item["label"].lower(): item["value"] for item in run.get("constraints", [])}
    return _redact(
        {
            "run_id": run["id"],
            "started_at": started_at,
            "completed_at": completed_at,
            "duration_seconds": duration_seconds,
            "status": run.get("status", "failed"),
            "task": run.get("task"),
            "agent": {"model": "gemini-3.5-flash", "browser": "Airbnb"},
            "constraints": constraints,
            "plan": [item.get("label", item) if isinstance(item, dict) else item for item in run.get("plan", [])],
            "events": run.get("events", []),
            "recovery_count": len(run.get("recovery_events", [])),
            "human_interventions": 0,
            "final_result": {"summary": run.get("result") or "Not available"},
            "safety": {
                "reservation_attempted": False,
                "payment_attempted": False,
                "safety_stop": run.get("status") == "completed",
            },
        }
    )


def save_run(run: dict[str, Any]) -> Path:
    RUNS_DIRECTORY.mkdir(parents=True, exist_ok=True)
    destination = _run_path(run["id"])
    temporary = destination.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as file:
        json.dump(build_history_record(run), file, ensure_ascii=False, indent=2)
        file.write("\n")
    temporary.replace(destination)
    return destination


def load_run(run_id: str) -> dict[str, Any] | None:
    path = _run_path(run_id)
    if not path.exists():
        return None
    try:
        with path.open(encoding="utf-8") as file:
            return json.load(file)
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("Saved history file could not be read") from exc


def list_runs() -> list[dict[str, Any]]:
    if not RUNS_DIRECTORY.exists():
        return []
    records: list[dict[str, Any]] = []
    for path in RUNS_DIRECTORY.glob("run_*.json"):
        try:
            with path.open(encoding="utf-8") as file:
                record = json.load(file)
            if isinstance(record, dict) and record.get("run_id"):
                records.append(
                    {
                        "run_id": record["run_id"],
                        "started_at": record.get("started_at"),
                        "completed_at": record.get("completed_at"),
                        "status": record.get("status"),
                        "task": record.get("task"),
                        "duration_seconds": record.get("duration_seconds"),
                        "recovery_count": record.get("recovery_count", 0),
                    }
                )
        except (OSError, json.JSONDecodeError):
            # A malformed local file should not break the whole history page.
            continue
    return sorted(records, key=lambda record: record.get("started_at") or "", reverse=True)


def delete_run(run_id: str) -> bool:
    path = _run_path(run_id)
    if not path.exists():
        return False
    path.unlink()
    return True
