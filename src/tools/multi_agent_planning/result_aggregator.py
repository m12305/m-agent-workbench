"""
===========================================================================
L2: result_aggregator — 合并 subagent 结果
===========================================================================

MainAgent.synthesize 节点使用。
收集所有 subagent 返回的结果，综合为最终回答。
===========================================================================
"""

from pydantic import BaseModel, Field


# ═══════════════════════════════════════════════════════════════════════
# Prompt 模板
# ═══════════════════════════════════════════════════════════════════════

AGGREGATE_PROMPT = """你是一位 AI 综合报告专家。请将以下多个子智能体的执行结果综合为一份连贯的最终回答。

## 原始用户任务
{user_task}

## 执行计划与结果
{step_results}

## 综合要求
1. 按用户任务的自然逻辑组织回答
2. 引用各子智能体的关键发现
3. 如果某个步骤失败，如实说明并给出建议
4. 回答风格: 清晰、专业、面向最终用户
5. 标注信息来源 (来自哪个 subagent 类型的哪个步骤)

请综合上述结果，生成最终回答。"""


class AggregationOutput(BaseModel):
    """综合结果的结构化输出"""
    answer: str = Field(description="综合后的最终回答")
    sources: list[str] = Field(
        default_factory=list,
        description="引用的来源 (subagent_type:step_id 列表)",
    )
    confidence: str = Field(
        default="medium",
        description="综合结果的置信度: low / medium / high",
    )
    missing_info: str = Field(
        default="",
        description="未能覆盖的信息或建议的补充步骤",
    )


def aggregate_results(
    user_task: str,
    step_results: str,
) -> str:
    """构建结果聚合 prompt"""
    return AGGREGATE_PROMPT.format(
        user_task=user_task,
        step_results=step_results,
    )
