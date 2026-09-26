"""负责生成和修复视频生成提示词。"""

import copy

from core.agent_base import 智能体基类
from core.skill_result import 技能结果


class 提示词智能体实例(智能体基类):
    名称 = "提示词智能体"
    阶段 = "提示词"
    说明 = "生成 H3 R2V 提示词，维护 Picture 编号、动作时序和台词完整性。"
    技能清单 = ("生成 H3 提示词", "检查台词完整性", "检查动作连续性", "检查角色边界", "检查镜头服装", "修复提示词")

    def 执行(self, 项目, 技能注册表, 参数=None):
        参数 = dict(参数 or {})
        try:
            index = int(参数.get("index", 参数.get("镜头编号", 0)))
        except (TypeError, ValueError):
            return 技能结果(False, 错误="缺少有效的镜头编号")
        if index < 1:
            return 技能结果(False, 错误="镜头编号必须大于 0")

        import app
        project = app.load_project(项目.get("id", "")) or 项目
        from infrastructure.agent_commit import commit
        baseline = copy.deepcopy(project.get('智能体决策记录', []))
        def save_changes(document):
            nonlocal baseline
            latest = commit(app, document, index, baseline, maps=('prompts', 'continuity_prompt_checks', 'prompt_failures'), shot_fields=('prompt', 'error'))
            baseline = copy.deepcopy(document.get('智能体决策记录', []))
            return latest

        script_shots = (project.get("script") or {}).get("shots") or []
        shot = next((item for item in script_shots if item.get("index") == index), None)
        if not shot:
            shot = next((item for item in project.get("shots") or [] if item.get("index") == index), None)
        if not isinstance(shot, dict):
            return 技能结果(False, 错误=f"镜头{index}不存在")
        shot = copy.deepcopy(shot)
        feedback_constraints = str(
            参数.get("修复约束") or 参数.get("审片修复约束") or ""
        ).strip()
        if feedback_constraints:
            shot["action"] = (
                f"{shot.get('action', '')}\n"
                f"【审片反馈修复约束】{feedback_constraints}"
            )
        assets = project.get("assets") or {}
        ref_paths = app.assemble_shot_ref_paths(shot, assets)
        if not ref_paths:
            return 技能结果(False, 错误="没有可用参考图，无法生成提示词")
        _audio_paths, audio_roles = app.assemble_shot_audio_paths(shot, assets)

        def call(name, values):
            return self.调用技能(
                技能注册表,
                project,
                name,
                values,
            )

        wardrobe_check = call("检查镜头服装", {"script": {"shots": [shot]}})
        if not wardrobe_check.成功 or not wardrobe_check.数据.get("通过"):
            return 技能结果(False, 错误="镜头服装未就绪，请先运行分镜服装补全", 数据={"checks": wardrobe_check.数据})

        try:
            max_retries = max(
                0,
                min(int(参数.get("最大重试次数", self.配置().get("最大重试次数", 2))), 3),
            )
        except (TypeError, ValueError):
            max_retries = 2
        result = call("生成 H3 提示词", {
            "shot": shot,
            "ref_paths": ref_paths,
            "audio_roles": audio_roles,
            "feedback_constraints": feedback_constraints,
        })
        attempts = 0
        checks = {}
        prompt = ""
        problems = []
        while attempts <= max_retries:
            if result.成功:
                prompt = (result.数据 or {}).get("prompt", "")
                checks = {}
                for name, values in (
                    ("检查台词完整性", {"shot": shot, "prompt": prompt}),
                    ("检查动作连续性", {"shot": shot, "prompt": prompt}),
                    ("检查角色边界", {"shot": shot, "prompt": prompt, "ref_count": len(ref_paths)}),
                ):
                    check = call(name, values)
                    checks[name] = check.数据 if check.成功 else {"通过": False, "问题": [check.错误]}
                problems = []
                for value in checks.values():
                    if value.get("通过") is False:
                        problems.extend(value.get("问题") or value.get("缺失台词") or value.get("未标记台词") or [])
                        problems.extend(value.get("对白边界问题") or [])
                        problems.extend(value.get("未标记台词") or [])
                        problems.extend(value.get("缺失台词") or [])
                if not problems and prompt:
                    break
            else:
                problems = [result.错误 or "提示词生成失败"]

            if attempts >= max_retries:
                self.记录决策(project, "转失败", "提示词未通过质量门禁", attempts + 1, checks, "失败")
                project.setdefault('prompt_failures', {})[str(index)] = {
                    'prompt': prompt, 'problems': list(dict.fromkeys(problems)),
                    'checks': checks, 'attempts': attempts + 1, 'status': 'needs_edit'}
                save_changes(project)
                return 技能结果(False, 错误=f"镜头{index}提示词质量检查失败（已尝试{attempts + 1}次）：" + ("；".join(dict.fromkeys(problems)) or "请检查台词和角色引用"),
                              数据={"index": index, "attempts": attempts + 1, "checks": checks})
            attempts += 1
            self.记录决策(project, "修复提示词", "；".join(dict.fromkeys(problems)), attempts, checks)
            save_changes(project)
            result = call("修复提示词", {
                "shot": shot,
                "ref_paths": ref_paths,
                "audio_roles": audio_roles,
                "constraints": list(dict.fromkeys(problems)),
            })

        from infrastructure.agent_continuity import enabled, visual_handoff, check_prompt
        continuity_check = None
        if enabled(project) and shot.get("continuity"):
            try:
                from infrastructure.shot_continuity import apply_continuity_intro
                prompt = apply_continuity_intro(shot, prompt)
                frame = visual_handoff(app, project, shot)
                prompt, continuity_check = check_prompt(app, shot, prompt, frame)
                prompt = apply_continuity_intro(shot, prompt)
            except Exception as exc:
                return 技能结果(False, 错误=f"衔接预审失败：{exc}")

        latest = app.load_project(project.get("id", "")) or project
        if continuity_check is not None:
            latest.setdefault("continuity_prompt_checks", {})[str(index)] = continuity_check
        latest.setdefault("prompt_failures", {})[str(index)] = {"status": "resolved"}
        latest.setdefault("prompts", {})[str(index)] = prompt
        target = next((item for item in latest.get("shots") or [] if item.get("index") == index), None)
        if target is not None:
            target["prompt"] = prompt
            target.pop("error", None)
        self.记录决策(latest, "接受提示词", "通过全部质量门禁", attempts + 1, checks, "已完成")
        save_changes(latest)
        return 技能结果(True, 数据={
            "index": index,
            "prompt": prompt,
            "attempts": attempts + 1,
            "checks": checks,
            "ref_count": len(ref_paths),
            "audio_roles": audio_roles,
        })


提示词智能体 = 提示词智能体实例()
