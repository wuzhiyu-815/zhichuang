# Windows x64 runtime

此目录随 Git 仓库提供 Windows 64 位 Python、已安装的 Python 依赖、FFmpeg 与 ffprobe。
双击项目根目录的 `start_windows.bat` 即可启动，无需预先安装 Python 或 FFmpeg。
首次运行由 Windows PowerShell 校验 SHA-256 并解压至项目根目录的 `python/` 和 `ffmpeg/`。
后续启动复用已解压的环境，不会每次执行联网安装。

目录示例：`C:\zhichuang\python\python.exe`、`C:\zhichuang\ffmpeg\ffmpeg.exe`。
旧版的 `runtime/windows/<版本>/` 不再使用；更新后首次启动会从随包压缩文件重新解压到根目录。

压缩包分别小于 GitHub 的 100 MiB 单文件限制。下载 GitHub ZIP 也包含完整环境；
应用内 Git 同步仍要求通过 Git 克隆项目，并单独安装 Git 和配置仓库访问权限。
模型、ComfyUI、LLM 服务、用户配置及业务数据不包含在运行环境中。
Ubuntu 不使用这些 Windows 二进制文件，仍按原 Linux 安装步骤部署。

## 来源与许可证

- Python 3.13.12：Python.org 官方 Windows x64 embeddable package，
  https://www.python.org/ftp/python/3.13.12/python-3.13.12-embed-amd64.zip 。
  PSF 许可及第三方声明位于 `python.zip` 内的 `python/LICENSE.txt`。
- Python 依赖：从 PyPI 安装 `requirements.txt` 和 pip，实际版本记录在
  `requirements-lock.txt`，各包许可证保留在 `*.dist-info` 等原始包目录内。
- FFmpeg / ffprobe：本机现有的 Gyan Windows x64 static full build，
  版本 `2025-06-08-git-5fea5e3e11`，GPL v3。
  原始 LICENSE、包含构建配置与依赖信息的 README 均保留在两个压缩包内。
  上游构建来源：https://www.gyan.dev/ffmpeg/builds/ 。
  对应 FFmpeg 源码：https://github.com/FFmpeg/FFmpeg/commit/5fea5e3e11 。

## 重新打包

在独立临时目录解压官方 Python 嵌入包，用同版本、同架构的 Python 执行：

```powershell
python -m pip install --target <嵌入包目录>/Lib/site-packages -r requirements.txt pip
python infrastructure/build_windows_bundle.py --python-dir <嵌入包目录> --ffmpeg-dir <含bin和LICENSE的FFmpeg目录>
```

脚本只打包指定的干净目录，不复制个人虚拟环境。重建后检查清单、校验值和运行测试。
依赖清单后续变化时，启动器会安装新依赖，需要网络。
运行包更新后先关闭程序，再重新双击启动，启动器会更新根目录内的运行环境。
