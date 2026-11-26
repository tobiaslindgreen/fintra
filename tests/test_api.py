"""Tests for the asynchronous ForældreIntra client."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.fintra.api import (
    FintraAuthError,
    FintraClient,
    FintraConnectionError,
    normalize_host,
)
from custom_components.fintra.models import Child


class FakeResponse:
    """Minimal aiohttp response used by the client tests."""

    def __init__(self, url: str, body: str, status: int = 200) -> None:
        """Initialize the response."""
        self.url = url
        self._body = body
        self.status = status

    async def text(self) -> str:
        """Return the response body."""
        return self._body


async def test_login_preserves_hidden_fields_and_discovers_children() -> None:
    """Test the ordinary login flow used by the verified school page."""
    login_response = FakeResponse(
        "https://school.example/Account/IdpLogin?partnerSp=test",
        """
        <form method="post" action="/Account/IdpLogin?partnerSp=test">
          <input name="RoleType" type="hidden" value="Parent">
          <input name="__RequestVerificationToken" type="hidden" value="csrf">
          <input name="UserName" type="text">
          <input name="Password" type="password">
        </form>
        """,
    )
    parent_response = FakeResponse(
        "https://school.example/parent/641/Ellie/Index",
        """
        <button id="sk-personal-menu-button">Ellie 2.KL.</button>
        <a href="/parent/641/Ellie/Index">Ellie 2.KL.</a>
        <a href="/parent/712/Vester/Index">Vester 0.KL.</a>
        """,
    )
    session = MagicMock()
    session.get = AsyncMock(return_value=login_response)
    session.post = AsyncMock(return_value=parent_response)
    client = FintraClient(session, "school.example", "parent", "secret")

    children = await client.async_login()

    assert [child.key for child in children] == ["641:Ellie", "712:Vester"]
    session.post.assert_awaited_once()
    request = session.post.await_args
    assert request.args[0] == ("https://school.example/Account/IdpLogin?partnerSp=test")
    assert request.kwargs["data"] == {
        "RoleType": "Parent",
        "__RequestVerificationToken": "csrf",
        "UserName": "parent",
        "Password": "secret",
    }


async def test_login_submits_saml_assertion_form() -> None:
    """Test the browser-driven SAML form used after credential validation."""
    login_response = FakeResponse(
        "https://school.example/Account/IdpLogin?partnerSp=test",
        """
        <form method="post">
          <input name="UserName"><input name="Password">
        </form>
        """,
    )
    saml_response = FakeResponse(
        "https://identity.example/login",
        """
        <form method="post"
              action="https://school.example/sso/assertionconsumerservice">
          <input name="SAMLResponse" type="hidden" value="assertion">
          <input name="RelayState" type="hidden" value="relay">
        </form>
        """,
    )
    parent_response = FakeResponse(
        "https://school.example/parent/712/Vester/Index",
        '<a href="/parent/712/Vester/Index">Vester 0.KL.</a>',
    )
    session = MagicMock()
    session.get = AsyncMock(return_value=login_response)
    session.post = AsyncMock(side_effect=[saml_response, parent_response])
    client = FintraClient(session, "school.example", "parent", "secret")

    children = await client.async_login()

    assert [child.key for child in children] == ["712:Vester"]
    saml_request = session.post.await_args_list[1]
    assert saml_request.args[0] == (
        "https://school.example/sso/assertionconsumerservice"
    )
    assert saml_request.kwargs["data"] == {
        "SAMLResponse": "assertion",
        "RelayState": "relay",
    }


async def test_login_only_reports_auth_error_for_returned_login_form() -> None:
    """Test rejected credentials are distinct from an unknown login response."""
    login_html = """
    <form method="post">
      <input name="UserName"><input name="Password">
    </form>
    """
    login_response = FakeResponse(
        "https://school.example/Account/IdpLogin?partnerSp=test", login_html
    )
    session = MagicMock()
    session.get = AsyncMock(return_value=login_response)
    session.post = AsyncMock(return_value=login_response)
    client = FintraClient(session, "school.example", "parent", "wrong")

    with pytest.raises(FintraAuthError):
        await client.async_login()


async def test_login_reports_unknown_intermediate_response() -> None:
    """Test an unexpected identity-provider response is not blamed on credentials."""
    login_response = FakeResponse(
        "https://school.example/Account/IdpLogin?partnerSp=test",
        '<form><input name="UserName"><input name="Password"></form>',
    )
    unknown_response = FakeResponse(
        "https://identity.example/unexpected", "<html>Unexpected</html>"
    )
    session = MagicMock()
    session.get = AsyncMock(return_value=login_response)
    session.post = AsyncMock(return_value=unknown_response)
    client = FintraClient(session, "school.example", "parent", "secret")

    with pytest.raises(FintraConnectionError):
        await client.async_login()


CONTACT_FORM = """
<form method="post" action="/parent/ConfirmContacts">
  <input type="hidden" name="__RequestVerificationToken" value="csrf-contact">
  <input name="Email" value="parent@example.test">
  <input name="Phone" value="12345678">
  <input type="hidden" name="ReceiveSms" value="false">
  <input type="checkbox" name="ReceiveSms" value="true" checked>
  <input type="checkbox" name="Optional" value="true">
  <input name="Disabled" value="ignored" disabled>
  <textarea name="Address">Existing address</textarea>
  <select name="Country"><option value="dk" selected>Danmark</option></select>
  <button type="submit" name="command" value="edit">Rediger</button>
  <button type="submit" name="command" value="confirm">Bekræft oplysninger</button>
