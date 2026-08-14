"""
===========================================================================
L2: task_analyzer — 分析用户任务
===========================================================================

MainAgent.analyze_task 节点使用。
将用户自然语言任务转化为结构化分析结果。
===========================================================================
"""
from typing import Literal

from pydantic import BaseModel, Field
from ...prompt.planning import ANALYZE_TASK_PROMPT


# ═══════════════════════════════════════════════════════════════════════
# Prompt 模板
# ═══════════════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════════════
# 结构化输出模型
# ═══════════════════════════════════════════════════════════════════════

class TaskAnalysisOutput(BaseModel):
    """任务分析的结构化输出"""
    needs_subagents: bool = Field(
        description="是否需要子智能体协作",
    )
    task_summary: str = Field(
        description="对用户任务的结构化摘要 (1-3 句话)",
    )
    complexity: Literal["simple", "medium", "complex"] = Field(
        description="任务复杂度: simple / medium / complex",
    )
    suggested_subagents: list[str] = Field(
        description="建议调用的 subagent 类型列表 (从可用列表中选取)",
    )
    reason: str = Field(
        description="简要说明为什么选择 (或不需要) 子智能体",
    )


# ═══════════════════════════════════════════════════════════════════════
# 辅助函数
# ═══════════════════════════════════════════════════════════════════════

def analyze_user_task(
    user_task: str,
    subagent_list: str = "（无可用子智能体）",
) -> str:
    """构建 task_analyzer 的完整 prompt"""
    return ANALYZE_TASK_PROMPT.format(
        subagent_list=subagent_list,
        user_task=user_task,
    )
