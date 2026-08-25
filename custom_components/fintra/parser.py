"""Parsers for ForældreIntra pages and message payloads."""

from __future__ import annotations

from datetime import date, datetime
import json
import re
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from .models import (
    Child,
    Conversation,
    DayPlan,
    Lesson,
    MessageSignal,
    PlanLink,
    WeekPlan,
)

_CHILD_URL = re.compile(r"^/parent/(?P<id>\d+)/(?P<slug>[^/]+)/Index$")
_PLAN_URL = re.compile(
    r"^/parent/(?P<id>\d+)/(?P<slug>[^/]+)item/weeklyplansandhomework/"
    r"item/(?P<type>class|sfo)/(?P<week>\d+)-(?P<year>\d{4})(?:/v\d+)?$"
)
_TIME_RANGE = re.compile(
    r"(?P<start>[0-2]?\d[:.]\d{2})\s*-\s*(?P<end>[0-2]?\d[:.]\d{2})"
)
_DANISH_MONTHS = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "maj": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "okt": 10,
    "nov": 11,
    "dec": 12,
}
_MESSAGE_ATTRIBUTE = re.compile(r"messageconversations", re.IGNORECASE)
_ACTION_PATTERNS = {
    "remember": re.compile(r"\b(husk|huskes|mind(?:e|er)|glem ikke)\b", re.I),
    "bring": re.compile(
        r"\b(medbring(?:e|er|es)?|tage med|have med|i tasken|pakket ind)\b", re.I
    ),
    "signup_deadline": re.compile(
        r"\b(tilmeld|tilmelding|svarfrist|frist|senest|krydse af)\b", re.I
    ),
    "meeting": re.compile(r"\b(forældremøde|møde|samtale)\b", re.I),
    "trip": re.compile(r"\b(tur|udflugt|bus|afgang|hjemme ca)\b", re.I),
    "schedule_change": re.compile(
        r"\b(ændret|aflyst|flyttet|vikar|fri|lukket|mødetid|skoledag)\b", re.I
    ),
}


def parse_children(html: str) -> tuple[Child, ...]:
    """Discover children from a parent front page."""
    soup = BeautifulSoup(html, "html.parser")
    children: dict[str, Child] = {}
    personal_name = _clean_text(
        soup.select_one("#sk-personal-menu-button"), fallback=""
    )

    for anchor in soup.find_all("a", href=True):
        match = _CHILD_URL.match(str(anchor["href"]))
        if match is None:
            continue
        name = anchor.get_text(" ", strip=True) or personal_name or match["slug"]
        child = Child(match["id"], match["slug"], name)
        children.setdefault(child.key, child)

    return tuple(sorted(children.values(), key=lambda child: child.name.casefold()))


def parse_plan_links(
    html: str, base_url: str, *, week: int, year: int
) -> tuple[PlanLink, ...]:
    """Return class and SFO plan links for an ISO week."""
    soup = BeautifulSoup(html, "html.parser")
    plans: list[PlanLink] = []
    for anchor in soup.find_all("a", href=True):
        href = str(anchor["href"])
        match = _PLAN_URL.match(href)
        if match is None:
            continue
        plan_week = int(match["week"])
        plan_year = int(match["year"])
        if (plan_week, plan_year) != (week, year):
            continue
        plans.append(
            PlanLink(
                child_id=match["id"],
                slug=match["slug"],
                plan_type=match["type"],
                week=plan_week,
                year=plan_year,
                url=urljoin(base_url, href),
            )
        )
    return tuple(plans)


