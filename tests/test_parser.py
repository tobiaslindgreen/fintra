"""Tests for the ForældreIntra parsers."""

from datetime import date
import html
import json

from custom_components.fintra.parser import (
    parse_children,
    parse_conversations,
    parse_message,
    parse_plan_links,
    parse_week_plan,
)


def test_parse_children_deduplicates_menu_links() -> None:
    page = """
    <button id="sk-personal-menu-button">Vester 0.KL.</button>
    <a href="/parent/712/Vester/Index"></a>
    <a href="/parent/712/Vester/Index">Vester 0.KL.</a>
    <a href="/parent/641/Ellie/Index">Ellie 2.KL.</a>
    """

    children = parse_children(page)

    assert [(child.child_id, child.slug, child.name) for child in children] == [
        ("641", "Ellie", "Ellie 2.KL."),
        ("712", "Vester", "Vester 0.KL."),
    ]


def test_parse_current_class_and_sfo_plan_links() -> None:
    page = """
    <a href="/parent/641/Ellieitem/weeklyplansandhomework/item/class/35-2026">Klasse</a>
    <a href="/parent/641/Ellieitem/weeklyplansandhomework/item/sfo/35-2026/v1">SFO</a>
    <a href="/parent/641/Ellieitem/weeklyplansandhomework/item/class/34-2026">Gammel</a>
    """

    plans = parse_plan_links(page, "https://school.example", week=35, year=2026)

    assert [plan.plan_type for plan in plans] == ["class", "sfo"]
    assert plans[1].url == (
        "https://school.example/parent/641/Ellieitem/weeklyplansandhomework/"
        "item/sfo/35-2026/v1"
    )


def test_parse_week_plan_days_general_and_lessons() -> None:
    page = """
    <div class="sk-weekly-plan-container">
      <h3>Ugeplan for 2.KL. - uge 35-2026</h3>
      <div class="section">
        <div class="sk-weekly-plan-header-cell"><div><span class="sk-weekly-plan-day">Generelt</span></div></div>
                <div>
                    <p>Husk læsebogen gerne skal være pakket ind til på mandag.</p>
                    <p>Eleverne får frilæsningsbøger med.</p>
                </div>
            </div>
            <div class="section">
                <div class="sk-weekly-plan-header-cell"><div><span class="sk-weekly-plan-day">Mandag</span><span class="sk-weekly-plan-date">24. aug.</span></div></div>
                <div><p>Dansk</p><p>Husk at læsebogen skal være pakket ind og lægges i tasken.</p></div>
      </div>
      <div class="section">
        <div class="sk-weekly-plan-header-cell"><div><span class="sk-weekly-plan-day">Tirsdag</span><span class="sk-weekly-plan-date">25. aug.</span></div></div>
        <div><p>Emnedag starter.</p></div>
        <div><div><span>08:20 - 09:05</span><span>2.KL. DAN</span></div></div>
      </div>
            <div class="section">
                <div class="sk-weekly-plan-header-cell"><div><span class="sk-weekly-plan-day">Torsdag</span><span class="sk-weekly-plan-date">27. aug.</span></div></div>
                <div>
                    <p>Vi tager på tur til Verdenskortet i Klejtrup.</p>
                    <p>Vi er hjemme ca. 14.45/15.00.</p>
                </div>
            </div>
    </div>
    """

    plan = parse_week_plan(page, year=2026)

    assert plan is not None
    assert plan.general == (
        "Husk læsebogen gerne skal være pakket ind til på mandag.\n"
        "Eleverne får frilæsningsbøger med."
    )
    assert plan.days[0].date == date(2026, 8, 24)
    assert "lægges i tasken" in plan.days[0].text
    assert plan.days[1].date == date(2026, 8, 25)
    assert plan.days[1].text == "Emnedag starter.\n08:20 - 09:05\n2.KL. DAN"
    assert plan.days[1].lessons[0].subject == "2.KL. DAN"
    assert plan.days[2].date == date(2026, 8, 27)
    assert "Verdenskortet i Klejtrup" in plan.days[2].text
    assert "14.45/15.00" in plan.days[2].text


