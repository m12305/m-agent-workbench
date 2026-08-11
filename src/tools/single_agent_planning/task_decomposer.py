"""
===========================================================================
L3: task_decomposer — 将分配的任务分解为子步骤
===========================================================================

SubAgent.plan 节点使用。
将 MainAgent 分配的单个任务进一步分解为可执行的子步骤。
===========================================================================
"""

from pydantic import BaseModel, Field


# ═══════════════════════════════════════════════════════════════════════
# Prompt 模板
# ═══════════════════════════════════════════════════════════════════════

DECOMPOSE_TASK_PROMPT = """你是一位 AI 任务分解专家。你需要将一个具体的任务分解为有序的执行步骤。

## 你的身份
你是 **{subagent_type}**，擅长: {capabilities}

## 可用的工具
{available_tools}

## 分配给你的任务
{assigned_task}

## 来自前置步骤的上下文
{context}

## 分解规则
1. 每个步骤应该是独立的、可执行的原子操作
2. 优先使用"可用的工具"中列出的工具来完成每个步骤
3. 如果某个步骤需要用到前一步的输出，在 description 中说明依赖关系
4. 步骤数量控制在 2-5 个
5. tool_hint 字段填写预期使用的工具名称 (从可用工具中选)

请分解这个任务。"""


class SubStepOutput(BaseModel):
    """子步骤的结构化输出"""
    step_id: int = Field(description="子步骤序号, 从 1 开始")
    description: str = Field(description="该子步骤的详细描述")
    tool_hint: str | None = Field(
        default=None,
        description="预期使用的工具名称 (从可用工具列表中选择)",
    )


class DecompositionOutput(BaseModel):
    """任务分解的结构化输出"""
    sub_plan: list[SubStepOutput] = Field(
        description="子步骤列表 (2-5 个)",
    )
    strategy: str = Field(
        description="执行策略简述 (1 句话)",
    )


def decompose_task(
    assigned_task: str,
    subagent_type: str = "通用助手",
    capabilities: str = "通用任务处理",
    available_tools: str = "（无特殊工具）",
    context: str = "",
) -> str:
    """构建任务分解 prompt"""
    return DECOMPOSE_TASK_PROMPT.format(
        subagent_type=subagent_type,
        capabilities=capabilities,
        available_tools=available_tools,
        assigned_task=assigned_task,
        context=context or "（无前置上下文）",
    )