def parse_week_plan(html: str, *, year: int) -> WeekPlan | None:
    """Parse a weekly plan using the current 2026 page structure."""
    soup = BeautifulSoup(html, "html.parser")
    embedded_plan = _parse_embedded_week_plan(soup)
    if embedded_plan is not None:
        return embedded_plan

    container = soup.select_one(".sk-weekly-plan-container")
    if container is None:
        return None

    title = _clean_text(container.find("h3"), fallback="Ugeplan")
    general = ""
    days: list[DayPlan] = []

    for marker in container.select(".sk-weekly-plan-day"):
        day_name = marker.get_text(" ", strip=True)
        header = marker.find_parent(class_="sk-weekly-plan-header-cell")
        section = header.parent if header is not None and header.parent else marker.parent
        if not isinstance(section, Tag):
            continue

        section_copy = BeautifulSoup(str(section), "html.parser")
        for removable in section_copy.select(
            ".sk-weekly-plan-header-cell, script, style"
        ):
            removable.decompose()
        text = _normalize_text(section_copy.get_text("\n", strip=True))

        if day_name.casefold() == "generelt":
            general = text
            continue

        date_marker = header.select_one(".sk-weekly-plan-date") if header else None
        parsed_date = _parse_short_danish_date(
            date_marker.get_text(" ", strip=True) if date_marker else "", year
        )
        lessons = _parse_lessons(section)
        days.append(DayPlan(day_name, parsed_date, text, lessons))

    return WeekPlan(title=title, general=general, days=tuple(days))


def _parse_embedded_week_plan(soup: BeautifulSoup) -> WeekPlan | None:
    settings_element = soup.find(
        attrs={"data-clientlogic-settings-weeklyplansapp": True}
    )
    if not isinstance(settings_element, Tag):
        return None
    raw_settings = settings_element.get(
        "data-clientlogic-settings-weeklyplansapp"
    )
    if not isinstance(raw_settings, str):
        return None
    try:
        settings = json.loads(raw_settings)
    except json.JSONDecodeError:
        return None
    if not isinstance(settings, dict):
        return None

    selected = settings.get("SelectedPlan")
    if not isinstance(selected, dict):
        return None
    class_or_group = str(selected.get("ClassOrGroup") or "").strip()
    formatted_week = str(selected.get("FormattedWeek") or "").strip()
    title = "Ugeplan"
    if class_or_group and formatted_week:
        title = f"Ugeplan for {class_or_group} - uge {formatted_week}"

    general_plan = selected.get("GeneralPlan")
    general = _embedded_lesson_plan_text(general_plan)
    days: list[DayPlan] = []
    daily_plans = selected.get("DailyPlans")
    if isinstance(daily_plans, list):
        for daily_plan in daily_plans:
            if not isinstance(daily_plan, dict):
                continue
            date_value = str(daily_plan.get("Date") or "")
            try:
                parsed_date = date.fromisoformat(date_value)
            except ValueError:
                parsed_date = None
            lessons = _embedded_schedule(daily_plan.get("Schedule"))
            plan_text = _embedded_lesson_plan_text(daily_plan)
            schedule_text = "\n".join(
                f"{lesson.start} - {lesson.end}\n{lesson.subject}".rstrip()
                for lesson in lessons
            )
            text = _normalize_text(f"{plan_text}\n{schedule_text}")
            days.append(
                DayPlan(
                    day_name=str(daily_plan.get("Day") or "Dag"),
                    date=parsed_date,
                    text=text,
                    lessons=lessons,
                )
            )

    if not general and not days:
        return None
    return WeekPlan(title=title, general=general, days=tuple(days))


def _embedded_lesson_plan_text(plan: object) -> str:
    if not isinstance(plan, dict):
        return ""
    lesson_plans = plan.get("LessonPlans")
    if not isinstance(lesson_plans, list):
        return ""

    blocks: list[str] = []
    for lesson_plan in lesson_plans:
        if not isinstance(lesson_plan, dict):
            continue
        subject = lesson_plan.get("Subject")
        subject_title = (
            str(subject.get("Title") or "").strip()
            if isinstance(subject, dict)
            else ""
        )
        if subject_title.casefold() == "uden angivelse af fag":
            subject_title = ""
        content = _html_to_multiline_text(str(lesson_plan.get("Content") or ""))
        block = _normalize_text(f"{subject_title}\n{content}")
        if block:
            blocks.append(block)
    return "\n\n".join(blocks)


def _embedded_schedule(value: object) -> tuple[Lesson, ...]:
    if not isinstance(value, list):
        return ()
    lessons: list[Lesson] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        match = _TIME_RANGE.search(str(item.get("TimeString") or ""))
        if match is None:
            continue
        lessons.append(
            Lesson(
                start=match["start"].replace(".", ":"),
                end=match["end"].replace(".", ":"),
                subject=str(item.get("Title") or "").strip(),
            )
        )
    return tuple(lessons)


