import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient


# 测试使用每次生命周期重新创建的内存仓储，不读取真实数据库或静态 Key。
os.environ["REPOSITORY_BACKEND"] = "memory"

_test_keys: dict[str, str] = {}


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    from src.server.main import app

    async with LifespanManager(app) as manager:
        auth_service = app.state.auth_service
        admin = await auth_service.create_user("Test Admin", "admin")
        user = await auth_service.create_user("Test User", "user")
        admin_key = await auth_service.create_api_key(admin["user_id"])
        user_key = await auth_service.create_api_key(user["user_id"])
        _test_keys.update(admin=admin_key["key"], user=user_key["key"])

        transport = ASGITransport(app=manager.app)

        async with AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as async_client:
            yield async_client

        _test_keys.clear()


@pytest.fixture
def user_headers(client: AsyncClient) -> dict[str, str]:
    return {"Authorization": f"Bearer {_test_keys['user']}"}


@pytest.fixture
def admin_headers(client: AsyncClient) -> dict[str, str]:
    return {"Authorization": f"Bearer {_test_keys['admin']}"}
