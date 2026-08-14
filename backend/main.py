import asyncio
import logging
import os
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from browser_agent import run_task
from history_store import delete_run as delete_saved_run
from history_store import list_runs, load_run, save_run
from observability import create_run_payload


app = FastAPI(title="Navigator AI")
logger = logging.getLogger("uvicorn.error")

frontend_url = os.getenv("FRONTEND_URL", "").rstrip("/")
allowed_origins = ["http://localhost:5173", "http://127.0.0.1:5173"]
if frontend_url and frontend_url not in allowed_origins:
    allowed_origins.append(frontend_url)

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class TaskRequest(BaseModel):
    task: str = Field(min_length=3, max_length=2000)


# In-memory state is intentional for this hackathon dashboard. It avoids adding
# infrastructure while letting the UI poll only user-facing execution status.
runs: dict[str, dict] = {}
active_tasks: set[asyncio.Task] = set()
latest_run_id: str | None = None
# Browser previews are deliberately transient. Execution history continues to
# contain only the existing safe run metadata.
run_connections: dict[str, set[WebSocket]] = {}
latest_screenshots: dict[str, str] = {}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def schedule_broadcast(run_id: str, event: dict) -> None:
    """Publish without delaying Browser Use callbacks or the agent action loop."""
    try:
        asyncio.get_running_loop().create_task(broadcast_run_event(run_id, event))
    except RuntimeError:
        # This only occurs outside an active ASGI event loop (for example a
        # synchronous unit test); the run state remains available via REST.
        return


async def broadcast_run_event(run_id: str, event: dict) -> None:
    stale_connections: list[WebSocket] = []
    for connection in tuple(run_connections.get(run_id, set())):
        try:
            await connection.send_json(event)
        except (RuntimeError, WebSocketDisconnect):
            stale_connections.append(connection)
        except Exception as exc:
            # A disconnected preview client must never affect the agent run.
            logger.debug("[Navigator] Browser preview delivery failed: %s", type(exc).__name__)
            stale_connections.append(connection)
    for connection in stale_connections:
        run_connections.get(run_id, set()).discard(connection)


def publish_browser_preview(run_id: str, event: dict) -> None:
    """Keep only the latest real Chromium screenshot in memory for a run."""
    if event.get("type") == "browser_screenshot" and isinstance(event.get("image"), str):
        latest_screenshots[run_id] = event["image"]
    schedule_broadcast(run_id, {**event, "run_id": run_id})


def emit(
    run_id: str,
    event_type: str,
    message: str,
    next_action: str | None = None,
    state: str | None = None,
) -> None:
    run = runs.get(run_id)
    if not run:
        return
    run["current_decision"] = message
    if next_action:
        run["next_action"] = next_action
    if state:
        previous_state = run.get("state")
        if (
            previous_state
            and previous_state not in {state, "RECOVER", "ERROR", "COMPLETE"}
            and previous_state not in run["completed_states"]
        ):
            run["completed_states"].append(previous_state)
        if state == "COMPLETE" and state not in run["completed_states"]:
            run["completed_states"].append(state)
        run["state"] = state
    event = {"type": event_type, "message": message, "timestamp": now()}
    run["events"].append(event)
    if event_type == "recovery":
        run["recovery_events"].append(event)
    schedule_broadcast(run_id, {"type": "browser_status", "run_id": run_id, "status": run.get("status", "queued"), "event": event})


