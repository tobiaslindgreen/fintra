"""Data models for Fintra."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime


@dataclass(frozen=True, slots=True)
class Child:
    """A child available to the authenticated parent."""

    child_id: str
    slug: str
    name: str

    @property
    def key(self) -> str:
        """Return the stable child key."""
        return f"{self.child_id}:{self.slug}"


@dataclass(frozen=True, slots=True)
class PlanLink:
    """A link to a weekly plan."""

    child_id: str
    slug: str
    plan_type: str
    week: int
    year: int
    url: str


@dataclass(frozen=True, slots=True)
class Lesson:
    """A lesson listed in a daily plan."""

    start: str
    end: str
    subject: str


@dataclass(frozen=True, slots=True)
class DayPlan:
    """Plan content for one day."""

    day_name: str
    date: date | None
    text: str
    lessons: tuple[Lesson, ...] = ()


@dataclass(frozen=True, slots=True)
class WeekPlan:
    """A parsed weekly plan."""

    title: str
    general: str
    days: tuple[DayPlan, ...]


@dataclass(frozen=True, slots=True)
class Conversation:
    """Metadata for a ForældreIntra conversation."""

    thread_id: str
    latest_message_id: str
    date_label: str
    is_unread: bool

    @property
    def key(self) -> str:
        """Return a key suitable for deduplication across children."""
        return f"{self.thread_id}:{self.latest_message_id}"


@dataclass(frozen=True, slots=True)
class MessageSignal:
    """Actionable information extracted from a message."""

    message_id: str
    sent_at: datetime
    categories: tuple[str, ...]
    summary: str


@dataclass(frozen=True, slots=True)
class ChildData:
    """The normalized data exposed for one child."""

    child: Child
    class_plan: WeekPlan | None = None
    sfo_plan: WeekPlan | None = None
    message_signals: tuple[MessageSignal, ...] = ()
    updated_at: datetime | None = None
    source_urls: tuple[str, ...] = field(default_factory=tuple)
