"""
===========================================================================
MainAgent — 层级多智能体编排器
===========================================================================

基于 LangGraph 的编排器, 负责:
  1. analyze:   分析用户任务, 判断是否需要 subagent
  2. plan:      生成执行计划 (选择 subagent + 步骤排序)
  3. execute:   逐步骤调度 subagent, 收集结果
  4. synthesize: 综合 subagent 结果 → 最终回答
  5. retry:     步骤失败时回到当前执行步骤重试

与 SubAgent 的关系:
  MainAgent 通过 SubAgentRegistry 发现可用 subagent,
  按需实例化, 通过 subagent.run() 委托任务。

流式输出:
  每个节点过渡时 yield SSE event, 支持分级展示进度。

使用:
    registry = SubAgentRegistry()
    # ... 注册 subagent 类型 ...

    main = MainAgent(sub_agent_registry=registry)
    main.initialize()

    # 同步
    answer = main.run("帮我分析销售数据并生成报告")

    # 流式
    for event in main.run_stream("帮我分析销售数据并生成报告"):
        print(event)
===========================================================================
"""

import asyncio
import sqlite3
import threading
import uuid
from pathlib import Path
from typing import AsyncGenerator, Generator

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from langgraph.store.memory import InMemoryStore
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from langchain_core.runnables import RunnableConfig

from ..base import BaseAgent
from ...models.llm import get_model, CAN_RUN
from ...tools.registry import ToolRegistry
from ...tools.base import BUILTIN_TOOLS, BUILTIN_TOOLS_META
from ...tools.general import GENERAL_TOOLS
from ...tools.multi_agent_planning.task_analyzer import (
    analyze_user_task, TaskAnalysisOutput,
)
from ...tools.multi_agent_planning.subagent_matcher import (
    match_subagents, build_selection_context, SubagentMatchOutput,
)
from ...tools.multi_agent_planning.delegation_builder import (
    build_delegation,
)
from ...tools.multi_agent_planning.result_aggregator import (
    aggregate_results, AggregationOutput,
)
from .sub_agent_registry import SubAgentRegistry
from .sub_agent import SubAgent
from .states import MainAgentState
from .events import MultiAgentEvent
from .events import AgentRunCancelled
from ...utils.logger import get_logger
from ...prompt import (
    MAIN_AGENT_SYSTEM_PROMPT,
    build_delegation_task_prompt,
    build_direct_response_prompt,
    build_direct_step_prompt,
)


GRAPH_RECURSION_LIMIT = 50


# ═══════════════════════════════════════════════════════════════════════
# MainAgent
# ═══════════════════════════════════════════════════════════════════════

