# Multi-Agent 请求后端逻辑梳理

从 `POST /api/v1/multi-agent/chat/stream` 发起请求到返回完整 SSE 事件流的全链路。

---

## 一、请求入口 — API 路由层

**文件:** `src/server/api/multi_agent.py` → `multi_agent_chat_stream()`

```
POST /api/v1/multi-agent/chat/stream
Body: { "query": "帮我分析销售数据", "session_id": null }
Headers: Authorization: Bearer sk-xxx
```

### 处理步骤

```
1. AuthMiddleware 提取 Bearer token
   └→ request.state.user_id / role / api_key_prefix
   
2. FastAPI Depends 注入
   ├→ get_identity(request)     → Identity(user_id, role)
   ├→ get_session_service(req)  → SessionService (app.state)
   └→ get_multi_agent_service(req) → MultiAgentService (app.state)

3. 会话管理
   ├─ session_id 已传 → 验证存在 + 所有权
   └─ session_id 为空 → 调用 session_service.create_session() 创建新会话
                          标题 = query[:50]

4. 构建 SSE 生成器 event_generator()
   ├─ yield { event: "start", data: {session_id} }
   ├─ async for event in multi_agent_service.chat_stream(...):
   │     yield { event: event.event, data: JSON(event.data) }
   ├─ yield { event: "error", ... }   (异常时)
   └─ yield { event: "done", data: {session_id} }

5. 返回 EventSourceResponse(event_generator())
   后台任务: session_service.bump_message_count(session_id)
```

---

## 二、服务层 — MultiAgentService

**文件:** `src/server/services/multi_agent_service.py`

### chat_stream()

```
chat_stream(user_id, session_id, query)
│
├─ _get_or_create_agent(user_id)
│   └→ MainAgent 缓存: dict[str, MainAgent]
│       ├─ 命中 → 返回已有实例
│       └─ 未命中 → MainAgent(name="orchestrator-{user_id[:8]}", registry=...)
│                    → agent.initialize()  ← 触发 _setup()
│                    → 存入缓存
│
├─ tid = f"{user_id}:{session_id}"   ← LangGraph thread_id
│
└─ async for event in agent.arun_stream(query, thread_id=tid):
      yield event
```

**initialize() → _setup()** 做了 4 件事：

```
1. get_model()              → LangChain ChatModel
2. ToolRegistry()           → 注册 L1 通用 tools
3. MemorySaver/InMemoryStore → LangGraph Checkpointer (对话记忆)
4. _build_graph()           → 编译 LangGraph 状态图
```

---

## 三、编排引擎 — MainAgent

**文件:** `src/agents/multi_agent/main_agent.py`

### LangGraph 状态图

```
                        ┌─────────┐
                        │ analyze │  ← 入口
                        └────┬────┘
                             │
                    after_analyze(state)
                     /              \
            needs_subagents=False   needs_subagents=True
                   │                      │
                   ▼                      ▼
            ┌─────────┐            ┌──────────┐
            │ respond │            │   plan   │
            └────┬────┘            └────┬─────┘
                 │                      │
                 │                      ▼
                 │               ┌───────────┐
                 │               │  execute  │ ← 循环入口
                 │               └─────┬─────┘
                 │                     │
                 │           after_execute(state)
                 │          /        │         \
                 │    还有步骤    全部完成    有失败
                 │         │        │         │
                 │         ▼        ▼         ▼
                 │    ┌──────┐ ┌─────────┐ ┌────────┐
                 │    │execute│ │synthesize│ │replan │
                 │    │(循环) │ └────┬─────┘ └───┬────┘
                 │    └──────┘      │           │
                 │                  ▼           │
                 │                END     ┌─────┘
                 │                        │
                 ▼                        ▼
               END                back to plan
```

### 5 个图节点详解

#### 3.1 analyze_node — 任务分析

