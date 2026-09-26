"""智能体之间共享的项目上下文。"""

import copy
import time


class 项目上下文:
    """为智能体提供项目状态、运行配置和决策记录。"""

    def __init__(self, 项目=None, 运行配置=None):
        self.项目 = copy.deepcopy(项目 or {})
        self.运行配置 = copy.deepcopy(运行配置 or {})

    @property
    def 项目编号(self):
        return self.项目.get("id", "")

    def 记录智能体决策(self, 智能体, 动作, 原因="", 数据=None):
        记录 = {
            "时间": time.time(),
            "智能体": 智能体,
            "动作": 动作,
            "原因": 原因,
            "数据": copy.deepcopy(数据 or {}),
        }
        self.项目.setdefault("智能体记录", []).append(记录)
        return 记录
