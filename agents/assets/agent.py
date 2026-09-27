"""负责角色、场景、道具参考资产。"""

import os
import time

from core.agent_base import 智能体基类
from core.skill_result import 技能结果


class 资产智能体实例(智能体基类):
    名称 = "资产智能体"
    阶段 = "资产"
    说明 = "生成、分析、复用和检查角色、场景、道具参考资产。"
    技能清单 = ("生成角色参考图", "生成场景参考图", "生成道具参考图", "检查资产文件", "保存资产")

    def 执行(self, 项目, 技能注册表, 参数=None):
        参数 = dict(参数 or {})
        import app
        project = app.load_project(项目.get("id", "")) or 项目
        script = project.get("script") or {}
        targets = []
        requested_kind = str(参数.get("kind") or "").strip()
        requested_name = str(参数.get("name") or "").strip()
        groups = (
            ("char", script.get("characters") or [], "appearance", "character", "生成角色参考图"),
            ("scene", script.get("scenes") or [], "description", "scene", "生成场景参考图"),
            ("prop", script.get("props") or [], "description", "prop", "生成道具参考图"),
        )
        for kind, items, desc_key, output_kind, skill in groups:
            if requested_kind and requested_kind not in (kind, output_kind):
                continue
            for item in items:
                name = str(item.get("name") or "").strip()
                if requested_name and name != requested_name:
                    continue
                if name:
                    targets.append((kind, output_kind, skill, item, desc_key))
        if not targets:
            return 技能结果(False, 错误="没有找到待处理的资产")

        results = []
        progress_callback = 参数.get("progress_callback")

        def notify_asset():
            if callable(progress_callback):
                progress_callback(dict(results[-1]), len(results), len(targets))

        assets = project.setdefault("assets", {})
        for kind, output_kind, skill, item, desc_key in targets:
            key = f"{kind}_{item['name']}"
            current = assets.get(key) or {}
            path = current.get("path") if isinstance(current, dict) else ""
            wrong_canvas = bool(kind == 'char' and path and not current.get('uploaded')
                                and not app.character_reference_is_landscape(path))
            if path and os.path.isfile(path) and os.path.getsize(path) > 0 and not wrong_canvas and not 参数.get("强制生成"):
                results.append({
                    "key": key,
                    "name": item["name"],
                    "kind": output_kind,
                    "path": path,
                    "prompt": current.get("prompt", ""),
                    "cached": True,
                })
                notify_asset()
                continue
            result = self.调用技能(
                技能注册表,
                project,
                skill,
                {
                    "name": item["name"],
                    "desc": item.get(desc_key) or "",
                    "style": 参数.get("style") or (project.get("render_config") or {}).get("style", "电影写实"),
                    "characters": script.get("characters") or [],
                },
            )
            if not result.成功:
                self.记录决策(project, "资产生成失败", f"{item['name']}：{result.错误}", 1, {}, "失败")
                app.save_project(project)
                return 技能结果(False, 错误=result.错误 or f"{item['name']}生成失败", 数据={"results": results})
            data = result.数据 or {}
            path = data.get("path", "")
            check = self.调用技能(技能注册表, project, "检查资产文件", {"path": path})
            if not check.成功 or not (check.数据 or {}).get("通过"):
                error = f"{item['name']}生成后文件无效"
                self.记录决策(project, "资产验收失败", error, 1, {"check": check.数据}, "失败")
                app.save_project(project)
                return 技能结果(False, 错误=error, 数据={"results": results})
            if wrong_canvas:
                app._archive_asset_version(project, key, current, label='横向重生成前版本')
            project.setdefault('asset_confirm', {}).pop('__all__', None)
            assets[key] = {
                "path": path,
                "kind": output_kind,
                "prompt": data.get("prompt", ""),
                "updated": time.time(),
            }
            results.append({
                "key": key,
                "name": item["name"],
                "kind": output_kind,
                "path": path,
                "prompt": data.get("prompt", ""),
                "cached": False,
            })
            app.save_project(project)
            notify_asset()

        project["assets_checked"] = True
        self.记录决策(project, "接受资产", f"完成{len(results)}项资产处理", 1, {"results": results}, "已完成")
        app.save_project(project)
        return 技能结果(True, 数据={"results": results, "count": len(results)})


资产智能体 = 资产智能体实例()
