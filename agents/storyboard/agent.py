"""负责把剧本动作拆成可生成的视频镜头。"""

import copy

from core.agent_base import 智能体基类
from core.skill_result import 技能结果


class 分镜智能体实例(智能体基类):
    名称 = "分镜智能体"
    阶段 = "分镜"
    说明 = "检查镜头节奏、动作连续性、时长、景别和资产引用。"
    技能清单 = ("检查镜头连续性", "检查景别机位", "检查资产引用", "检查镜头服装", "补全镜头服装", "调整镜头时长")

    def 执行(self, 项目, 技能注册表, 参数=None):
        参数 = dict(参数 or {})
        import app
        project = app.load_project(项目.get("id", "")) or 项目
        script = copy.deepcopy(project.get("script") or {})
        shots = script.get("shots") or []
        if not shots:
            return 技能结果(False, 错误="剧本中没有可检查的镜头")
        for index, shot in enumerate(shots, start=1):
            shot["index"] = index
            shot["camera"] = str(shot.get("camera") or "固定中景").strip()
            try:
                duration = int(shot.get("duration", 8))
            except (TypeError, ValueError):
                duration = 8
            shot["duration"] = max(8, min(duration, 15))
            shot["action"] = app.filter_slow_motion(str(shot.get("action") or "").strip())
            shot["wardrobe"] = str(shot.get("wardrobe") or "").strip()

        def call(name, values):
            return self.调用技能(技能注册表, project, name, values)

        wardrobe_check = call("检查镜头服装", {"script": script})
        if not wardrobe_check.成功 or not wardrobe_check.数据.get("通过"):
            repaired = call("补全镜头服装", {"script": script})
            if not repaired.成功:
                self.记录决策(project, "服装补全失败", repaired.错误, 状态="失败")
                app.save_project(project)
                return repaired
            script = repaired.数据["script"]
            shots = script["shots"]
            self.记录决策(project, "补全镜头服装", "仅补全缺失或不完整的服装，保留剧情及已有有效着装")

        checks = {}
        problems = []
        for name in ("检查镜头连续性", "检查景别机位", "检查资产引用", "检查镜头服装"):
            check = call(name, {"script": script})
            checks[name] = check.数据 if check.成功 else {"通过": False, "问题": [check.错误]}
            problems.extend(checks[name].get("问题") or [])
        if problems:
            self.记录决策(project, "分镜检查失败", "；".join(dict.fromkeys(problems)), 1, checks, "失败")
            app.save_project(project)
            return 技能结果(False, 错误="；".join(dict.fromkeys(problems)), 数据={"checks": checks})

        from infrastructure.agent_continuity import enabled, plan_script, source_signature, LEGACY_RULES
        if enabled(project):
            try:
                previous_script = copy.deepcopy(script)
                script = plan_script(app, script, project.get("continuity_plan_signature"))
                shots = script["shots"]
                new_signature = source_signature(script)
                def visual_plan(document):
                    document = copy.deepcopy(document)
                    for item in document.get('shots', []):
                        plan = item.get('continuity') or {}
                        plan.pop('handoff_mode', None)
                        plan.pop('reason', None)
                    return document
                metadata_only = (project.get('continuity_plan_signature') == source_signature(previous_script, LEGACY_RULES)
                                 and visual_plan(previous_script) == visual_plan(script))
                if project.get("continuity_plan_signature") != new_signature and not metadata_only:
                    project["prompts"] = {}
                    for rendered in project.get("shots", []):
                        if rendered.get("video_url"):
                            rendered["continuity_stale"] = True
                        else:
                            rendered.pop("prompt", None)
                    for confirmation in project.get("shot_confirm", {}).values():
                        if isinstance(confirmation, dict):
                            confirmation.pop("prompt", None)
                project["continuity_plan_signature"] = new_signature
                self.记录决策(project, "规划镜头交接", "文字状态衔接允许并行；仅实际尾帧依赖保持串行", 检查结果={"镜头数": len(shots)})
            except Exception as exc:
                return 技能结果(False, 错误=str(exc))

        script["shots"] = shots
        project["script"] = script
        if enabled(project):
            from infrastructure.dependency_scheduler import render_groups
            project["render_groups"] = render_groups(shots)
        project["分镜检查"] = {
            "通过": True,
            "镜头数": len(shots),
            "检查时间": __import__("time").time(),
        }
        self.记录决策(project, "接受分镜", "通过连续性、景别、时长和资产引用检查", 1, checks, "已完成")
        app.save_project(project)
        return 技能结果(True, 数据={"shots": shots, "checks": checks, "count": len(shots)})


分镜智能体 = 分镜智能体实例()