async def execute_run(run_id: str, task: str) -> None:
    run = runs[run_id]
    run["status"] = "running"
    run["started_at"] = now()
    logger.info("[Navigator] Starting browser agent for run %s", run_id)
    emit(run_id, "decision", "Understanding user request", "Plan the browser workflow", "UNDERSTAND")
    try:
        result = await run_task(
            task,
            status_callback=lambda message, next_action=None, state=None, event_type="decision": emit(
                run_id, event_type, message, next_action, state
            ),
            preview_callback=lambda event: publish_browser_preview(run_id, event),
        )
        if result is None or not str(result).strip():
            raise RuntimeError("Browser agent returned no final result")
        run["status"] = "completed"
        run["result"] = result
        logger.info("[Navigator] Agent execution completed for run %s", run_id)
        emit(run_id, "safety", "Workflow finished with the safety guard active", "Stop before reservation or payment", "COMPLETE")
    except asyncio.CancelledError:
        run["status"] = "cancelled"
        run["error"] = "The task was cancelled before completion."
        logger.warning("[Navigator] Agent execution cancelled for run %s", run_id)
        emit(run_id, "error", "Browser task was cancelled", "Return to the dashboard and try again", "ERROR")
        raise
    except Exception as exc:
        # Keep operational details out of the dashboard and server response.
        run["status"] = "failed"
        run["error"] = "Browser agent encountered an error. Please try again."
        emit(run_id, "error", "Browser session could not complete", "Review the task and retry", "ERROR")
        logger.warning("[Navigator] Agent execution failed for run %s: %s", run_id, type(exc).__name__)
    finally:
        run["completed_at"] = now()
        try:
            save_run(run)
            run["saved_to_history"] = True
            logger.info("[Navigator] Run saved to execution history: %s", run_id)
        except Exception as exc:
            run["saved_to_history"] = False
            logger.warning("[Navigator] Run history save failed for %s: %s", run_id, type(exc).__name__)
        schedule_broadcast(run_id, {"type": "browser_status", "run_id": run_id, "status": run["status"]})


@app.get("/")
def root():
    return {"status": "online", "agent": "Navigator AI"}


@app.post("/run")
async def run_agent(request: TaskRequest):
    global latest_run_id
    task = request.task.strip()
    if not task:
        raise HTTPException(status_code=422, detail="Task cannot be empty")

    run_id = f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:8]}"
    logger.info("[Navigator] Task received for run %s", run_id)
    run = create_run_payload(task)
    run["id"] = run_id
    runs[run_id] = run
    latest_run_id = run_id
    execution_task = asyncio.create_task(execute_run(run_id, task))
    active_tasks.add(execution_task)
    execution_task.add_done_callback(active_tasks.discard)
    return run


@app.websocket("/ws/runs/{run_id}")
async def run_websocket(websocket: WebSocket, run_id: str):
    """Stream only safe browser status and the latest in-memory preview image."""
    if run_id not in runs:
        await websocket.close(code=4404)
        return

    await websocket.accept()
    run_connections.setdefault(run_id, set()).add(websocket)
    try:
        await websocket.send_json({"type": "browser_status", "run_id": run_id, "status": runs[run_id].get("status", "queued")})
        if screenshot := latest_screenshots.get(run_id):
            await websocket.send_json({"type": "browser_screenshot", "run_id": run_id, "image": screenshot})
        while True:
            # The client need not send data. Waiting here keeps the socket open
            # while screenshot broadcasts are sent by independent tasks.
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        run_connections.get(run_id, set()).discard(websocket)


@app.get("/runs/{run_id}")
def get_run(run_id: str):
    run = runs.get(run_id)
    if run:
        return run
    try:
        saved_run = load_run(run_id)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not saved_run:
        raise HTTPException(status_code=404, detail="Run not found")
    return saved_run


@app.get("/runs")
def get_runs():
    return list_runs()


@app.delete("/runs/{run_id}")
def delete_run(run_id: str):
    if run_id in runs and runs[run_id].get("status") in {"queued", "running"}:
        raise HTTPException(status_code=409, detail="An active run cannot be deleted")
    try:
        deleted = delete_saved_run(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="Saved run not found")
    return {"status": "deleted", "run_id": run_id}


@app.get("/status")
def get_status():
    """Return the latest public dashboard status without exposing agent internals."""
    if latest_run_id and latest_run_id in runs:
        return runs[latest_run_id]
    return {
        "status": "idle",
        "state": "UNDERSTAND",
        "completed_states": [],
        "message": "Navigator is ready for a task.",
        "recovery_events": [],
        "completed": False,
    }
