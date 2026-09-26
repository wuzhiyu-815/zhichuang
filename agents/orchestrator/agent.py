"""负责判断项目阶段并向下游 Agent 分派任务。"""

from core.agent_base import 智能体基类
from core.skill_result import 技能结果
from core.task_state import 初始化任务状态, 更新任务状态


class 总控智能体实例(智能体基类):
    名称 = "总控智能体"
    阶段 = "总控"
    说明 = "读取项目状态，决定下一步调用哪个专业智能体。"
    技能清单 = ("读取项目状态", "判断下一步动作", "发送协同任务", "处理失败")

    def 判断下一步(self, 项目):
        初始化任务状态(项目)
        if 项目.get("final"):
            动作, 阶段 = "完成", "合成"
        elif not 项目.get("script"):
            动作, 阶段 = "生成剧本", "剧本"
        elif not 项目.get("script_confirmed", True):
            动作, 阶段 = "等待剧本确认", "剧本"
        elif not 项目.get("分镜检查", {}).get("通过"):
            动作, 阶段 = "检查分镜", "分镜"
        elif not 项目.get("assets_checked"):
            动作, 阶段 = "生成或检查资产", "资产"
        elif 项目.get("custom_assets") and not 项目.get("assets_confirmed"):
            动作, 阶段 = "等待参考图", "资产"
        else:
            镜头 = 项目.get("shots") or []
            if any(镜头.get("review_status") == "待优化" for 镜头 in 镜头):
                动作, 阶段 = "反馈优化", "优化"
            elif any(镜头.get("error") for 镜头 in 镜头):
                动作, 阶段 = "处理失败镜头", "优化"
            elif any(not 镜头.get("video_url") for 镜头 in 镜头):
                动作, 阶段 = "生成提示词或分镜视频", "提示词"
            else:
                动作, 阶段 = "合成成片", "合成"
        更新任务状态(项目, 阶段=阶段, 智能体=self.名称, 下一步=动作, 状态="已规划")
        return {"动作": 动作, "阶段": 阶段}

    def 执行(self, 项目, 技能注册表, 参数=None):
        参数 = dict(参数 or {})
        import app
        project = app.load_project(项目.get("id", "")) or 项目
        state = self.调用技能(技能注册表, project, "读取项目状态", {})
        decision = self.判断下一步(project)
        result = {
            "动作": decision["动作"],
            "阶段": decision["阶段"],
            "状态": state.数据 if state.成功 else {},
        }
        target_map = {
            "生成剧本": ("剧本智能体", {}),
            "检查分镜": ("分镜智能体", {}),
            "生成或检查资产": ("资产智能体", {}),
            "生成提示词或分镜视频": ("提示词智能体", {"index": 参数.get("index", 1)}),
            "反馈优化": ("优化智能体", {
                "index": 参数.get("index", 1),
                "审片": (project.get("reviews") or {}).get(str(参数.get("index", 1)), {}),
                "自动反馈": True,
            }),
            "合成成片": ("合成智能体", {}),
        }
        target = target_map.get(decision["动作"])
        if 参数.get("自动执行") and target:
            target_name, target_params = target
            target_params.update(参数.get("任务参数") or {})
            dispatched = app.协同调度器实例.执行(target_name, project, target_params)
            result["目标智能体"] = target_name
            result["执行结果"] = dispatched
            self.记录决策(
                project,
                "执行下一步" if dispatched.get("成功") else "下一步失败",
                f"{decision['动作']} -> {target_name}",
                1,
                {"result": dispatched},
                "已完成" if dispatched.get("成功") else "失败",
            )
            app.save_project(app.load_project(project.get("id", "")) or project)
        else:
            self.记录决策(project, "规划下一步", f"{decision['动作']} / {decision['阶段']}", 1, result, "已规划")
            app.save_project(project)
        return 技能结果(True, 数据=result)


总控智能体 = 总控智能体实例()
