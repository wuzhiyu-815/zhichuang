"""负责检查镜头并合成为最终视频。"""

from core.agent_base import 智能体基类
from core.skill_result import 技能结果


class 合成智能体实例(智能体基类):
    名称 = "合成智能体"
    阶段 = "合成"
    说明 = "检查所有镜头的当前版本并按顺序合成最终视频。"
    技能清单 = ("合成成片",)

    def 执行(self, 项目, 技能注册表, 参数=None):
        参数 = 参数 or {}
        import os
        import app
        project = app.load_project(项目.get("id", "")) or 项目
        expected = len(((project.get("script") or {}).get("shots") or []))
        shots = project.get("shots") or []
        if not expected:
            return 技能结果(False, 错误="项目没有可合成的剧本镜头")
        missing = []
        for index in range(1, expected + 1):
            shot = next((item for item in shots if item.get("index") == index), None)
            path = (shot or {}).get("path") or ""
            if (shot or {}).get("error") or (shot or {}).get('continuity_stale') or (shot or {}).get('reference_video_stale') or not path:
                missing.append(f"镜头{index}")
                continue
            absolute = path if os.path.isabs(path) else os.path.join(app.BASE_DIR, path)
            if not os.path.isfile(absolute) or os.path.getsize(absolute) <= 0:
                missing.append(f"镜头{index}")
        if missing:
            self.记录决策(
                project,
                "合成前置校验失败",
                "缺少有效视频：" + "、".join(missing),
                1,
                {"missing": missing},
                "失败",
            )
            app.save_project(project)
            return 技能结果(False, 错误="合成前缺少有效镜头：" + "、".join(missing))

        事件 = []

        def send(event, payload=None):
            事件.append({
                "event": event,
                "data": dict(payload or {}),
            })

        结果 = self.调用技能(
            技能注册表,
            项目,
            "合成成片",
            {"send": send, "cancel_check": 参数.get("cancel_check")},
        )
        if not 结果.成功:
            return 技能结果(
                False,
                错误=结果.错误 or "合成失败",
                数据={
                    "状态": "失败",
                    "项目编号": 项目.get("id", ""),
                    "事件": 事件,
                },
            )

        最新项目 = app.load_project(项目.get("id", "")) or 项目
        final_url = 最新项目.get("final")
        if not final_url:
            return 技能结果(
                False,
                错误="合成函数返回成功，但项目没有最终视频地址",
                数据={
                    "状态": "失败",
                    "项目编号": 项目.get("id", ""),
                    "事件": 事件,
                },
            )
        self.记录决策(最新项目, "接受成片", "所有镜头通过合成前置校验且最终文件已生成", 1, {"final": final_url}, "已完成")
        app.save_project(最新项目)
        return 技能结果(
            True,
            数据={
                "状态": "已完成",
                "项目编号": 项目.get("id", ""),
                "final": final_url,
                "事件": 事件,
            },
        )


合成智能体 = 合成智能体实例()