</form>
"""


async def test_login_confirms_contacts_after_saml() -> None:
    """Continue daily refresh after confirming unchanged contact information."""
    session = MagicMock()
    session.get = AsyncMock(
        return_value=FakeResponse(
            "https://school.example/Account/IdpLogin",
            '<form><input name="UserName"><input name="Password"></form>',
        )
    )
    session.post = AsyncMock(
        side_effect=[
            FakeResponse(
                "https://identity.example/login",
                """
        <form action="https://school.example/sso/assertionconsumerservice">
          <input name="SAMLResponse" value="assertion">
        </form>""",
            ),
            FakeResponse("https://school.example/parent/ConfirmContacts", CONTACT_FORM),
            FakeResponse(
                "https://school.example/parent/712/Vester/Index",
                '<a href="/parent/712/Vester/Index">Vester</a>',
            ),
        ]
    )
    client = FintraClient(session, "school.example", "parent", "secret")

    children = await client.async_login()

    assert children[0].key == "712:Vester"
    request = session.post.await_args_list[2]
    assert request.args[0] == "https://school.example/parent/ConfirmContacts"
    assert request.kwargs["data"] == [
        ("__RequestVerificationToken", "csrf-contact"),
        ("Email", "parent@example.test"),
        ("Phone", "12345678"),
        ("ReceiveSms", "false"),
        ("ReceiveSms", "true"),
        ("Address", "Existing address"),
        ("Country", "dk"),
        ("command", "confirm"),
    ]
    assert client._logged_in


@pytest.mark.parametrize(
    "form",
    [
        "<html>Unknown contact page</html>",
        CONTACT_FORM.replace(
            'action="/parent/ConfirmContacts"', 'action="https://other.example/collect"'
        ),
        CONTACT_FORM.replace(
            'value="confirm">',
            'value="confirm" formaction="https://other.example/collect">',
        ),
        CONTACT_FORM + CONTACT_FORM,
    ],
)
async def test_contact_confirmation_rejects_unknown_or_unsafe_forms(form: str) -> None:
    """Do not guess a form or submit contact information to a different host."""
    session = MagicMock()
    session.post = AsyncMock()
    client = FintraClient(session, "school.example", "parent", "secret")
    with pytest.raises(FintraConnectionError):
        await client._async_confirm_contacts(
            FakeResponse("https://school.example/parent/ConfirmContacts", form), form
        )
    session.post.assert_not_awaited()


async def test_contact_confirmation_does_not_loop_when_rejected() -> None:
    """A server validation failure must not trigger repeated submissions."""
    response = FakeResponse(
        "https://school.example/parent/ConfirmContacts", CONTACT_FORM
    )
    session = MagicMock()
    session.post = AsyncMock(return_value=response)
    client = FintraClient(session, "school.example", "parent", "secret")
    with pytest.raises(FintraConnectionError, match="accepterede ikke"):
        await client._async_confirm_contacts(response, CONTACT_FORM)
    session.post.assert_awaited_once()


@pytest.mark.parametrize("trailing_slash", ["", "/"])
async def test_login_confirms_contacts_with_existing_session(
    trailing_slash: str,
) -> None:
    """A retained session may reach the contact gate before any login form."""
    session = MagicMock()
    session.get = AsyncMock(
        return_value=FakeResponse(
            "https://school.example/parent/ConfirmContacts" + trailing_slash,
            CONTACT_FORM,
        )
    )
    session.post = AsyncMock(
        return_value=FakeResponse(
            "https://school.example/parent/712/Vester/Index",
            '<a href="/parent/712/Vester/Index">Vester</a>',
        )
    )
    client = FintraClient(session, "school.example", "parent", "secret")
    assert (await client.async_login())[0].key == "712:Vester"
    session.post.assert_awaited_once()
    assert "Password" not in dict(session.post.await_args.kwargs["data"])


async def test_login_reuses_authenticated_parent_page() -> None:
    """Daily updates can reuse the session after the contact gate is cleared."""
    session = MagicMock()
    session.get = AsyncMock(
        return_value=FakeResponse(
            "https://school.example/parent/712/Vester/Index",
            '<a href="/parent/712/Vester/Index">Vester</a>',
        )
    )
    session.post = AsyncMock()
    client = FintraClient(session, "school.example", "parent", "secret")
    assert (await client.async_login())[0].key == "712:Vester"
    session.post.assert_not_awaited()


@pytest.mark.parametrize("landing_path", ["/", "/parent/", "/parent/712/Vester/Index/"])
async def test_login_accepts_authenticated_landing_urls(landing_path: str) -> None:
    """Authenticated root and trailing-slash URLs still provide child links."""
    session = MagicMock()
    session.get = AsyncMock(
        return_value=FakeResponse(
            "https://school.example" + landing_path,
            '<a href="/parent/712/Vester/Index">Vester</a>',
        )
    )
    session.post = AsyncMock()
    client = FintraClient(session, "school.example", "parent", "secret")
    assert (await client.async_login())[0].key == "712:Vester"
    session.post.assert_not_awaited()
    session.cookie_jar.clear.assert_not_called()


async def test_next_day_login_starts_with_saml_instead_of_credentials() -> None:
    """An identity-provider cookie can bypass the credential form next morning."""
    login = FakeResponse(
        "https://school.example/Account/IdpLogin",
        """
        <form><input name="UserName"><input name="Password"></form>
    """,
    )
    parent = FakeResponse(
        "https://school.example/parent/712/Vester/Index",
        '<a href="/parent/712/Vester/Index">Vester</a>',
    )
    saml = FakeResponse(
        "https://school.example/Account/IdpLogin",
        """
        <form method="post" action="/sso/assertionconsumerservice">
          <input name="SAMLResponse" value="fresh-assertion">
          <input name="RelayState" value="state">
        </form>
    """,
    )
    session = MagicMock()
    session.get = AsyncMock(side_effect=[login, saml])
    session.post = AsyncMock(side_effect=[parent, parent])
    client = FintraClient(session, "school.example", "parent", "secret")
    first = await client.async_login()
    second = await client.async_login()
    assert first == second
    assert session.post.await_args_list[1].kwargs["data"] == {
        "SAMLResponse": "fresh-assertion",
        "RelayState": "state",
    }
    session.cookie_jar.clear.assert_not_called()


async def test_saml_at_login_url_is_not_rejected_as_bad_password() -> None:
    """Login URL alone cannot distinguish credentials from a successful SAML step."""
    session = MagicMock()
    session.get = AsyncMock(
        return_value=FakeResponse(
            "https://school.example/Account/IdpLogin",
            '<form><input name="UserName"><input name="Password"></form>',
        )
    )
    session.post = AsyncMock(
        side_effect=[
            FakeResponse(
                "https://school.example/Account/IdpLogin",
                """
          <form action="/sso/assertionconsumerservice">
            <input name="SAMLResponse" value="assertion">
          </form>""",
            ),
            FakeResponse(
                "https://school.example/parent/712/Vester/Index",
                '<a href="/parent/712/Vester/Index">Vester</a>',
            ),
        ]
    )
    client = FintraClient(session, "school.example", "parent", "secret")
    assert (await client.async_login())[0].key == "712:Vester"


async def test_unknown_retained_session_is_reset_once() -> None:
    """Recover a stale cookie session without requiring an HA restart."""
    session = MagicMock()
    session.get = AsyncMock(
        side_effect=[
            FakeResponse("https://school.example/SessionExpired", "Expired"),
            FakeResponse(
                "https://school.example/Account/IdpLogin",
                """
            <form><input name="UserName"><input name="Password"></form>
        """,
            ),
        ]
    )
    session.post = AsyncMock(
        return_value=FakeResponse(
            "https://school.example/parent/712/Vester/Index",
            '<a href="/parent/712/Vester/Index">Vester</a>',
        )
    )
    client = FintraClient(session, "school.example", "parent", "secret")
    assert (await client.async_login())[0].key == "712:Vester"
    session.cookie_jar.clear.assert_called_once_with()
    assert session.get.await_count == 2


async def test_unknown_session_has_bounded_retry_and_private_error() -> None:
    """Unknown responses stop after one retry without leaking HTML or query tokens."""
    session = MagicMock()
    session.get = AsyncMock(
        return_value=FakeResponse(
            "https://school.example/unknown?token=private",
            "private contact information",
        )
    )
    session.post = AsyncMock()
    client = FintraClient(session, "school.example", "parent", "secret")
    with pytest.raises(FintraConnectionError, match="ny session") as error:
        await client.async_login()
    assert "private" not in str(error.value)
    assert "secret" not in str(error.value)
    assert session.get.await_count == 2
    session.cookie_jar.clear.assert_called_once_with()
    session.post.assert_not_awaited()
    assert not client._logged_in


async def test_rejected_credentials_do_not_trigger_cookie_reset() -> None:
    """A wrong password is reported once rather than retried as a stale session."""
    session = MagicMock()
    login = FakeResponse(
        "https://school.example/Account/IdpLogin",
        """
        <form><input name='UserName'><input name='Password'></form>
    """,
    )
    session.get = AsyncMock(return_value=login)
    session.post = AsyncMock(return_value=login)
    client = FintraClient(session, "school.example", "parent", "wrong")
    with pytest.raises(FintraAuthError):
        await client.async_login()
    session.cookie_jar.clear.assert_not_called()
    session.post.assert_awaited_once()


@pytest.mark.parametrize("status", [403, 500])
async def test_contact_confirmation_reports_http_errors(status: int) -> None:
    """Propagate failed confirmations without treating them as successful logins."""
    session = MagicMock()
    session.post = AsyncMock(
        return_value=FakeResponse(
            "https://school.example/parent/ConfirmContacts", "Error", status
        )
    )
    client = FintraClient(session, "school.example", "parent", "secret")
    with pytest.raises(FintraConnectionError, match=f"HTTP {status}"):
        await client._async_confirm_contacts(
            FakeResponse("https://school.example/parent/ConfirmContacts", CONTACT_FORM),
            CONTACT_FORM,
        )


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("lyngbjerggaardskolen", "lyngbjerggaardskolen.m.skoleintra.dk"),
        ("SCHOOL-NORTH", "school-north.m.skoleintra.dk"),
        ("school.example", "school.example"),
        ("https://school.example/", "school.example"),
    ],
)
def test_normalize_host(value: str, expected: str) -> None:
    """Test school names and legacy addresses normalize to hostnames."""
    assert normalize_host(value) == expected


async def test_linked_plans_with_unknown_format_raise_connection_error() -> None:
    """Test parser failures do not silently become empty plan sensors."""
    client = FintraClient(MagicMock(), "school.example", "parent", "secret")
    client._async_get_text = AsyncMock(
        side_effect=[
            (
                '<a href="/parent/641/Ellieitem/weeklyplansandhomework/'
                'item/class/35-2026">Klasse</a>'
            ),
            "<html><body>Unknown plan markup</body></html>",
        ]
    )

    with pytest.raises(FintraConnectionError, match="ukendt format"):
        await client._async_fetch_plans(
            Child("641", "Ellie", "Ellie 2.KL."), week=35, year=2026
        )
