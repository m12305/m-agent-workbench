"""
===========================================================================
MainAgent — 层级多智能体编排器
===========================================================================

基于 LangGraph 的编排器, 负责:
  1. analyze:   分析用户任务, 判断是否需要 subagent
  2. plan:      生成执行计划 (选择 subagent + 步骤排序)
  3. execute:   逐步骤调度 subagent, 收集结果
  4. synthesize: 综合 subagent 结果 → 最终回答
  5. replan:    步骤失败时调整计划

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
import uuid
from pathlib import Path
from typing import AsyncGenerator, Generator

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from langgraph.store.memory import InMemoryStore
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage

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
from ...tools.multi_agent_planning.plan_adjuster import (
    adjust_plan, AdjustedPlanOutput,
)
from .sub_agent_registry import SubAgentRegistry
from .sub_agent import SubAgent
from .states import MainAgentState
from .events import MultiAgentEvent
from ...utils.logger import get_logger


# ═══════════════════════════════════════════════════════════════════════
# System Prompt
# ═══════════════════════════════════════════════════════════════════════

MAIN_AGENT_SYSTEM_PROMPT = """你是一个 AI 主智能体和任务编排专家。你的职责是理解用户意图，判断任务所需能力，并选择最合适的执行方式，而不是默认由自己回答所有问题。

## 核心职责

1. 准确理解用户任务及其目标。
2. 分别判断任务复杂度，以及是否需要调用子智能体。
3. 当任务依赖实时信息、工具、外部数据或专业能力时，选择能力匹配的子智能体。
4. 对复杂任务制定清晰、最小且可执行的计划。
5. 综合子智能体返回的真实结果，生成完整、准确的最终回答。

## 路由原则

- `complexity` 与 `needs_subagents` 是两个独立维度。
- `simple` 只表示任务步骤少，不代表不需要子智能体。
- 只有不依赖实时信息、工具、外部数据或专业能力的普通对话和静态知识问答，才可以由主智能体直接回答。
- 只要任务必须使用某个已注册子智能体的能力，即使任务只有一个步骤，也必须调用该子智能体。
- 当前时间、当前日期、系统状态等实时信息不能依靠模型记忆推测；如果存在对应子智能体或工具能力，必须委派执行。
- 例如：当 `general_assistant` 具备 `get_current_time` 能力时，“现在几点了”应判定为 `complexity=simple`、`needs_subagents=true`，并推荐 `general_assistant`。
- 选择能够完成任务的最少子智能体，不要为了展示多智能体流程而进行无意义委派。
- 不得虚构工具执行结果、实时数据或子智能体输出。

## 执行与失败处理

- 制定计划时只能使用当前已注册的子智能体类型，不得虚构不存在的类型。
- 委派内容必须说明目标、必要上下文和预期输出。
- 如果子智能体执行失败，应根据失败原因重试、替换执行者、调整计划或明确说明能力限制。
- 最终回答必须基于实际执行结果；使用了子智能体时，应准确整合其发现，不得编造未返回的信息。

