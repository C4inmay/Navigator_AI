import asyncio
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from browser_agent import run_task
from history_store import delete_run as delete_saved_run
from history_store import list_runs, load_run, save_run
from observability import create_run_payload


app = FastAPI(title="Navigator AI")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class TaskRequest(BaseModel):
    task: str = Field(min_length=3, max_length=2000)


# In-memory state is intentional for this hackathon dashboard. It avoids adding
# infrastructure while letting the UI poll only user-facing execution status.
runs: dict[str, dict] = {}
latest_run_id: str | None = None


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


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


async def execute_run(run_id: str, task: str) -> None:
    run = runs[run_id]
    run["status"] = "running"
    run["started_at"] = now()
    emit(run_id, "decision", "Understanding user request", "Plan the browser workflow", "UNDERSTAND")
    try:
        result = await run_task(
            task,
            status_callback=lambda message, next_action=None, state=None, event_type="decision": emit(
                run_id, event_type, message, next_action, state
            ),
        )
        run["status"] = "completed"
        run["result"] = result
        emit(run_id, "safety", "Workflow finished with the safety guard active", "Stop before reservation or payment", "COMPLETE")
    except asyncio.CancelledError:
        run["status"] = "cancelled"
        run["error"] = "The task was cancelled before completion."
        emit(run_id, "error", "Browser task was cancelled", "Return to the dashboard and try again", "ERROR")
        raise
    except Exception as exc:
        # Keep operational details out of the dashboard and server response.
        run["status"] = "failed"
        run["error"] = "The browser session could not complete. Please try again."
        emit(run_id, "error", "Browser session could not complete", "Review the task and retry", "ERROR")
        print(f"Navigator run {run_id} failed: {type(exc).__name__}")
    finally:
        run["completed_at"] = now()
        try:
            save_run(run)
            run["saved_to_history"] = True
        except Exception as exc:
            run["saved_to_history"] = False
            print(f"Navigator run {run_id} could not be saved: {type(exc).__name__}")


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
    run = create_run_payload(task)
    run["id"] = run_id
    runs[run_id] = run
    latest_run_id = run_id
    asyncio.create_task(execute_run(run_id, task))
    return run


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
