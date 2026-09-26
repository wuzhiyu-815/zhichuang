"""ffmpeg 查找和命令执行封装。"""

import shutil
import subprocess


class FFmpeg执行器:
    def __init__(self, bundled_path=None, logger=print):
        self.bundled_path = bundled_path
        self.logger = logger

    def 查找(self):
        if self.bundled_path and shutil.which(self.bundled_path):
            return self.bundled_path
        if self.bundled_path:
            import os
            if os.path.exists(self.bundled_path):
                return self.bundled_path
        return shutil.which("ffmpeg")

    def 执行(self, command, cwd=None, timeout=600):
        return subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

