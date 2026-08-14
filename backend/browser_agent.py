import asyncio
import base64
import inspect
import logging
import os
from collections.abc import Callable
from contextlib import suppress
from typing import Any

from dotenv import load_dotenv
from browser_use import Agent, Browser, ChatGoogle

load_dotenv()
logger = logging.getLogger("uvicorn.error")

TASK = """
You are Navigator AI, an autonomous browser-use agent.

USER REQUEST:
Find a suitable Airbnb in Goa for 2 guests for next weekend.
Prefer the cheapest suitable option with a good rating.

OBJECTIVE:
1. Open Airbnb.
2. Search for Goa.
3. Select appropriate dates for next weekend.
4. Set guests to 2.
5. Search available stays.
6. Inspect the visible results.
7. Compare prices and ratings.
8. Identify a good low-price option.
9. Open the most suitable listing.
10. Inspect its details.

AUTONOMOUS BEHAVIOR:
- Observe the current page before every action.
- Decide the next action based on what is actually visible.
- If an element is missing, look for an alternative.
- If a popup appears, handle it appropriately.
- Verify that important actions succeeded before continuing.

SAFETY:
- NEVER make a reservation.
- NEVER enter payment information.
- NEVER click a final reservation/payment/confirmation button.
- STOP after opening and inspecting the best suitable listing.

At the end, clearly report the selected listing and why it was selected.
"""


def build_safe_task(task: str) -> str:
    """Keep user requests generic while enforcing the existing safety boundary."""
    return f"""You are Navigator AI, an autonomous browser-use agent.

USER REQUEST:
{task}

SAFETY BOUNDARY:
- Never make a reservation, payment, or final booking confirmation.
- Never enter payment information or click irreversible booking controls.
- Stop after opening and inspecting the strongest suitable listing.

WORKING STYLE:
- Observe the current page before every action.
- Handle unexpected popups when they actually appear.
- Verify important actions and summarize the selected listing for the user.
"""


async def run_task(
    task: str,
    status_callback: Callable[[str, str | None, str | None, str], None] | None = None,
    preview_callback: Callable[[dict], Any] | None = None,
):
    print("=" * 60)
    print("NAVIGATOR AI - AUTONOMOUS AIRBNB AGENT")
    print("=" * 60)
    logger.info("[Navigator] Initializing browser agent")

    if status_callback:
        status_callback("Planning browser workflow", "Launch Airbnb and prepare the search", "PLAN", "decision")

    llm = ChatGoogle(model="gemini-3.5-flash")

    browser = Browser(
        headless=os.getenv("BROWSER_USE_HEADLESS", "false").strip().lower() in {"1", "true", "yes", "on"},
        window_size={
            "width": 1400,
            "height": 900,
        },
    )

    seen_popup_messages: set[str] = set()

    def report_browser_step(browser_state: Any, _agent_output: Any, _step: int) -> None:
        """Map public Browser Use events to concise dashboard status only."""
        if not status_callback:
            return
        popup_messages = getattr(browser_state, "closed_popup_messages", []) or []
        new_popups = [message for message in popup_messages if message not in seen_popup_messages]
        if new_popups:
            seen_popup_messages.update(new_popups)
            status_callback("Unexpected browser dialog detected", "Find a safe dismiss action", "RECOVER", "recovery")
            status_callback("Browser dialog closed; workflow resumed", "Re-observe the current page", "OBSERVE", "recovery")
            return
        status_callback("Interacting with the current page", "Verify the page response", "ACT", "decision")

    agent = Agent(
        task=build_safe_task(task),
        llm=llm,
        browser=browser,
        register_new_step_callback=report_browser_step,
    )
    logger.info("[Navigator] Browser agent initialized")

    async def capture_browser_previews() -> None:
        """Capture the existing Browser Use Chromium session at a modest rate."""
        preview_error_reported = False
        while True:
            try:
                screenshot = await browser.take_screenshot(format="jpeg", quality=65)
                if preview_callback:
                    callback_result = preview_callback(
                        {
                            "type": "browser_screenshot",
                            "image": "data:image/jpeg;base64," + base64.b64encode(screenshot).decode("ascii"),
                        }
                    )
                    if inspect.isawaitable(callback_result):
                        await callback_result
                preview_error_reported = False
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("[Navigator] Browser screenshot capture failed: %s", type(exc).__name__)
                if preview_callback and not preview_error_reported:
                    callback_result = preview_callback({"type": "browser_preview_unavailable"})
                    if inspect.isawaitable(callback_result):
                        await callback_result
                preview_error_reported = True
            await asyncio.sleep(1.5)

    if status_callback:
        status_callback("Observing Airbnb", "Inspect the current page before interacting", "OBSERVE", "decision")

    logger.info("[Navigator] Agent execution started")
    preview_task = asyncio.create_task(capture_browser_previews()) if preview_callback else None
    try:
        history = await agent.run(max_steps=30)
    finally:
        if preview_task:
            preview_task.cancel()
            with suppress(asyncio.CancelledError):
                await preview_task

    print("\n" + "=" * 60)
    print("NAVIGATOR AI - FINAL RESULT")
    print("=" * 60)

    result = history.final_result()

    print(result)
    if result is None or not str(result).strip():
        logger.warning("[Navigator] Agent execution ended without a final result")
    if status_callback:
        status_callback("Verifying the selected listing", "Stop before reservation or payment", "VERIFY", "decision")
    return result


async def main():
    await run_task(TASK)


if __name__ == "__main__":
    asyncio.run(main())
