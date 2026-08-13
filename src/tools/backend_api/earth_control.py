"""遥感中心使用的球体展示与交互工具。"""

import json

from langchain_core.tools import tool


@tool
def earth_move(target: str, lon: float, lat: float) -> str:
    """生成移动地球视角的请求体。

    Args:
        target: 目标地点中文名称，例如“合肥”。
        lon: 目标地点的 WGS84 经度，范围 -180 到 180。
        lat: 目标地点的 WGS84 纬度，范围 -90 到 90。

    Returns:
        供前端消费的 EARTH_MOVE 请求体 JSON 字符串。
    """
    return json.dumps(
        {
            "type": "EARTH_MOVE",
            "params": {
                "target": target,
                "lon": lon,
                "lat": lat,
            },
        },
        ensure_ascii=False,
    )


REMOTE_SENSING_TOOLS = [earth_move]

REMOTE_SENSING_TOOLS_META= {
    "earth_move": {
        "category": "earth_control",
        "tags": ["视角移动", "定位", "观察"],
        "version": "0.1.0",
    },
}

__all__ = ["earth_move", "REMOTE_SENSING_TOOLS","REMOTE_SENSING_TOOLS_META"]
