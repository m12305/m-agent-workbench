"""多智能体系统 — 公开导出

快速开始:
    from agents.multi_agent import (
        MainAgent, SubAgent, SubAgentRegistry, SubAgentMeta,
        create_default_registry,
    )

    registry = create_default_registry()
    main = MainAgent(sub_agent_registry=registry)
    main.initialize()
    answer = main.run("帮我分析数据并生成报告")
"""

from .states import MainAgentState, SubAgentState
from .schemas import (
    PlanStep, SubStep, TaskAnalysis,
    DelegationRequest, SubAgentResult, SynthesisResult,
)
from .events import MultiAgentEvent, EVENT_SCHEMAS
from .sub_agent_registry import SubAgentRegistry, SubAgentMeta
from .sub_agent import SubAgent
from .main_agent import MainAgent


def create_default_registry() -> SubAgentRegistry:
    """创建预置了通用 subagent 类型的注册中心

    用户可以调用 registry.register() 添加更多 subagent 类型。
    """
    registry = SubAgentRegistry()

    # 注册一个通用子智能体 (示例)
    registry.register(SubAgentMeta(
        subagent_type="general_assistant",
        display_name="通用子智能体",
        description="获取当前日期和时间，返回 ISO 格式的时间字符串。",
        capabilities=["get_current_time"],
        factory=lambda: SubAgent(
            name="GeneralAssistant",
            subagent_type="general_assistant",
            description="通用子智能体，获取当前日期和时间，返回 ISO 格式的时间字符串。",
            capabilities=["get_current_time"],
        ),
    ))

    return registry


__all__ = [
    # Agents
    "MainAgent", "SubAgent",
    # States
    "MainAgentState", "SubAgentState",
    # Schemas
    "PlanStep", "SubStep", "TaskAnalysis",
    "DelegationRequest", "SubAgentResult", "SynthesisResult",
    # Events
    "MultiAgentEvent", "EVENT_SCHEMAS",
    # Registry
    "SubAgentRegistry", "SubAgentMeta",
    "create_default_registry",
]
