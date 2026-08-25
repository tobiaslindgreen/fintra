"""Plain-text formatting for Fintra data."""

from __future__ import annotations

from .models import WeekPlan


def format_week_plan_text(plan: WeekPlan | None, plan_type: str) -> str:
    """Return an unfiltered weekly plan suitable for display and AI input."""
    if plan is None:
        return ""

    sections = [f"{plan_type}: {plan.title}"]
    if plan.general:
        sections.append(f"Generelt\n{plan.general}")
    for day in plan.days:
        heading = day.day_name
        if day.date is not None:
            heading = f"{heading} {day.date.isoformat()}"
        sections.append(f"{heading}\n{day.text}" if day.text else heading)
    return "\n\n".join(sections)