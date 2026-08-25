"""Tests for the asynchronous ForældreIntra client."""

from unittest.mock import AsyncMock, MagicMock

from custom_components.fintra.api import FintraClient


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