"""Multi-Agent SQLite 隔离、锁释放与生命周期回归测试。"""

import sqlite3
import threading
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import pytest

import src.agents.multi_agent.main_agent as main_agent_module
import src.agents.multi_agent.sub_agent as sub_agent_module
from src.agents.multi_agent.main_agent import MainAgent
from src.agents.multi_agent.sub_agent import SubAgent
from src.server.services.multi_agent_service import MultiAgentService
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.store.memory import InMemoryStore

from src.tools.registry import ToolRegistry


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


class _StructuredModel:
    def __init__(self, schema):
        self.schema = schema

    def invoke(self, _messages):
        if self.schema.__name__ == "DecompositionOutput":
            return SimpleNamespace(
                strategy="two steps",
                sub_plan=[
                    SimpleNamespace(step_id=1, description="first", tool_hint=None),
                    SimpleNamespace(step_id=2, description="second", tool_hint=None),
                ],
            )
        return SimpleNamespace(
            needs_revision=False,
            completeness="complete",
            accuracy="accurate",
            feedback="ok",
            ready_for_main_agent=True,
        )


class _SubAgentModel:
    def __init__(self):
        self.agent_calls = 0

    def bind_tools(self, _tools):
        return self

    def with_structured_output(self, schema):
        return _StructuredModel(schema)

    def invoke(self, _messages):
        self.agent_calls += 1
        return AIMessage(content=f"result-{self.agent_calls}")


def test_subagent_persists_each_planned_step_before_evaluation():
    agent = SubAgent()
    agent.model = _SubAgentModel()
    agent.tool_registry = ToolRegistry()
    agent._checkpointer = MemorySaver()
    agent._store = InMemoryStore()
    agent._initialized = True
    agent._build_graph()

    result = agent.run("do two things", thread_id="two-steps")

    assert "result-1" in result
    assert "result-2" in result
    assert agent.model.agent_calls == 2


class _MainAgentStructuredModel:
    def __init__(self, schema):
        self.schema = schema

    def invoke(self, _messages):
        if self.schema.__name__ == "TaskAnalysisOutput":
            return SimpleNamespace(
                needs_subagents=True,
                task_summary="delegate one step",
                complexity="simple",
                suggested_subagents=["worker"],
                reason="test",
            )
        if self.schema.__name__ == "SubagentMatchOutput":
            return SimpleNamespace(
                overall_strategy="one step",
                plan=[SimpleNamespace(
                    step_id=1,
                    description="flaky work",
                    subagent_type="worker",
                    input_summary="",
                    depends_on=[],
                )],
            )
        if self.schema.__name__ == "AggregationOutput":
            return SimpleNamespace(
                answer="aggregated success",
                sources=["worker:1"],
                confidence="high",
                missing_info="",
            )
        raise AssertionError(f"unexpected schema: {self.schema.__name__}")


class _MainAgentModel:
    def with_structured_output(self, schema):
        return _MainAgentStructuredModel(schema)


class _FlakySubAgent:
    def __init__(self):
        self.calls = 0

    def run(self, *_args, **_kwargs):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("temporary failure")
        return "recovered result"


class _FailingSubAgent:
    def __init__(self):
        self.calls = 0

    def run(self, *_args, **_kwargs):
        self.calls += 1
        raise RuntimeError("persistent failure")


def test_main_agent_retries_failed_execute_step_without_replanning():
    agent = MainAgent(max_step_retries=2)
    agent.model = _MainAgentModel()
    agent._checkpointer = MemorySaver()
    agent._store = InMemoryStore()
    agent._initialized = True
    flaky_subagent = _FlakySubAgent()
    agent._get_or_create_subagent = lambda _subagent_type: flaky_subagent
    agent._build_graph()

    result = agent.run("delegate this", thread_id="execute-retry")
    final_state = agent._graph.get_state({
        "configurable": {"thread_id": "execute-retry"}
    }).values

    assert result == "aggregated success"
    assert flaky_subagent.calls == 2
    assert final_state["current_step_index"] == 1
    assert final_state["subagent_statuses"] == {"1": "success"}
    assert final_state["subagent_results"] == {"1": "recovered result"}
    assert final_state["step_retry_counts"] == {}


def test_main_agent_stops_retrying_step_after_configured_limit():
    agent = MainAgent(max_step_retries=2)
    agent.model = _MainAgentModel()
    agent._checkpointer = MemorySaver()
    agent._store = InMemoryStore()
    agent._initialized = True
    failing_subagent = _FailingSubAgent()
    agent._get_or_create_subagent = lambda _subagent_type: failing_subagent
    agent._build_graph()

    agent.run("delegate this", thread_id="execute-retry-limit")
    final_state = agent._graph.get_state({
        "configurable": {"thread_id": "execute-retry-limit"}
    }).values

    assert failing_subagent.calls == 3
    assert final_state["current_step_index"] == 1
    assert final_state["subagent_statuses"] == {"1": "failed"}
    assert final_state["step_retry_counts"] == {"1": 3}


@pytest.mark.asyncio
async def test_subagent_async_stream_uses_one_generator_and_propagates_cancel():
    agent = SubAgent()
    calls = 0
    cancellation_event = threading.Event()

    def fake_run_stream(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        yield {"event": "token", "data": {"text": "one"}}
        yield {"event": "subagent_done", "data": {"success": True}}

    agent.run_stream = fake_run_stream
    events = [
        event
        async for event in agent.arun_stream(
            "task", cancellation_event=cancellation_event
        )
    ]

    assert calls == 1
    assert [event["event"] for event in events] == ["token", "subagent_done"]
    assert cancellation_event.is_set()


def test_service_cancel_run_sets_active_cancellation_event():
    service = MultiAgentService()
    cancellation_event = threading.Event()
    service._active_runs["user:session"] = cancellation_event

    assert service.cancel_run("user:session") is True
    assert cancellation_event.is_set()
    assert service.cancel_run("missing") is False
