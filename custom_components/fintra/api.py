"""Asynchronous client for ForældreIntra."""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any
from urllib.parse import quote, urljoin, urlparse

from aiohttp import ClientError, ClientResponse, ClientSession
from bs4 import BeautifulSoup

from .const import PLAN_TYPE_CLASS, PLAN_TYPE_SFO
from .models import Child, ChildData, MessageSignal, WeekPlan
from .parser import (
    parse_children,
    parse_conversations,
    parse_message,
    parse_plan_links,
    parse_week_plan,
)

_SCHOOL_NAME = re.compile(r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$", re.IGNORECASE)
_SAML_CONSUMER_PATH = "/sso/assertionconsumerservice"


class FintraError(Exception):
    """Base exception for Fintra."""


class FintraAuthError(FintraError):
    """Raised when ForældreIntra rejects the credentials."""


class FintraConnectionError(FintraError):
    """Raised when ForældreIntra cannot be reached."""


def normalize_host(value: str) -> str:
    """Normalize a school name or hostname supplied by the user."""
    candidate = value.strip().rstrip("/")
    if not candidate:
        raise ValueError("Host is empty")
    if "." not in candidate and "://" not in candidate:
        if not _SCHOOL_NAME.fullmatch(candidate):
            raise ValueError("School name is invalid")
        return f"{candidate.lower()}.m.skoleintra.dk"
    if "://" not in candidate:
        candidate = f"https://{candidate}"
    parsed = urlparse(candidate)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("Host must be a valid HTTPS address")
    return parsed.hostname.lower()


class FintraClient:
    """Fetch and normalize data from one ForældreIntra account."""

    def __init__(
        self,
        session: ClientSession,
        host: str,
        username: str,
        password: str,
    ) -> None:
        """Initialize the client."""
        self._session = session
        self.host = normalize_host(host)
        self.username = username
        self._password = password
        self._base_url = f"https://{self.host}"
        self._logged_in = False

    async def async_login(self) -> tuple[Child, ...]:
        """Log in and return children available to the account."""
        self._logged_in = False
        try:
            for attempt in range(2):
                response = await self._session.get(self._base_url, allow_redirects=True)
                html = await self._read_response(response)
                for _ in range(6):
                    # A retained identity-provider session can return a SAML form
                    # immediately, without ever displaying the credential form.
                    next_response, next_html = await self._async_submit_saml_form(
                        response, html
                    )
                    if next_response is not response:
                        response, html = next_response, next_html
                        continue
                    if self._is_contact_confirmation(response):
                        response, html = await self._async_confirm_contacts(
                            response, html
                        )
                        continue
                    if self._find_login_form(html) is not None:
                        response, html = await self._async_submit_login_form(
                            response, html
                        )
                        continue
                    # Authenticated landing URLs vary (Index, /parent/, child
                    # selection). Validate the school origin and actual child
                    # links rather than requiring one exact final URL.
                    if (
                        urlparse(str(response.url)).netloc
                        == urlparse(self._base_url).netloc
                    ):
                        children = parse_children(html)
                        if children:
                            self._logged_in = True
                            return children
                    break
                if attempt == 0:
                    # The integration owns a separate CookieJar per account.
                    # Retry an unknown/looping session once, never rejected
                    # credentials or contact confirmation failures.
                    self._session.cookie_jar.clear()
        except ClientError as err:
            raise FintraConnectionError("ForældreIntra kunne ikke kontaktes") from err
        raise FintraConnectionError(
            "Loginformularen eller en gyldig forældreside blev ikke fundet, "
            "heller ikke med en ny session "
            f"(formularer: {len(BeautifulSoup(html, 'html.parser').find_all('form'))})"
        )

    @staticmethod
    def _find_login_form(html: str) -> Any:
        """Find credentials by form controls, independently of URL or quoting."""
        return next(
            (
                candidate
                for candidate in BeautifulSoup(html, "html.parser").find_all("form")
                if candidate.find(attrs={"name": "UserName"})
                and candidate.find(attrs={"name": "Password"})
            ),
            None,
        )

    async def _async_submit_login_form(
        self, response: ClientResponse, html: str
    ) -> tuple[ClientResponse, str]:
        """Submit credentials when the existing session needs a fresh login."""
        form = self._find_login_form(html)
        if form is None:
            raise FintraConnectionError("Loginformularen blev ikke fundet")
        fields = {
            str(field["name"]): str(field.get("value", ""))
            for field in form.find_all("input", attrs={"name": True})
        }
        fields["UserName"] = self.username
        fields["Password"] = self._password
        action = urljoin(str(response.url), str(form.get("action") or response.url))
        response = await self._session.post(action, data=fields, allow_redirects=True)
        html = await self._read_response(response)
        if self._is_login_response(response, html):
            raise FintraAuthError("Brugernavn eller adgangskode blev afvist")
        return response, html

    @staticmethod
    def _is_contact_confirmation(response: ClientResponse) -> bool:
        """Recognize the contact gate, including an optional trailing slash."""
        return (
            urlparse(str(response.url))
            .path.rstrip("/")
            .lower()
            .endswith("/confirmcontacts")
        )

    async def _async_confirm_contacts(
        self, response: ClientResponse, html: str
    ) -> tuple[ClientResponse, str]:
        """Confirm existing contact values using the school's own HTML form."""
        if self._is_contact_confirmation(response):
            page_url = str(response.url)
            if urlparse(page_url).netloc != urlparse(self._base_url).netloc:
                raise FintraConnectionError(
                    "Kontaktbekræftelsen havde en ukendt adresse"
                )
            soup = BeautifulSoup(html, "html.parser")
            candidates = []
            for form in soup.find_all("form"):
                action = urljoin(page_url, str(form.get("action") or page_url))
                if (
                    urlparse(action).scheme != "https"
                    or urlparse(action).netloc != urlparse(self._base_url).netloc
                    or str(form.get("method", "get")).lower() != "post"
                ):
                    continue
                submit = None
                for button in form.find_all(["button", "input"]):
                    kind = str(
                        button.get(
                            "type", "submit" if button.name == "button" else "text"
                        )
                    ).lower()
                    if kind != "submit" or button.has_attr("disabled"):
                        continue
                    label = button.get_text(" ", strip=True) or str(
                        button.get("value", "")
                    )
                    if re.search(
                        r"\b(bekræft|confirm|godkend|fortsæt|continue|gem|save|ok)\b",
                        label,
                        re.IGNORECASE,
                    ):
                        submit = button
                        break
                if submit is not None:
                    candidates.append((form, action, submit))
            if len(candidates) != 1:
                raise FintraConnectionError(
                    "Kontaktbekræftelsens formular kunne ikke genkendes; "
                    "bekræft kontaktoplysningerne manuelt i ForældreIntra"
                )
            form, action, submit = candidates[0]
            fields: list[tuple[str, str]] = []
            for field in form.find_all(
                ["input", "select", "textarea"], attrs={"name": True}
            ):
                if field.has_attr("disabled") or field.find_parent(
                    "fieldset", disabled=True
                ):
                    continue
                name = str(field["name"])
                kind = str(field.get("type", "text")).lower()
                if field.name == "input":
                    if kind in {"submit", "button", "reset", "image", "file"}:
                        continue
                    if kind in {"checkbox", "radio"} and not field.has_attr("checked"):
                        continue
                    fields.append(
                        (
                            name,
                            str(
                                field.get(
                                    "value",
                                    "on" if kind in {"checkbox", "radio"} else "",
                                )
                            ),
                        )
                    )
                elif field.name == "textarea":
                    fields.append((name, field.get_text()))
                else:
                    options = [
                        option
                        for option in field.find_all("option")
                        if not option.has_attr("disabled")
                        and not option.find_parent("optgroup", disabled=True)
                    ]
                    selected = [
                        option for option in options if option.has_attr("selected")
                    ]
                    if not selected and not field.has_attr("multiple"):
                        selected = options[:1]
                    for option in selected:
                        fields.append(
                            (name, str(option.get("value", option.get_text())))
                        )
            if submit.get("name"):
                fields.append((str(submit["name"]), str(submit.get("value", ""))))
            # Respect a button-specific endpoint; never send personal data elsewhere.
            action = urljoin(page_url, str(submit.get("formaction") or action))
            if (
                urlparse(action).scheme != "https"
                or urlparse(action).netloc != urlparse(self._base_url).netloc
                or str(submit.get("formmethod", "post")).lower() != "post"
            ):
                raise FintraConnectionError(
                    "Kontaktbekræftelsen havde en ukendt adresse"
                )
            response = await self._session.post(
                action, data=fields, allow_redirects=True
            )
            html = await self._read_response(response)
            if self._is_login_response(response, html):
                raise FintraAuthError("Sessionen er udløbet under kontaktbekræftelsen")
            if self._is_contact_confirmation(response):
                raise FintraConnectionError(
                    "ForældreIntra accepterede ikke kontaktbekræftelsen; "
                    "kontrollér kontaktoplysningerne manuelt"
                )
        return response, html

    async def _async_submit_saml_form(
        self, response: ClientResponse, html: str
    ) -> tuple[ClientResponse, str]:
        """Submit the browser-driven SAML assertion form when present."""
        soup = BeautifulSoup(html, "html.parser")
        for form in soup.find_all("form"):
            action = urljoin(str(response.url), str(form.get("action") or response.url))
            parsed_action = urlparse(action)
            if (
                parsed_action.hostname != self.host
                or parsed_action.path.lower() != _SAML_CONSUMER_PATH
                or form.find(attrs={"name": "SAMLResponse"}) is None
            ):
                continue
            fields = {
                str(field["name"]): str(field.get("value", ""))
                for field in form.find_all("input", attrs={"name": True})
            }
            saml_response = await self._session.post(
                action, data=fields, allow_redirects=True
            )
            return saml_response, await self._read_response(saml_response)
        return response, html

    async def async_fetch_data(
        self,
        selected_child_keys: set[str],
        *,
        today: date,
        include_messages: bool,
    ) -> dict[str, ChildData]:
        """Fetch current plans and recent actionable messages."""
        children = await self.async_login()
        selected = [child for child in children if child.key in selected_child_keys]
        if not selected:
            raise FintraError("Ingen af de valgte børn findes længere på kontoen")

        iso_year, iso_week, _ = today.isocalendar()
        plans: dict[str, tuple[WeekPlan | None, WeekPlan | None, tuple[str, ...]]] = {}
        for child in selected:
            plans[child.key] = await self._async_fetch_plans(
                child, week=iso_week, year=iso_year
            )

        signals: dict[str, list[MessageSignal]] = {child.key: [] for child in selected}
        if include_messages:
            await self._async_fetch_messages(selected, today=today, result=signals)

        return {
            child.key: ChildData(
                child=child,
                class_plan=plans[child.key][0],
                sfo_plan=plans[child.key][1],
                message_signals=tuple(signals[child.key]),
                source_urls=plans[child.key][2],
            )
            for child in selected
        }

    async def _async_fetch_plans(
        self, child: Child, *, week: int, year: int
    ) -> tuple[WeekPlan | None, WeekPlan | None, tuple[str, ...]]:
        list_path = (
            f"/parent/{child.child_id}/{child.slug}item/weeklyplansandhomework/list"
        )
        html = await self._async_get_text(list_path)
        links = parse_plan_links(html, self._base_url, week=week, year=year)
        class_plan: WeekPlan | None = None
        sfo_plan: WeekPlan | None = None
        source_urls: list[str] = []
        for link in links:
            plan_html = await self._async_get_text(link.url)
            plan = parse_week_plan(plan_html, year=year)
            if plan is None:
                raise FintraConnectionError(
                    f"{link.plan_type.upper()}-ugeplanen havde et ukendt format"
                )
            source_urls.append(link.url)
            if link.plan_type == PLAN_TYPE_CLASS:
                class_plan = plan
            elif link.plan_type == PLAN_TYPE_SFO:
                sfo_plan = plan
        return class_plan, sfo_plan, tuple(source_urls)

    async def _async_fetch_messages(
        self,
        children: list[Child],
        *,
        today: date,
        result: dict[str, list[MessageSignal]],
    ) -> None:
        cutoff = today - timedelta(days=6)
        signal_cache: dict[str, MessageSignal | None] = {}
        for child in children:
            inbox_path = f"/parent/{child.child_id}/{child.slug}/messages/conversations"
            inbox = await self._async_get_text(inbox_path)
            for conversation in parse_conversations(inbox):
                if conversation.key not in signal_cache:
                    payloads = await self._async_get_message_payloads(
                        child, conversation.thread_id, conversation.latest_message_id
                    )
                    latest_signal = None
                    for payload in payloads:
                        signal = parse_message(payload)
                        if signal is None or signal.sent_at.date() < cutoff:
                            continue
                        if (
                            latest_signal is None
                            or signal.sent_at > latest_signal.sent_at
                        ):
                            latest_signal = signal
                    signal_cache[conversation.key] = latest_signal
                signal = signal_cache[conversation.key]
                if signal is not None and signal.sent_at.date() >= cutoff:
                    result[child.key].append(signal)

    async def _async_get_message_payloads(
        self, child: Child, thread_id: str, message_id: str
    ) -> list[dict[str, Any]]:
        prefix = f"/parent/{child.child_id}/{child.slug}/messages/conversations"
        if thread_id:
            path = (
                f"{prefix}/loadmessagesforselectedconversation"
                f"?threadId={quote(thread_id)}"
                f"&takeFromRootMessageId={quote(message_id)}"
                "&takeToMessageId=0&searchRequest="
            )
        else:
            path = (
                f"{prefix}/getmessageforthreadlessconversation"
                f"?messageId={quote(message_id)}"
            )
        payload = await self._async_get_json(path)
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        return [payload] if isinstance(payload, dict) else []

    async def _async_get_text(self, path_or_url: str) -> str:
        if not self._logged_in:
            await self.async_login()
        url = urljoin(self._base_url, path_or_url)
        try:
            response = await self._session.get(url, allow_redirects=True)
            html = await self._read_response(response)
        except ClientError as err:
            raise FintraConnectionError("ForældreIntra kunne ikke kontaktes") from err
        if self._is_login_response(response, html):
            self._logged_in = False
            raise FintraAuthError("Sessionen er udløbet")
        return html

    async def _async_get_json(self, path_or_url: str) -> Any:
        if not self._logged_in:
            await self.async_login()
        url = urljoin(self._base_url, path_or_url)
        try:
            response = await self._session.get(url, allow_redirects=True)
            text = await self._read_response(response)
        except ClientError as err:
            raise FintraConnectionError("ForældreIntra kunne ikke kontaktes") from err
        if self._is_login_response(response, text):
            self._logged_in = False
            raise FintraAuthError("Sessionen er udløbet")
        try:
            return await response.json(content_type=None)
        except (ValueError, ClientError) as err:
            raise FintraConnectionError("Beskeddata havde et ukendt format") from err

    @staticmethod
    async def _read_response(response: ClientResponse) -> str:
        if response.status >= 400:
            raise FintraConnectionError(
                f"ForældreIntra svarede med HTTP {response.status}"
            )
        return await response.text()

    @staticmethod
    def _is_login_response(response: ClientResponse, html: str) -> bool:
        # The identity provider may serve a SAML assertion at the login URL
        # itself. Only a returned credential form proves login is required.
        return FintraClient._find_login_form(html) is not None
