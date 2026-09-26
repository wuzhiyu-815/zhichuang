"""负责剧本、角色、场景、道具和分镜结构。"""

import copy

from core.agent_base import 智能体基类
from core.skill_result import 技能结果


class 剧本智能体实例(智能体基类):
    名称 = "剧本智能体"
    阶段 = "剧本"
    说明 = "把故事创意转换为结构化短剧剧本，并检查剧本结构。"
    技能清单 = ("解析故事创意", "检查镜头数量", "检查角色引用", "检查剧情节奏", "检查镜头服装", "修复剧本 JSON")

    def 执行(self, 项目, 技能注册表, 参数=None):
        参数 = dict(参数 or {})
        import app
        project = app.load_project(项目.get("id", "")) or 项目
        idea = str(参数.get("idea") or project.get("idea") or "").strip()
        if not idea:
            return 技能结果(False, 错误="缺少故事创意")
        imported_script = bool(project.get("full_script_import"))

        progress = 参数.get("progress_callback")
        def report(done, phase):
            if callable(progress):
                progress({"done": done, "total": 7, "phase": phase})

        def call(name, values):
            return self.调用技能(技能注册表, project, name, values)

        report(0, "AI 正在撰写剧本，等待模型返回")
        result = call("解析故事创意", {
            "idea": idea,
            "series_ctx": project.get("series"),
            "full_script_import": imported_script,
        })
        max_retries = max(0, min(int(参数.get("最大重试次数", 2) or 0), 2))
        attempts = 0
        problems = []
        checks = {}
        script = {}
        while attempts <= max_retries:
            if result.成功:
                script = copy.deepcopy((result.数据 or {}).get("script") or {})
                completed = 1
                for name, values in (
                    ("检查镜头数量", {"script": script, "expected": 参数.get("镜头数量")}),
                    ("检查角色引用", {"script": script}),
                    ("检查剧情节奏", {"script": script}),
                    ("检查镜头服装", {"script": script}),
                ):
                    report(completed, name)
                    check = call(name, values)
                    checks[name] = check.数据 if check.成功 else {"通过": False, "问题": [check.错误]}
                    completed += 1
                problems = []
                for value in checks.values():
                    problems.extend(value.get("问题") or [])
                if script.get("title") and script.get("shots") and not problems:
                    break
                if not script.get("title"):
                    problems.append("缺少title")
            else:
                problems = [result.错误 or "剧本生成失败"]
            if attempts >= max_retries:
                self.记录决策(project, "剧本生成失败", "；".join(dict.fromkeys(problems)), attempts + 1, checks, "失败")
                app.save_project(project)
                return 技能结果(False, 错误="；".join(dict.fromkeys(problems)), 数据={"attempts": attempts + 1, "checks": checks})
            attempts += 1
            self.记录决策(project, "修复剧本", "；".join(dict.fromkeys(problems)), attempts, checks)
            app.save_project(project)
            report(0, f"第 {attempts} 次修复剧本，等待模型返回")
            result = call("修复剧本 JSON", {
                "idea": idea,
                "script": script,
                "problems": list(dict.fromkeys(problems)),
                "series_ctx": project.get("series"),
                "full_script_import": imported_script,
            })

        report(5, "整理并保存剧本")
        script = self._规范化剧本(script)
        project["script"] = script
        project["title"] = script.get("title") or "未命名短剧"
        project["script_confirmed"] = bool(参数.get("自动确认", project.get("script_confirmed", False)))
        project.setdefault("script_review", {})["agent_checked"] = True
        self.记录决策(project, "接受剧本", "通过结构和引用检查", attempts + 1, checks, "已完成")
        app.save_project(project)
        report(6, "检查角色、场景和连续性")
        return 技能结果(True, 数据={"script": script, "attempts": attempts + 1, "checks": checks})

    def _规范化剧本(self, script):
        import app
        script = copy.deepcopy(script or {})
        shots = script.get("shots") or []
        for index, shot in enumerate(shots, start=1):
            shot["index"] = index
            try:
                duration = int(shot.get("duration", 8))
            except (TypeError, ValueError):
                duration = 8
            shot["duration"] = max(8, min(duration, 15))
            shot["action"] = app.filter_slow_motion(str(shot.get("action") or "").strip())
            shot["camera"] = app.filter_slow_motion(str(shot.get("camera") or "固定中景").strip())
            shot["wardrobe"] = str(shot.get("wardrobe") or "").strip()
            shot["characters"] = [str(value).strip() for value in shot.get("characters") or [] if str(value).strip()]
            shot["props"] = [str(value).strip() for value in shot.get("props") or [] if str(value).strip()]
        script["shots"] = shots
        script.setdefault("characters", [])
        script.setdefault("scenes", [])
        script.setdefault("props", [])
        return script


剧本智能体 = 剧本智能体实例()
