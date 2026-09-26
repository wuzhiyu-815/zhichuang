"""项目级任务状态和 Agent/Skill 调用记录。"""

import copy
import time


def 初始化任务状态(项目):
    项目.setdefault("协同状态", {
        "当前阶段": "未开始",
        "当前智能体": "",
        "下一步动作": "",
        "状态": "等待中",
        "更新时间": time.time(),
    })
    项目.setdefault("智能体通信记录", [])
    项目.setdefault("技能调用记录", [])
    项目.setdefault("智能体决策记录", [])
    return 项目


def 更新任务状态(项目, 阶段=None, 智能体=None, 下一步=None, 状态=None):
    初始化任务状态(项目)
    状态对象 = 项目["协同状态"]
    if 阶段 is not None:
        状态对象["当前阶段"] = 阶段
    if 智能体 is not None:
        状态对象["当前智能体"] = 智能体
    if 下一步 is not None:
        状态对象["下一步动作"] = 下一步
    if 状态 is not None:
        状态对象["状态"] = 状态
    状态对象["更新时间"] = time.time()
    return 状态对象


def 记录消息(项目, 消息):
    初始化任务状态(项目)
    项目["智能体通信记录"].append(copy.deepcopy(消息))
    return 消息


def 记录技能调用(项目, 智能体, 技能, 输入=None, 输出=None, 成功=True, 错误=None):
    初始化任务状态(项目)
    记录 = {
        "时间": time.time(),
        "智能体": 智能体,
        "技能": 技能,
        "输入": copy.deepcopy(输入 or {}),
        "输出": copy.deepcopy(输出 or {}),
        "成功": bool(成功),
        "错误": 错误,
    }
    项目["技能调用记录"].append(记录)
    return 记录
