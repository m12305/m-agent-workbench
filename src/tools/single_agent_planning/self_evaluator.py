"""
===========================================================================
L3: self_evaluator — 评估结果质量
===========================================================================

SubAgent.evaluate 节点使用。
对自己执行的结果进行自我评估，判断是否需要修正。
===========================================================================
"""

from pydantic import BaseModel, Field


# ═══════════════════════════════════════════════════════════════════════
# Prompt 模板
# ═══════════════════════════════════════════════════════════════════════

EVALUATE_PROMPT = """你是一位严格的 AI 质量评估专家。请对你的执行结果进行自我评估。

## 原始分配任务
{assigned_task}

## 执行计划
{plan_summary}

## 执行结果
{execution_results}

## 评估维度
1. **完整性**: 是否完全回答了分配的任务？是否有遗漏？
2. **准确性**: 结果是否准确 (基于可用的工具和上下文)？
3. **可操作性**: 结果是否可以直接被主智能体使用？

## 评估标准
- 如果结果完整、准确、可用 → needs_revision=False
- 如果存在明显遗漏或错误 → needs_revision=True, 并在 feedback 中说明问题
- 只需要 1 轮自评，不要过度完美主义

请给出评估。"""


class EvaluationOutput(BaseModel):
    """自评结果的结构化输出"""
    needs_revision: bool = Field(
        description="是否需要修正",
    )
    completeness: str = Field(
        description="完整性评估: complete / partial / incomplete",
    )
    accuracy: str = Field(
        description="准确性评估: accurate / uncertain / inaccurate",
    )
    feedback: str = Field(
        description="具体的改进建议 (如果 needs_revision=True)",
    )
    ready_for_main_agent: bool = Field(
        description="结果是否可以直接返回给主智能体",
    )


def evaluate_result(
    assigned_task: str,
    plan_summary: str,
    execution_results: str,
) -> str:
    """构建自评 prompt"""
    return EVALUATE_PROMPT.format(
        assigned_task=assigned_task,
        plan_summary=plan_summary,
        execution_results=execution_results,
    )
