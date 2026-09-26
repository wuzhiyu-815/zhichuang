"""负责根据审片报告选择修复策略。"""

import copy

from core.agent_base import 智能体基类
from core.skill_result import 技能结果
from agents.optimizer.legacy import 优化智能体 as 旧版优化智能体


class 优化智能体实例(智能体基类):
    名称 = "优化智能体"
    阶段 = "优化"
    说明 = "分类审片问题，决定接受、自动重制或转人工。"
    技能清单 = ("分类审片问题", "生成修复约束")

    def 评估(self, 审片, 阈值=72, 当前次数=0, 最大次数=1):
        return 旧版优化智能体.评估(审片, 阈值, 当前次数, 最大次数)

    def 执行(self, 项目, 技能注册表, 参数=None):
        参数 = dict(参数 or {})
        审片 = copy.deepcopy(参数.get("审片") or {})
        if not 参数.get("自动反馈"):
            return self.评估(
                审片,
                参数.get("阈值", 72),
                参数.get("当前次数", 0),
                参数.get("最大次数", 1),
            )

        try:
            index = int(参数.get("index", 参数.get("镜头编号", 0)))
        except (TypeError, ValueError):
            return 技能结果(False, 错误="自动反馈缺少有效的镜头编号")
        if index < 1:
            return 技能结果(False, 错误="镜头编号必须大于 0")

        import app
        project = app.load_project(项目.get("id", "")) or 项目
        try:
            threshold = int(参数.get("阈值", project.get("render_config", {}).get("review_threshold", 72)))
        except (TypeError, ValueError):
            threshold = 72
        try:
            current_attempt = int(参数.get("当前次数", 0))
            max_attempts = max(0, min(int(参数.get("最大次数", project.get("render_config", {}).get("max_auto_rerenders", 1))), 3))
        except (TypeError, ValueError):
            current_attempt, max_attempts = 0, 1

        decision = self.评估(审片, threshold, current_attempt, max_attempts)
        decision_data = decision.数据 or {}
        self.记录决策(
            project,
            decision_data.get("动作", "评估"),
            "；".join(decision_data.get("分类", [])) or "根据审片分数判断",
            current_attempt,
            {"score": decision_data.get("分数"), "threshold": threshold},
            "执行中",
        )
        app.save_project(project)
        if not decision_data.get("需要优化"):
            status = "已完成" if decision_data.get("分数", 0) >= threshold else "转人工"
            self.记录决策(project, status, decision_data.get("动作", ""), current_attempt, decision_data, status)
            app.save_project(project)
            return 技能结果(True, 数据=decision_data)

        constraints = decision_data.get("修复约束", "")
        prompt_result = app.协同调度器实例.执行(
            "提示词智能体",
            project,
            {
                "index": index,
                "修复约束": constraints,
                "最大重试次数": 2,
            },
        )
        if not prompt_result.get("成功"):
            self.记录决策(project, "修复失败", prompt_result.get("错误", "提示词修复失败"), current_attempt + 1, {}, "失败")
            app.save_project(project)
            return 技能结果(False, 错误=prompt_result.get("错误", "提示词修复失败"), 数据=decision_data)
        prompt_data = prompt_result.get("数据") or {}

        render_result = app.协同调度器实例.执行(
            "渲染智能体",
            project,
            {
                "index": index,
                "prompt": prompt_data.get("prompt", ""),
                "duration": prompt_data.get("duration"),
            },
        )
        if not render_result.get("成功"):
            self.记录决策(project, "重制失败", render_result.get("错误", "渲染失败"), current_attempt + 1, {}, "失败")
            app.save_project(project)
            return 技能结果(False, 错误=render_result.get("错误", "渲染失败"), 数据=decision_data)

        review_result = app.协同调度器实例.执行(
            "审片智能体",
            app.load_project(project.get("id", "")) or project,
            {"index": index, "阈值": threshold},
        )
        review_data = review_result.get("数据") or {}
        if not review_result.get("成功"):
            self.记录决策(project, "复审失败", review_result.get("错误", "重制后审片失败"), current_attempt + 1, {}, "失败")
            app.save_project(project)
            return 技能结果(False, 错误=review_result.get("错误", "重制后审片失败"), 数据=decision_data)

        new_score = review_data.get("score")
        history = {
            "镜头": index,
            "第几次": current_attempt + 1,
            "分数优化前": decision_data.get("分数"),
            "分数优化后": new_score,
            "分类": decision_data.get("分类", []),
            "修复约束": constraints,
            "结果": "通过" if review_data.get("passed") else "仍需优化",
        }
        latest = app.load_project(project.get("id", "")) or project
        latest.setdefault("优化历史", []).append(history)
        self.记录决策(
            latest,
            "重制后通过" if review_data.get("passed") else "重制后仍需优化",
            f"{decision_data.get('分数')} -> {new_score}",
            current_attempt + 1,
            history,
            "已完成",
        )
        app.save_project(latest)
        return 技能结果(True, 数据={
            "index": index,
            "动作": "自动重制",
            "分数优化前": decision_data.get("分数"),
            "分数优化后": new_score,
            "通过": bool(review_data.get("passed")),
            "提示词": prompt_data,
            "渲染": render_result.get("数据") or {},
            "复审": review_data,
            "优化历史": history,
        })


优化智能体 = 优化智能体实例()
