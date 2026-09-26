"""负责检查生成视频质量。"""

import copy

from core.agent_base import 智能体基类
from core.skill_result import 技能结果


class 审片智能体实例(智能体基类):
    名称 = "审片智能体"
    阶段 = "审片"
    说明 = "通过关键帧和视觉模型检查角色、动作、构图、场景和台词匹配。"
    技能清单 = ("输出审片报告", "检查审片报告", "分类审片问题", "生成修复约束")

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
            latest = commit(app, document, index, baseline, maps=('reviews',), shot_fields=('review_score', 'review_status', 'review_error'))
            baseline = copy.deepcopy(document.get('智能体决策记录', []))
            return latest

        script_shot = next(
            (item for item in ((project.get("script") or {}).get("shots") or [])
             if item.get("index") == index),
            None,
        )
        rendered_shot = next(
            (item for item in (project.get("shots") or []) if item.get("index") == index),
            None,
        )
        if not isinstance(script_shot, dict) or not isinstance(rendered_shot, dict):
            return 技能结果(False, 错误=f"镜头{index}缺少剧本或已渲染视频")
        video_path = rendered_shot.get("path") or ""
        if not video_path:
            return 技能结果(False, 错误=f"镜头{index}没有视频路径")
        if not app.os.path.isabs(video_path):
            video_path = app._safe_join_under(app.BASE_DIR, video_path)
        if not video_path or not app.os.path.isfile(video_path):
            return 技能结果(False, 错误=f"镜头{index}视频文件不存在")

        refs = []
        for path in rendered_shot.get("refs") or []:
            absolute = path if app.os.path.isabs(path) else app.os.path.join(app.BASE_DIR, path)
            if app.os.path.isfile(absolute):
                refs.append(absolute)
        if not refs:
            refs = app.assemble_shot_ref_paths(script_shot, project.get("assets") or {})

        def call(name, values):
            return self.调用技能(技能注册表, project, name, values)

        previous_config = copy.deepcopy(app.runtime_config())
        old_config = app.project_render_config(project)
        app.set_runtime_config({**old_config, "auto_review": True})
        try:
            report_result = call("输出审片报告", {
                "shot": script_shot,
                "video_path": video_path,
                "ref_paths": refs,
            })
        finally:
            app.set_runtime_config(previous_config)
        if not report_result.成功:
            self.记录决策(project, "审片失败", report_result.错误 or "未返回报告", 1, {}, "失败")
            save_changes(project)
            return 技能结果(False, 错误=report_result.错误 or "审片失败")

        report = dict(report_result.数据 or {})
        report_check = call("检查审片报告", {"report": report})
        if not report_check.成功 or not (report_check.数据 or {}).get("通过"):
            problems = (report_check.数据 or {}).get("问题") or [report_check.错误 or "报告校验失败"]
            self.记录决策(project, "审片报告无效", "；".join(problems), 1, {"报告": report_check.数据}, "失败")
            save_changes(project)
            return 技能结果(False, 错误="；".join(problems), 数据={"index": index, "report": report})

        classify = call("分类审片问题", {"审片": report})
        categories = (classify.数据 or {}).get("分类", []) if classify.成功 else []
        fix_result = call("生成修复约束", {"report": report, "分类": categories})
        fix_data = fix_result.数据 or {}
        try:
            threshold = int(参数.get("阈值", old_config.get("review_threshold", 72)))
        except (TypeError, ValueError):
            threshold = 72
        score = int(report_check.数据.get("score", 0))
        audio = report.get('audio_review') or rendered_shot.get('audio_review') or {}
        report['audio_review'] = audio
        audio_ok = audio.get('status') == 'passed' if old_config.get('audio_review_enabled', True) else True
        passed = score >= threshold and audio_ok
        decision = "通过审片" if passed else "转优化"
        report.update({
            "index": index,
            "threshold": threshold,
            "passed": passed,
            "categories": categories,
            "fix_constraints": fix_data.get("修复约束", ""),
        })
        project.setdefault("reviews", {})[str(index)] = report
        rendered_shot["review_score"] = score
        rendered_shot["review_status"] = "通过" if passed else "待优化"
        if not passed:
            rendered_shot["review_error"] = ("听音检查未通过或未完成，请展开报告复核" if not audio_ok else
                                              "；".join(report.get("problems") or []) or "审片分数低于阈值")
        else:
            rendered_shot.pop("review_error", None)
        self.记录决策(
            project,
            decision,
            "；".join(categories) or ("分数达到阈值" if passed else "分数低于阈值"),
            1,
            {"score": score, "threshold": threshold, "categories": categories},
            "已完成",
        )
        save_changes(project)
        result_data = {
            "index": index,
            "score": score,
            "threshold": threshold,
            "passed": passed,
            "categories": categories,
            "fix_constraints": fix_data.get("修复约束", ""),
            "report": report,
            "audio_review": audio,
        }
        if not passed and audio_ok and 参数.get("自动反馈"):
            feedback_result = app.协同调度器实例.执行(
                "优化智能体",
                project,
                {
                    "自动反馈": True,
                    "index": index,
                    "审片": report,
                    "阈值": threshold,
                    "当前次数": 参数.get("当前次数", 0),
                    "最大次数": 参数.get("最大次数", 1),
                },
            )
            result_data["反馈结果"] = feedback_result
            latest = app.load_project(project.get("id", "")) or project
            self.记录决策(
                latest,
                "启动自动反馈" if feedback_result.get("成功") else "自动反馈失败",
                feedback_result.get("错误", "审片低于阈值，已交给优化智能体"),
                int(参数.get("当前次数", 0)) + 1,
                {"反馈": feedback_result.get("数据", {})},
                "已完成" if feedback_result.get("成功") else "失败",
            )
            save_changes(latest)
        return 技能结果(True, 数据=result_data)


审片智能体 = 审片智能体实例()
