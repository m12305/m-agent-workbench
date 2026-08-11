"""
===========================================================================
L2: delegation_builder — 构建委托指令
===========================================================================

MainAgent.execute 节点的 dispatch_to_subagent 使用。
将计划步骤 + 前置结果转化为 SubAgent 可理解的委托请求。
===========================================================================
"""

from pydantic import BaseModel, Field


# ═══════════════════════════════════════════════════════════════════════
# Prompt 模板
# ═══════════════════════════════════════════════════════════════════════

DELEGATION_PROMPT = """请根据以下信息，构建一份清晰的委托指令给子智能体。

## 当前步骤
步骤 ID: {step_id}
任务描述: {description}
目标子智能体: {subagent_type}

## 前置步骤的上下文
{context}

## 原始用户任务
{user_task}

请构建一份委托指令，包含:
1. 具体要完成的任务
2. 前置步骤提供的相关数据/上下文
3. 期望的输出格式"""


class DelegationOutput(BaseModel):
    """委托指令的结构化输出"""
    task: str = Field(description="分配给 subagent 的完整任务描述")
    context: str = Field(description="来自前置步骤的上下文/数据")
    expected_output: str = Field(description="期望的输出格式说明")


def build_delegation(
    step_id: int,
    description: str,
    subagent_type: str,
    context: str = "",
    user_task: str = "",
) -> str:
    """构建委托指令 prompt"""
    return DELEGATION_PROMPT.format(
        step_id=step_id,
        description=description,
        subagent_type=subagent_type,
        context=context or "（无前置步骤）",
        user_task=user_task,
    )
