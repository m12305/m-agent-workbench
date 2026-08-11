"""Multi-Agent SQLite 隔离、锁释放与生命周期回归测试。"""

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

import src.agents.multi_agent.main_agent as main_agent_module
import src.agents.multi_agent.sub_agent as sub_agent_module
from src.agents.multi_agent.main_agent import MainAgent
from src.agents.multi_agent.sub_agent import SubAgent
from src.server.services.multi_agent_service import MultiAgentService


@pytest.fixture
def disable_models(monkeypatch):
    """禁止真实模型调用，仅验证 SQLite 基础设施。"""
    monkeypatch.setattr(main_agent_module, "CAN_RUN", False)
    monkeypatch.setattr(main_agent_module, "get_model", lambda **_kwargs: None)
    monkeypatch.setattr(sub_agent_module, "CAN_RUN", False)
    monkeypatch.setattr(sub_agent_module, "get_model", lambda **_kwargs: None)


@pytest.mark.parametrize("agent_class", [MainAgent, SubAgent])
def test_sqlite_store_does_not_hold_checkpoint_write_lock(
    tmp_path,
    disable_models,
    agent_class,
):
    db_path = tmp_path / f"{agent_class.__name__}.db"
    agent = agent_class(store_type="sqlite", sqlite_path=str(db_path))
    agent.initialize()

    checkpointer_conn, store_conn = agent._sqlite_connections
    assert not checkpointer_conn.in_transaction
    assert not store_conn.in_transaction

    # 外部写连接能立即取得写锁，证明 Store 初始化未残留事务。
    with closing(sqlite3.connect(db_path, timeout=0.1)) as probe:
        probe.execute("BEGIN IMMEDIATE")
        probe.rollback()

    connections = agent._sqlite_connections
    agent.close()
    assert agent._sqlite_connections == ()
    for connection in connections:
        with pytest.raises(sqlite3.ProgrammingError):
            connection.execute("SELECT 1")


def test_service_derives_stable_isolated_database_per_user(
    tmp_path,
    disable_models,
):
    base_path = tmp_path / "multi_agent.db"
    service = MultiAgentService(store_type="sqlite", sqlite_path=str(base_path))

    user_a_path = service._sqlite_path_for_user("user-a")
    user_b_path = service._sqlite_path_for_user("user-b")

    assert user_a_path == service._sqlite_path_for_user("user-a")
    assert user_a_path != user_b_path
    assert Path(user_a_path).parent == tmp_path
    assert "user-a" not in Path(user_a_path).name

    user_a_agent = service._get_or_create_agent("user-a")
    user_b_agent = service._get_or_create_agent("user-b")
    assert user_a_agent._sqlite_path == user_a_path
    assert user_b_agent._sqlite_path == user_b_path
    assert Path(user_a_path).is_file()
    assert Path(user_b_path).is_file()

    service.close_all()
    assert service._agents == {}