def parse_conversations(html: str) -> tuple[Conversation, ...]:
    """Parse conversation metadata embedded as JSON in the inbox page."""
    soup = BeautifulSoup(html, "html.parser")
    for element in soup.find_all(True):
        for name, value in element.attrs.items():
            if not _MESSAGE_ATTRIBUTE.search(name) or not isinstance(value, str):
                continue
            try:
                payload = json.loads(value)
            except json.JSONDecodeError:
                continue
            conversations = payload.get("Conversations")
            if not isinstance(conversations, list):
                continue
            return tuple(
                Conversation(
                    thread_id=str(item.get("ThreadId") or ""),
                    latest_message_id=str(item.get("LatestMessageId") or ""),
                    date_label=str(item.get("Date") or ""),
                    is_unread=bool(item.get("IsUnread")),
                )
                for item in conversations
                if item.get("LatestMessageId")
            )
    return ()


def parse_message(payload: dict[str, Any]) -> MessageSignal | None:
    """Extract bounded, actionable information from a message payload."""
    sent_at = _parse_message_datetime(str(payload.get("SentReceivedDateText") or ""))
    if sent_at is None:
        return None

    subject = _html_to_text(str(payload.get("Subject") or ""))
    body = _html_to_text(str(payload.get("BaseText") or ""))
    text = _normalize_text(f"{subject}\n{body}")
    categories = tuple(
        name for name, pattern in _ACTION_PATTERNS.items() if pattern.search(text)
    )
    if not categories:
        return None

    summary = subject or body
    if len(summary) > 240:
        summary = summary[:237].rstrip() + "..."
    return MessageSignal(
        message_id=str(payload.get("Id") or ""),
        sent_at=sent_at,
        categories=categories,
        summary=summary,
    )


def _parse_lessons(section: Tag) -> tuple[Lesson, ...]:
    lessons: list[Lesson] = []
    for element in section.find_all(string=_TIME_RANGE):
        match = _TIME_RANGE.search(str(element))
        if match is None:
            continue
        parent = element.parent
        subject = ""
        if parent is not None:
            sibling = parent.find_next_sibling()
            if sibling is not None:
                subject = sibling.get_text(" ", strip=True)
            elif parent.parent is not None:
                texts = list(parent.parent.stripped_strings)
                subject = texts[-1] if len(texts) > 1 else ""
        lesson = Lesson(
            start=match["start"].replace(".", ":"),
            end=match["end"].replace(".", ":"),
            subject=subject,
        )
        if lesson not in lessons:
            lessons.append(lesson)
    return tuple(lessons)


def _parse_short_danish_date(value: str, year: int) -> date | None:
    match = re.search(r"(?P<day>\d{1,2})\.\s*(?P<month>[a-zæøå]{3})\.?", value, re.I)
    if match is None:
        return None
    month = _DANISH_MONTHS.get(match["month"].casefold())
    if month is None:
        return None
    return date(year, month, int(match["day"]))


def _parse_message_datetime(value: str) -> datetime | None:
    match = re.search(
        r"(?P<day>\d{1,2})\.\s*(?P<month>[a-zæøå]{3})\.\s*"
        r"(?P<year>\d{4})\s+(?P<hour>\d{1,2}):(?P<minute>\d{2})",
        value,
        re.I,
    )
    if match is None:
        return None
    month = _DANISH_MONTHS.get(match["month"].casefold())
    if month is None:
        return None
    return datetime(
        int(match["year"]),
        month,
        int(match["day"]),
        int(match["hour"]),
        int(match["minute"]),
    )


def _html_to_text(value: str) -> str:
    return BeautifulSoup(value, "html.parser").get_text(" ", strip=True)


def _html_to_multiline_text(value: str) -> str:
    return _normalize_text(
        BeautifulSoup(value, "html.parser").get_text("\n", strip=True)
    )


def _normalize_text(value: str) -> str:
    return "\n".join(line.strip() for line in value.splitlines() if line.strip())


def _clean_text(element: Tag | None, *, fallback: str) -> str:
    return element.get_text(" ", strip=True) if element is not None else fallback
