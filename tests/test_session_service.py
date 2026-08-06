import pytest

from src.server.exceptions import NotFoundError
from src.server.repositories.memory import InMemorySessionRepo
from src.server.services.session_service import SessionService


@pytest.mark.asyncio
async def test_regular_user_can_rename_own_session():
    service = SessionService(InMemorySessionRepo())
    session = await service.create_session("user-1", "旧标题")

    updated = await service.rename_session(
        "user-1", session.session_id, "新标题",
    )

    assert updated.title == "新标题"


@pytest.mark.asyncio
async def test_user_cannot_rename_another_users_session():
    service = SessionService(InMemorySessionRepo())
    session = await service.create_session("user-1", "原标题")

    with pytest.raises(NotFoundError):
        await service.rename_session(
            "user-2", session.session_id, "越权修改",
        )

    unchanged = await service.get_session(session.session_id)
    assert unchanged.title == "原标题"
