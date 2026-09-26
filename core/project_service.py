"""项目级业务服务。

集中处理项目 JSON、项目资产路径和镜头视频版本。
Flask 路由通过 app.py 中的兼容函数调用本服务，避免接口层直接操作文件。
"""

import os
import re
import shutil
import time
import uuid
from core.final_video import invalidate_final


class 项目服务:
    def __init__(
        self,
        storage,
        projects_dir,
        outputs_dir,
        base_dir,
        io_lock,
        logger=print,
    ):
        self.storage = storage
        self.projects_dir = os.path.abspath(projects_dir)
        self.outputs_dir = os.path.abspath(outputs_dir)
        self.base_dir = os.path.abspath(base_dir)
        self.io_lock = io_lock
        self.logger = logger

    def 路径(self, pid):
        return self.storage.path(pid)

    def 资产目录(self, pid):
        return os.path.join(self.outputs_dir, str(pid), "assets")

    def 资产URL(self, pid, path):
        if not path:
            return ""
        abs_path = os.path.abspath(path)
        project_root = os.path.abspath(self.资产目录(pid))
        try:
            if os.path.commonpath([project_root, abs_path]) == project_root:
                return f"/file/outputs/{pid}/assets/{os.path.basename(abs_path)}"
        except ValueError:
            pass
        return f"/file/assets/{os.path.basename(abs_path)}"

    def 保存(self, project):
        with self.io_lock:
            self.storage.save(project["id"], project)

    def 加载(self, pid):
        path = self.路径(pid)
        changed = False
        with self.io_lock:
            project = self.storage.load(pid)
            if not isinstance(project, dict):
                if os.path.exists(path):
                    self.logger(f"[项目] 读取失败 {pid}")
                return None

            # 历史项目迁移：修正已知的连续剧集数错误。
            if pid == "5a97a7481233" and "第4章 静园与静谧优雅的车" in str(project.get("idea") or ""):
                idea = str(project.get("idea") or "")
                fixed_idea = idea.replace(
                    "连续剧：是；剧名《都重生了》；第2集",
                    "连续剧：是；剧名《都重生了》；第4集",
                )
                if fixed_idea != idea:
                    project["idea"] = fixed_idea
                    changed = True
                series = project.setdefault("series", {})
                if series.get("episode") != 4:
                    series["episode"] = 4
                    changed = True

            config = project.get("render_config")
            if not isinstance(config, dict):
                config = {}
                project["render_config"] = config
                changed = True
            if int(config.get("shot_rules_version", 0) or 0) < 2:
                config["shot_duration"] = "auto"
                config["shot_count"] = "auto"
                config["shot_rules_version"] = 2
                changed = True

            def normalize_shot(shot):
                nonlocal changed
                if not isinstance(shot, dict):
                    return
                try:
                    duration = int(shot.get("duration", 8))
                except (TypeError, ValueError):
                    duration = 8
                normalized = max(8, min(duration, 15))
                if shot.get("duration") != normalized:
                    shot["duration"] = normalized
                    changed = True

            for shot in (project.get("script") or {}).get("shots", []):
                normalize_shot(shot)
            for shot in project.get("shots", []):
                normalize_shot(shot)
            for value in (project.get("shot_confirm") or {}).values():
                normalize_shot(value)

            if changed:
                try:
                    self.storage.save(pid, project)
                except Exception as exc:
                    self.logger(f"[项目] 规则迁移保存失败 {pid}: {exc}")
            return project

    def 镜头(self, project, index):
        try:
            target_index = int(index)
        except (TypeError, ValueError):
            return None
        return next(
            (shot for shot in (project or {}).get("shots", [])
             if self._镜头编号(shot.get("index")) == target_index),
            None,
        )

    @staticmethod
    def _镜头编号(value):
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def 当前镜头路径(self, pid, index):
        return os.path.join(self.outputs_dir, str(pid), f"shot_{int(index):02d}.mp4")

    def 版本URL(self, pid, index, filename):
        return f"/file/outputs/{pid}/versions/shot_{int(index):02d}/{filename}"

    def 归档当前版本(self, project, index, label="生成版本", force_new=False):
        if not project:
            return None
        target = self.镜头(project, index)
        if not target:
            return None
        versions = project.setdefault("shot_versions", {}).setdefault(str(index), [])
        current_id = target.get("current_version_id")
        if current_id and not force_new:
            current = next(
                (version for version in versions if version.get("id") == current_id),
                None,
            )
            if current:
                return current

        source = self.当前镜头路径(project["id"], index)
        if not os.path.isfile(source):
            raw_path = (target.get("path") or "").strip()
            if not raw_path:
                return None
            source = raw_path if os.path.isabs(raw_path) else os.path.join(self.base_dir, raw_path)
            source = os.path.normpath(source)
            if not os.path.isfile(source):
                return None

        version_id = f"v{int(time.time())}_{uuid.uuid4().hex[:6]}"
        version_dir = os.path.join(
            self.outputs_dir,
            project["id"],
            "versions",
            f"shot_{int(index):02d}",
        )
        os.makedirs(version_dir, exist_ok=True)
        filename = f"{version_id}.mp4"
        destination = os.path.join(version_dir, filename)
        try:
            shutil.copyfile(source, destination)
        except (OSError, shutil.Error) as exc:
            self.logger(f"[分镜版本] 跳过归档 镜头{index}: {exc}")
            return None

        item = {
            "id": version_id,
            "created": time.time(),
            "label": label,
            "filename": filename,
            "url": self.版本URL(project["id"], index, filename),
            "prompt": target.get("prompt", ""),
            "duration": target.get("duration", 8),
            "camera": target.get("camera", ""),
        }
        versions.append(item)
        target["current_version_id"] = version_id
        return item

    def 覆盖前归档(self, project, index):
        target = self.镜头(project, index)
        if not target:
            return None
        canonical = self.当前镜头路径(project.get("id", ""), index)
        raw_path = (target.get("path") or "").strip()
        has_file = os.path.isfile(canonical)
        if not has_file and raw_path:
            candidate = raw_path if os.path.isabs(raw_path) else os.path.join(self.base_dir, raw_path)
            has_file = os.path.isfile(os.path.normpath(candidate))
        if not has_file:
            return None
        return self.归档当前版本(project, index, label="历史版本")

    def 渲染后归档(self, project, index, label="新生成"):
        target = self.镜头(project, index)
        if target:
            target.pop("current_version_id", None)
        return self.归档当前版本(project, index, label=label, force_new=True)

    def 同步镜头元数据(self, project, index, prompt=None, duration=None, camera=None):
        target = self.镜头(project, index)
        if target:
            if prompt is not None:
                target["prompt"] = prompt
            if duration is not None:
                target["duration"] = duration
            if camera is not None:
                target["camera"] = camera
        if prompt is not None:
            project.setdefault("prompts", {})[str(index)] = prompt
        confirm = project.setdefault("shot_confirm", {}).setdefault(str(index), {})
        if prompt is not None:
            confirm["prompt"] = prompt
        if duration is not None:
            confirm["duration"] = duration
        if camera is not None:
            confirm["camera"] = camera
        for shot in ((project.get("script") or {}).get("shots") or []):
            if shot.get("index") == index:
                if duration is not None:
                    shot["duration"] = duration
                if camera is not None:
                    shot["camera"] = camera
                break

    def 选择版本(self, project, index, version_id):
        target = self.镜头(project, index)
        if not target:
            return None, "镜头不存在"
        versions = (project.get("shot_versions") or {}).get(str(index), [])
        version = next((item for item in versions if item.get("id") == version_id), None)
        if not version:
            return None, "历史版本不存在"
        version_path = os.path.join(
            self.outputs_dir,
            project["id"],
            "versions",
            f"shot_{int(index):02d}",
            version.get("filename", ""),
        )
        if not os.path.isfile(version_path):
            return None, "历史版本视频文件不存在"
        canonical = self.当前镜头路径(project["id"], index)
        os.makedirs(os.path.dirname(canonical), exist_ok=True)
        shutil.copyfile(version_path, canonical)
        prompt = version.get("prompt", target.get("prompt", ""))
        duration = version.get("duration", target.get("duration", 8))
        camera = version.get("camera", target.get("camera", ""))
        target.update({
            "video_url": f"/file/outputs/{project['id']}/shot_{int(index):02d}.mp4?t={int(time.time())}",
            "path": os.path.join("outputs", project["id"], f"shot_{int(index):02d}.mp4"),
            "current_version_id": version_id,
        })
        target.pop("error", None)
        self.同步镜头元数据(
            project,
            index,
            prompt=prompt,
            duration=duration,
            camera=camera,
        )
        invalidate_final(project)
        return target, version

    def 删除(self, pid):
        path = self.路径(pid)
        if self.storage.load(pid) is None:
            return False
        with self.io_lock:
            if hasattr(self.storage, 'delete'):
                self.storage.delete(pid)
            else:
                os.remove(path)
            output_dir = os.path.join(self.outputs_dir, str(pid))
            if os.path.isdir(output_dir):
                shutil.rmtree(output_dir, ignore_errors=True)
        return True

    def 列表(self, 可见=None):
        items = []
        if not os.path.isdir(self.projects_dir):
            return items
        for pid in sorted(self.storage.keys(), reverse=True):
            if 可见 is not None and not 可见(pid):
                continue
            project = self.storage.load(pid)
            if not isinstance(project, dict) or not project.get("id"):
                continue
            items.append(project)
        return items