class MainAgent(BaseAgent):
    """层级多智能体编排器

    参数:
        name:                   Agent 名称
        sub_agent_registry:     SubAgent 注册中心
        model_kwargs:           传递给 get_model() 的参数
        store_type:             存储类型: "memory" | "sqlite"
        sqlite_path:            SQLite 路径
        max_step_retries:       单个执行步骤的最大重试次数 (默认 2)
        max_replans:            max_step_retries 的兼容别名
    """

    def __init__(
        self,
        name: str = "MainAgent",
        sub_agent_registry: SubAgentRegistry | None = None,
        model_kwargs: dict | None = None,
        store_type: str = "memory",
        sqlite_path: str | None = None,
        max_step_retries: int = 2,
        max_replans: int | None = None,
        **kwargs,
    ):
        super().__init__(name=name, **kwargs)
        self.sub_agent_registry = sub_agent_registry or SubAgentRegistry()
        self._model_kwargs = model_kwargs or {}
        self._store_type = store_type
        self._sqlite_path = sqlite_path
        # Backwards-compatible alias: failures now retry the same execute step.
        self._max_step_retries = (
            max_replans if max_replans is not None else max_step_retries
        )

        # 在 _setup 中设置
        self.tool_registry: ToolRegistry | None = None
        self._graph = None
        self._checkpointer = None
        self._store = None
        self._sqlite_connections: tuple[sqlite3.Connection, ...] = ()
        self._sub_agents_cache: dict[str, SubAgent] = {}
        self._cancellation_events: dict[str, threading.Event] = {}

    # ═══ 初始化 ═══

    def _setup(self, **kwargs):
        """初始化 MainAgent 组件"""
        logger = get_logger(f"MainAgent.{self.name}")

        # 1. 模型
        self.model = get_model(**self._model_kwargs)
        if self.model is None:
            logger.warning("无可用 LLM — MainAgent 将以降级模式运行")

        # 2. 工具注册中心 (仅 L1 通用 tools)
        self.tool_registry = ToolRegistry()
        self.tool_registry.register_with_meta(BUILTIN_TOOLS, BUILTIN_TOOLS_META)
        #self.tool_registry.register_many(GENERAL_TOOLS, category="general")

        # 3. 存储
        if self._store_type == "sqlite":
            try:
                from langgraph.checkpoint.sqlite import SqliteSaver
                from langgraph.store.sqlite import SqliteStore
            except ImportError:
                logger.warning("langgraph-checkpoint-sqlite 未安装，回退到内存存储")
                self._checkpointer = MemorySaver()
                self._store = InMemoryStore()
            else:
                db_path = Path(self._sqlite_path or "./data/main_agent.db").expanduser()
                db_path.parent.mkdir(parents=True, exist_ok=True)

                checkpointer_conn = sqlite3.connect(
                    str(db_path),
                    check_same_thread=False,
                    timeout=30.0,
                )
                store_conn = None
                try:
                    # SqliteStore 官方连接工厂使用 autocommit。缺少该参数时，
                    # setup() 的最后一条迁移记录会留下写事务并锁住 SqliteSaver。
                    store_conn = sqlite3.connect(
                        str(db_path),
                        check_same_thread=False,
                        isolation_level=None,
                        timeout=30.0,
                    )
                    checkpointer_conn.execute("PRAGMA busy_timeout = 30000")
                    store_conn.execute("PRAGMA busy_timeout = 30000")

                    self._checkpointer = SqliteSaver(checkpointer_conn)
                    self._checkpointer.setup()
                    self._store = SqliteStore(store_conn)
                    self._store.setup()
                except Exception:
                    checkpointer_conn.close()
                    if store_conn is not None:
                        store_conn.close()
                    raise

                self._sqlite_connections = (checkpointer_conn, store_conn)
                self._sqlite_path = str(db_path)
                logger.info("SQLite 存储: %s", db_path)
        else:
            self._checkpointer = MemorySaver()
            self._store = InMemoryStore()

        # 4. 构建图
        if CAN_RUN and self.model is not None:
            self._build_graph()
        else:
            logger.warning("跳过图构建 (无可用模型)")

    def _build_graph(self):
        """构建编排器 LangGraph 图:
        analyze → (simple? → respond) → plan → execute → synthesize → END
                  execute 内部: dispatch → (fail? → retry execute)
        """

        # ── 节点定义 ──

        def analyze_node(state: MainAgentState, config: RunnableConfig) -> dict:
            self._raise_if_cancelled(config)
            """分析用户任务"""
            user_task = state.get("user_task", "")
            subagent_list = self.sub_agent_registry.build_selection_prompt()

            prompt = analyze_user_task(user_task, subagent_list)
            messages = [
                SystemMessage(content=MAIN_AGENT_SYSTEM_PROMPT),
                HumanMessage(content=prompt),
            ]
            structured_model = self.model.with_structured_output(TaskAnalysisOutput)
            response = structured_model.invoke(messages)

            self.logger.info(
                "Analyze: needs_subagents=%s, complexity=%s, suggested=%s",
                response.needs_subagents, response.complexity,
                response.suggested_subagents,
            )
            return {
                "needs_subagents": response.needs_subagents,
                "task_summary": response.task_summary,
                "iteration_count": 0,
                "messages": [AIMessage(
                    content=f"任务分析: {response.task_summary} "
                    f"(复杂度: {response.complexity})"
                )],
            }

        def respond_node(state: MainAgentState, config: RunnableConfig) -> dict:
            self._raise_if_cancelled(config)
            """简单任务直接回答"""
            user_task = state.get("user_task", "")
            messages = [
                SystemMessage(content=MAIN_AGENT_SYSTEM_PROMPT),
                HumanMessage(content=build_direct_response_prompt(user_task)),
            ]
            response = self.model.invoke(messages)
            return {
                "synthesized_answer": response.content if response.content else "",
                "messages": [response],
            }

        def plan_node(state: MainAgentState, config: RunnableConfig) -> dict:
            self._raise_if_cancelled(config)
            """生成执行计划"""
            user_task = state.get("user_task", "")
            task_summary = state.get("task_summary", "")

            # 构建 subagent 选择上下文
            entries = self.sub_agent_registry.list_all()
            context_lines = []
            for i, meta in enumerate(entries, 1):
                context_lines.append(meta.to_prompt_line(i))
            subagent_context = build_selection_context(context_lines)

            prompt = match_subagents(user_task, task_summary, subagent_context)
            messages = [HumanMessage(content=prompt)]
            structured_model = self.model.with_structured_output(SubagentMatchOutput)
            response = structured_model.invoke(messages)

            plan = [
                {
                    "step_id": s.step_id,
                    "description": s.description,
                    "subagent_type": s.subagent_type,
                    "input_summary": s.input_summary,
                    "depends_on": s.depends_on,
                }
                for s in response.plan
            ]

            self.logger.info("Plan: %d steps — %s", len(plan), response.overall_strategy)
            return {
                "plan": plan,
                "plan_raw": response.overall_strategy,
                "current_step_index": 0,
                "subagent_results": {},
                "subagent_statuses": {},
                "step_retry_counts": {},
                "messages": [
                    AIMessage(content=f"执行计划已生成: {len(plan)} 个步骤\n{response.overall_strategy}")
                ],
            }

        def execute_node(state: MainAgentState, config: RunnableConfig) -> dict:
            self._raise_if_cancelled(config)
            """执行当前步骤 — 调度 subagent"""
            plan = state.get("plan", [])
            step_idx = state.get("current_step_index", 0)
            results = dict(state.get("subagent_results", {}))
            statuses = dict(state.get("subagent_statuses", {}))
            retry_counts = dict(state.get("step_retry_counts", {}))

            if step_idx >= len(plan):
                return {"subagent_results": results, "subagent_statuses": statuses}

            step = plan[step_idx]
            step_id = str(step["step_id"])
            subagent_type = step.get("subagent_type")

            self.logger.info("Execute step %d/%d: %s → %s",
                             step_idx + 1, len(plan), step_id, subagent_type or "direct")

            if subagent_type is None:
                # 无需 subagent — main_agent 直接处理
                task_desc = step["description"]
                prompt = build_direct_step_prompt(
                    task_desc,
                    state.get("user_task", ""),
                )
                messages = [
                    SystemMessage(content=MAIN_AGENT_SYSTEM_PROMPT),
                    HumanMessage(content=prompt),
                ]
                try:
                    response = self.model.invoke(messages)
                    results[step_id] = response.content if response else ""
                    statuses[step_id] = "success"
                except AgentRunCancelled:
                    raise
                except Exception as e:
                    self.logger.error("MainAgent direct step %s failed: %s", step_id, e)
                    results[step_id] = f"[失败] {e}"
                    statuses[step_id] = "failed"
            else:
                # 调度 subagent
                try:
                    sub = self._get_or_create_subagent(subagent_type)
                    context = self._build_context_for_step(step, results)
                    delegation_task = build_delegation_task_prompt(
                        step["description"],
                        context,
                        state.get("user_task", ""),
                    )
                    result = sub.run(
                        delegation_task,
                        context=context,
                        cancellation_event=self._cancellation_events.get(
                            config.get("configurable", {}).get("thread_id")
                        ),
                    )
                    self._raise_if_cancelled(config)
                    results[step_id] = result
                    statuses[step_id] = "success"
                except AgentRunCancelled:
                    raise
                except Exception as e:
                    self.logger.error("SubAgent %s failed: %s", subagent_type, e)
                    results[step_id] = f"[失败] {e}"
                    statuses[step_id] = "failed"

            if statuses[step_id] == "failed":
                failed_attempts = retry_counts.get(step_id, 0) + 1
                retry_counts[step_id] = failed_attempts
                if failed_attempts <= self._max_step_retries:
                    next_step_idx = step_idx
                    self.logger.warning(
                        "Retrying failed step %s (%d/%d)",
                        step_id,
                        failed_attempts,
                        self._max_step_retries,
                    )
                else:
                    next_step_idx = step_idx + 1
                    self.logger.error(
                        "Step %s exhausted %d retries; continuing with failure",
                        step_id,
                        self._max_step_retries,
                    )
            else:
                retry_counts.pop(step_id, None)
                next_step_idx = step_idx + 1

            return {
                "subagent_results": results,
                "subagent_statuses": statuses,
                "step_retry_counts": retry_counts,
                "current_step_index": next_step_idx,
                "messages": [
                    AIMessage(content=f"步骤 {step_id} ({subagent_type or 'direct'}): "
                              f"{statuses[step_id]}")
                ],
            }

        def synthesize_node(state: MainAgentState, config: RunnableConfig) -> dict:
            self._raise_if_cancelled(config)
            """综合所有 subagent 结果"""
            user_task = state.get("user_task", "")
            results = state.get("subagent_results", {})
            plan = state.get("plan", [])

            # 格式化步骤结果
            result_lines = []
            for step in plan:
                sid = str(step["step_id"])
                status = state.get("subagent_statuses", {}).get(sid, "pending")
                result_text = results.get(sid, "（无结果）")
                result_lines.append(
                    f"### 步骤 {sid}: {step['description']} "
                    f"[subagent: {step.get('subagent_type', 'direct')}] "
                    f"[状态: {status}]\n{result_text}"
                )

            prompt = aggregate_results(user_task, "\n\n".join(result_lines))
            messages = [HumanMessage(content=prompt)]
            structured_model = self.model.with_structured_output(AggregationOutput)
            response = structured_model.invoke(messages)

            self.logger.info("Synthesize: confidence=%s, sources=%s",
                             response.confidence, response.sources)
            return {
                "synthesized_answer": response.answer,
                "messages": [AIMessage(content=response.answer)],
            }

        # ── 路由函数 ──

        def after_analyze(state: MainAgentState) -> str:
            """分析后: 简单任务直接回答, 复杂任务进入规划"""
            if state.get("needs_subagents", False):
                return "plan"
            return "respond"

        def after_plan(state: MainAgentState) -> str:
            """规划后: 开始执行"""
            return "execute"

        def after_execute(state: MainAgentState) -> str:
            """Retry or continue using the index selected by execute_node."""
            plan = state.get("plan", [])
            step_idx = state.get("current_step_index", 0)
            return "execute" if step_idx < len(plan) else "synthesize"

        # ── 构建图 ──

        workflow = StateGraph(MainAgentState)
        workflow.add_node("analyze", analyze_node)
        workflow.add_node("respond", respond_node)
        workflow.add_node("plan", plan_node)
        workflow.add_node("execute", execute_node)
        workflow.add_node("synthesize", synthesize_node)

        workflow.set_entry_point("analyze")

        workflow.add_conditional_edges(
            "analyze",
            after_analyze,
            {"respond": "respond", "plan": "plan"},
        )
        workflow.add_edge("plan", "execute")
        workflow.add_conditional_edges(
            "execute",
            after_execute,
            {
                "execute": "execute",
                "synthesize": "synthesize",
            },
        )
        workflow.add_edge("respond", END)
        workflow.add_edge("synthesize", END)

        self._graph = workflow.compile(
            checkpointer=self._checkpointer,
            store=self._store,
        )
        self.logger.info(
            "Graph compiled: analyze→(respond|plan→execute(retry)→synthesize)"
        )

    # ═══ 执行 (同步) ═══

    def run(
        self,
        user_task: str,
        thread_id: str | None = None,
        cancellation_event: threading.Event | None = None,
    ) -> str:
        """执行用户任务 (同步)

        返回: 最终回答文本
        """
        self.initialize()
        tid = thread_id or str(uuid.uuid4())[:12]
        if cancellation_event is not None:
            self._cancellation_events[tid] = cancellation_event
        config = {
            "configurable": {"thread_id": tid},
            "recursion_limit": GRAPH_RECURSION_LIMIT,
        }

        initial_state = {
            "user_task": user_task,
            "messages": [
                SystemMessage(content=MAIN_AGENT_SYSTEM_PROMPT),
                HumanMessage(content=user_task),
            ],
        }

        try:
            result = self._graph.invoke(initial_state, config)
            return result.get("synthesized_answer", "无法完成任务")
        finally:
            self._cancellation_events.pop(tid, None)

    def run_stream(
        self,
        user_task: str,
        thread_id: str | None = None,
        cancellation_event: threading.Event | None = None,
    ) -> Generator[dict, None, str]:
        """执行任务 (同步流式)

        Yields:
            dict: {event, data} SSE event

        Returns:
            str: 最终回答 (generator return)
        """
        self.initialize()
        tid = thread_id or str(uuid.uuid4())[:12]
        if cancellation_event is not None:
            self._cancellation_events[tid] = cancellation_event
        config = {
            "configurable": {"thread_id": tid},
            "recursion_limit": GRAPH_RECURSION_LIMIT,
        }

        initial_state = {
            "user_task": user_task,
            "messages": [
                SystemMessage(content=MAIN_AGENT_SYSTEM_PROMPT),
                HumanMessage(content=user_task),
            ],
        }

        last_node = None
        final_answer = ""

        for chunk, metadata in self._graph.stream(
            initial_state, config, stream_mode="messages"
        ):
            node_name = metadata.get("langgraph_node", "")
            if isinstance(chunk, AIMessage) and chunk.content:
                text = self._message_chunk_text(chunk.content)
                if text:
                    yield {
                        "event": MultiAgentEvent.TOKEN,
                        "data": {"text": text, "agent": "main"},
                    }

            # 节点转换事件
            if node_name != last_node:
                event = self._node_to_event(node_name)
                if event:
                    yield event
                last_node = node_name

        # 获取最终状态
        final_state = self._graph.get_state(config)
        if final_state and final_state.values:
            final_answer = final_state.values.get("synthesized_answer", "")

        yield {
            "event": MultiAgentEvent.DONE,
            "data": {"session_id": tid},
        }

        return final_answer

    # ═══ 执行 (异步) ═══

    async def arun(
        self,
        user_task: str,
        thread_id: str | None = None,
        cancellation_event: threading.Event | None = None,
    ) -> str:
        """执行任务 (异步)"""
        return await asyncio.to_thread(
            self.run, user_task, thread_id, cancellation_event
        )

    async def arun_stream(
        self,
        user_task: str,
        thread_id: str | None = None,
        cancellation_event: threading.Event | None = None,
    ) -> AsyncGenerator[dict, None]:
        """执行任务 (异步流式)"""
        effective_tid = thread_id or str(uuid.uuid4())[:12]
        gen = self.run_stream(
            user_task, effective_tid, cancellation_event=cancellation_event
        )
        sentinel = object()

        def next_event():
            return next(gen, sentinel)

        try:
            while True:
                chunk = await asyncio.to_thread(next_event)
                if chunk is sentinel:
                    break
                yield chunk
        finally:
            if cancellation_event is not None:
                cancellation_event.set()
            self._cancellation_events.pop(effective_tid, None)

    # ═══ SubAgent 管理 ═══

    def _get_or_create_subagent(self, subagent_type: str) -> SubAgent:
        """按需获取或创建 SubAgent 实例"""
        if subagent_type not in self._sub_agents_cache:
            meta = self.sub_agent_registry.get(subagent_type)
            if meta is None:
                raise ValueError(f"未知的 SubAgent 类型: {subagent_type}")

            if meta.factory is not None:
                sub = meta.factory()
                if sub is not None:
                    sub.initialize()
                    self._sub_agents_cache[subagent_type] = sub
                    self.logger.info("创建 SubAgent: %s", subagent_type)
                    return sub

            # 使用默认工厂
            sub = SubAgent(
                name=meta.display_name,
                subagent_type=meta.subagent_type,
                description=meta.description,
                capabilities=meta.capabilities,
                store_type=self._store_type,
                sqlite_path=self._subagent_sqlite_path(meta.subagent_type),
            )
            sub.initialize()
            self._sub_agents_cache[subagent_type] = sub

        return self._sub_agents_cache[subagent_type]

    def _subagent_sqlite_path(self, subagent_type: str) -> str | None:
        """为默认 SubAgent 派生独立数据库，避免与 MainAgent 争用同一文件。"""
        if self._store_type != "sqlite":
            return None
        if self._sqlite_path == ":memory:":
            return ":memory:"

        main_path = Path(self._sqlite_path or "./data/main_agent.db")
        suffix = main_path.suffix or ".db"
        safe_type = "".join(
            char if char.isalnum() or char in {"-", "_"} else "-"
            for char in subagent_type
        ).strip("-") or "general"
        return str(main_path.with_name(f"{main_path.stem}-{safe_type}{suffix}"))

    def _build_context_for_step(
        self,
        step: dict,
        all_results: dict[str, str],
    ) -> str:
        """为步骤构建上下文 (前置步骤的结果)"""
        depends_on = step.get("depends_on", [])
        if not depends_on:
            return ""

        context_parts = []
        for dep_id in depends_on:
            dep_result = all_results.get(str(dep_id), "")
            if dep_result:
                context_parts.append(f"[前置步骤 {dep_id} 的结果]\n{dep_result}")

        return "\n\n".join(context_parts)

    # ═══ 辅助方法 ═══

    @staticmethod
    def _node_to_event(node_name: str) -> dict | None:
        """将 LangGraph 节点名转为 SSE event"""
        mapping = {
            "analyze": MultiAgentEvent.ANALYZING,
            "plan": MultiAgentEvent.STATUS,
            "execute": MultiAgentEvent.DISPATCHING,
            "synthesize": MultiAgentEvent.SYNTHESIZING,
            "respond": MultiAgentEvent.STATUS,
        }
        event_type = mapping.get(node_name)
        if event_type is None:
            return None

        messages = {
            "analyze": "正在分析任务...",
            "plan": "正在生成执行计划...",
            "execute": "正在执行计划步骤...",
            "synthesize": "正在综合结果...",
            "respond": "正在生成回答...",
        }
        return {
            "event": event_type,
            "data": {
                "agent": "main",
                "node": node_name,
                "message": messages.get(node_name, ""),
            },
        }

    @staticmethod
    def _message_chunk_text(content) -> str:
        """提取 message chunk 的文本"""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict) and "text" in item:
                    parts.append(item["text"])
                elif isinstance(item, str):
                    parts.append(item)
            return "".join(parts)
        return str(content) if content else ""

    def _raise_if_cancelled(self, config: RunnableConfig) -> None:
        thread_id = config.get("configurable", {}).get("thread_id")
        cancellation_event = self._cancellation_events.get(thread_id)
        if cancellation_event is not None and cancellation_event.is_set():
            raise AgentRunCancelled("任务已由用户中止")

    # ═══ 生命周期 ═══

    def close(self):
        """清理所有 subagent 和资源"""
        for sub in self._sub_agents_cache.values():
            try:
                sub.close()
            except Exception:
                pass
        self._sub_agents_cache.clear()

        # Graph 持有 checkpointer/store 引用，先释放 graph 再关闭底层连接。
        self._graph = None
        for cancellation_event in self._cancellation_events.values():
            cancellation_event.set()
        self._cancellation_events.clear()
        connections = self._sqlite_connections
        self._sqlite_connections = ()
        for connection in reversed(connections):
            try:
                if connection.in_transaction:
                    connection.rollback()
                connection.close()
            except sqlite3.Error as exc:
                self.logger.warning("关闭 SQLite 连接失败: %s", exc)
        self._checkpointer = None
        self._store = None
        self.logger.info("MainAgent 已关闭")
