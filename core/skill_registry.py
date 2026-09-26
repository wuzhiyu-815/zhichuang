"""技能注册表：让智能体通过名称调用能力。"""

from .skill_result import 技能结果


class 技能注册表:
    def __init__(self, archive=None):
        self._技能 = {}
        self.archive = archive

    def 注册(self, 名称, 技能):
        if not 名称 or not callable(技能):
            raise ValueError("技能名称和技能函数不能为空")
        self._技能[str(名称)] = 技能

    def 获取(self, 名称):
        return self._技能.get(str(名称))

    def 是否注册(self, 名称):
        return self.获取(名称) is not None

    def 调用(self, 名称, 上下文=None, 参数=None):
        handle = self.archive.safely('start', 名称, 上下文, 参数) if self.archive else None
        技能 = self.获取(名称)
        try:
            if not 技能:
                result = 技能结果(False, 错误=f"未注册技能：{名称}")
            else:
                结果 = 技能(上下文, 参数 or {})
                result = 结果 if isinstance(结果, 技能结果) else 技能结果(True, 数据=结果)
        except Exception as 异常:
            result = 技能结果(False, 错误=str(异常))
        if self.archive:
            self.archive.safely('finish', handle, result)
        return result

    def 列表(self):
        return sorted(self._技能.keys())
