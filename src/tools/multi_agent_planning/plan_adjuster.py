"""
===========================================================================
L2: plan_adjuster — 失败时重新规划
===========================================================================

MainAgent.replan 节点使用。
当某个 subagent 执行失败时，调整后续计划。
===========================================================================
"""

from pydantic import BaseModel, Field


# ═══════════════════════════════════════════════════════════════════════
# Prompt 模板
# ═══════════════════════════════════════════════════════════════════════

ADJUST_PLAN_PROMPT = """你是一位 AI 容错规划专家。某个子智能体的执行步骤失败了，请调整执行计划。

## 原始用户任务
{user_task}

## 原始计划
{original_plan}

## 已完成的步骤
{completed_steps}

## 失败的步骤
{failed_step}

## 失败原因
{error_info}

## 调整选项
1. **重试**: 如果失败原因是暂时的 (如网络超时)，可以用相同参数重试
2. **替换**: 如果当前 subagent 不适合，选择另一个能力相近的 subagent
3. **跳过**: 如果该步骤对最终结果影响不大，可以跳过
4. **降级**: 用更简单的方式完成该步骤

请给出调整后的计划 (仅包含未完成的步骤)。"""


class AdjustedPlanStep(BaseModel):
    """调整后的计划步骤"""
    step_id: int = Field(description="步骤序号 (延续原始编号)")
    description: str = Field(description="调整后的任务描述")
    subagent_type: str | None = Field(default=None)
    input_summary: str = Field(default="")
    depends_on: list[int] = Field(default_factory=list)
    action: str = Field(description="retry / replace / skip / degrade")


class AdjustedPlanOutput(BaseModel):
    """调整后计划的结构化输出"""
    adjusted_plan: list[AdjustedPlanStep] = Field(description="调整后的剩余步骤")
    strategy: str = Field(description="调整策略说明")


def adjust_plan(
    user_task: str,
    original_plan: str,
    completed_steps: str,
    failed_step: str,
    error_info: str = "",
) -> str:
    """构建计划调整 prompt"""
    return ADJUST_PLAN_PROMPT.format(
        user_task=user_task,
        original_plan=original_plan,
        completed_steps=completed_steps,
        failed_step=failed_step,
        error_info=error_info or "未知错误",
    )
