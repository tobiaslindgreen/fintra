"""Sensor platform for Fintra."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .coordinator import FintraCoordinator
from .formatting import format_week_plan_text
from .models import ChildData, DayPlan, MessageSignal, WeekPlan


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry[FintraCoordinator],
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up two sensors for every selected child."""
    coordinator = entry.runtime_data
    entities: list[FintraSensor] = []
    for child_key in coordinator.data:
        entities.extend(
            (
                FintraSensor(coordinator, entry, child_key, "day"),
                FintraSensor(coordinator, entry, child_key, "week"),
            )
        )
    async_add_entities(entities)


class FintraSensor(CoordinatorEntity[FintraCoordinator], SensorEntity):
    """A daily or weekly Fintra sensor."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: FintraCoordinator,
        entry: ConfigEntry,
        child_key: str,
        period: str,
    ) -> None:
        """Initialize a sensor."""
        super().__init__(coordinator)
        self._entry = entry
        self._child_key = child_key
        self._period = period
        child = coordinator.data[child_key].child
        self._attr_unique_id = f"{entry.entry_id}_{child.child_id}_{period}"
        self._attr_translation_key = f"{period}_plan"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, child.key)},
            name=child.name,
            manufacturer="itslearning",
            model="ForældreIntra",
            configuration_url=f"https://{coordinator.client.host}",
        )

    @property
    def available(self) -> bool:
        """Return whether data for the child is available."""
        return super().available and self._child_key in self.coordinator.data

    @property
    def native_value(self) -> str | int:
        """Return a short recorder-friendly state."""
        data = self.coordinator.data[self._child_key]
        today = dt_util.now().date()
        if self._period == "week":
            iso_year, iso_week, _ = today.isocalendar()
            return f"{iso_year}-W{iso_week:02d}"
        return len(_daily_items(data, today))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return bounded, structured plan data."""
        data = self.coordinator.data[self._child_key]
        today = dt_util.now().date()
        if self._period == "week":
            return _week_attributes(data)
        return _day_attributes(data, today)


def _day_attributes(data: ChildData, today: date) -> dict[str, Any]:
    dates = (today, today + timedelta(days=1))
    return {
        "barn": data.child.name,
        "fra_dato": dates[0].isoformat(),
        "til_dato": dates[1].isoformat(),
        "dage": [_combined_day(data, day) for day in dates],
        "vigtigt": [_signal_dict(signal) for signal in data.message_signals],
        "kilder": list(data.source_urls),
    }


def _week_attributes(data: ChildData) -> dict[str, Any]:
    all_dates = sorted(
        {
            day.date
            for plan in (data.class_plan, data.sfo_plan)
            if plan is not None
            for day in plan.days
            if day.date is not None
        }
    )
    class_text = format_week_plan_text(data.class_plan, "Klasse")
    sfo_text = format_week_plan_text(data.sfo_plan, "SFO")
    return {
        "barn": data.child.name,
        "fra_dato": all_dates[0].isoformat() if all_dates else None,
        "til_dato": all_dates[-1].isoformat() if all_dates else None,
        "ugeplan_tekst": "\n\n".join(
            text for text in (class_text, sfo_text) if text
        ),
        "klasse_ugeplan_tekst": class_text,
        "sfo_ugeplan_tekst": sfo_text,
        "generelt": {
            "klasse": _bounded(data.class_plan.general) if data.class_plan else "",
            "sfo": _bounded(data.sfo_plan.general) if data.sfo_plan else "",
        },
        "dage": [_combined_day(data, day) for day in all_dates],
        "vigtigt": [_signal_dict(signal) for signal in data.message_signals],
        "kilder": list(data.source_urls),
    }


def _daily_items(data: ChildData, day: date) -> list[object]:
    items: list[object] = []
    for plan in (data.class_plan, data.sfo_plan):
        if plan is not None:
            items.extend(item for item in plan.days if item.date == day)
    items.extend(data.message_signals)
    return items


def _combined_day(data: ChildData, day: date) -> dict[str, Any]:
    return {
        "dato": day.isoformat(),
        "klasse": _find_day(data.class_plan, day),
        "sfo": _find_day(data.sfo_plan, day),
    }


def _find_day(plan: WeekPlan | None, day: date) -> dict[str, Any] | None:
    if plan is None:
        return None
    match = next((item for item in plan.days if item.date == day), None)
    return _day_dict(match) if match is not None else None


def _day_dict(day: DayPlan) -> dict[str, Any]:
    return {
        "dag": day.day_name,
        "tekst": _bounded(day.text),
        "lektioner": [
            {"fra": lesson.start, "til": lesson.end, "fag": lesson.subject}
            for lesson in day.lessons
        ],
    }


def _signal_dict(signal: MessageSignal) -> dict[str, Any]:
    return {
        "dato": signal.sent_at.isoformat(),
        "kategorier": list(signal.categories),
        "resume": signal.summary,
    }


def _bounded(value: str, limit: int = 4000) -> str:
    return value if len(value) <= limit else value[: limit - 3].rstrip() + "..."
