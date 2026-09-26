"""负责 ComfyUI 节点分发和视频生成。"""

from core.agent_base import 智能体基类
from core.skill_result import 技能结果


class 渲染智能体实例(智能体基类):
    名称 = "渲染智能体"
    阶段 = "渲染"
    说明 = "把单镜头任务分发到 ComfyUI 节点池，生成并保存视频。"
    技能清单 = ("渲染单镜",)

    def 执行(self, 项目, 技能注册表, 参数=None):
        参数 = dict(参数 or {})
        try:
            index = int(参数.get("index", 参数.get("镜头编号", 0)))
        except (TypeError, ValueError):
            return 技能结果(False, 错误="缺少有效的镜头编号")
        if index < 1:
            return 技能结果(False, 错误="镜头编号必须大于 0")

        参数["index"] = index
        结果 = self.调用技能(技能注册表, 项目, "渲染单镜", 参数)
        if not 结果.成功:
            return 结果
        数据 = 结果.数据 if isinstance(结果.数据, dict) else {}
        if not 数据.get("video_url"):
            return 技能结果(
                False,
                错误="渲染函数返回成功，但没有视频地址",
                数据=数据,
            )
        return 技能结果(True, 数据=数据)


渲染智能体 = 渲染智能体实例()
