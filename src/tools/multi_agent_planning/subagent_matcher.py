"""
===========================================================================
L2: subagent_matcher — 匹配任务到最佳 subagent
===========================================================================

MainAgent.plan 节点使用。
将分析结果转化为具体的 subagent 选择 + 执行计划。
===========================================================================
"""

from pydantic import BaseModel, Field


# ═══════════════════════════════════════════════════════════════════════
# Prompt 模板
# ═══════════════════════════════════════════════════════════════════════

MATCH_SUBAGENT_PROMPT = """你是一位 AI 任务规划专家。根据用户任务和可用的子智能体列表，生成一份详细的执行计划。

{subagent_context}

## 用户任务
{user_task}

## 任务分析摘要
{task_summary}

## 计划生成规则
1. 每个计划步骤应明确指定由哪个 subagent 执行 (subagent_type)
2. 不需要子智能体的步骤 (如: 最终综合回复、简单计算查询), subagent_type 留空
3. 步骤间可以有依赖关系 (depends_on 字段)
4. 每个步骤的 description 应该是清晰、可独立执行的任务描述
5. 按照逻辑顺序排列步骤

请生成执行计划。"""


# ═══════════════════════════════════════════════════════════════════════
# 结构化输出模型
# ═══════════════════════════════════════════════════════════════════════

class PlanStepOutput(BaseModel):
    """单个计划步骤 (LLM 输出的格式)"""
    step_id: int = Field(description="步骤序号, 从 1 开始")
    description: str = Field(description="该步骤的详细任务描述")
    subagent_type: str | None = Field(
        default=None,
        description="分配给哪个 subagent 类型 (不需要子智能体则留空)",
    )
    input_summary: str = Field(
        default="",
        description="传递给 subagent 的输入摘要",
    )
    depends_on: list[int] = Field(
        default_factory=list,
        description="依赖的前置步骤 ID 列表",
    )


class SubagentMatchOutput(BaseModel):
    """subagent 匹配 + 计划的完整输出"""
    plan: list[PlanStepOutput] = Field(
        description="执行计划步骤列表",
    )
    overall_strategy: str = Field(
        description="整体执行策略说明 (1-2 句话)",
    )


# ═══════════════════════════════════════════════════════════════════════
# 辅助函数
# ═══════════════════════════════════════════════════════════════════════

def build_selection_context(subagent_descriptions: list[str]) -> str:
    """构建 subagent 选择上下文 (纯文本列表)"""
    if not subagent_descriptions:
        return "## 可用的子智能体\n（无）"
    return "## 可用的子智能体\n" + "\n".join(subagent_descriptions)


def match_subagents(
    user_task: str,
    task_summary: str,
    subagent_context: str,
) -> str:
    """构建 subagent_matcher 的完整 prompt"""
    return MATCH_SUBAGENT_PROMPT.format(
        subagent_context=subagent_context,
        user_task=user_task,
        task_summary=task_summary,
    )