```
输入: state.user_task

1. 构建 Prompt
   ├─ analyze_user_task(user_task, subagent_list)
   │   注入 L2 task_analyzer 模板 + SubAgentRegistry.build_selection_prompt()
   └─ 列出所有可用 subagent 的能力描述

2. 调用 LLM
   model.with_structured_output(TaskAnalysisOutput)
   └→ 结构化输出: { needs_subagents, task_summary, complexity, suggested_subagents, reason }

3. 返回 state 更新
   ├─ needs_subagents: bool
   ├─ task_summary:    str     "这是一项复杂的数据分析任务，需要..."
   ├─ iteration_count: 0
   └─ messages:         [AIMessage("任务分析: ... (复杂度: complex)")]
```

**LLM 输出示例:**
```json
{
  "needs_subagents": true,
  "task_summary": "用户需要分析销售数据并生成报告，涉及数据查询、统计分析和报告生成三个环节",
  "complexity": "complex",
  "suggested_subagents": ["data_analyst", "report_generator"],
  "reason": "任务跨越数据查询和报告生成两个专业领域，需要子智能体协作"
}
```

#### 3.2 after_analyze — 路由判断

```
if state.needs_subagents == False → "respond"   (简单任务直接回答)
if state.needs_subagents == True  → "plan"      (复杂任务进入规划)
```

#### 3.3 plan_node — 生成执行计划

```
输入: state.user_task + state.task_summary

1. 构建 subagent 选择上下文
   └→ SubAgentRegistry.build_selection_prompt()
       格式化: "1. **data_analyst** (数据分析助手): 擅长SQL查询... [能力: sql, statistics]"

2. 调用 LLM
   model.with_structured_output(SubagentMatchOutput)
   └→ 结构化输出: { plan: [PlanStep...], overall_strategy }

3. 返回 state 更新
   ├─ plan: [
   │     {step_id:1, description:"查询上月销售数据",     subagent_type:"data_analyst",    depends_on:[]},
   │     {step_id:2, description:"计算同比增长率",       subagent_type:"data_analyst",    depends_on:[1]},
   │     {step_id:3, description:"生成分析报告",         subagent_type:"report_generator", depends_on:[1,2]},
   │   ]
   ├─ current_step_index: 0
   ├─ subagent_results:   {}
   └─ subagent_statuses:  {}
```

#### 3.4 execute_node — 逐步骤调度

```
循环: 每次调用执行 plan[current_step_index]

1. 取出当前步骤
   step = plan[step_idx]   → {step_id, description, subagent_type, ...}

2. 分支处理:
   
   subagent_type == None (无需子智能体)
   ├─ 构建 Prompt: "请完成以下任务步骤: {step.description}"
   ├─ model.invoke(messages)
   └─ results[step_id] = AIMessage.content
   
   subagent_type != None (需要子智能体)
   ├─ sub = _get_or_create_subagent(subagent_type)
   │   ├─ 查 SubAgentRegistry.get(type) → SubAgentMeta
   │   ├─ meta.factory() → SubAgent 实例
   │   └─ sub.initialize() → 触发 SubAgent._setup()
   │
   ├─ context = _build_context_for_step(step, all_results)
   │   └→ 注入 depends_on 中前置步骤的执行结果
   │
   ├─ delegation_task = step.description + context
   └─ result = sub.run(delegation_task, context=context)
       └→ 进入 SubAgent 执行路径 (见第四节)

3. 返回 state 更新
   ├─ subagent_results:   {..., "1": "查询结果: 上月销售总额 500万..."}
   ├─ subagent_statuses:  {..., "1": "success"}
   └─ current_step_index: step_idx + 1
```

#### 3.5 after_execute — 执行后路由

```
1. 检查是否有失败步骤
   has_failed = any(status == "failed")
   ├─ 有失败 + iteration < max_replans(2) → "replan"
   └─ 达到最大重规划次数 → 继续执行

2. 还有未执行步骤 → "execute" (循环)

3. 全部完成 → "synthesize"
```

#### 3.6 synthesize_node — 综合结果

```
输入: state.user_task + state.subagent_results

1. 格式化所有步骤结果
   └→ "### 步骤 1: 查询上月销售数据 [subagent: data_analyst] [状态: success]\n{result1}"

2. 调用 aggregate_results(user_task, result_text)
   注入 L2 result_aggregator 模板

3. 调用 LLM
   model.with_structured_output(AggregationOutput)
   └→ 结构化输出: { answer, sources, confidence, missing_info }

4. 返回: { synthesized_answer: "根据分析，上月销售总额为500万..." }
```

