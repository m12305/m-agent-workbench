"""
===========================================================================
SubAgent — Plan-and-Solve 子执行器
===========================================================================

基于 LangGraph 的 Plan-and-Solve 智能体:
  1. plan:     分解分配的任务为子步骤
  2. execute:  ReAct 循环执行每个子步骤 (复用 ChatAgent 模式)
  3. evaluate: 自评结果质量
  4. report:   格式化结果返回 MainAgent

Tool 隔离:
  每个 SubAgent 实例创建独立的 ToolRegistry:
    - L1: GENERAL_TOOLS (共享函数引用)
    - L3: 单智能体规划 tools (prompt 函数)
    - L4: 本 subagent 专属 API tools (构造参数注入)

使用:
    sub = SubAgent(
        name="DataAnalyst",
        subagent_type="data_analyst",
        description="擅长数据分析",
        capabilities=["data_query", "statistics"],
        api_tools=[sql_query, chart_data],
    )
    sub.initialize()
    result = sub.run("查询上月销售总额并按地区分组")
===========================================================================
"""

import asyncio
import sqlite3
import threading
import uuid
from pathlib import Path
from typing import AsyncGenerator, Generator

from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
from langgraph.checkpoint.memory import MemorySaver
from langgraph.store.memory import InMemoryStore
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage, ToolMessage
from langchain_core.runnables import RunnableConfig

from ..base import BaseAgent
from ...models.llm import get_model, CAN_RUN
from ...tools.registry import ToolRegistry
from ...tools.base import BUILTIN_TOOLS, BUILTIN_TOOLS_META
from ...tools.general import GENERAL_TOOLS
from ...tools.single_agent_planning.task_decomposer import (
    decompose_task, DecompositionOutput,
)
from ...tools.single_agent_planning.step_tracker import StepTracker
from ...tools.single_agent_planning.self_evaluator import (
    evaluate_result, EvaluationOutput,
)
from ...utils.logger import get_logger
from ...prompt import SUBAGENT_SYSTEM_PROMPT, build_subagent_step_prompt


# ═══════════════════════════════════════════════════════════════════════
# State
# ═══════════════════════════════════════════════════════════════════════

from .states import SubAgentState
from .events import AgentRunCancelled


GRAPH_RECURSION_LIMIT = 50


# ═══════════════════════════════════════════════════════════════════════
# SubAgent
# ═══════════════════════════════════════════════════════════════════════

