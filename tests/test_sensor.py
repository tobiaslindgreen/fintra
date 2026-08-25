"""Tests for Fintra sensor attributes."""

from datetime import date

from custom_components.fintra.formatting import format_week_plan_text
from custom_components.fintra.models import DayPlan, WeekPlan


def test_week_text_includes_complete_context() -> None:
    """Test general text, homework, past days, and trips remain in plain text."""
    class_plan = WeekPlan(
        title="Ugeplan for 2.KL. - uge 35-2026",
        general=(
            "Husk læsebogen gerne skal være pakket ind til på mandag.\n"
            "Eleverne får frilæsningsbøger med."
        ),
        days=(
            DayPlan(
                day_name="Mandag",
                date=date(2026, 8, 24),
                text="Dansk\nHusk at læsebogen skal være pakket ind og lægges i tasken.",
            ),
            DayPlan(
                day_name="Torsdag",
                date=date(2026, 8, 27),
                text=(
                    "Vi tager på tur til Verdenskortet i Klejtrup.\n"
                    "Vi er hjemme ca. 14.45/15.00."
                ),
            ),
        ),
    )
    text = format_week_plan_text(class_plan, "Klasse")

    assert "Generelt\nHusk læsebogen" in text
    assert "Eleverne får frilæsningsbøger med." in text
    assert "Mandag 2026-08-24" in text
    assert "lægges i tasken" in text
    assert "Torsdag 2026-08-27" in text
    assert "Verdenskortet i Klejtrup" in text


def test_week_text_handles_sfo_and_missing_plans() -> None:
    """Test plan labels are explicit and missing plans produce no text."""
    sfo_plan = WeekPlan("SFO uge 35", "SFO-info", ())

    assert format_week_plan_text(sfo_plan, "SFO") == (
        "SFO: SFO uge 35\n\nGenerelt\nSFO-info"
    )
    assert format_week_plan_text(None, "Klasse") == ""