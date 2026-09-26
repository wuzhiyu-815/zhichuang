"""运行时 JSON 存储基础设施。

项目内容保存在独立文件夹，用户与权限由团队 SQLite 管理。
本模块提供兼容旧 JSON 的读取、原子写入和迁移。
"""

import copy
import json
import os
import tempfile
import threading


class JSON存储:
    """单目录 JSON 文件存储。"""

    def __init__(self, directory, filename_builder, name="JSON"):
        self.directory = os.path.abspath(directory)
        self.filename_builder = filename_builder
        self.name = name
        self.lock = threading.RLock()

    def path(self, key):
        filename = self.filename_builder(str(key))
        path = os.path.abspath(os.path.join(self.directory, filename))
        if os.path.commonpath([self.directory, path]) != self.directory:
            raise ValueError(f"{self.name}键非法")
        return path

    def load(self, key, default=None):
        path = self.path(key)
        if not os.path.isfile(path):
            return copy.deepcopy(default)
        with self.lock:
            try:
                with open(path, "r", encoding="utf-8") as file:
                    return json.load(file)
            except (OSError, ValueError):
                return copy.deepcopy(default)

    def save(self, key, data):
        path = self.path(key)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with self.lock:
            fd, temp_path = tempfile.mkstemp(
                prefix=f".{os.path.basename(path)}.",
                suffix=".tmp",
                dir=os.path.dirname(path),
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as file:
                    json.dump(data, file, ensure_ascii=False, indent=2)
                    file.flush()
                    os.fsync(file.fileno())
                os.replace(temp_path, path)
            finally:
                if os.path.exists(temp_path):
                    try:
                        os.remove(temp_path)
                    except OSError:
                        pass


    def keys(self):
        if not os.path.isdir(self.directory):
            return []
        return sorted(name[:-5] for name in os.listdir(self.directory)
                      if name.endswith('.json') and os.path.isfile(os.path.join(self.directory, name)))


class 项目文件存储(JSON存储):
    """独立项目目录；兼容旧 JSON，首次保存成功后归档旧文件。"""

    def __init__(self, directory, outputs_dir=None):
        super().__init__(directory, lambda key: os.path.join(key, 'project.json'), name='项目')
        self.outputs_dir = os.path.abspath(outputs_dir) if outputs_dir else None

    def path(self, key):
        key = str(key)
        if not key or key in ('.', '..') or any(c in key for c in ('/', chr(92), chr(0))):
            raise ValueError('项目键非法')
        path = super().path(key)
        if os.path.realpath(os.path.dirname(path)) != os.path.dirname(path):
            raise ValueError('项目目录不能使用符号链接')
        return path

    def legacy_path(self, key):
        self.path(key)
        return os.path.join(self.directory, str(key) + '.json')

    def load(self, key, default=None):
        with self.lock:
            if os.path.isfile(self.path(key)):
                return super().load(key, default)
            self.legacy_path(key)
            return JSON存储(self.directory, lambda _: str(key) + '.json').load(key, default)

    def keys(self):
        keys = set(super().keys())
        if os.path.isdir(self.directory):
            for name in os.listdir(self.directory):
                try:
                    if os.path.isfile(self.path(name)):
                        keys.add(name)
                except ValueError:
                    continue
        return sorted(keys)

    def save(self, key, data):
        with self.lock:
            root = os.path.dirname(self.path(key))
            os.makedirs(root, exist_ok=True)
            for name in ('shared', 'runs'):
                os.makedirs(os.path.join(root, name), exist_ok=True)
            if self.outputs_dir:
                output = os.path.join(self.outputs_dir, str(key))
                os.makedirs(output, exist_ok=True)
                link = os.path.join(root, 'outputs')
                # 实际读写统一使用 outputs_dir；项目内链接仅方便浏览。
                # Windows 普通账户通常没有创建符号链接的权限，不能因此阻断保存。
                if os.name != 'nt' and not os.path.lexists(link):
                    os.symlink(os.path.relpath(output, root), link, target_is_directory=True)
            super().save(key, data)
            legacy = self.legacy_path(key)
            if os.path.isfile(legacy):
                import uuid
                archive = os.path.join(root, 'legacy')
                os.makedirs(archive, exist_ok=True)
                os.replace(legacy, os.path.join(archive, 'project-' + uuid.uuid4().hex + '.json'))

    def delete(self, key):
        import shutil
        with self.lock:
            root = os.path.dirname(self.path(key))
            legacy = self.legacy_path(key)
            exists = os.path.isfile(self.path(key)) or os.path.isfile(legacy)
            if os.path.isdir(root):
                shutil.rmtree(root)
            if os.path.isfile(legacy):
                os.remove(legacy)
            return exists

    def migrate_existing(self):
        """仅在服务启动、接收请求之前调用；失败时保留旧文件。"""
        migrated, skipped = [], []
        for key in self.keys():
            if not os.path.isfile(self.legacy_path(key)):
                continue
            data = self.load(key)
            if not isinstance(data, dict) or data.get('id') != key:
                skipped.append(key)
                continue
            self.save(key, data)
            migrated.append(key)
        return {'migrated': migrated, 'skipped': skipped}
