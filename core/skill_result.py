"""所有技能统一使用的结果对象。"""


class 技能结果:
    """封装技能执行结果，避免各模块自行约定返回值格式。"""

    def __init__(self, 成功, 数据=None, 错误=None, 指标=None):
        self.成功 = bool(成功)
        self.数据 = {} if 数据 is None else 数据
        self.错误 = 错误
        self.指标 = {} if 指标 is None else 指标

    def 转字典(self):
        return {
            "成功": self.成功,
            "数据": self.数据,
            "错误": self.错误,
            "指标": self.指标,
        }
