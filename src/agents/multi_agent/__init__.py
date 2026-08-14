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
from ...prompt import (
    GENERAL_ASSISTANT_CAPABILITIES,
    GENERAL_ASSISTANT_DESCRIPTION,
    REMOTE_SENSING_CAPABILITIES,
    REMOTE_SENSING_DESCRIPTION,
)
from ...tools.backend_api import REMOTE_SENSING_TOOLS, REMOTE_SENSING_TOOLS_META
from ...tools.backend_api.tavily_tools import TAVILY_TOOLS, TAVILY_TOOLS_META

def create_default_registry(
    mcp_tools: list | None = None,
    mcp_tools_meta: dict[str, dict] | None = None,
) -> SubAgentRegistry:
    """创建预置了通用 subagent 类型的注册中心

    用户可以调用 registry.register() 添加更多 subagent 类型。
    mcp_tools/mcp_tools_meta 会注入到所有预置 SubAgent。
    """
    registry = SubAgentRegistry()

    # 注册一个通用子智能体 (示例)
    registry.register(SubAgentMeta(
        subagent_type="general_assistant",
        display_name="通用子智能体",
        description=GENERAL_ASSISTANT_DESCRIPTION,
        capabilities=GENERAL_ASSISTANT_CAPABILITIES,
        factory=lambda: SubAgent(
            name="GeneralAssistant",
            subagent_type="general_assistant",
            description=GENERAL_ASSISTANT_DESCRIPTION,
            capabilities=GENERAL_ASSISTANT_CAPABILITIES,
            api_tools=TAVILY_TOOLS,
            api_tools_meta=TAVILY_TOOLS_META,
            mcp_tools=mcp_tools,
            mcp_tools_meta=mcp_tools_meta,
        ),
    ))

    registry.register(SubAgentMeta(
        subagent_type="remote_sensing",
        display_name="遥感中心",
        description=REMOTE_SENSING_DESCRIPTION,
        capabilities=REMOTE_SENSING_CAPABILITIES,
        factory=lambda: SubAgent(
            name="RemoteSensingCenter",
            subagent_type="remote_sensing",
            description=REMOTE_SENSING_DESCRIPTION,
            capabilities=REMOTE_SENSING_CAPABILITIES,
            api_tools=REMOTE_SENSING_TOOLS,
            api_tools_meta=REMOTE_SENSING_TOOLS_META,
            mcp_tools=mcp_tools,
            mcp_tools_meta=mcp_tools_meta,
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
