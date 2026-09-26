"""短剧生成总控智能体：根据项目状态给出下一步动作。"""

from core.project_context import 项目上下文


class 总控智能体:
    名称 = "总控智能体"

    def 判断下一步(self, 项目, 运行配置=None):
        上下文 = 项目上下文(项目, 运行配置)
        if 项目.get("final"):
            动作, 原因 = "完成", "项目已有最终成片"
        elif not 项目.get("script"):
            动作, 原因 = "生成剧本", "项目尚未生成剧本"
        elif 项目.get("custom_assets") and not 项目.get("assets_confirmed"):
            动作, 原因 = "等待参考图", "项目正在等待自定义参考图确认"
        else:
            镜头 = 项目.get("shots") or []
            失败 = [镜头 for 镜头 in 镜头 if 镜头.get("error")]
            未完成 = [镜头 for 镜头 in 镜头 if not 镜头.get("video_url")]
            if 失败:
                动作, 原因 = "处理失败镜头", f"有{len(失败)}个镜头生成失败"
            elif 未完成:
                动作, 原因 = "生成分镜视频", f"还有{len(未完成)}个镜头未完成"
            else:
                动作, 原因 = "合成成片", "所有分镜均已生成"
        记录 = 上下文.记录智能体决策(self.名称, 动作, 原因)
        return {"动作": 动作, "原因": 原因, "记录": 记录}


总控智能体 = 总控智能体()
