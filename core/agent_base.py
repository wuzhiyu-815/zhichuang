"""所有 Agent 的共同基类。"""

import json
import time
from pathlib import Path

from .messages import 创建消息
from .skill_result import 技能结果
from .task_state import 初始化任务状态, 记录消息, 记录技能调用, 更新任务状态


class 智能体基类:
    名称 = "未命名智能体"
    阶段 = "未定义"
    说明 = ""
    技能清单 = ()
    真实接入 = False

    def 读取配置(self):
        """从当前 Agent 目录读取配置，缺失或损坏时使用安全默认值。"""
        配置路径 = Path(__file__).resolve().parent.parent / "agents" / self.目录名称() / "config.json"
        默认配置 = {
            "名称": self.名称,
            "阶段": self.阶段,
            "启用": True,
            "版本": "1.0.0",
            "协作模式": "请求-响应",
            "输入": [],
            "输出": [],
            "依赖技能": list(self.技能清单),
            "超时秒数": 600,
            "最大重试次数": 1,
            "真实接入": bool(self.真实接入),
        }
        try:
            with 配置路径.open("r", encoding="utf-8") as 文件:
                配置 = json.load(文件)
            if not isinstance(配置, dict):
                raise ValueError("配置必须是对象")
            默认配置.update(配置)
        except Exception as 异常:
            默认配置["配置错误"] = str(异常)
        默认配置["名称"] = str(默认配置.get("名称") or self.名称)
        默认配置["阶段"] = str(默认配置.get("阶段") or self.阶段)
        默认配置["启用"] = bool(默认配置.get("启用", True))
        默认配置["真实接入"] = bool(默认配置.get("真实接入", self.真实接入))
        return 默认配置

    def 目录名称(self):
        """由模块目录推断 Agent 英文目录名，兼容旧版扁平模块。"""
        模块路径 = Path(self.__class__.__module__.replace(".", "/"))
        return 模块路径.parent.name if 模块路径.parent.name != "." else self.名称

    def 配置(self):
        return self.读取配置()

    def 描述(self):
        配置 = self.配置()
        配置技能 = 配置.get("依赖技能") or self.技能清单
        return {
            "名称": self.名称,
            "阶段": self.阶段,
            "说明": self.说明,
            "技能清单": list(配置技能),
            "启用": 配置.get("启用", True),
            "版本": 配置.get("版本", "1.0.0"),
            "协作模式": 配置.get("协作模式", ""),
            "输入": 配置.get("输入", []),
            "输出": 配置.get("输出", []),
            "超时秒数": 配置.get("超时秒数", 600),
            "最大重试次数": 配置.get("最大重试次数", 1),
            "真实接入": 配置.get("真实接入", False),
            "配置错误": 配置.get("配置错误"),
        }

    def 发送(self, 项目, 接收者, 任务类型, 数据=None, 状态="待处理", 镜头编号=None):
        消息 = 创建消息(
            self.名称, 接收者, 任务类型,
            项目编号=项目.get("id", ""), 数据=数据,
            状态=状态, 镜头编号=镜头编号,
        )
        记录消息(项目, 消息)
        return 消息

    def 调用技能(self, 技能注册表, 项目, 技能名称, 参数=None):
        更新任务状态(项目, 阶段=self.阶段, 智能体=self.名称, 状态="执行中")
        实际参数 = 参数 or {}
        记录参数 = {
            key: value
            for key, value in 实际参数.items()
            if not callable(value)
        }
        结果 = 技能注册表.调用(技能名称, 项目, 实际参数)
        记录技能调用(
            项目, self.名称, 技能名称, 记录参数,
            结果.数据, 结果.成功, 结果.错误,
        )
        return 结果

    def 记录决策(self, 项目, 动作, 原因="", 尝试次数=0, 检查结果=None, 状态="执行中"):
        """记录 Agent 的判断和质量门禁结果，而不只记录函数调用。"""
        初始化任务状态(项目)
        记录 = {
            "时间": time.time(),
            "智能体": self.名称,
            "阶段": self.阶段,
            "动作": 动作,
            "原因": 原因,
            "尝试次数": 尝试次数,
            "检查结果": 检查结果 or {},
            "状态": 状态,
        }
        项目["智能体决策记录"].append(记录)
        项目["智能体决策记录"] = 项目["智能体决策记录"][-100:]
        return 记录

    def 执行(self, 项目, 技能注册表, 参数=None):
        return 技能结果(False, 错误=f"{self.名称}尚未实现执行逻辑")