#### 3.7 replan_node — 失败重规划

```
输入: state (含失败步骤信息)

1. 构建 adjust_plan prompt
   ├─ original_plan: 原始计划
   ├─ completed_steps: 已完成步骤
   ├─ failed_step: 失败步骤 + 错误信息
   └─ 调整选项: retry / replace / skip / degrade

2. 调用 LLM
   model.with_structured_output(AdjustedPlanOutput)
   └→ 返回调整后的剩余步骤

3. 返回: { plan: new_plan, current_step_index: 0, iteration_count: +1 }
   路由: → back to plan_node
```

---

## 四、执行引擎 — SubAgent

**文件:** `src/agents/multi_agent/sub_agent.py`

MainAgent 通过 `sub.run(delegation_task, context=context)` 调用。

### LangGraph 状态图

```
          ┌──────────┐
          │   plan   │ ← 入口
          └────┬─────┘
               │
               ▼
          ┌──────────┐
     ┌───→│  agent   │ ← LLM 决策: 输出文本 or 调用工具
     │    └────┬─────┘
     │         │
     │   should_continue?
     │    /           \
     │  "tools"    "advance_step"
     │    │              │
     │    ▼              ▼
     │ ┌───────┐   ┌───────────┐
     │ │ tools │   │ evaluate  │
     │ └───┬───┘   └─────┬─────┘
     │     │              │
     │     └──→ agent ────┘
     │              after_evaluate
     │              /           \
     │      needs_revision     !needs_revision
     │         (back to plan)  (continue)
     │              │              │
     └──────────────┘              ▼
                            ┌──────────┐
                            │  report  │
                            └────┬─────┘
                                 │
                                 ▼
                                END
```

### 4 个图节点详解

#### 4.1 plan_node — 任务分解

```
输入: state.assigned_task  (MainAgent 分配的任务)

1. 构建 Prompt
   ├─ decompose_task(assigned_task, subagent_type, capabilities, available_tools, context)
   └─ 注入 L3 task_decomposer 模板 + L1/L4 可用工具列表

2. 调用 LLM
   model.with_structured_output(DecompositionOutput)
   └→ 结构化输出: { sub_plan: [SubStep...], strategy }

3. 返回:
   sub_plan = [
     {step_id:1, description:"连接数据库",     tool_hint:"sql_connect"},
     {step_id:2, description:"查询上月销售记录", tool_hint:"sql_query"},
     {step_id:3, description:"按地区分组汇总",   tool_hint:"sql_aggregate"},
   ]
```

#### 4.2 agent_node + tools_node — ReAct 循环

```
agent_node (LLM 决策):
  ├─ 注入当前步骤指令: "## 当前执行步骤 (2/3)\n查询上月销售记录\n请使用可用工具完成此步骤。"
  ├─ model_with_tools.invoke(messages)
  │   └→ 模型绑定 L1 + L4 tools (bind_tools)
  └─ 返回 AIMessage
       ├─ 有 tool_calls → 下一步: "tools"
       └─ 无 tool_calls → 下一步: "advance_step"

tools_node (工具执行):
  ├─ ToolNode(tools).invoke(messages)
  │   └→ 提取 AIMessage.tool_calls → 执行对应函数 → 返回 ToolMessage
  └─ 循环回 agent_node
```

#### 4.3 evaluate_node — 自评

```
输入: state (含所有步骤结果)

1. 构建 evaluate_result prompt
   ├─ assigned_task
   ├─ plan_summary: 所有子步骤描述
   └─ execution_results: 所有步骤的文本结果

2. 调用 LLM
   model.with_structured_output(EvaluationOutput)
   └→ { needs_revision, completeness, accuracy, feedback, ready_for_main_agent }

3. 路由 after_evaluate:
   ├─ needs_revision=True + iteration < 3 → "plan" (重新规划)
   └─ 否则 → "report"
```

#### 4.4 report_node — 格式化返回

```
输入: state.step_results

1. 拼接所有步骤结果:
   "## 步骤 1\n查询结果: ...\n\n## 步骤 2\n汇总结果: ..."

2. 返回: { final_result: "..." }
   └→ 这个结果会被 MainAgent.execute_node 收集到 subagent_results
```

