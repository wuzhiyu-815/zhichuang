# 智创

面向短剧制作的 Python / Flask 工作台，包含剧本与分镜编辑、参考资产管理、提示词编辑、ComfyUI 多节点渲染及视频合成。

本仓库用于 Windows 调试与 Ubuntu 部署之间的代码同步。目前是私有开发仓库；第三方资源授权尚未全部核实，不代表整个项目已采用开源许可证。详见 [第三方资源说明](THIRD_PARTY_NOTICES.md)。

## 环境

- Windows 64 位：仓库已带 Python 3.13.12、项目依赖、FFmpeg 和 ffprobe。
- Ubuntu：Python 3.11 或 3.12；FFmpeg 与 ffprobe 放入系统 PATH。
- 可连接的 LLM API，以及具有相应节点、模型的 ComfyUI 服务。
- GPU 模型和第三方下载器不随仓库分发。工作流 JSON 不包含模型权重。

## Windows

```powershell
git clone https://github.com/wuzhiyu-815/zhichuang.git
cd zhichuang
.\start_windows.bat
```

也可以下载仓库 ZIP，解压后双击 `start_windows.bat`。启动器会校验并解压自带环境，不需要另外安装 Python、FFmpeg 或首次联网安装依赖；已有 `config.json` 会保留，缺失时才从示例创建。浏览器访问 `http://127.0.0.1:7860`，在设置中填入自己的服务地址与密钥。团队模式使用 `start_team.bat`。Git 同步功能需要单独安装 Git 并使用克隆目录。

Python 和 FFmpeg 解压在项目根目录的 `python/` 和 `ffmpeg/` 文件夹中。运行环境详情和许可证见 [Windows 运行包](vendor/windows-x64/README.md)。环境检查：`powershell -NoProfile -ExecutionPolicy Bypass -File infrastructure/windows_runtime.ps1 check`。

## Ubuntu 首次安装

```bash
git clone https://github.com/wuzhiyu-815/zhichuang.git
cd zhichuang
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp -n config.example.json config.json
bash start_ubuntu.sh
```

先确保系统已安装 Python venv 支持、FFmpeg 和 ffprobe。默认使用单机模式；团队模式使用 `SHORT_DRAMA_MULTIUSER=1 bash start_ubuntu.sh`。团队管理员初始凭据保存在本机 `runtime/team/initial-admin.txt`，不要提交到 Git。

服务会监听局域网接口；单机模式不提供团队登录隔离。部署到公网前请配置访问控制或启用团队模式。

番茄下载功能依赖单独安装的平台对应下载器，本仓库不包含其可执行文件。Windows 安装的虚拟环境不能复制到 Ubuntu 使用。

## 开发与验证

```bash
python -m unittest discover -s tests -p 'test_*.py' -v
node --check static/workspace-main.js
node tests/test_render_selection.js
```

Node.js 仅用于 JavaScript 检查。测试不替代真实 LLM、ComfyUI 与视频合成的端到端验证。

个人开发统一使用 `main` 分支，修改并验证后推送；Ubuntu 拉取 `main`。具体流程见 [部署与回滚](docs/DEPLOYMENT.md)。

## 配置和数据

Git 管理源代码、内置技能、工作流、文档及 `vendor/windows-x64` 中的 Windows 运行包。`config.json`、`.venv`、`projects`、`assets`、`outputs`、`series`、`reviews`、`runtime`、`novel_downloads`、数据库和运行队列均保留在各自机器。

新增根目录源码文件需要相应更新 `.gitignore` 的白名单。提交前检查 `git diff --cached`；不要使用 `git add -f` 上传运行数据。
