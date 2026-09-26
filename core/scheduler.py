"""多 Agent 协同调度器。"""

from .task_state import 初始化任务状态, 更新任务状态


class 协同调度器:
    def __init__(self, 技能注册表):
        self.技能注册表 = 技能注册表
        self._智能体 = {}

    def 注册智能体(self, 智能体):
        配置 = 智能体.配置() if hasattr(智能体, "配置") else {}
        if 配置.get("启用", True):
            self._智能体[智能体.名称] = 智能体
        return 配置

    def 获取智能体(self, 名称):
        return self._智能体.get(名称)

    def 列表(self):
        return [self.诊断(名称) for 名称 in self._智能体]

    def 诊断(self, 名称):
        智能体 = self.获取智能体(名称)
        if not 智能体:
            return {"名称": 名称, "状态": "未注册", "启用": False}
        描述 = 智能体.描述()
        依赖技能 = 描述.get("技能清单") or []
        缺失技能 = [
            技能 for 技能 in 依赖技能
            if not self.技能注册表.是否注册(技能)
        ]
        占位执行 = not 描述.get("真实接入", False)
        if not 描述.get("启用", True):
            状态 = "已禁用"
        elif 缺失技能:
            状态 = "技能待迁移"
        elif 占位执行:
            状态 = "接口已建"
        else:
            状态 = "已接入"
        描述["状态"] = 状态
        描述["缺失技能"] = 缺失技能
        描述["配置完整"] = not 描述.get("配置错误") and not 缺失技能
        return 描述

    def 执行(self, 名称, 项目, 参数=None):
        初始化任务状态(项目)
        智能体 = self.获取智能体(名称)
        if not 智能体:
            更新任务状态(项目, 状态="失败")
            return {"成功": False, "错误": f"未注册智能体：{名称}"}
        配置 = 智能体.配置() if hasattr(智能体, "配置") else {}
        结果 = 智能体.执行(项目, self.技能注册表, 参数 or {})
        返回 = 结果.转字典() if hasattr(结果, "转字典") else {"成功": True, "数据": 结果}
        返回["智能体"] = 智能体.名称
        返回["配置版本"] = 配置.get("版本", "1.0.0")
        返回["真实接入"] = 配置.get("真实接入", False)
        return 返回
