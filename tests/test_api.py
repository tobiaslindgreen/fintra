"""Tests for the asynchronous ForældreIntra client."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.fintra.api import (
    FintraAuthError,
    FintraClient,
    FintraConnectionError,
    normalize_host,
)


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
    assert request.args[0] == (
        "https://school.example/Account/IdpLogin?partnerSp=test"
    )
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