---

## 五、全链路数据流总览

```
时间线 ──────────────────────────────────────────────────────────→

SSE Event:   start    analyzing   analysis_done    plan_created
              │         │            │                 │
MainAgent:  entry → analyze_node → after_analyze → plan_node
                                       │ (needs_subagents=true)
                                       │
                                       ▼
                              SubAgentRegistry.build_selection_prompt()
                              model.with_structured_output(TaskAnalysisOutput)
                              model.with_structured_output(SubagentMatchOutput)

────────────────────────────────────────────────────────────────────

SSE Event:  dispatching  subagent_start  subagent_plan  token  tool_call  subagent_done
              │               │              │           │        │            │
MainAgent: execute_node ──→ sub.run() ──→ SubAgent 独立执行 ──────────────→ 收集结果
              │                                                               │
              │    SubAgent 内部:                                              │
              │    plan_node → agent_node → tools_node → evaluate → report    │
              │    (model.bind_tools(L1+L4) → ReAct循环)                       │
              │                                                               │
              └──→ after_execute → (还有步骤?) → execute_node (循环) ←────────┘

────────────────────────────────────────────────────────────────────

SSE Event:  synthesizing   synthesis_done   token   done
              │                │              │       │
MainAgent: synthesize_node ──→               │       │
              │                              │       │
              │  aggregate_results()         │       │
              │  model.with_structured_output(AggregationOutput)
              │                              │       │
              └──────────────────────────────┘       │
                                                     │
                  最终回答: "根据分析，上月销售..." ←──┘
```

---

## 六、关键数据结构

### MainAgentState (LangGraph 状态)

| 字段 | 类型 | 来源 | 说明 |
|------|------|------|------|
| `messages` | `Annotated[list[BaseMessage], add_messages]` | 初始 + 各节点追加 | checkpointer 持久化 |
| `user_task` | `str` | 初始注入 | 用户原始输入 |
| `needs_subagents` | `bool` | analyze_node | 路由信号 |
| `task_summary` | `str` | analyze_node | LLM 分析结果 |
| `plan` | `list[dict]` | plan_node | 执行计划 [{step_id, description, subagent_type, depends_on}] |
| `current_step_index` | `int` | execute_node | 当前步骤指针 |
| `subagent_results` | `dict[str,str]` | execute_node | {step_id → result_text} |
| `subagent_statuses` | `dict[str,str]` | execute_node | {step_id → success/failed} |
| `synthesized_answer` | `str` | synthesize_node | 最终回答 |
| `iteration_count` | `int` | 各节点递增 | 防死循环 |

### SubAgentState (LangGraph 状态)

| 字段 | 类型 | 来源 | 说明 |
|------|------|------|------|
| `messages` | `Annotated[list[BaseMessage], add_messages]` | ReAct 循环累积 | checkpointer 持久化 |
| `assigned_task` | `str` | 初始注入 | MainAgent 分配的任务 |
| `subagent_type` | `str` | 初始注入 | 类型标识 |
| `sub_plan` | `list[dict]` | plan_node | 子步骤 [{step_id, description, tool_hint}] |
| `current_step_index` | `int` | execute 中 | 当前子步骤指针 |
| `step_results` | `dict[str,str]` | execute 中 | {step_id → output} |
| `final_result` | `str` | report_node | 返回给 MainAgent |
| `self_evaluation` | `str` | evaluate_node | 自评反馈 |
| `needs_revision` | `bool` | evaluate_node | 路由信号 |

---

## 七、工具调用链

```
MainAgent._setup()
  └─ ToolRegistry
       └─ L1: GENERAL_TOOLS [get_current_time]
       (L2 规划 tools 作为 graph node 内部 prompt 函数，不注册为 tool)

SubAgent._setup()
  └─ ToolRegistry (独立实例，完全隔离)
       ├─ L1: GENERAL_TOOLS [get_current_time]
       ├─ L3: 单智能体规划 (在 graph node 内部使用)
       └─ L4: 本 subagent 专属 API tools [sql_query, chart_data, ...]
            └─ 通过 bind_tools() 绑定到 model，在 ReAct 循环中由 LLM 决定调用
```
