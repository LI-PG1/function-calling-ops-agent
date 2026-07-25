"""工具 JSON Schema 注册表（MCP 风格：名称 + 描述 + 入参约束）。

v0.2：出行服务编排工具集（15 个）——共用 4 / 车主 8 / Robotaxi 3。
动态装载：按路由身份（owner / robotaxi）过滤后传给模型。
"""

from __future__ import annotations

# ---------- 共用（4）----------
SHARED = [
    {
        "type": "function",
        "function": {
            "name": "get_vehicle_status",
            "description": "获取车辆当前状态：位置、电量、行驶态、速度、车门、安全带、乘员、空调、目的地。",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "assess_risk",
            "description": "对场景做安全风险评估（规则库匹配），返回风险等级、处置策略与命中规则。",
            "parameters": {
                "type": "object",
                "properties": {
                    "situation": {
                        "type": "string",
                        "description": "需要评估的情形描述（如：用户在高速上说困了）",
                    }
                },
                "required": ["situation"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_safety_rules",
            "description": "检索安全规则库（场景处置要点 / 危险动作拦截规则）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "查询内容（场景或行为描述）"},
                    "top_k": {"type": "integer", "description": "返回条数，默认 3"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "escalate_human",
            "description": "转人工客服（生成工单）。当出现严重安全风险、紧急状况或用户明确要求投诉时使用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {"type": "string", "description": "转人工原因"},
                    "priority": {
                        "type": "string",
                        "enum": ["normal", "urgent", "critical"],
                        "description": "优先级",
                    },
                },
                "required": ["reason"],
            },
        },
    },
]

# ---------- 车主模式（8）----------
OWNER = [
    {
        "type": "function",
        "function": {
            "name": "control_climate",
            "description": "控制空调：制冷 cool / 制热 heat / 通风除雾 fan_defrost / 关闭 off；可指定分区 zone 与温度 temp。",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["cool", "heat", "fan_defrost", "off"]},
                    "zone": {"type": "string", "description": "all / front / rear（默认 all）"},
                    "temp": {"type": "integer", "description": "目标温度（摄氏，如 22）"},
                },
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "control_seat",
            "description": "控制座椅：通风 vent / 加热 heat / 按摩 massage / 放平 recline / 恢复 restore；可指定 zone。",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["heat", "vent", "massage", "recline", "restore"],
                    },
                    "zone": {
                        "type": "string",
                        "description": "driver / passenger / rear（默认 driver）",
                    },
                },
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "control_door",
            "description": "控制车门：开 open / 关 close / 上锁 lock / 解锁 unlock；可指定 door（fl/fr/rl/rr）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["open", "close", "lock", "unlock"]},
                    "door": {"type": "string", "description": "fl / fr / rl / rr（默认 fl）"},
                },
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "control_safety",
            "description": "安全装置控制：解开安全带 release_seatbelt / 系上安全带 fasten_seatbelt / 设定巡航速度 set_cruise_speed（value=km/h）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["release_seatbelt", "fasten_seatbelt", "set_cruise_speed"],
                    },
                    "value": {
                        "type": "integer",
                        "description": "仅 set_cruise_speed 使用：巡航速度 km/h",
                    },
                },
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "navigate",
            "description": "设置导航目的地（如服务区、充电站、回家、公司、某地点）。",
            "parameters": {
                "type": "object",
                "properties": {"destination": {"type": "string", "description": "目的地名称"}},
                "required": ["destination"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_parking",
            "description": "查询附近停车场（名称、距离、空位）。",
            "parameters": {
                "type": "object",
                "properties": {"near": {"type": "string", "description": "位置提示（可选）"}},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_charging",
            "description": "查询附近/沿途充电站（名称、距离、是否快充、空闲桩数）。",
            "parameters": {
                "type": "object",
                "properties": {"near": {"type": "string", "description": "位置提示（可选）"}},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "play_media",
            "description": "播放媒体内容（轻音乐 / 提神歌单 / 儿歌等）。注意：疲劳场景下仅作辅助，不能替代休息。",
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "description": "内容类别，如：轻音乐 / 提神 / 儿童",
                    }
                },
                "required": ["category"],
            },
        },
    },
]

# ---------- Robotaxi 模式（3）----------
ROBOTAXI = [
    {
        "type": "function",
        "function": {
            "name": "query_ride_order",
            "description": "查询 Robotaxi 订单（状态、司机、车辆位置、上车点、目的地、预计到达）。不传 order_id 时查当前进行中订单。",
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {"type": "string", "description": "订单号（如 ORD-2101）"}
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "modify_pickup_point",
            "description": "修改订单上车点。仅在订单未进入行程（created/accepted/enroute/arrived）时可用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {"type": "string"},
                    "point": {"type": "string", "description": "新的上车点"},
                },
                "required": ["order_id", "point"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "change_destination",
            "description": "修改订单目的地。订单已完成/已取消时不可修改。",
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {"type": "string"},
                    "destination": {"type": "string", "description": "新的目的地"},
                },
                "required": ["order_id", "destination"],
            },
        },
    },
]

TOOLS = SHARED + OWNER + ROBOTAXI
TOTAL = len(TOOLS)


def tools_for_mode(mode: str) -> list[dict]:
    """按身份模式动态装载工具集。unknown 仅给查询类最小集。"""
    if mode == "robotaxi":
        return SHARED + ROBOTAXI
    if mode == "owner":
        return SHARED + OWNER
    # unknown：最小工具集（不足以执行危险操作，宽表兜底场景）
    return [t for t in SHARED if t["function"]["name"] in ("search_safety_rules", "escalate_human")]


if __name__ == "__main__":
    print(
        "total:",
        TOTAL,
        "| owner:",
        len(tools_for_mode("owner")),
        "| robotaxi:",
        len(tools_for_mode("robotaxi")),
        "| unknown:",
        len(tools_for_mode("unknown")),
    )