始终遵守当前节点提示中规定的输出格式。执行任务分析时只返回要求的结构化结果，不要提前回答用户问题。"""


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
        max_replans:            最大重规划次数 (默认 2)
    """

    def __init__(
        self,
        name: str = "MainAgent",
        sub_agent_registry: SubAgentRegistry | None = None,
        model_kwargs: dict | None = None,
        store_type: str = "memory",
        sqlite_path: str | None = None,
        max_replans: int = 2,
        **kwargs,
    ):
        super().__init__(name=name, **kwargs)
        self.sub_agent_registry = sub_agent_registry or SubAgentRegistry()
        self._model_kwargs = model_kwargs or {}
        self._store_type = store_type
        self._sqlite_path = sqlite_path
        self._max_replans = max_replans

        # 在 _setup 中设置
        self.tool_registry: ToolRegistry | None = None
        self._graph = None
        self._checkpointer = None
        self._store = None
        self._sqlite_connections: tuple[sqlite3.Connection, ...] = ()
        self._sub_agents_cache: dict[str, SubAgent] = {}

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
                  execute 内部: dispatch → (fail? → replan → plan)
        """

        # ── 节点定义 ──

        def analyze_node(state: MainAgentState) -> dict:
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

        def respond_node(state: MainAgentState) -> dict:
            """简单任务直接回答"""
            user_task = state.get("user_task", "")
            messages = [
                SystemMessage(content=MAIN_AGENT_SYSTEM_PROMPT),
                HumanMessage(content=(
                    f"这是一个简单任务，不需要子智能体。请直接回答:\n\n{user_task}"
                )),
            ]
            response = self.model.invoke(messages)
            return {
                "synthesized_answer": response.content if response.content else "",
                "messages": [response],
            }

        def plan_node(state: MainAgentState) -> dict:
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
                "messages": [
                    AIMessage(content=f"执行计划已生成: {len(plan)} 个步骤\n{response.overall_strategy}")
                ],
            }

        def execute_node(state: MainAgentState) -> dict:
            """执行当前步骤 — 调度 subagent"""
            plan = state.get("plan", [])
            step_idx = state.get("current_step_index", 0)
            results = dict(state.get("subagent_results", {}))
            statuses = dict(state.get("subagent_statuses", {}))

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
                prompt = (
                    f"请完成以下任务步骤:\n\n{task_desc}\n\n"
                    f"原始用户任务: {state.get('user_task', '')}"
                )
                messages = [
                    SystemMessage(content=MAIN_AGENT_SYSTEM_PROMPT),
                    HumanMessage(content=prompt),
                ]
                response = self.model.invoke(messages)
                results[step_id] = response.content if response else ""
                statuses[step_id] = "success"
            else:
                # 调度 subagent
                try:
                    sub = self._get_or_create_subagent(subagent_type)
                    context = self._build_context_for_step(step, results)
                    delegation_task = (
                        f"{step['description']}\n\n"
                        f"上下文: {context}\n\n"
                        f"请完成此任务并返回结果。"
                    )
                    result = sub.run(delegation_task, context=context)
                    results[step_id] = result
                    statuses[step_id] = "success"
                except Exception as e:
                    self.logger.error("SubAgent %s failed: %s", subagent_type, e)
                    results[step_id] = f"[失败] {e}"
                    statuses[step_id] = "failed"

            return {
                "subagent_results": results,
                "subagent_statuses": statuses,
                "current_step_index": step_idx + 1,
                "messages": [
                    AIMessage(content=f"步骤 {step_id} ({subagent_type or 'direct'}): "
                              f"{statuses[step_id]}")
                ],
            }

        def synthesize_node(state: MainAgentState) -> dict:
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

        def replan_node(state: MainAgentState) -> dict:
            """失败时重新规划"""
            plan = state.get("plan", [])
            results = state.get("subagent_results", {})
            statuses = state.get("subagent_statuses", {})

            # 已完成和失败的步骤
            completed = "\n".join(
                f"步骤 {sid}: {results.get(sid, '')}"
                for sid, st in statuses.items() if st == "success"
            ) or "（无）"

            failed_steps = [
                f"步骤 {sid}: {results.get(sid, '')}"
                for sid, st in statuses.items() if st == "failed"
            ]
            failed = "\n".join(failed_steps) if failed_steps else "（无）"

            prompt = adjust_plan(
                user_task=state.get("user_task", ""),
                original_plan=str(plan),
                completed_steps=completed,
                failed_step=failed,
            )
            messages = [HumanMessage(content=prompt)]
            structured_model = self.model.with_structured_output(AdjustedPlanOutput)
            response = structured_model.invoke(messages)

            # 转换为 plan 格式
            new_plan = [
                {
                    "step_id": s.step_id,
                    "description": s.description,
                    "subagent_type": s.subagent_type,
                    "input_summary": s.input_summary,
                    "depends_on": s.depends_on,
                }
                for s in response.adjusted_plan
            ]

            self.logger.info("Replan: %s — %d adjusted steps",
                             response.strategy, len(new_plan))
            return {
                "plan": new_plan,
                "current_step_index": 0,
                "needs_replan": False,
                "iteration_count": state.get("iteration_count", 0) + 1,
                "messages": [
                    AIMessage(content=f"计划已调整: {response.strategy}")
                ],
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
            """执行后: 全部完成→综合, 有失败→重规划, 继续→执行"""
            plan = state.get("plan", [])
            step_idx = state.get("current_step_index", 0)
            statuses = state.get("subagent_statuses", {})

            # 检查是否有失败的步骤
            has_failed = any(s == "failed" for s in statuses.values())
            if has_failed:
                iteration = state.get("iteration_count", 0)
                if iteration < self._max_replans:
                    return "replan"
                self.logger.warning("达到最大重规划次数 %d，跳过失败步骤", self._max_replans)

            # 还有未执行的步骤
            if step_idx < len(plan):
                return "execute"

            # 全部完成
            return "synthesize"

        def after_replan(state: MainAgentState) -> str:
            """重规划后: 回到 plan 节点"""
            return "plan"

        # ── 构建图 ──

        workflow = StateGraph(MainAgentState)
        workflow.add_node("analyze", analyze_node)
        workflow.add_node("respond", respond_node)
        workflow.add_node("plan", plan_node)
        workflow.add_node("execute", execute_node)
        workflow.add_node("synthesize", synthesize_node)
        workflow.add_node("replan", replan_node)

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
                "replan": "replan",
            },
        )
        workflow.add_edge("replan", "plan")
        workflow.add_edge("respond", END)
        workflow.add_edge("synthesize", END)

        self._graph = workflow.compile(
            checkpointer=self._checkpointer,
            store=self._store,
        )
        self.logger.info(
            "Graph compiled: analyze→(respond|plan→execute→(synthesize|replan))"
        )

    # ═══ 执行 (同步) ═══

    def run(
        self,
        user_task: str,
        thread_id: str | None = None,
    ) -> str:
        """执行用户任务 (同步)

        返回: 最终回答文本
        """
        self.initialize()
        tid = thread_id or str(uuid.uuid4())[:12]
        config = {"configurable": {"thread_id": tid}}

        initial_state = {
            "user_task": user_task,
            "messages": [
                SystemMessage(content=MAIN_AGENT_SYSTEM_PROMPT),
                HumanMessage(content=user_task),
            ],
        }

        result = self._graph.invoke(initial_state, config)
        return result.get("synthesized_answer", "无法完成任务")

    def run_stream(
        self,
        user_task: str,
        thread_id: str | None = None,
    ) -> Generator[dict, None, str]:
        """执行任务 (同步流式)

        Yields:
            dict: {event, data} SSE event

        Returns:
            str: 最终回答 (generator return)
        """
        self.initialize()
        tid = thread_id or str(uuid.uuid4())[:12]
        config = {"configurable": {"thread_id": tid}}

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
    ) -> str:
        """执行任务 (异步)"""
        return await asyncio.to_thread(self.run, user_task, thread_id)

    async def arun_stream(
        self,
        user_task: str,
        thread_id: str | None = None,
    ) -> AsyncGenerator[dict, None]:
        """执行任务 (异步流式)"""
        loop = asyncio.get_event_loop()

        def _sync_gen():
            yield from self.run_stream(user_task, thread_id)

        done = False
        gen = _sync_gen()
        while not done:
            try:
                chunk = await loop.run_in_executor(None, next, gen)
                yield chunk
            except StopIteration:
                done = True

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
            "replan": MultiAgentEvent.STATUS,
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
            "replan": "正在调整计划...",
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