def test_parse_week_plan_from_embedded_vue_settings() -> None:
    settings = {
        "SelectedPlan": {
            "ClassOrGroup": "2.KL.",
            "FormattedWeek": "35-2026",
            "GeneralPlan": {
                "LessonPlans": [
                    {
                        "Subject": {"Title": "Uden angivelse af fag"},
                        "Content": (
                            "<p>Husk læsebogen gerne skal være pakket ind.</p>"
                            "<p>Eleverne får frilæsningsbøger med.</p>"
                        ),
                    }
                ]
            },
            "DailyPlans": [
                {
                    "Date": "2026-08-24",
                    "Day": "Mandag",
                    "LessonPlans": [
                        {
                            "Subject": {"Title": "Dansk"},
                            "Content": (
                                "<p>Husk at læsebogen skal være pakket ind "
                                "og lægges i tasken.</p>"
                            ),
                        }
                    ],
                    "Schedule": [
                        {"TimeString": "12:30 - 13:15", "Title": "2.KL. DAN"}
                    ],
                },
                {
                    "Date": "2026-08-27",
                    "Day": "Torsdag",
                    "LessonPlans": [
                        {
                            "Subject": {"Title": "Uden angivelse af fag"},
                            "Content": (
                                "<p>Vi tager på tur til Verdenskortet i Klejtrup.</p>"
                                "<p>Vi er hjemme ca. 14.45/15.00.</p>"
                            ),
                        }
                    ],
                    "Schedule": [],
                },
            ],
        }
    }
    page = (
        '<div data-clientlogic-settings-weeklyplansapp="'
        + html.escape(json.dumps(settings), quote=True)
        + '"></div><script id="sk-weekly-plan-template"></script>'
    )

    plan = parse_week_plan(page, year=2026)

    assert plan is not None
    assert plan.title == "Ugeplan for 2.KL. - uge 35-2026"
    assert "Husk læsebogen gerne" in plan.general
    assert "frilæsningsbøger" in plan.general
    assert plan.days[0].date == date(2026, 8, 24)
    assert "Dansk\nHusk at læsebogen" in plan.days[0].text
    assert "12:30 - 13:15\n2.KL. DAN" in plan.days[0].text
    assert plan.days[0].lessons[0].subject == "2.KL. DAN"
    assert "Verdenskortet i Klejtrup" in plan.days[1].text


def test_parse_conversations_and_actionable_message() -> None:
    settings = {
        "Conversations": [
            {
                "ThreadId": "thread-1",
                "LatestMessageId": 42,
                "Date": "25. aug.",
                "IsUnread": True,
            }
        ]
    }
    page = (
        '<div data-clientlogic-settings-messageconversationswitharchivefunctionality="'
        + html.escape(json.dumps(settings), quote=True)
        + '"></div>'
    )

    conversations = parse_conversations(page)
    signal = parse_message(
        {
            "Id": 42,
            "Subject": "Tur torsdag",
            "BaseText": "<p>Husk at medbringe madpakke kl. 08:15.</p>",
            "SentReceivedDateText": "Tirsdag, 25. aug. 2026 09:27",
        }
    )

    assert conversations[0].key == "thread-1:42"
    assert conversations[0].is_unread is True
    assert signal is not None
    assert signal.categories == ("remember", "bring", "trip")
    assert signal.summary == "Tur torsdag"


def test_parse_message_ignores_non_actionable_content() -> None:
    signal = parse_message(
        {
            "Id": 43,
            "Subject": "Orientering",
            "BaseText": "Tak for en god uge.",
            "SentReceivedDateText": "Mandag, 24. aug. 2026 09:33",
        }
    )

    assert signal is None