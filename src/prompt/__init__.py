"""集中管理 Agent 使用的提示词。"""

from .multi_agent import (
    MAIN_AGENT_SYSTEM_PROMPT,
    SUBAGENT_SYSTEM_PROMPT,
    build_delegation_task_prompt,
    build_direct_response_prompt,
    build_direct_step_prompt,
    build_subagent_step_prompt,
)
from .remote_sensing import (
    REMOTE_SENSING_CAPABILITIES,
    REMOTE_SENSING_DESCRIPTION,
)
from .chat import DEFAULT_SYSTEM_PROMPT

__all__ = [
    "MAIN_AGENT_SYSTEM_PROMPT",
    "SUBAGENT_SYSTEM_PROMPT",
    "REMOTE_SENSING_CAPABILITIES",
    "REMOTE_SENSING_DESCRIPTION",
    "DEFAULT_SYSTEM_PROMPT",
    "build_delegation_task_prompt",
    "build_direct_response_prompt",
    "build_direct_step_prompt",
    "build_subagent_step_prompt",
]
