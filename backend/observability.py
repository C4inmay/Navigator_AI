"""Small, user-facing run metadata helpers for the Navigator dashboard.

These helpers deliberately produce only concise execution summaries.  They do
not inspect or expose browser-agent reasoning.
"""

from __future__ import annotations

import re
from typing import Any


NOT_SPECIFIED = "Not specified"


def _first_match(patterns: list[str], task: str, flags: int = re.IGNORECASE) -> str:
    for pattern in patterns:
        match = re.search(pattern, task, flags)
        if match:
            return re.sub(r"\s+", " ", match.group(1)).strip(" ,.")
    return NOT_SPECIFIED


def extract_constraints(task: str) -> list[dict[str, str]]:
    """Extract only explicit, high-confidence trip requirements from text."""
    destination = _first_match(
        [
            r"\b(?:in|to|near)\s+([A-Za-z][A-Za-z .,'-]*?)(?=\s+(?:for|with|under|below|less than|next|this|on|from|between|prefer|looking|$)|[.?!]?$)",
            r"\b(?:visit|stay at)\s+([A-Za-z][A-Za-z .,'-]*?)(?=\s+(?:for|with|under|below|next|this|on|prefer|$)|[.?!]?$)",
        ],
        task,
    )
    guests = _first_match([r"\b(\d+)\s*(?:guests?|people|persons?|adults?)\b"], task)
    if guests != NOT_SPECIFIED:
        guests = f"{guests} adult{'s' if guests != '1' else ''}"

    dates = _first_match(
        [
            r"\b(next weekend|this weekend|next week|this week)\b",
            r"\b((?:from|between)\s+[^.?!,]+?(?:\s+(?:to|and)\s+[^.?!,]+)?)\b",
            r"\b(on\s+[A-Za-z]+\s+\d{1,2}(?:st|nd|rd|th)?)\b",
        ],
        task,
    )

    budget = _first_match(
        [
            r"\b((?:under|below|less than|up to|maximum of)\s*(?:₹|Rs\.?|INR|\$|€|£)?\s*[\d,]+(?:\s*(?:per|/)\s*night)?)\b",
            r"\b((?:₹|Rs\.?|INR|\$|€|£)\s*[\d,]+\s*(?:per|/)\s*night)\b",
        ],
        task,
    )

    preference = _first_match(
        [
            r"\b(highly rated|good rating|cheap(?:est)?|budget[- ]friendly)\b",
            r"\b(prefer(?:ably)?\s+(?!(?:under|below|less than|up to)\b)[^.?!]+)",
        ],
        task,
    )

    return [
        {"label": "Destination", "value": destination},
        {"label": "Guests", "value": guests},
        {"label": "Dates", "value": dates.title() if dates != NOT_SPECIFIED else dates},
        {"label": "Budget", "value": budget},
        {"label": "Preference", "value": preference},
    ]


def build_execution_plan(task: str) -> list[dict[str, str]]:
    constraints = {item["label"]: item["value"] for item in extract_constraints(task)}
    plan = ["Understand user request"]
    if constraints["Destination"] != NOT_SPECIFIED:
        plan.append("Identify destination")
    if constraints["Dates"] != NOT_SPECIFIED:
        plan.append("Determine dates")
    if constraints["Guests"] != NOT_SPECIFIED:
        plan.append("Set guest count")
    plan.extend(
        [
            "Search Airbnb",
            "Apply user constraints",
            "Compare candidate listings",
            "Verify best candidate",
            "Stop before reservation or payment",
        ]
    )
    return [{"label": item, "state": "pending"} for item in plan]


def create_run_payload(task: str) -> dict[str, Any]:
    return {
        "task": task,
        "plan": build_execution_plan(task),
        "constraints": extract_constraints(task),
        "status": "queued",
        "state": "UNDERSTAND",
        "completed_states": [],
        "current_decision": "Preparing autonomous browser session",
        "next_action": "Open Airbnb and begin the requested search",
        "events": [],
        "recovery_events": [],
        "result": None,
        "error": None,
    }