class SubAgent(BaseAgent):
    """Plan-and-Solve 子智能体

    参数:
        name:            Agent 名称 (用于日志)
        subagent_type:   类型标识, 如 "data_analyst"
        description:     能力描述 (LLM 选择依据)
        capabilities:    能力标签列表
        api_tools:       本 subagent 专属的 L4 API tools 列表
        model_kwargs:    传递给 get_model() 的额外参数
        store_type:      存储类型: "memory" | "sqlite"
        sqlite_path:     SQLite 路径 (store_type="sqlite" 时)
    """

    def __init__(
        self,
        name: str = "SubAgent",
        subagent_type: str = "general",
        description: str = "通用子智能体",
        capabilities: list[str] | None = None,
        api_tools: list | None = None,
        api_tools_meta: dict[str, dict] | None = None,
        model_kwargs: dict | None = None,
        store_type: str = "memory",
        sqlite_path: str | None = None,
        **kwargs,
    ):
        super().__init__(name=name, **kwargs)
        self.subagent_type = subagent_type
        self.description = description
        self.capabilities = capabilities or []
        self._api_tools = api_tools or []
        self._api_tools_meta = api_tools_meta or {}
        self._model_kwargs = model_kwargs or {}
        self._store_type = store_type
        self._sqlite_path = sqlite_path

        # 在 _setup 中设置
        self.tool_registry: ToolRegistry | None = None
        self._graph = None
        self._checkpointer = None
        self._store = None
        self._sqlite_connections: tuple[sqlite3.Connection, ...] = ()
        self._cancellation_events: dict[str, threading.Event] = {}

    # ═══ 初始化 ═══

    def _setup(self, **kwargs):
        """初始化 SubAgent 组件"""
        logger = get_logger(f"SubAgent.{self.name}")

        # 1. 模型
        self.model = get_model(**self._model_kwargs)
        if self.model is None:
            logger.warning("无可用 LLM — SubAgent 将以降级模式运行")

        # 2. 工具注册中心 (隔离)
        self.tool_registry = ToolRegistry()
        # L1: 通用 tools
        self.tool_registry.register_with_meta(BUILTIN_TOOLS, BUILTIN_TOOLS_META)
        # L4: 本 subagent 专属 API tools
        if self._api_tools:
            if self._api_tools_meta:
                self.tool_registry.register_with_meta(self._api_tools, self._api_tools_meta)
            else:
                self.tool_registry.register_many(self._api_tools, category="backend_api")
        logger.info(
            "ToolRegistry: %d tools (L1=%d, L4=%d)",
            self.tool_registry.tool_count,
            len(GENERAL_TOOLS),
            len(self._api_tools),
        )

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
                db_path = Path(self._sqlite_path or "./data/subagent.db").expanduser()
                db_path.parent.mkdir(parents=True, exist_ok=True)

                checkpointer_conn = sqlite3.connect(
                    str(db_path),
                    check_same_thread=False,
                    timeout=30.0,
                )
                store_conn = None
                try:
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
        """构建 Plan-and-Solve LangGraph 图:
        plan → execute(ReAct) → evaluate → (needs_revision? → plan | → report) → END
        """
        # 绑定 tools 用于 execute 节点的 ReAct 循环
        tools = self.tool_registry.list_all()
        model_with_tools = self.model.bind_tools(tools) if tools else self.model

        # ── 节点定义 ──

        def plan_node(state: SubAgentState, config: RunnableConfig) -> dict:
            self._raise_if_cancelled(config)
            """分解任务为子步骤"""
            prompt = decompose_task(
                assigned_task=state.get("assigned_task", ""),
                subagent_type=self.subagent_type,
                capabilities=", ".join(self.capabilities),
                available_tools=self._format_available_tools(),
                context=state.get("step_results", {}).get("_context", ""),
            )
            messages = [SystemMessage(content=SUBAGENT_SYSTEM_PROMPT.format(
                subagent_type=self.subagent_type,
                description=self.description,
                capabilities=", ".join(self.capabilities),
            )), HumanMessage(content=prompt)]

            structured_model = self.model.with_structured_output(DecompositionOutput)
            response = structured_model.invoke(messages)

            sub_plan = [
                {"step_id": s.step_id, "description": s.description,
                 "tool_hint": s.tool_hint}
                for s in response.sub_plan
            ]

            self.logger.info("Plan: %d steps — %s", len(sub_plan), response.strategy)
            return {
                "sub_plan": sub_plan,
                "plan_raw": response.strategy,
                "current_step_index": 0,
                "react_iteration_count": 0,
                "iteration_count": state.get("iteration_count", 0),
                "messages": [AIMessage(content=f"计划已生成: {response.strategy}")],
            }

        def agent_node(state: SubAgentState, config: RunnableConfig) -> dict:
            self._raise_if_cancelled(config)
            """ReAct agent 节点 — 决定调用工具或输出文本"""
            step_idx = state.get("current_step_index", 0)
            sub_plan = state.get("sub_plan", [])
            step_desc = ""
            if 0 <= step_idx < len(sub_plan):
                step_desc = sub_plan[step_idx].get("description", "")

            step_instruction = ""
            # 每个计划步骤只在首次进入 agent 节点时注入一次执行指令。
            # 工具调用后的消息历史已经包含 ToolMessage，不能再次提示模型
            # “请使用工具”，否则模型容易在同一步骤重复调用相同工具。
            if step_desc and state.get("react_iteration_count", 0) == 0:
                step_instruction = build_subagent_step_prompt(
                    step_desc,
                    step_idx + 1,
                    len(sub_plan),
                )

            messages = list(state.get("messages", []))
            if step_instruction:
                messages.append(HumanMessage(content=step_instruction))

            response = model_with_tools.invoke(messages)
            self._raise_if_cancelled(config)
            return {
                "messages": [response],
                "react_iteration_count": state.get("react_iteration_count", 0) + 1,
            }

        def tools_node(state: SubAgentState, config: RunnableConfig) -> dict:
            self._raise_if_cancelled(config)
            """工具执行节点"""
            tool_node = ToolNode(tools)
            result = tool_node.invoke({"messages": state["messages"]})
            self._raise_if_cancelled(config)
            return result

        def advance_step_node(state: SubAgentState, config: RunnableConfig) -> dict:
            """Persist the current output and move to the next planned step."""
            self._raise_if_cancelled(config)
            step_idx = state.get("current_step_index", 0)
            sub_plan = state.get("sub_plan", [])
            step_id = str(
                sub_plan[step_idx].get("step_id", step_idx + 1)
                if 0 <= step_idx < len(sub_plan)
                else step_idx + 1
            )
            step_results = dict(state.get("step_results", {}))
            step_results[step_id] = self._latest_execution_result(
                state.get("messages", [])
            )
            return {
                "step_results": step_results,
                "current_step_index": step_idx + 1,
                "react_iteration_count": 0,
            }

        def evaluate_node(state: SubAgentState, config: RunnableConfig) -> dict:
            self._raise_if_cancelled(config)
            """自评结果质量"""
            sub_plan = state.get("sub_plan", [])
            step_results = {
                key: value
                for key, value in state.get("step_results", {}).items()
                if not str(key).startswith("_")
            }
            plan_summary = "\n".join(
                f"  {s['step_id']}: {s['description']}" for s in sub_plan
            ) if sub_plan else "（无计划）"

            results_text = "\n".join(
                f"步骤 {k}: {v}" for k, v in step_results.items()
            ) if step_results else "（无结果）"

            prompt = evaluate_result(
                assigned_task=state.get("assigned_task", ""),
                plan_summary=plan_summary,
                execution_results=results_text,
            )
            messages = [HumanMessage(content=prompt)]
            structured_model = self.model.with_structured_output(EvaluationOutput)
            response = structured_model.invoke(messages)

            self.logger.info(
                "Evaluate: needs_revision=%s, completeness=%s, accuracy=%s",
                response.needs_revision,
                response.completeness,
                response.accuracy,
            )
            return {
                "self_evaluation": response.feedback,
                "needs_revision": response.needs_revision,
                "iteration_count": state.get("iteration_count", 0) + 1,
                "messages": [AIMessage(content=f"自评: {response.feedback}")],
            }

        def report_node(state: SubAgentState, config: RunnableConfig) -> dict:
            self._raise_if_cancelled(config)
            """格式化最终结果"""
            step_results = {
                key: value
                for key, value in state.get("step_results", {}).items()
                if not str(key).startswith("_")
            }
            result_parts = []
            for step_id, result in sorted(step_results.items()):
                result_parts.append(f"## 步骤 {step_id}\n{result}")

            final = "\n\n".join(result_parts) if result_parts else "（无结果）"
            self.logger.info("Report: %d steps completed", len(step_results))
            return {
                "final_result": final,
                "messages": [AIMessage(content=f"任务完成。执行了 {len(step_results)} 个步骤。")],
            }

        # ── 路由函数 ──

        def should_continue(state: SubAgentState) -> str:
            """ReAct 循环: 检查是否需要调用工具"""
            messages = state.get("messages", [])
            if not messages:
                return END
            last_msg = messages[-1]
            if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
                # 只要存在 tool_calls，就必须先由 ToolNode 为每个
                # tool_call_id 生成对应 ToolMessage，不能直接跳过。
                return "tools"
            return "advance_step"

        def after_advance_step(state: SubAgentState) -> str:
            if state.get("current_step_index", 0) < len(state.get("sub_plan", [])):
                return "agent"
            """计划执行后: 进入评估"""
            return "evaluate"

        def after_evaluate(state: SubAgentState) -> str:
            """评估后: 需要修正则重新规划, 否则提交结果"""
            needs_revision = state.get("needs_revision", False)
            iteration = state.get("iteration_count", 0)
            if needs_revision and iteration < 3:
                self.logger.info("需要修正，重新规划 (迭代 %d)", iteration)
                return "plan"
            return "report"

        # ── 构建图 ──

        workflow = StateGraph(SubAgentState)
        workflow.add_node("plan", plan_node)
        workflow.add_node("agent", agent_node)
        workflow.add_node("tools", tools_node)
        workflow.add_node("advance_step", advance_step_node)
        workflow.add_node("evaluate", evaluate_node)
        workflow.add_node("report", report_node)

        workflow.set_entry_point("plan")

        # plan → agent (开始 ReAct 执行)
        workflow.add_edge("plan", "agent")

        # ReAct 循环
        workflow.add_conditional_edges(
            "agent",
            should_continue,
            {"tools": "tools", "advance_step": "advance_step"},
        )
        # 子计划中的每个步骤都是原子操作。工具执行完成后直接保存工具
        # 结果并推进下一步，避免 tools → agent 循环导致同一步骤重复调用。
        workflow.add_edge("tools", "advance_step")
        workflow.add_conditional_edges(
            "advance_step",
            after_advance_step,
            {"agent": "agent", "evaluate": "evaluate"},
        )

        # 评估 → 修正或提交
        workflow.add_conditional_edges(
            "evaluate",
            after_evaluate,
            {"plan": "plan", "report": "report"},
        )
        workflow.add_edge("report", END)

        self._graph = workflow.compile(
            checkpointer=self._checkpointer,
            store=self._store,
        )
        self.logger.info("Graph compiled: plan → agent→tools?→advance → evaluate → (plan|report)")

    # ═══ 执行 (同步) ═══

    def run(
        self,
        assigned_task: str,
        thread_id: str | None = None,
        context: str = "",
        cancellation_event: threading.Event | None = None,
    ) -> str:
        """执行分配的任务 (同步)

        参数:
            assigned_task: MainAgent 分配的任务描述
            thread_id:     会话隔离 ID (默认自动生成)
            context:       来自前置步骤的上下文

        返回:
            执行结果文本
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
            "assigned_task": assigned_task,
            "subagent_type": self.subagent_type,
            "step_results": {"_context": context},
            "iteration_count": 0,
            "react_iteration_count": 0,
            "messages": [
                SystemMessage(content=SUBAGENT_SYSTEM_PROMPT.format(
                    subagent_type=self.subagent_type,
                    description=self.description,
                    capabilities=", ".join(self.capabilities),
                )),
            ],
        }

        try:
            result = self._graph.invoke(initial_state, config)
            return result.get("final_result", "")
        finally:
            self._cancellation_events.pop(tid, None)

    def run_stream(
        self,
        assigned_task: str,
        thread_id: str | None = None,
        context: str = "",
        cancellation_event: threading.Event | None = None,
    ) -> Generator[dict, None, str]:
        """执行任务 (同步流式)

        Yields:
            dict: {event, data} SSE 事件

        Returns:
            str: 最终结果 (generator return)
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
            "assigned_task": assigned_task,
            "subagent_type": self.subagent_type,
            "step_results": {"_context": context},
            "iteration_count": 0,
            "react_iteration_count": 0,
            "messages": [
                SystemMessage(content=SUBAGENT_SYSTEM_PROMPT.format(
                    subagent_type=self.subagent_type,
                    description=self.description,
                    capabilities=", ".join(self.capabilities),
                )),
            ],
        }

        final_result = ""
        tracker = StepTracker()

        for chunk, metadata in self._graph.stream(
            initial_state, config, stream_mode="messages"
        ):
            node_name = metadata.get("langgraph_node", "")
            if isinstance(chunk, AIMessage) and chunk.content:
                text = self._message_chunk_text(chunk.content)
                if text:
                    yield {"event": "token", "data": {"text": text, "agent": self.subagent_type}}

            # 检测节点转换
            if node_name == "plan" and not final_result:
                yield {
                    "event": "subagent_plan",
                    "data": {"subagent_type": self.subagent_type, "plan": []},
                }
            elif node_name == "evaluate":
                yield {
                    "event": "subagent_step",
                    "data": {
                        "subagent_type": self.subagent_type,
                        "status": "evaluating",
                    },
                }

        # 获取最终状态
        final_state = self._graph.get_state(config)
        if final_state and final_state.values:
            final_result = final_state.values.get("final_result", "")

        yield {
            "event": "subagent_done",
            "data": {
                "subagent_type": self.subagent_type,
                "result_summary": final_result[:200] if final_result else "",
                "success": bool(final_result),
            },
        }

        return final_result

    # ═══ 执行 (异步) ═══

    async def arun(
        self,
        assigned_task: str,
        thread_id: str | None = None,
        context: str = "",
        cancellation_event: threading.Event | None = None,
    ) -> str:
        """执行任务 (异步)"""
        return await asyncio.to_thread(
            self.run, assigned_task, thread_id, context, cancellation_event
        )

    async def arun_stream(
        self,
        assigned_task: str,
        thread_id: str | None = None,
        context: str = "",
        cancellation_event: threading.Event | None = None,
    ) -> AsyncGenerator[dict, None]:
        """执行任务 (异步流式)"""
        cancel = cancellation_event or threading.Event()
        effective_tid = thread_id or str(uuid.uuid4())[:12]
        gen = self.run_stream(
            assigned_task, effective_tid, context, cancellation_event=cancel
        )
        sentinel = object()

        def next_event():
            return next(gen, sentinel)

        # 在线程池中运行同步生成器
        try:
            while True:
                chunk = await asyncio.to_thread(next_event)
                if chunk is sentinel:
                    break
                yield chunk
        finally:
            cancel.set()
            self._cancellation_events.pop(effective_tid, None)

    # ═══ 辅助方法 ═══

    def _format_available_tools(self) -> str:
        """格式化可用工具列表 (注入 plan prompt)"""
        if not self.tool_registry:
            return "（无可用工具）"

        tools = self.tool_registry.list_all()
        if not tools:
            return "（无可用工具）"

        lines = []
        for t in tools:
            desc = getattr(t, "description", "") or ""
            # 截断过长的描述
            if len(desc) > 120:
                desc = desc[:120] + "..."
            lines.append(f"  - **{t.name}**: {desc}")
        return "\n".join(lines)

    @staticmethod
    def _message_chunk_text(content) -> str:
        """提取 message chunk 的文本内容"""
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

    @staticmethod
    def _latest_execution_result(messages) -> str:
        """Return the latest useful model/tool output for a completed step."""
        for message in reversed(messages):
            content = getattr(message, "content", None)
            if isinstance(message, AIMessage) and not getattr(message, "tool_calls", None):
                text = SubAgent._message_chunk_text(content)
                if text:
                    return text
            if isinstance(message, ToolMessage):
                text = SubAgent._message_chunk_text(content)
                if text:
                    return text
        return "（该步骤未返回可用结果）"

    def _raise_if_cancelled(self, config: RunnableConfig) -> None:
        thread_id = config.get("configurable", {}).get("thread_id")
        cancellation_event = self._cancellation_events.get(thread_id)
        if cancellation_event is not None and cancellation_event.is_set():
            raise AgentRunCancelled("任务已由用户中止")

    # ═══ 生命周期 ═══

    def close(self):
        """清理资源"""
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
        self.logger.info("SubAgent 已关闭")
