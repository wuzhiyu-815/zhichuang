# -*- coding: utf-8 -*-
"""
全自动短剧生成系统（完全自包含整合包）
流程：剧本解析 → 图片生成 → 分镜视频生成 → 视频合成
图片：Qwen image 2.1 工作流 | 视频：Dasiwa MiniMax H3 8步工作流 | LLM：deepseek
整合包内含：ComfyUI便携版+全部所需模型+llama.cpp+ffmpeg，无任何外部依赖
"""
import os, sys, json, time, re, uuid, copy, random, shutil, subprocess, threading, webbrowser, tempfile, hashlib, zipfile, posixpath, contextlib, glob
# Agents import app lazily. The executable entry point must share its thread-local
# configuration and task registries with those imports, not initialize a second app.
if __name__ == '__main__':
    sys.modules['app'] = sys.modules[__name__]
import html as html_lib
from functools import wraps
from html.parser import HTMLParser
from xml.etree import ElementTree
from urllib.parse import quote, urlparse
from pathlib import Path
import requests
from flask import Flask, request, jsonify, Response, send_file, send_from_directory
from comfy_pool import ComfyPool
from infrastructure.node_monitor import NodeMonitor
from infrastructure.style_lock import lock_prompt as default_lock_prompt, style_instruction as default_style_instruction, is_2d, is_3d_animation
from infrastructure.krea_prompt import apply_krea_skill, SKILL_PATH as KREA_SKILL_PATH
from infrastructure.qwen_image import build_workflow as build_qwen_workflow, reference_prompt, MODEL as QWEN_IMAGE_MODEL
from infrastructure.generation_reference import ReferenceStore
from infrastructure.work_archive import WorkArchive
from infrastructure.comfy_client import Comfy客户端
from infrastructure.jimeng_client import 即梦客户端
from infrastructure.ffmpeg_runner import FFmpeg执行器
from infrastructure.llm_client import LLM客户端
from infrastructure.render_executor import 渲染执行器
from core.storage import JSON存储, 项目文件存储
from core.run_archive import RunArchive
from core.project_service import 项目服务
from core.skill_registry import 技能注册表
from core.scheduler import 协同调度器
from core.task_state import 初始化任务状态, 记录消息, 更新任务状态
from agents.review.skills.issue_classifier import 分类审片问题
from skills.adapters import 注册现有技能
from agents.orchestrator.legacy import 总控智能体
from agents.optimizer.legacy import 优化智能体
from agents.orchestrator.agent import 总控智能体 as 协同总控智能体
from agents.script.agent import 剧本智能体
from agents.assets.agent import 资产智能体
from agents.storyboard.agent import 分镜智能体
from agents.prompts.agent import 提示词智能体
from agents.render.agent import 渲染智能体
from agents.review.agent import 审片智能体
from agents.optimizer.agent import 优化智能体 as 协同优化智能体
from agents.composition.agent import 合成智能体

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WORKFLOWS_DIR = os.path.join(BASE_DIR, 'workflows')
GENERATION_REFERENCES = ReferenceStore(BASE_DIR)
ASSETS_DIR = os.path.join(BASE_DIR, 'assets')
OUTPUTS_DIR = os.path.join(BASE_DIR, 'outputs')
PROJECTS_DIR = os.path.join(BASE_DIR, 'projects')
SERIES_DIR = os.path.join(BASE_DIR, 'series')
REVIEWS_DIR = os.path.join(BASE_DIR, 'reviews')
RENDER_QUEUE_PATH = os.path.join(BASE_DIR, 'render_queue.json')
CONFIG_PATH = os.path.join(BASE_DIR, 'config.json')
CUSTOM_SKILLS_DIR = os.path.join(BASE_DIR, 'skills', 'custom')
SKILLS_INDEX_PATH = os.path.join(CUSTOM_SKILLS_DIR, 'index.json')
COMBAT_SKILL_PATH = os.path.join(BASE_DIR, 'skills', 'seedance-combat-prompt', 'SKILL.md')
LLM_BAT = os.path.join(BASE_DIR, 'llm', 'qwen4b', 'start_qwen4b.bat')
COMFY_BAT = os.path.join(BASE_DIR, 'ComfyUI', 'run_nvidia_gpu_fast_fp16_accumulation.bat')
FFMPEG_LOCAL = os.path.join(BASE_DIR, 'tools', 'ffmpeg', 'ffmpeg.exe')
DIALOGUE_SKILL_PATH = os.path.join(BASE_DIR, 'skills', 'minimax-dialogue-prompt', 'SKILL.md')
ACTION_SKILL_PATH = os.path.join(BASE_DIR, 'skills', 'minimax-action-prompt', 'SKILL.md')
番茄下载器目录 = os.path.join(BASE_DIR, 'tools', 'tomato-novel-downloader')
番茄下载器程序 = os.path.join(
    番茄下载器目录,
    'TomatoNovelDownloader-Win64-v2.4.15.exe' if os.name == 'nt'
    else 'TomatoNovelDownloader-Linux_amd64-v2.4.15',
)
番茄下载器数据目录 = os.path.join(BASE_DIR, 'novel_downloads', 'data')
番茄下载器日志 = os.path.join(BASE_DIR, 'novel_downloads', 'tomato-web.log')
番茄下载器进程 = None
番茄下载器锁 = threading.RLock()
小说查看器缓存 = {}
小说查看器锁 = threading.RLock()
CONFIG_IO_LOCK = threading.RLock()
配置存储 = JSON存储(BASE_DIR, lambda _key: "config.json", name="配置")
项目存储 = 项目文件存储(PROJECTS_DIR, OUTPUTS_DIR)
系列存储 = JSON存储(SERIES_DIR, lambda key: f"{key}.json", name="系列")
FFMPEG执行器实例 = FFmpeg执行器(FFMPEG_LOCAL)

MULTIUSER = None
app = Flask(__name__, static_folder=None)
app.config["MAX_CONTENT_LENGTH"] = 30 * 1024 * 1024

@app.errorhandler(404)
def api_not_found(error):
    if request.path.startswith("/api/"):
        return jsonify({"ok": False, "error": f"接口不存在: {request.path}"}), 404
    return error

# ============================== 配置管理 ==============================
DEFAULT_CONFIG = {
    "llm_mode": "local",                      # local=内置Qwen3.5-4B | custom=自定义API
    "local_llm_url": "http://127.0.0.1:8084",
    "local_llm_model": "qwen3.5-4b",
    "custom_base_url": "http://192.168.1.100:9016/v1",
    "custom_api_key": "EMPTY",
    "custom_model": "qwen3.8-27b",
    "comfyui_url": "http://127.0.0.1:8189",
    "style": "电影写实",
    "shot_duration": "auto",                  # auto=LLM逐镜自定(8~15秒) | 固定秒数(8/10/12/15)
    "shot_count": "auto",                     # auto=LLM按故事节奏定 | 用户指定镜头数
    "prompt_skill_mode": "auto",              # auto=自动识别 | dialogue=文戏 | action=武戏 | anime_action=二次元武戏 | none=基础H3
    "video_skill_id": "auto",                 # 统一 Skill 注册中心中的视频提示词 Skill
    "script_skill_id": "auto",                # 统一 Skill 注册中心中的剧本解析 Skill
    "subtitle_enabled": False,                # 合成时将剧本对白烧录到最终视频
    "shot_rules_version": 2,                  # 分镜时长/镜头数规则版本，旧项目载入时自动迁移
    "h3_steps": 8,                            # Dasiwa H3 8步工作流默认采样步数
    "exclusive_mode": False,                  # 互斥模式：本地LLM与ComfyUI不同时运行（低显存友好）
    "llm_profiles": [],
    "active_llm_profile_id": "",
    "comfyui_servers": [],
    "media_provider": "comfyui",          # comfyui | jimeng
    "jimeng_base_url": "http://192.168.31.176:8001",
    "jimeng_api_key": "",
    "jimeng_image_model": "jimeng-image-5.0-lite",
    "jimeng_video_model": "jimeng-video-seedance-2.0-mini",
    "manual_mode": True,                      # 手动确认模式（默认开启）：每镜提示词就绪后暂停，待用户在卡片上确认/编辑后再渲染（人工把关）
    "batch_prompt_mode": True,                # 批量提示词模式：先把全部镜头提示词生成出来，统一编辑后再按所选镜头批量渲染
    "script_review_mode": True,               # 新项目先生成剧本供用户查阅，确认后才进入资产和视频阶段
    "aspect_ratio": "16:9 (Widescreen)",
    "megapixels": 0.4,                        # 默认横屏 864×480
    "asset_width": 1280,
    "asset_height": 720,
    "story_bible_enabled": True,             # 连续剧角色/场景圣经与资产复用
    "audio_review_enabled": True,
    "audio_asr_url": "http://192.168.31.210:8101",
    "audio_review_url": "http://192.168.31.210:8102",
    "auto_review": False,                    # AI自动审片（默认关闭，开启会增加LLM与渲染耗时）
    "review_threshold": 72,                  # 审片低于该分自动尝试修复
    "max_auto_rerenders": 1,                 # 单镜自动重渲染上限
    "review_frame_count": 3,                 # 审片抽帧数量
    "agent_pipeline_enabled": True,          # 保留旧配置字段兼容存档，生产入口统一由智能体执行
}

def normalize_config(cfg):
    prompt_mode = str(cfg.get('prompt_skill_mode') or 'auto')
    if prompt_mode not in ('auto', 'dialogue', 'action', 'anime_action', 'none') and not prompt_mode.startswith('custom:'):
        cfg['prompt_skill_mode'] = 'auto'
    for key in ('video_skill_id', 'script_skill_id'):
        cfg[key] = str(cfg.get(key) or 'auto')
    if cfg['video_skill_id'] == 'auto' and prompt_mode.startswith('custom:'):
        cfg['video_skill_id'] = cfg['prompt_skill_mode']
    profiles = cfg.get('llm_profiles')
    if not isinstance(profiles, list) or not profiles:
        if cfg.get('custom_base_url'):
            profiles = [{
                'id': 'legacy',
                'name': '默认 API',
                'base_url': cfg.get('custom_base_url', ''),
                'api_key': cfg.get('custom_api_key', '') or 'EMPTY',
                'model': cfg.get('custom_model', ''),
            }]
        else:
            profiles = []
    clean_profiles = []
    for p in profiles:
        if not isinstance(p, dict):
            continue
        clean_profiles.append({
            'id': str(p.get('id') or uuid.uuid4().hex[:12]),
            'name': str(p.get('name') or '未命名 API'),
            'base_url': str(p.get('base_url') or '').strip().rstrip('/'),
            'api_key': str(p.get('api_key') or 'EMPTY'),
            'model': str(p.get('model') or '').strip(),
        })
    cfg['llm_profiles'] = clean_profiles
    active = next((p for p in clean_profiles if p['id'] == cfg.get('active_llm_profile_id')), None)
    active = active or (clean_profiles[0] if clean_profiles else None)
    cfg['active_llm_profile_id'] = active['id'] if active else ''
    if active:
        cfg['custom_base_url'] = active['base_url']
        cfg['custom_api_key'] = active['api_key']
        cfg['custom_model'] = active['model']
    servers = cfg.get('comfyui_servers')
    if not isinstance(servers, list) or not servers:
        servers = [{'id': 'legacy', 'name': '默认 ComfyUI', 'url': cfg.get('comfyui_url', ''), 'enabled': True}] if cfg.get('comfyui_url') else []
    cfg['comfyui_servers'] = [{
        'id': str(s.get('id') or uuid.uuid4().hex[:12]),
        'name': str(s.get('name') or 'ComfyUI'),
        'url': str(s.get('url') or '').strip().rstrip('/'),
        'enabled': bool(s.get('enabled', True)),
    } for s in servers if isinstance(s, dict)]
    first = next((s for s in cfg['comfyui_servers'] if s['enabled'] and s['url']), None)
    cfg['comfyui_url'] = first['url'] if first else ''
    return cfg

def load_config():
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    with CONFIG_IO_LOCK:
        saved = 配置存储.load("config.json")
        if isinstance(saved, dict):
            cfg.update(saved)
        elif os.path.exists(CONFIG_PATH):
            print("[配置] 读取失败，用默认值")
    return normalize_config(cfg)

def save_config(cfg):
    """通过统一存储层原子保存配置。"""
    with CONFIG_IO_LOCK:
        配置存储.save("config.json", cfg)


CONFIG = load_config()

def 读取二次元打戏技能():
    """读取整理后的二次元打戏规则，详细原稿只作为按需参考。"""
    try:
        with open(COMBAT_SKILL_PATH, 'r', encoding='utf-8-sig') as f:
            return f.read()
    except Exception as e:
        print(f"[技能] 二次元打戏技能读取失败: {e}")
        return ""

def 是否打戏场景(text):
    text = str(text or '')
    return bool(re.search(r'打斗|打戏|战斗|对战|搏斗|格斗|拳|掌|肘|膝|踢|刀光|剑招|攻防|连招|击打|二次元|动漫', text))

def 获取二次元打戏规则(_context=None, 参数=None):
    """供技能注册表和提示词流程读取精简后的可执行规则。"""
    return 读取二次元打戏技能()

def 读取武戏技能():
    """读取整理后的 MiniMax H3 武戏规则，完整模板仅按需参考。"""
    try:
        with open(ACTION_SKILL_PATH, 'r', encoding='utf-8-sig') as f:
            return f.read()
    except Exception as e:
        print(f"[技能] MiniMax 武戏技能读取失败: {e}")
        return ""

def 获取武戏提示词规则(_context=None, 参数=None):
    """供技能注册表和 H3 提示词流程读取武戏规则。"""
    return 读取武戏技能()

def 读取文戏技能():
    """读取整理后的 MiniMax H3 文戏规则，完整模板仅按需参考。"""
    try:
        with open(DIALOGUE_SKILL_PATH, 'r', encoding='utf-8-sig') as f:
            return f.read()
    except Exception as e:
        print(f"[技能] MiniMax 文戏技能读取失败: {e}")
        return ""

def 读取自定义技能(mode):
    """按 custom:<id> 读取用户上传的技能文件，避免路径穿越。"""
    raw = str(mode or '')
    raw_id = raw[7:] if raw.startswith('custom:') else raw
    if raw_id.startswith('skill:'):
        raw_id = raw_id[6:]
    filename = os.path.basename(raw_id)
    if not raw_id or filename != raw_id:
        return ""
    path = os.path.join(CUSTOM_SKILLS_DIR, filename)
    if not os.path.isfile(path) or not filename.lower().endswith(('.md', '.txt')):
        return ""
    try:
        with open(path, 'r', encoding='utf-8-sig') as f:
            return f.read()[:12000]
    except Exception as e:
        print(f"[技能] 自定义技能读取失败: {e}")
        return ""

def 自定义技能列表():
    os.makedirs(CUSTOM_SKILLS_DIR, exist_ok=True)
    result = []
    for filename in sorted(os.listdir(CUSTOM_SKILLS_DIR)):
        path = os.path.join(CUSTOM_SKILLS_DIR, filename)
        if os.path.isfile(path) and filename.lower().endswith(('.md', '.txt')):
            display_name = filename.rsplit('.', 1)[0]
            if display_name.startswith('custom_') and '_' in display_name[7:]:
                display_name = display_name.split('_', 2)[-1]
            result.append({"id": filename, "name": display_name})
    return result

内置技能定义 = {
    "builtin:krea2-image": {
        "id": "builtin:krea2-image", "name": "Krea 2 图片提示词", "description": "旧版 Krea 2 提示词规则存档；当前资产生成使用 Qwen Image 2.1。",
        "filename": "skills/krea2-image-prompt/SKILL.md", "path": str(KREA_SKILL_PATH),
        "stages": ["asset"], "builtin": True,
    },
    "builtin:minimax-dialogue": {
        "id": "builtin:minimax-dialogue", "name": "MiniMax 文戏", "description": "对白、关系变化和轻喜剧视频提示词规则。",
        "filename": "skills/minimax-dialogue-prompt/SKILL.md", "path": DIALOGUE_SKILL_PATH,
        "stages": ["script", "video_prompt"], "builtin": True,
    },
    "builtin:minimax-action": {
        "id": "builtin:minimax-action", "name": "MiniMax 武戏", "description": "战斗、追逐和高密度动作视频提示词规则。",
        "filename": "skills/minimax-action-prompt/SKILL.md", "path": ACTION_SKILL_PATH,
        "stages": ["video_prompt"], "builtin": True,
    },
    "builtin:anime-action": {
        "id": "builtin:anime-action", "name": "二次元打戏", "description": "动漫、二次元和高燃动作场景增强规则。",
        "filename": "skills/seedance-combat-prompt/SKILL.md", "path": COMBAT_SKILL_PATH,
        "stages": ["video_prompt"], "builtin": True,
    },
    "builtin:high-density-fight": {
        "id": "builtin:high-density-fight", "name": "高密度打斗导演", "description": "连续因果的电影级打斗提示词，支持中文母稿与 H3 六段稿。",
        "filename": "agents/prompts/skills/high-density-fight-prompt/SKILL.md", "path": os.path.join(BASE_DIR, "agents", "prompts", "skills", "high-density-fight-prompt", "SKILL.md"),
        "agent_skill": "high-density-fight-prompt",
        "stages": ["video_prompt", "script"], "builtin": True,
    },
    "builtin:fight-choreography-director": {
        "id": "builtin:fight-choreography-director", "name": "全域打斗导演", "description": "按角色、世界规则和镜头设计连续打斗编排。",
        "filename": "agents/prompts/skills/fight-choreography-director/SKILL.md", "path": os.path.join(BASE_DIR, "agents", "prompts", "skills", "fight-choreography-director", "SKILL.md"),
        "agent_skill": "fight-choreography-director",
        "stages": ["video_prompt", "script"], "builtin": True,
    },
    "builtin:fight-prompt-director": {
        "id": "builtin:fight-prompt-director", "name": "动作导演", "description": "将图片、文字和分镜素材编排为动作视频提示词。",
        "filename": "agents/prompts/skills/fight-prompt-director/SKILL.md", "path": os.path.join(BASE_DIR, "agents", "prompts", "skills", "fight-prompt-director", "SKILL.md"),
        "agent_skill": "fight-prompt-director",
        "stages": ["video_prompt"], "builtin": True,
    },
    "builtin:fight-scene-director": {
        "id": "builtin:fight-scene-director", "name": "打斗场景导演", "description": "设计可执行的打斗场景、轨迹、镜头和平台提示词。",
        "filename": "agents/prompts/skills/fight-scene-director/SKILL.md", "path": os.path.join(BASE_DIR, "agents", "prompts", "skills", "fight-scene-director", "SKILL.md"),
        "agent_skill": "fight-scene-director",
        "stages": ["video_prompt", "script"], "builtin": True,
    },
    "builtin:lark-yelaoshi": {
        "id": "builtin:lark-yelaoshi", "name": "叶老师打戏指导", "description": "打戏诊断、表情强制规则和高速运镜质检。",
        "filename": "agents/prompts/skills/lark-yelaoshi/SKILL.md", "path": os.path.join(BASE_DIR, "agents", "prompts", "skills", "lark-yelaoshi", "SKILL.md"),
        "agent_skill": "lark-yelaoshi",
        "stages": ["video_prompt", "script"], "builtin": True,
    },
    "builtin:minimax-h3-action-director": {
        "id": "builtin:minimax-h3-action-director", "name": "MiniMax H3 动作导演", "description": "MiniMax H3 动作场景、分镜、运镜和声音设计。",
        "filename": "agents/prompts/skills/minimax-h3-action-director/SKILL.md", "path": os.path.join(BASE_DIR, "agents", "prompts", "skills", "minimax-h3-action-director", "SKILL.md"),
        "agent_skill": "minimax-h3-action-director",
        "stages": ["video_prompt", "script"], "builtin": True,
    },
}

def _读取技能索引():
    os.makedirs(CUSTOM_SKILLS_DIR, exist_ok=True)
    try:
        with open(SKILLS_INDEX_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}

def _保存技能索引(data):
    os.makedirs(CUSTOM_SKILLS_DIR, exist_ok=True)
    with open(SKILLS_INDEX_PATH, 'w', encoding='utf-8') as f:
        json.dump(data if isinstance(data, dict) else {}, f, ensure_ascii=False, indent=2)

def _技能内容(skill_id):
    sid = str(skill_id or '').strip()
    if sid in 内置技能定义:
        path = 内置技能定义[sid]["path"]
    elif sid.startswith('custom:'):
        path = os.path.join(CUSTOM_SKILLS_DIR, os.path.basename(sid[7:]))
    else:
        path = os.path.join(CUSTOM_SKILLS_DIR, os.path.basename(sid))
    if not os.path.isfile(path):
        return ""
    try:
        with open(path, 'r', encoding='utf-8-sig') as f:
            return f.read()[:20000]
    except Exception:
        return ""

def skills_catalog(include_content=False):
    catalog = []
    for item in 内置技能定义.values():
        entry = copy.deepcopy(item)
        if include_content:
            entry["content"] = _技能内容(entry["id"])
        catalog.append(entry)
    index = _读取技能索引()
    known = set()
    for filename in sorted(os.listdir(CUSTOM_SKILLS_DIR)):
        if filename == 'index.json' or not filename.lower().endswith(('.md', '.txt')):
            continue
        sid = f"custom:{filename}"
        meta = index.get(filename) if isinstance(index.get(filename), dict) else {}
        display_name = str(meta.get("name") or filename.rsplit('.', 1)[0])
        if display_name.startswith('custom_') and '_' in display_name[7:]:
            display_name = display_name.split('_', 2)[-1]
        entry = {
            "id": sid, "name": display_name,
            "description": str(meta.get("description") or "用户导入的 Skill"),
            "filename": filename, "stages": meta.get("stages") or ["video_prompt"],
            "builtin": False, "updated_at": meta.get("updated_at"),
        }
        if include_content:
            entry["content"] = _技能内容(sid)
        catalog.append(entry)
        known.add(filename)
    return catalog

def _阶段技能(skill_id, stage):
    sid = str(skill_id or '').strip()
    if sid in ('', 'auto', 'none'):
        return ""
    item = next((x for x in skills_catalog() if x["id"] == sid), None)
    if not item or stage not in (item.get("stages") or []):
        return ""
    if item.get("agent_skill"):
        from skills.agent_documents import load_agent_skill
        return load_agent_skill(BASE_DIR, item["agent_skill"], stage)
    return _技能内容(sid)

def 获取文戏提示词规则(_context=None, 参数=None):
    """供技能注册表和 H3 提示词流程读取文戏规则。"""
    return 读取文戏技能()

def 是否文戏场景(text):
    """判断是否应启用对白/关系表演规则；打戏优先级更高。"""
    text = str(text or '')
    if 是否打戏场景(text):
        return False
    return bool(re.search(
        r'对白|台词|说话|对话|争吵|质问|回应|沉默|注视|微笑|哭|'
        r'情绪|关系|拥抱|亲吻|礼物|杯子|手机|聊天|轻喜剧|独白|内心',
        text
    ))

def 获取提示词技能模式(text=''):
    """返回当前项目的提示词技能路由；显式选择优先于自动识别。"""
    selected = str(runtime_config().get('video_skill_id') or 'auto').strip()
    selected_map = {
        "builtin:minimax-dialogue": "dialogue",
        "builtin:minimax-action": "action",
        "builtin:anime-action": "anime_action",
    }
    if selected in selected_map:
        return selected_map[selected]
    if _阶段技能(selected, 'video_prompt'):
        return selected
    mode = str(runtime_config().get('prompt_skill_mode', 'auto') or 'auto').strip().lower()
    if mode in ('dialogue', 'action', 'anime_action', 'none'):
        return mode
    if mode.startswith('custom:') and 读取自定义技能(mode):
        return mode
    text = str(text or '')
    if 是否打戏场景(text):
        return 'anime_action' if re.search(r'二次元|动漫|日漫|国漫|动画|漫画', text) else 'action'
    if 是否文戏场景(text):
        return 'dialogue'
    return 'none'

def 构造提示词技能规则(shot):
    """根据当前项目配置和分镜内容，返回视频提示词流程共用的 Skill 规则。"""
    shot = shot or {}
    combat_text = " ".join([
        str(shot.get('scene', '')),
        str(shot.get('action', '')),
        str(shot.get('camera', '')),
        str(shot.get('dialogue', '')),
    ])
    skill_mode = 获取提示词技能模式(combat_text)
    if skill_mode.startswith(('custom:', 'builtin:')):
        return (
            "【用户自定义视频提示词技能】\n"
            "以下规则由用户上传，作为当前镜头的专项创作要求。必须应用到本次提示词修改；"
            "遵守系统 H3 格式、8~15秒时长、台词完整性、参考图一致性和安全约束；"
            "若与系统基础规则冲突，以系统基础规则为准。\n"
            + _阶段技能(skill_mode, "video_prompt")
        )
    if skill_mode in ('action', 'anime_action'):
        rules = "【MiniMax H3 武戏提示词技能】\n" + 读取武戏技能()
        if skill_mode == 'anime_action':
            rules += "\n\n【二次元打戏提示词技能】\n" + 读取二次元打戏技能()
        if shot.get('dialogue'):
            rules += (
                "\n\n【武戏中的台词补充规则】\n"
                "保留分镜中的每句台词和说话人，不改写、不翻译；使用稳定的(S1)/(S2)与"
                "<d>[Chinese]台词</d>格式。台词不能打断武戏动作因果链，不新增旁白、字幕或未绑定说话人。"
            )
        return rules
    if skill_mode == 'dialogue':
        return "【MiniMax H3 文戏提示词技能】\n" + 读取文戏技能()
    return "【基础 H3 提示词规则】\n保持当前提示词的 H3 三字段结构、时间轴、参考图编号、角色连续性和原有台词。"

# ============================== 运行时隔离 / 并发保护 ==============================
_RUNTIME = threading.local()
PROJECT_IO_LOCK = threading.RLock()
SERIES_IO_LOCK = threading.RLock()
GPU_JOB_LOCK = threading.RLock()
项目服务实例 = 项目服务(
    项目存储,
    PROJECTS_DIR,
    OUTPUTS_DIR,
    BASE_DIR,
    PROJECT_IO_LOCK,
    logger=print,
)
NODE_MONITOR = NodeMonitor()
COMFY_POOL = ComfyPool(health=NODE_MONITOR)
技能注册表实例 = 技能注册表(archive=RunArchive(lambda: 项目存储))
技能注册表实例.注册("分类审片问题", 分类审片问题)
注册现有技能(技能注册表实例)
协同调度器实例 = 协同调度器(技能注册表实例)
for _智能体 in (
    协同总控智能体, 剧本智能体, 资产智能体, 分镜智能体,
    提示词智能体, 渲染智能体, 审片智能体, 协同优化智能体, 合成智能体,
):
    协同调度器实例.注册智能体(_智能体)
SERVICE_SWITCH_LOCK = threading.RLock()
COMFY_MONITOR_LOCK = threading.RLock()
COMFY_SERVICE_LOCK = threading.RLock()
COMFY_SERVICE_BLOCKED = False
COMFY_MONITOR_STATE = {
    'active': False, 'status': 'idle', 'phase': '空闲', 'percent': 0,
    'elapsed': 0, 'eta': 0, 'prompt_id': None, 'current_node': None,
    'current_title': '', 'task_label': '', 'started_at': None, 'finished_at': None,
    'nodes': [], 'edges': [], 'completed_nodes': [], 'error': None
}
PIPELINE_CANCEL_EVENTS = {}
PIPELINE_CANCEL_LOCK = threading.RLock()

# ============================== 批量视频队列 ==============================
RENDER_QUEUE_LOCK = threading.RLock()
RENDER_QUEUE_WAKE = threading.Event()
RENDER_QUEUE_STATE = {"running": False, "pause_requested": False, "worker": None, "workers": []}

def serialized_queue(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        with RENDER_QUEUE_LOCK:
            return function(*args, **kwargs)
    return wrapped

def load_render_queue():
    if not os.path.exists(RENDER_QUEUE_PATH):
        return {"version": 1, "updated": time.time(), "items": []}
    with RENDER_QUEUE_LOCK:
        try:
            with open(RENDER_QUEUE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("队列文件格式不是对象")
            data.setdefault("version", 1)
            data.setdefault("items", [])
            return data
        except Exception as e:
            print(f"[视频队列] 读取失败: {e}")
            return {"version": 1, "updated": time.time(), "items": []}

def save_render_queue(data):
    data["updated"] = time.time()
    with RENDER_QUEUE_LOCK:
        fd, tmp = tempfile.mkstemp(prefix=".render_queue_", suffix=".tmp", dir=BASE_DIR)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, RENDER_QUEUE_PATH)
        finally:
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except Exception:
                    pass

def render_queue_snapshot():
    data = load_render_queue()
    items = []
    for item in data.get("items", []):
        item = copy.deepcopy(item)
        project = load_project(item.get("pid", "")) if item.get("pid") else None
        item["title"] = (project or {}).get("title") or item.get("title") or item.get("pid", "")
        item["final"] = bool((project or {}).get("final"))
        item["series"] = (project or {}).get("series") or item.get("series")
        items.append(item)
    # 单镜生成和镜头重渲染使用独立的后台线程，不能写入项目队列文件，
    # 但它们仍然是视频任务，必须和项目队列一起展示。
    for task_id, task in list(globals().get("SINGLE_TASKS", {}).items()):
        if not isinstance(task, dict) or task.get("status") == "removed":
            continue
        status = task.get("status") or "running"
        items.append({
            "id": f"single_{task_id}",
            "queue_type": "single_shot",
            "task_id": task_id,
            "title": f"单镜头生成 · {str(task.get('mode') or 'r2v').upper()}",
            "pid": "",
            "status": status,
            "progress": task.get("progress", 0),
            "message": task.get("msg", ""),
            "error": task.get("msg", "") if status == "error" else "",
            "phase": task.get("phase", ""),
            "server": task.get("server", ""),
            "updated": task.get("updated", time.time()),
            "final": False,
            "series": None,
        })
    for task_id, task in list(globals().get("RERENDER_TASKS", {}).items()):
        if not isinstance(task, dict) or task.get("status") == "removed":
            continue
        pid = str(task.get("pid") or "")
        project = load_project(pid) if pid else None
        index = task.get("index")
        title = (project or {}).get("title") or pid or "项目"
        title = f"{title} · 镜头{index}重渲染" if index is not None else f"{title} · 重渲染"
        status = task.get("status") or "running"
        items.append({
            "id": f"rerender_{task_id}",
            "queue_type": "rerender",
            "task_id": task_id,
            "title": title,
            "pid": pid,
            "index": index,
            "status": status,
            "progress": task.get("progress", 0),
            "message": task.get("msg", ""),
            "error": task.get("msg", "") if status == "error" else "",
            "phase": task.get("phase", ""),
            "server": task.get("server", ""),
            "updated": task.get("updated", time.time()),
            "final": False,
            "series": (project or {}).get("series"),
        })
    for task_id, task in list(globals().get("BATCH_RENDER_TASKS", {}).items()):
        if not isinstance(task, dict) or task.get("status") == "removed":
            continue
        pid = str(task.get("pid") or "")
        project = load_project(pid) if pid else None
        indexes = task.get("indexes") or []
        title = (project or {}).get("title") or pid or "项目"
        status = task.get("status") or "running"
        items.append({
            "id": f"batch_{task_id}",
            "queue_type": "batch_render",
            "task_id": task_id,
            "title": f"{title} · 批量生成 {len(indexes)} 镜",
            "pid": pid,
            "indexes": indexes,
            "status": status,
            "progress": task.get("progress", 0),
            "message": task.get("msg", ""),
            "error": task.get("msg", "") if status == "error" else "",
            "phase": task.get("phase", ""),
            "server": task.get("server", ""),
            "updated": task.get("updated", time.time()),
            "final": False,
            "series": (project or {}).get("series"),
        })
    busy_urls = COMFY_POOL.busy_urls()
    busy_names = []
    for server in enabled_comfy_servers():
        if server.get("url") in busy_urls:
            busy_names.append(server.get("name") or server.get("url"))
    monitor = comfy_monitor_snapshot()
    monitor_url = monitor.get("comfyui_url") if monitor.get("active") else ""
    if monitor_url:
        for server in enabled_comfy_servers():
            if server.get("url") == monitor_url:
                name = server.get("name") or server.get("url")
                if name not in busy_names:
                    busy_names.append(name)
                break
    return {
        "running": bool(RENDER_QUEUE_STATE.get("running")),
        "pause_requested": bool(RENDER_QUEUE_STATE.get("pause_requested")),
        "active_workers": len([
            worker for worker in RENDER_QUEUE_STATE.get("workers", [])
            if worker.is_alive()
        ]),
        "busy_nodes": len(busy_names),
        "active_nodes": busy_names,
        "configured_workers": len(enabled_comfy_servers()),
        "items": items,
        "updated": data.get("updated", 0),
    }

@serialized_queue
def _queue_update_item(item_id, **changes):
    data = load_render_queue()
    for item in data.get("items", []):
        if item.get("id") == item_id:
            item.update(changes)
            item["updated"] = time.time()
            break
    save_render_queue(data)

def _retire_queue_worker():
    """Caller holds RENDER_QUEUE_LOCK, so an enqueue cannot miss worker exit."""
    current = threading.current_thread()
    workers = [w for w in RENDER_QUEUE_STATE.get("workers", [])
               if w.is_alive() and w is not current]
    RENDER_QUEUE_STATE.update(workers=workers, worker=workers[0] if workers else None,
                              running=bool(workers))


def render_queue_worker():
    try:
        while True:
            with RENDER_QUEUE_LOCK:
                if RENDER_QUEUE_STATE.get("pause_requested"):
                    _retire_queue_worker()
                    return
                data = load_render_queue()
                target = (MULTIUSER.next_queued(data.get("items", [])) if MULTIUSER else
                          next((x for x in data.get("items", []) if x.get("status") in ("queued", "retry")), None))
                if not target:
                    _retire_queue_worker()
                    return
                _claim_queue_item(target)
                save_render_queue(data)
            _run_render_queue_item(target)
    finally:
        with RENDER_QUEUE_LOCK:
            _retire_queue_worker()


def _run_render_queue_item(target):
    pid = target.get("pid")
    pipeline_event = None
    try:
        project = load_project(pid)
        if not project:
            _queue_update_item(target["id"], status="error", error="单集项目不存在")
            return
        full_auto = target.get("pipeline_mode") == "full_auto"
        if full_auto:
            series_ctx = project.get("series") or {}
            try:
                episode_no = int(series_ctx.get("episode", 0) or 0)
            except (TypeError, ValueError):
                episode_no = 0
            if series_ctx.get("id") and episode_no > 1:
                series_obj = load_series(series_ctx["id"])
                previous_meta = ((series_obj or {}).get("episodes") or {}).get(str(episode_no - 1)) or {}
                previous_summary = str(previous_meta.get("synopsis") or "").strip()
                if previous_summary and series_ctx.get("previous_summary") != previous_summary:
                    project["series"] = dict(series_ctx)
                    project["series"]["previous_summary"] = previous_summary
                    idea_text = str(project.get("idea") or "")
                    project["idea"] = re.sub(
                        r"上一集承接：.*?(?=\n|$)",
                        f"上一集承接：{previous_summary}",
                        idea_text,
                        count=1,
                    )
                    save_project(project)
        # The persisted final URL is the completion contract.  A leftover
        # output file alone may belong to an interrupted/preview run; let the
        # pipeline reconcile it instead of silently skipping the queue item.
        if project.get("final") and _final_file_path(project):
            # Repair stale/missing series metadata whenever a worker observes a
            # verified final, including projects completed before this fix.
            _sync_series_episode_final(project)
            _queue_update_item(target["id"], status="done", progress=100, error="")
            return
        if not full_auto and not project.get("script"):
            _queue_update_item(target["id"], status="error", error="尚未生成剧本/分镜")
            return
        if not full_auto and project.get("script_review_required") and not project.get("script_confirmed"):
            _queue_update_item(target["id"], status="error", error="剧本尚未确认，请先在单集页面确认剧本")
            return
        if not full_auto and not project.get("assets"):
            _queue_update_item(target["id"], status="error", error="尚未生成参考资产")
            return

        try:
            with RENDER_QUEUE_LOCK:
                latest = next((x for x in load_render_queue().get("items", []) if x.get("id") == target["id"]), {})
                if latest.get("pause_requested") or RENDER_QUEUE_STATE.get("pause_requested"):
                    raise PipelineCancelled()
                pipeline_event = register_pipeline(pid)
        except ValueError as exc:
            _queue_update_item(target['id'], status='paused', error=str(exc), message=str(exc))
            return
        queue_cfg = project_render_config(project)
        # 节点列表是全局运行资源，队列启动时读取最新配置，避免单集旧快照遗漏新增节点或保留已停用节点。
        if not MULTIUSER:
            queue_cfg["comfyui_servers"] = copy.deepcopy(CONFIG.get("comfyui_servers") or queue_cfg.get("comfyui_servers") or [])
            queue_cfg["comfyui_url"] = CONFIG.get("comfyui_url") or queue_cfg.get("comfyui_url")
        queue_cfg.update({
            "manual_mode": False,
            "batch_prompt_mode": False,
            "script_review_mode": False,
        })
        last_msg = {"value": ""}

        def push(event, payload):
            msg = payload.get("msg") if isinstance(payload, dict) else ""
            if msg:
                last_msg["value"] = msg
            progress = 0
            if event == "stage":
                progress = {1: 15, 2: 35, 3: 85, 4: 100}.get(payload.get("stage"), 0)
            elif event == "shot_render_progress":
                # 阶段3占总流程约一半；把 H3 的实时进度映射到队列总进度。
                shot_pct = max(0, min(100, int(payload.get("percent") or 0)))
                progress = 35 + round(shot_pct * 0.5)
                msg = payload.get("phase") or msg or "分镜视频渲染中"
                server = payload.get("server")
                changes = {"progress": progress, "message": msg or last_msg["value"]}
                if server:
                    changes["server"] = server
                _queue_update_item(target["id"], **changes)
            elif event == "final":
                progress = 100
            if event == "error":
                _queue_update_item(target["id"], status="error", error=payload.get("msg", "生成失败"), progress=progress)
            elif event == "cancelled":
                _queue_update_item(target["id"], status="paused", error=payload.get("msg", ""), progress=progress)
            elif event in ("agent_wait", "wait_assets"):
                _queue_update_item(target["id"], status="paused", error="", message=msg or "等待确认")
            elif progress or msg:
                _queue_update_item(target["id"], progress=progress, message=msg or last_msg["value"])

        set_runtime_config(queue_cfg)
        run_id = uuid.uuid4().hex[:16]
        _queue_update_item(target["id"], run_id=run_id)
        # 不在整条项目流水线外层独占某一台节点。
        # 资产和分镜阶段内部会通过 COMFY_POOL 按任务分发到所有启用节点；
        # 如果这里提前 acquire，整个项目会固定在第一台节点，其他节点永远拿不到任务。
        _queue_update_item(
            target["id"],
            server="多节点调度",
        )
        run_agent_pipeline(pid, project.get("idea", ""), push,
                           custom_assets=False, run_id=run_id)
        fresh = load_project(pid)
        # A crash or an old pipeline can leave every shot rendered while the
        # final composition step was skipped.  Recover it in the queue worker
        # before declaring the item failed.
        if fresh and _project_shots_have_files(fresh) and not _final_file_path(fresh):
            if not resynth_pipeline(fresh, push, cancel_check=lambda: None):
                fresh = load_project(pid) or fresh
        if fresh and _final_file_path(fresh):
            _sync_series_episode_final(fresh)
            _queue_update_item(target["id"], status="done", progress=100, finished=time.time(), error="", message="视频已生成")
        else:
            current = next((x for x in load_render_queue().get("items", []) if x.get("id") == target["id"]), {})
            if current.get("status") == "running":
                _queue_update_item(target["id"], status="error", error=last_msg["value"] or "生成未完成")
    except PipelineCancelled:
        _queue_update_item(target["id"], status="paused", error="已暂停，已生成内容保留", message="已暂停")
    except Exception as e:
        import traceback
        traceback.print_exc()
        _queue_update_item(target["id"], status="error", error=str(e))
    finally:
        clear_runtime_config()
        if pipeline_event is not None:
            clear_pipeline(pid, pipeline_event)

def ensure_render_queue_worker():
    with RENDER_QUEUE_LOCK:
        # “启动队列/重新排队”明确表示继续执行，即使旧 worker 还在暂停等待，
        # 也必须先清掉暂停标志。
        RENDER_QUEUE_STATE["pause_requested"] = False
        workers = [w for w in RENDER_QUEUE_STATE.get("workers", []) if w.is_alive()]
        desired = MULTIUSER.user_config.worker_count(load_render_queue().get("items",[])) if MULTIUSER else max(1, len(enabled_comfy_servers()))
        missing = max(0, desired - len(workers))
        for offset in range(missing):
            worker = threading.Thread(target=render_queue_worker, daemon=True,
                                      name=f"render-queue-{len(workers) + offset + 1}")
            workers.append(worker)
            worker.start()
        RENDER_QUEUE_STATE["workers"] = workers
        RENDER_QUEUE_STATE["worker"] = workers[0] if workers else None
        RENDER_QUEUE_STATE["running"] = bool(workers)
        # 既要支持暂停后继续，也要唤醒正在等待队列变化的 worker。
        RENDER_QUEUE_WAKE.set()


def _claim_queue_item(item):
    """在持有 RENDER_QUEUE_LOCK 时把队列项从等待态变为运行态。"""
    now = time.time()
    item["status"] = "running"
    item["started"] = now
    item["updated"] = now
    item["error"] = ""
    item["progress"] = 0
    item.pop("pause_requested", None)

def recover_render_queue_on_startup():
    """服务重启后恢复上次被进程中断的队列任务。"""
    data = load_render_queue()
    recovered = 0
    for item in data.get("items", []):
        if item.get("status") == "running":
            item["status"] = "paused" if item.get("pause_requested") else "queued"
            item["message"] = "已暂停，等待继续" if item.get("pause_requested") else "服务已恢复，等待继续生成"
            item["error"] = ""
            item["updated"] = time.time()
            recovered += 1
    if recovered:
        save_render_queue(data)
        print(f"[视频队列] 已恢复 {recovered} 个中断任务")
    if any(item.get("status") in ("queued", "retry") for item in data.get("items", [])):
        ensure_render_queue_worker()

class PipelineCancelled(Exception):
    """当前项目收到终止请求后，用于安全退出流水线。"""

def register_pipeline(pid):
    with PIPELINE_CANCEL_LOCK:
        duplicate = pid in PIPELINE_CANCEL_EVENTS
        if duplicate and MULTIUSER:
            # When a duplicate request would also exceed the configured
            # parallel limit, preserve the quota error shown by the admin UI.
            from team.console import policy, reserve_start
            owner = MULTIUSER.store.owner("project", pid)
            limits = policy(MULTIUSER, owner) if owner else {}
            if limits.get("parallel"):
                active = sum(
                    MULTIUSER.store.owner("project", key) == owner
                    for key in PIPELINE_CANCEL_EVENTS
                ) if owner else 0
                if active >= limits["parallel"]:
                    reserve_start(MULTIUSER, pid)
        if duplicate:
            raise ValueError("该项目已有制作任务正在运行或停止中，请等待任务结束")
        if MULTIUSER:
            from team.console import reserve_start
            reserve_start(MULTIUSER, pid)
        event = threading.Event()
        PIPELINE_CANCEL_EVENTS[pid] = event
        return event

def cancel_pipeline(pid):
    with PIPELINE_CANCEL_LOCK:
        event = PIPELINE_CANCEL_EVENTS.get(pid)
        if not event:
            return False
        event.set()
        return True

def pipeline_cancelled(pid):
    with PIPELINE_CANCEL_LOCK:
        event = PIPELINE_CANCEL_EVENTS.get(pid)
        return bool(event and event.is_set())

def clear_pipeline(pid, event=None):
    with PIPELINE_CANCEL_LOCK:
        if event is None or PIPELINE_CANCEL_EVENTS.get(pid) is event:
            PIPELINE_CANCEL_EVENTS.pop(pid, None)

def runtime_config():
    """返回当前工作线程的配置快照；避免多个项目同时运行时互相污染全局CONFIG。"""
    cfg = getattr(_RUNTIME, 'config', None)
    return cfg if isinstance(cfg, dict) else (MULTIUSER.user_config.get(None) if MULTIUSER else CONFIG)

def reference_style_instruction():
    cfg = runtime_config()
    token = cfg.get('asset_reference_id')
    if not token:
        return ''
    from infrastructure.reference_style import extract_style, instruction
    def analyze(path, ask):
        parts = load_image_parts([path])
        if not parts:
            return None, '无法读取参考图'
        return llm_chat([{'role': 'user', 'content': [{'type': 'text', 'text': ask}] + parts}],
                        max_tokens=1000, temperature=0.2)
    return instruction(extract_style(GENERATION_REFERENCES, token, cfg.get('_owner_id'), analyze))


def style_instruction(style):
    return reference_style_instruction() or default_style_instruction(style)


def lock_prompt(prompt, style):
    rule = reference_style_instruction()
    if rule:
        from infrastructure.reference_style import apply_style
        return apply_style(prompt, rule)
    return default_lock_prompt(prompt, style)


def set_runtime_config(cfg):
    _RUNTIME.config = copy.deepcopy(cfg if isinstance(cfg, dict) else runtime_config())

def clear_runtime_config():
    try:
        delattr(_RUNTIME, 'config')
    except Exception:
        pass

def project_render_config(project):
    """合并项目快照与当前全局媒体配置，兼容旧项目缺少即梦字段。"""
    if MULTIUSER:
        try:
            cfg = normalize_config(MULTIUSER.user_config.project(project))
        except ValueError:
            # Internal maintenance tools may render an unclaimed temporary
            # project. Production requests still require an owned project via
            # the platform guards; this fallback only keeps local utilities
            # and tests from failing before media validation starts.
            cfg = copy.deepcopy(CONFIG)
        cfg['_project_id']=(project or {}).get('id')
        return cfg
    saved = project.get('render_config') if isinstance(project, dict) else None
    cfg = copy.deepcopy(saved if isinstance(saved, dict) else CONFIG)
    for key in (
        'media_provider',
        'jimeng_base_url',
        'jimeng_api_key',
        'jimeng_image_model',
        'jimeng_video_model',
        'jimeng_image_resolution',
        'jimeng_ratio',
    ):
        if key in CONFIG:
            cfg[key] = copy.deepcopy(CONFIG[key])
    # 项目可能保存了已经失效的 ComfyUI 节点列表；渲染和重制必须使用
    # 当前全局启用的节点，否则旧项目会继续把任务发往离线地址。
    if CONFIG.get('comfyui_servers') is not None:
        cfg['comfyui_servers'] = copy.deepcopy(CONFIG.get('comfyui_servers') or [])
    if CONFIG.get('comfyui_url'):
        cfg['comfyui_url'] = CONFIG['comfyui_url']
    return normalize_config(cfg)

def 记录阶段交接(项目, 阶段, 智能体, 下一步, 数据=None):
    """在不破坏旧流程的前提下记录专业 Agent 的阶段交接。"""
    初始化任务状态(项目)
    更新任务状态(项目, 阶段=阶段, 智能体=智能体, 下一步=下一步, 状态="执行中")
    消息 = 协同总控智能体.发送(
        项目, 智能体, f"{阶段}阶段任务",
        数据=数据 or {}, 状态="执行中",
    )
    return 消息

def _safe_join_under(root, rel):
    """安全拼接用户输入路径，防止 startswith 误判与路径穿越。"""
    root_abs = os.path.abspath(root)
    path_abs = os.path.abspath(os.path.join(root_abs, rel))
    try:
        if os.path.commonpath([root_abs, path_abs]) != root_abs:
            return None
    except Exception:
        return None
    return path_abs

for _d in (ASSETS_DIR, OUTPUTS_DIR, PROJECTS_DIR, SERIES_DIR, REVIEWS_DIR):
    os.makedirs(_d, exist_ok=True)

# ============================== 慢动作过滤 ==============================
SLOW_MO_PATTERNS = [
    r'慢动作', r'慢镜头', r'慢速镜头', r'(?<!慢)慢放', r'慢速播放', r'减速播放',
    r'升格镜头', r'升格拍摄', r'升格', r'子弹时间',
    # 只限制明确的慢放/冻结效果；自然动作速度和情绪节奏不等于视频慢放。
    r'定格', r'静帧', r'静止画面',
    r'画面仿佛静止',
    r'slow[- ]?motion', r'slowmotion', r'slow[- ]?mo', r'\bslo[- ]?mo\b',
    r'\bslomo\b', r'bullet time', r'super slow motion',
    r'freeze[- ]?frame', r'frozen frame',
    r'\b(120|240|480|960)\s?fps\b',
]
SLOW_MO_RE = re.compile('|'.join(SLOW_MO_PATTERNS), re.IGNORECASE)

def filter_slow_motion(text):
    if not text:
        return text
    cleaned = SLOW_MO_RE.sub('', text)
    cleaned = re.sub(r'[，,、]\s*[，,、]+', '，', cleaned)
    cleaned = re.sub(r'^\s*[，,、]+|[，,、]+\s*$', '', cleaned)
    cleaned = re.sub(r'[ \t]{2,}', ' ', cleaned)
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
    return cleaned.strip()

# ============================== LLM 统一调用 ==============================
def get_llm_endpoint():
    if runtime_config().get('llm_mode') == 'custom':
        profiles = runtime_config().get('llm_profiles') or []
        profile = next((p for p in profiles if p.get('id') == runtime_config().get('active_llm_profile_id')), None)
        if profile:
            return profile.get('base_url', '').rstrip('/'), profile.get('api_key', 'EMPTY'), profile.get('model', '')
        base = runtime_config().get('custom_base_url', '').rstrip('/')
        return base, runtime_config().get('custom_api_key', 'EMPTY'), runtime_config().get('custom_model', '')
    return runtime_config().get('local_llm_url', 'http://127.0.0.1:8084').rstrip('/'), 'EMPTY', runtime_config().get('local_llm_model', 'qwen3.5-4b')

def llm_chat(messages, max_tokens=4096, temperature=0.7, retries=1, timeout=180, response_format=None, model=None):
    client = LLM客户端(
        get_llm_endpoint,
        ensure_local=ensure_local_llm,
        logger=print,
    )
    return client.对话(
        messages,
        max_tokens=max_tokens,
        temperature=temperature,
        retries=retries,
        timeout=timeout,
        local_mode=runtime_config().get('llm_mode') == 'local',
        response_format=response_format,
        model=model,
    )

def ensure_local_llm():
    """本地LLM在线检测，不在线则用bat启动"""
    base, key, _ = get_llm_endpoint()
    if not base:
        return False, '请先在个人设置中配置大语言模型 API'
    if runtime_config().get('llm_mode') == 'custom':
        try:
            r = requests.get(f"{base}/models", headers={"Authorization": f"Bearer {key}"}, timeout=10)
            if r.status_code == 200:
                return True, None
            detail = r.text[:240].strip()
            return False, f"自定义LLM返回 HTTP {r.status_code}" + (f": {detail}" if detail else "")
        except Exception as e:
            return False, f"自定义LLM服务不可达: {e}"
    try:
        r = requests.get(f"{base}/models", timeout=3)
        if r.status_code == 200:
            return True, None
    except Exception:
        pass
    if MULTIUSER:
        return False, '个人配置的本地模型服务未在线，请检查服务地址'
    if not os.path.exists(LLM_BAT):
        return False, f"本地LLM启动脚本不存在: {LLM_BAT}"
    print("[LLM] 启动本地Qwen3.5-4B服务...")
    subprocess.Popen(['cmd', '/c', 'start', LLM_BAT], cwd=os.path.dirname(LLM_BAT))
    for i in range(90):
        time.sleep(2)
        try:
            r = requests.get(f"{base}/models", timeout=3)
            if r.status_code == 200:
                print("[LLM] 本地服务已就绪")
                return True, None
        except Exception:
            continue
    return False, "本地LLM启动超时(180秒)"

# ============================== 互斥调度（低显存模式） ==============================
def exclusive_on():
    """互斥模式仅在本地LLM时有意义（自定义API不耗本地显存）"""
    return not MULTIUSER and bool(runtime_config().get('exclusive_mode')) and runtime_config().get('llm_mode') == 'local'

def kill_by_port(port):
    """按监听端口杀掉进程（连其控制台窗口一起结束）"""
    try:
        out = subprocess.run(['netstat', '-ano'], capture_output=True, text=True, timeout=15).stdout
    except Exception:
        return
    pids = {ln.split()[-1] for ln in out.splitlines() if f':{port}' in ln and 'LISTENING' in ln}
    for p in pids:
        if p and p != '0':
            print(f"[互斥] taskkill PID={p} (端口{port})")
            subprocess.run(['taskkill', '/PID', p, '/F'], capture_output=True, timeout=15)

def stop_local_llm():
    if MULTIUSER:
        return
    """互斥模式：关闭本地LLM释放显存，并等待端口真正释放"""
    if runtime_config().get('llm_mode') != 'local':
        return
    base = runtime_config().get('local_llm_url', 'http://127.0.0.1:8084').rstrip('/')
    port = urlparse(base).port or 8084
    print(f"[互斥] 关闭本地LLM(端口{port})...")
    kill_by_port(port)
    for _ in range(15):
        time.sleep(1)
        try:
            requests.get(f"{base}/models", timeout=2)
        except Exception:
            print("[互斥] LLM已停止")
            return

def stop_comfyui():
    if MULTIUSER:
        return
    """互斥模式：关闭ComfyUI释放显存，并等待端口真正释放"""
    if media_provider() == 'jimeng':
        return
    port = urlparse(comfy_url()).port or 8189
    print(f"[互斥] 关闭ComfyUI(端口{port})...")
    kill_by_port(port)
    for _ in range(15):
        time.sleep(1)
        if not comfy_check():
            print("[互斥] ComfyUI已停止")
            return

# ============================== ComfyUI 客户端 ==============================
def comfy_url():
    cfg = runtime_config()
    bound = getattr(_RUNTIME, 'comfy_server_url', '')
    if bound:
        return str(bound).rstrip('/')
    servers = enabled_comfy_servers()
    selected = next((s for s in servers if NODE_MONITOR.online(s['url'])),None) or next(iter(servers),None)
    return (selected.get('url') if selected else ('' if MULTIUSER else cfg.get('comfyui_url', 'http://127.0.0.1:8189'))).rstrip('/')

def media_provider():
    return str(runtime_config().get('media_provider') or 'comfyui').strip().lower()

def jimeng_base_url():
    return str(runtime_config().get('jimeng_base_url') or '').rstrip('/')

def jimeng_api_key():
    return str(runtime_config().get('jimeng_api_key') or '').strip()

即梦客户端实例 = 即梦客户端(jimeng_base_url, jimeng_api_key, logger=print)

def node_source(cfg=None):
    """Capture the owner now: pool threads must not consult their own thread-local identity."""
    cfg=copy.deepcopy(cfg if cfg is not None else runtime_config())
    owner=cfg.get('_owner_id')
    platform=MULTIUSER
    if cfg.get('media_provider')=='jimeng':
        return lambda:[{'id':'jimeng','name':'即梦 API','url':'jimeng://'+str(owner or 'api'),'enabled':True}]
    def current():
        if platform:
            user=platform.store.user(owner) if owner else None
            if not user or not user['enabled']:return []
            source=platform.user_config.get(owner)
        else:
            source=CONFIG
        return [s for s in source.get('comfyui_servers',[]) if s.get('enabled') and s.get('url')]
    return current


def enabled_comfy_servers():
    return node_source()()


def monitored_nodes():
    if not MULTIUSER:
        return [s for s in CONFIG.get('comfyui_servers',[]) if s.get('enabled') and s.get('url')]
    nodes=[]
    for user in MULTIUSER.store.users():
        if user['enabled']:
            nodes.extend(s for s in MULTIUSER.user_config.get(user['id']).get('comfyui_servers',[]) if s.get('enabled') and s.get('url'))
    return nodes


def node_statuses(nodes):
    NODE_MONITOR.observe([n for n in nodes if n.get('enabled')])
    return [{**node,**NODE_MONITOR.snapshot(node['url']), 'busy':COMFY_POOL.is_busy(node['url'])} for node in nodes]


def dispatch_comfy(fn):
    @wraps(fn)
    def wrapped(*args,**kwargs):
        if media_provider()=='jimeng' or getattr(_RUNTIME,'comfy_server_url',''):
            return fn(*args,**kwargs)
        try:
            cancel_event=PIPELINE_CANCEL_EVENTS.get(runtime_config().get('_project_id'))
            with COMFY_POOL.acquire(node_source(),cancel_event=cancel_event) as server:
                bind_comfy_server(server['url'])
                try:
                    result=fn(*args,**kwargs)
                    if isinstance(result,tuple) and result and isinstance(result[0],dict):
                        result=({**result[0],'_comfy_origin':server['url']},*result[1:])
                    return result
                finally:
                    clear_comfy_server()
        except Exception as exc:
            return None,str(exc)
    return wrapped


def bind_comfy_server(url):
    _RUNTIME.comfy_server_url = str(url).rstrip('/')

def clear_comfy_server():
    try:
        delattr(_RUNTIME, 'comfy_server_url')
    except AttributeError:
        pass

COMFY客户端实例 = Comfy客户端(comfy_url, logger=print)

def comfy_check():
    if media_provider() == 'jimeng':
        ok, _ = 即梦客户端实例.检查()
        return ok
    if getattr(_RUNTIME,'comfy_server_url',''):
        return COMFY客户端实例.检查()
    servers=enabled_comfy_servers()
    NODE_MONITOR.observe(servers)
    return any(NODE_MONITOR.online(s['url']) for s in servers)

def ensure_comfyui(max_wait=300):
    """确保ComfyUI在线；不在线则用整合包内置的便携版自动启动"""
    if media_provider() == 'jimeng':
        ok, error = 即梦客户端实例.检查()
        if not ok:
            print(f"[即梦] 服务不可用: {error}")
        return ok
    if MULTIUSER:
        # Dispatch waits for health; an offline first node must not fail the whole batch.
        return bool(enabled_comfy_servers())
    with COMFY_SERVICE_LOCK:
        if COMFY_SERVICE_BLOCKED:
            return False
    if comfy_check():
        return True
    if MULTIUSER:
        return False
    if not os.path.exists(COMFY_BAT):
        return False
    print("[ComfyUI] 启动内置整合包...")
    subprocess.Popen(['cmd', '/c', 'start', COMFY_BAT], cwd=os.path.dirname(COMFY_BAT))
    for _ in range(max_wait // 3):
        time.sleep(3)
        if comfy_check():
            print("[ComfyUI] 已就绪")
            return True
    return False

def find_ffmpeg():
    """优先用整合包内置ffmpeg，其次系统PATH。"""
    return FFMPEG执行器实例.查找()

def _srt_time(seconds):
    seconds = max(0.0, float(seconds))
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int(round((seconds - int(seconds)) * 1000))
    if millis >= 1000:
        secs += 1
        millis = 0
    if secs >= 60:
        minutes += 1
        secs = 0
    if minutes >= 60:
        hours += 1
        minutes = 0
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"

def split_subtitle_line(line, max_chars=14):
    """长对白按标点优先拆为短字幕，每段独占一个时间片。"""
    text = ' '.join(str(line).split())
    chunks = []
    while len(text) > max_chars:
        cut = max_chars
        for pos in range(max_chars - 1, max_chars // 2 - 1, -1):
            if text[pos] in '，。！？；、,.!?;… ':
                cut = pos + 1
                break
        chunks.append(text[:cut].strip())
        text = text[cut:].strip()
    if text:
        chunks.append(text)
    return chunks


def build_subtitle_srt(proj, ordered):
    """按分镜时长为对白生成简易 SRT，供最终合成烧录。

    仅作为 ASR 无时间戳时的回退方案。
    """
    script_shots = {
        str(s.get('index')): s
        for s in ((proj.get('script') or {}).get('shots') or [])
        if isinstance(s, dict)
    }
    entries = []
    timeline = 0.0
    for rendered in ordered:
        source = script_shots.get(str(rendered.get('index')), rendered)
        try:
            duration = float(rendered.get('duration') or source.get('duration') or 8)
        except (TypeError, ValueError):
            duration = 8.0
        duration = max(0.1, duration)
        # 历史项目里的 dialogue 既有对象数组，也有单个字符串/字符串数组；
        # 统一成逐句记录，避免只识别到第一种格式而漏掉其余台词。
        raw_dialogues = source.get('dialogue')
        if raw_dialogues is None:
            raw_dialogues = rendered.get('dialogue')
        if isinstance(raw_dialogues, dict):
            raw_dialogues = [raw_dialogues]
        elif isinstance(raw_dialogues, str):
            raw_dialogues = [raw_dialogues]
        dialogues = []
        for item in raw_dialogues or []:
            if isinstance(item, dict):
                line = str(item.get('line') or item.get('text') or '').strip()
            else:
                line = str(item or '').strip()
            if line:
                dialogues.append(line)
        if dialogues:
            segment = duration / len(dialogues)
            for offset, line in enumerate(dialogues):
                chunks = split_subtitle_line(line)
                total = sum(len(chunk) for chunk in chunks)
                elapsed = 0
                for chunk in chunks:
                    start = timeline + offset * segment + segment * elapsed / total
                    elapsed += len(chunk)
                    end = timeline + offset * segment + segment * elapsed / total
                    # 短镜头也必须保证字幕仍落在本镜范围内。
                    shot_end = timeline + (offset + 1) * segment
                    start = min(start, max(timeline, shot_end - 0.1))
                    end = min(end, shot_end)
                    if end <= start:
                        continue
                    entries.append((start, end, chunk))
        timeline += duration
    return "\n\n".join(
        f"{idx}\n{_srt_time(start)} --> {_srt_time(end)}\n{text}"
        for idx, (start, end, text) in enumerate(entries, 1)
    ) + ("\n" if entries else "")

def _video_duration_seconds(path, ffmpeg_path=None):
    """读取已生成片段的真实时长；探测失败时由调用方使用计划时长回退。"""
    probe = shutil.which('ffprobe')
    if not probe and ffmpeg_path:
        probe = os.path.join(os.path.dirname(ffmpeg_path), 'ffprobe')
    if not probe or not path or not os.path.isfile(path):
        return None

def build_asr_subtitle_srt(ordered):
    """用听音服务的逐词时间戳生成成片字幕；无有效时间戳则返回空。"""
    entries = []
    timeline = 0.0
    for shot in ordered:
        report = shot.get('audio_review') or {}
        words = []
        for segment in report.get('segments') or []:
            for word in segment.get('words') or []:
                if not isinstance(word, dict) or not str(word.get('word') or word.get('text') or '').strip():
                    continue
                start, end = word.get('start'), word.get('end')
                if isinstance(start, (int, float)) and isinstance(end, (int, float)) and end > start:
                    words.append((float(start), float(end), str(word.get('word') or word.get('text')).strip()))
        if words:
            try:
                source_duration = float(report.get('duration') or 0)
            except (TypeError, ValueError):
                source_duration = 0
            try:
                target_duration = float(shot.get('duration') or source_duration or 8)
            except (TypeError, ValueError):
                target_duration = source_duration or 8.0
            # ASR 处理的是音频切片，拼接使用的是实际视频时长。逐镜缩放
            # 时间戳，避免每镜微小差异在整片上累积成数秒偏移。
            scale = target_duration / source_duration if source_duration > 0 else 1.0
            # ASR 时间戳相对当前镜头，按短语合并以免每个字单独显示。
            text, start, end = '', None, None
            for word_start, word_end, word in words:
                if start is None:
                    start, end, text = word_start, word_end, word
                elif word_start - end > 0.7 or len(text) + len(word) > 14 or text[-1:] in '。！？!?':
                    entries.append((timeline + start * scale, timeline + end * scale, text))
                    start, end, text = word_start, word_end, word
                else:
                    text += word
                    end = word_end
            if text:
                entries.append((timeline + start * scale, timeline + end * scale, text))
        try:
            timeline += float(shot.get('duration') or 8)
        except (TypeError, ValueError):
            timeline += 8.0
    if not entries:
        return ''
    return "\n\n".join(f"{i}\n{_srt_time(start)} --> {_srt_time(end)}\n{text}" for i, (start, end, text) in enumerate(entries, 1)) + "\n"

def transcribe_final_to_srt(video_path, srt_path, ffmpeg_path):
    """合成完成后对整片音轨重新 ASR，生成与成片时间轴一致的外挂 SRT。"""
    asr_url = runtime_config().get('audio_asr_url') or 'http://192.168.31.210:8101'
    try:
        with tempfile.TemporaryDirectory(prefix='final-asr-') as tmp:
            subprocess.run([ffmpeg_path, '-y', '-v', 'error', '-i', video_path, '-vn', '-c:a', 'pcm_s16le',
                            '-f', 'segment', '-segment_time', '25', os.path.join(tmp, '%04d.wav')],
                           check=True, capture_output=True, timeout=300)
            entries, offset = [], 0.0
            for wav_path in sorted(Path(tmp).glob('*.wav')):
                with __import__('wave').open(str(wav_path)) as wav:
                    part_duration = wav.getnframes() / wav.getframerate()
                with open(wav_path, 'rb') as audio:
                    response = requests.post(asr_url.rstrip('/') + '/v1/audio/transcriptions',
                                             files={'file': (wav_path.name, audio, 'audio/wav')},
                                             data={'language': 'zh', 'word_timestamps': 'true'},
                                             timeout=(10, 180))
                response.raise_for_status()
                data = response.json() if isinstance(response.json(), dict) else {}
                words = [w for w in data.get('words', []) if isinstance(w, dict) and w.get('word')]
                text, start, end = '', None, None
                for word in words:
                    ws, we = word.get('start'), word.get('end')
                    if not isinstance(ws, (int, float)) or not isinstance(we, (int, float)):
                        continue
                    token = str(word['word']).strip()
                    if start is None:
                        start, end, text = ws, we, token
                    elif ws - end > 0.7 or len(text) + len(token) > 14 or text[-1:] in '。！？!?':
                        entries.append((offset + start, offset + end, text)); start, end, text = ws, we, token
                    else:
                        text += token; end = we
                if text:
                    entries.append((offset + start, offset + end, text))
                offset += part_duration
        if not entries:
            return False
        Path(srt_path).write_text("\n\n".join(f"{i}\n{_srt_time(a)} --> {_srt_time(b)}\n{t}" for i, (a,b,t) in enumerate(entries, 1)) + "\n", encoding='utf-8-sig')
        return True
    except Exception as exc:
        print(f'[字幕ASR] 合成后转写失败: {exc}')
        return False

def reburn_existing_final_subtitles(proj, send):
    """只对现有成片重新听音并烧录字幕，不重新拼接分镜。"""
    pid = proj['id']
    out_dir = os.path.join(OUTPUTS_DIR, pid)
    final_path = _final_file_path(dict(proj, final=available_final(proj)))
    ffmpeg = find_ffmpeg()
    if not ffmpeg or not os.path.isfile(final_path):
        return False
    srt_path = os.path.join(out_dir, 'final.srt')
    send('stage', {'stage': 4, 'name': '字幕校准', 'status': 'running', 'msg': '正在对现有成片听音并生成字幕...'})
    # ASR 服务不可用时仍允许使用合成阶段生成的对白时间轴；否则“一键加字幕”
    # 会因为网络/ASR 短暂失败而完全无法输出成片。
    if not transcribe_final_to_srt(final_path, srt_path, ffmpeg):
        fallback = os.path.join(out_dir, 'subtitles.srt')
        if os.path.isfile(fallback) and os.path.getsize(fallback) > 0:
            shutil.copyfile(fallback, srt_path)
            send('stage', {'stage': 4, 'name': '字幕校准', 'status': 'running', 'msg': '听音服务不可用，使用对白时间轴烧录字幕...'})
        else:
            send('stage', {'stage': 4, 'name': '字幕校准', 'status': 'error', 'msg': '无法生成字幕时间轴：听音服务不可用且项目没有对白时间轴'})
            return False
    temp = os.path.join(out_dir, 'final_subtitled.mp4')
    cmd = [ffmpeg, '-y', '-i', final_path, '-vf',
           "subtitles=final.srt:force_style='FontName=Noto Sans CJK SC,FontSize=12,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,Outline=1,Shadow=0,Alignment=2,MarginV=24,WrapStyle=2'",
           '-c:v', 'libx264', '-preset', 'medium', '-crf', '18', '-c:a', 'copy', temp]
    proc = FFMPEG执行器实例.执行(cmd, cwd=out_dir, timeout=600)
    if proc.returncode != 0 or not os.path.isfile(temp):
        return False
    os.replace(temp, final_path)
    send('stage', {'stage': 4, 'name': '字幕校准', 'status': 'done', 'msg': '字幕已按成片听音时间轴烧录'})
    return True
    try:
        value = subprocess.check_output(
            [probe, '-v', 'error', '-show_entries', 'format=duration',
             '-of', 'default=noprint_wrappers=1:nokey=1', path],
            stderr=subprocess.DEVNULL, timeout=15, text=True,
        ).strip()
        duration = float(value)
        return duration if duration > 0 else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None

def comfy_upload_image(file_path):
    data = COMFY客户端实例.上传图片(file_path)
    return data.get('name', os.path.basename(file_path))

def comfy_upload_audio(file_path):
    """把音频文件放入ComfyUI的input目录，返回ComfyUI内文件名（供LoadAudio节点audio参数引用）。
    与图片不同，本版ComfyUI无/upload/audio端点，LoadAudio从input目录读取，故直接拷贝最稳。"""
    import shutil
    comfy_root = os.path.join(BASE_DIR, 'ComfyUI', 'ComfyUI')
    input_dir = os.path.join(comfy_root, 'input')
    os.makedirs(input_dir, exist_ok=True)
    name = os.path.basename(file_path)
    dest = os.path.join(input_dir, name)
    shutil.copyfile(file_path, dest)
    return name

def _workflow_monitor_graph(workflow):
    nodes = []
    edges = []
    wf = workflow or {}
    valid = {str(k) for k in wf.keys()}
    for nid, node in wf.items():
        nid = str(nid)
        node = node or {}
        meta = node.get('_meta') or {}
        ctype = str(node.get('class_type') or 'Unknown')
        title = str(meta.get('title') or ctype)
        nodes.append({'id': nid, 'type': ctype, 'title': title})
        inputs = node.get('inputs') or {}
        for input_name, value in inputs.items():
            if isinstance(value, list) and len(value) >= 2 and str(value[0]) in valid:
                edges.append({'from': str(value[0]), 'to': nid, 'input': str(input_name)})
    def node_sort_key(n):
        s = n['id']
        try:
            return (0, int(s))
        except Exception:
            return (1, s)
    nodes.sort(key=node_sort_key)
    return nodes, edges

def comfy_monitor_begin(workflow, task_label='ComfyUI工作流'):
    nodes, edges = _workflow_monitor_graph(workflow)
    with COMFY_MONITOR_LOCK:
        COMFY_MONITOR_STATE.update({
            'active': True, 'status': 'queued', 'phase': '提交工作流', 'percent': 0,
            'elapsed': 0, 'eta': 0, 'prompt_id': None, 'current_node': None,
            'current_title': '', 'task_label': task_label, 'started_at': time.time(),
            'finished_at': None, 'nodes': nodes, 'edges': edges, 'completed_nodes': [], 'error': None
        })

def comfy_monitor_set_prompt(prompt_id):
    with COMFY_MONITOR_LOCK:
        COMFY_MONITOR_STATE['prompt_id'] = prompt_id
        COMFY_MONITOR_STATE['status'] = 'running'
        COMFY_MONITOR_STATE['phase'] = '等待执行节点'
    # 渲染执行器直接调用 Comfy 客户端，绕过 comfy_submit；把已提交的
    # prompt_id 写入磁盘回执，服务重启后才能继续轮询原任务而不重复提交。
    receipt = (getattr(_RUNTIME, 'batch_render_receipt', None)
               or getattr(_RUNTIME, 'rerender_receipt', None))
    if isinstance(receipt, dict):
        receipt.update(prompt_id=prompt_id, node_url=comfy_url(), updated=time.time())
        rerender_store(PROJECTS_DIR, receipt['pid']).save(receipt['id'], receipt)

def comfy_monitor_update(percent=None, elapsed=None, eta=None, phase=None, current_node=None):
    with COMFY_MONITOR_LOCK:
        st = COMFY_MONITOR_STATE
        if percent is not None: st['percent'] = int(max(0, min(100, percent)))
        if elapsed is not None: st['elapsed'] = int(max(0, elapsed))
        if eta is not None: st['eta'] = int(max(0, eta))
        if phase is not None: st['phase'] = str(phase)
        if current_node is not None:
            current_node = str(current_node)
            prev = st.get('current_node')
            if prev and prev != current_node and prev not in st['completed_nodes']:
                st['completed_nodes'].append(prev)
            st['current_node'] = current_node
            title = next((n.get('title') for n in st.get('nodes', []) if n.get('id') == current_node), '')
            st['current_title'] = title or ''
        if st.get('active'):
            st['status'] = 'running'

def comfy_monitor_finish(success=True, error=None):
    with COMFY_MONITOR_LOCK:
        st = COMFY_MONITOR_STATE
        if st.get('current_node') and st['current_node'] not in st.get('completed_nodes', []):
            st['completed_nodes'].append(st['current_node'])
        st['active'] = False
        st['status'] = 'done' if success else 'error'
        st['phase'] = '完成' if success else '运行失败'
        if success: st['percent'] = 100
        st['eta'] = 0
        st['finished_at'] = time.time()
        st['error'] = str(error) if error else None

def comfy_monitor_snapshot():
    with COMFY_MONITOR_LOCK:
        out = copy.deepcopy(COMFY_MONITOR_STATE)
    out['comfyui_url'] = comfy_url()
    return out

渲染执行器实例 = 渲染执行器(
    COMFY客户端实例,
    monitor={
        "begin": comfy_monitor_begin,
        "set_prompt": comfy_monitor_set_prompt,
        "update": comfy_monitor_update,
        "finish": comfy_monitor_finish,
    },
    logger=print,
)

def comfy_submit(workflow, client_id=None):
    prompt_id = COMFY客户端实例.提交(workflow, client_id=client_id)
    task = getattr(_RUNTIME, 'rerender_receipt', None)
    if task is not None:
        task.update(prompt_id=prompt_id, node_url=comfy_url())
        rerender_store(PROJECTS_DIR, task['pid']).save(task['id'], task)
    return prompt_id

def comfy_wait(prompt_id, timeout=1200, interval=3):
    return COMFY客户端实例.等待(
        prompt_id,
        timeout=timeout,
        interval=interval,
    )

def _legacy_comfy_wait_video_progress(prompt_id, ws=None, timeout=1800, interval=2, progress_callback=None, estimated_seconds=240):
    """等待视频生成并报告实时进度。
    优先读取ComfyUI WebSocket的 sampler progress；若WebSocket不可用，则退化为估算百分比。
    progress_callback 接收 dict: percent / elapsed / eta / estimated / phase。
    """
    start = time.time()
    last_emit = 0.0
    max_pct = 0
    got_real_progress = False
    if ws is not None:
        try:
            ws.settimeout(0.8)
        except Exception:
            pass

    def emit(percent, phase='渲染中', estimated=False, force=False):
        nonlocal last_emit, max_pct
        now = time.time()
        if not force and now - last_emit < 0.7:
            return
        percent = max(max_pct, int(max(0, min(99, percent))))
        max_pct = percent
        elapsed = max(0, int(now - start))
        if percent > 2:
            eta = int(max(0, elapsed * (100 - percent) / max(percent, 1)))
        else:
            eta = int(max(0, estimated_seconds - elapsed))
        comfy_monitor_update(percent=percent, elapsed=elapsed, eta=eta, phase=phase)
        if progress_callback:
            try:
                progress_callback({"percent": percent, "elapsed": elapsed, "eta": eta,
                                   "estimated": bool(estimated), "phase": phase})
            except Exception:
                pass
        last_emit = now

    emit(0, '等待ComfyUI开始', estimated=(ws is None), force=True)
    next_poll = 0.0
    try:
        while time.time() - start < timeout:
            now = time.time()
            # WebSocket实时进度（通常来自采样节点 value/max）
            if ws is not None:
                try:
                    msg = ws.recv()
                    if isinstance(msg, str):
                        payload = json.loads(msg)
                        typ = payload.get('type')
                        data = payload.get('data') or {}
                        msg_pid = data.get('prompt_id')
                        if msg_pid and msg_pid != prompt_id:
                            pass
                        elif typ == 'progress':
                            value = float(data.get('value', 0) or 0)
                            maximum = float(data.get('max', 0) or 0)
                            if maximum > 0:
                                got_real_progress = True
                                # 采样进度占主要耗时；保留最后5%给解码/保存，避免过早显示100%。
                                pct = min(95, max(1, round((value / maximum) * 95)))
                                emit(pct, 'H3采样中', estimated=False, force=True)
                        elif typ == 'executing':
                            node = data.get('node')
                            if node is not None and (not msg_pid or msg_pid == prompt_id):
                                comfy_monitor_update(current_node=node, phase='执行节点')
                            if node is None and (not msg_pid or msg_pid == prompt_id):
                                emit(99, '编码保存中', estimated=not got_real_progress, force=True)
                        elif typ in ('execution_success', 'executed'):
                            emit(max(max_pct, 98), '输出处理中', estimated=not got_real_progress, force=True)
                except Exception:
                    pass

            # 每隔一段时间轮询history，确认完成/错误；同时在无WS时更新估算进度
            if now >= next_poll:
                next_poll = now + interval
                try:
                    r = requests.get(f"{comfy_url()}/history/{prompt_id}", timeout=15)
                    if r.status_code == 200:
                        h = r.json()
                        if prompt_id in h and h[prompt_id].get('status', {}).get('completed'):
                            if progress_callback:
                                elapsed = max(0, int(time.time() - start))
                                try:
                                    progress_callback({"percent": 100, "elapsed": elapsed, "eta": 0,
                                                       "estimated": False, "phase": '完成'})
                                except Exception:
                                    pass
                            comfy_monitor_finish(True)
                            return h[prompt_id], None
                        if prompt_id in h:
                            st = h[prompt_id].get('status', {})
                            if st.get('status_str') == 'error':
                                err_msg = f"ComfyUI执行错误: {json.dumps(st.get('messages', []), ensure_ascii=False)[:300]}"
                                comfy_monitor_finish(False, err_msg)
                                return None, err_msg
                except Exception as e:
                    print(f"[ComfyUI] 视频进度轮询异常: {e}")

                if not got_real_progress:
                    elapsed = time.time() - start
                    # 回退估算：先快速到10%，之后按预计耗时平滑推进，最高停在94%。
                    ratio = min(0.94, elapsed / max(float(estimated_seconds), elapsed + 30.0))
                    pct = max(2, round(ratio * 100))
                    emit(pct, '渲染中（估算）', estimated=True, force=True)
            time.sleep(0.08)
    finally:
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass
    err_msg = f"ComfyUI生成超时({timeout}秒)"
    comfy_monitor_finish(False, err_msg)
    return None, err_msg

def comfy_wait_video_progress(prompt_id, ws=None, timeout=1800, interval=2,
                              progress_callback=None, estimated_seconds=240):
    """兼容入口：统一由渲染执行器负责等待和进度处理。"""
    return 渲染执行器实例._wait(
        prompt_id,
        ws,
        timeout,
        interval,
        estimated_seconds,
        progress_callback,
    )

def comfy_download(file_info, save_path):
    origin=file_info.get('_comfy_origin') if isinstance(file_info,dict) else None
    if origin:
        return Comfy客户端(lambda:origin,logger=print).下载(file_info,save_path)
    return COMFY客户端实例.下载(file_info, save_path)

def media_download_video(file_info, save_path):
    """按当前媒体服务下载视频；即梦返回 URL，ComfyUI 返回 history 文件对象。"""
    if media_provider() == 'jimeng':
        if not isinstance(file_info, dict) or not file_info.get('jimeng_url'):
            raise RuntimeError("即梦视频没有返回可下载地址")
        return 即梦客户端实例.下载(file_info['jimeng_url'], save_path)
    return comfy_download(file_info, save_path)

# ============================== Krea2 Turbo 文生图 ==============================
# 画幅 → 默认生图尺寸（角色设定图和场景参考图单独固定为横向16:9）
ASPECT_IMG_SIZE = {
    "16:9 (Widescreen)": (1280, 720),
    "9:16 (Portrait)":   (720, 1280),
    "1:1 (Square)":      (960, 960),
    "4:3 (Standard)":    (1088, 816),
}

def load_t2i_workflow(reference=False):
    name = 'qwen-image-2.1-edit.json' if reference else 'qwen-image-2.1-t2i.json'
    with open(os.path.join(WORKFLOWS_DIR, name), 'r', encoding='utf-8') as f:
        return json.load(f)

@dispatch_comfy
def gen_image(prompt, width=None, height=None, seed=None, save_name=None, image_model=None, reference_path=None):
    """使用 Qwen Image 2.1 文生图或参考图编辑工作流生成图片，返回本地保存路径。尺寸默认跟随全局画幅设置。"""
    if not reference_path:
        prompt = lock_prompt(prompt,runtime_config().get('style'))
    if media_provider() == 'jimeng':
        if reference_path:
            return None, '参考图生图需选择 ComfyUI（Qwen Image 2.1）图片服务'
        if save_name is None:
            save_name = f"img_{uuid.uuid4().hex[:8]}.png"
        ratio = runtime_config().get('jimeng_ratio') or {
            "16:9 (Widescreen)": "16:9", "9:16 (Portrait)": "9:16",
            "1:1 (Square)": "1:1", "4:3 (Standard)": "4:3",
        }.get(runtime_config().get('aspect_ratio'), "16:9")
        if width and height:
            from fractions import Fraction
            image_ratio = Fraction(int(width), int(height))
            ratio = f"{image_ratio.numerator}:{image_ratio.denominator}"
        url = 即梦客户端实例.生成图片(
            prompt,
            image_model or runtime_config().get('jimeng_image_model') or "jimeng-image-5.0-lite",
            ratio,
            runtime_config().get('jimeng_image_resolution') or "2k",
        )
        return 即梦客户端实例.下载(url, os.path.join(ASSETS_DIR, save_name)), None
    if not width or not height:
        width, height = ASPECT_IMG_SIZE.get(runtime_config().get('aspect_ratio', '16:9 (Widescreen)'), (1280, 720))
    reference_name = None
    if reference_path:
        reference_name = comfy_upload_image(reference_path)
    try:
        wf = build_qwen_workflow(load_t2i_workflow(bool(reference_path)), prompt, width, height,
                                 seed if seed is not None else random.randint(1, 2**62),
                                 reference_name, image_model)
    except ValueError as exc:
        return None, str(exc)
    print(f"[资产生图] project={runtime_config().get('_project_id', '')} mode={'image-edit' if reference_path else 'text-to-image'} reference={os.path.basename(reference_path) if reference_path else '-'}", flush=True)
    pid = comfy_submit(wf)
    history, err = comfy_wait(pid, timeout=600)
    if err:
        return None, err
    images = []
    for nid, out in history.get('outputs', {}).items():
        for img in out.get('images', []):
            images.append(img)
    if not images:
        return None, "ComfyUI未返回图像"
    if save_name is None:
        save_name = f"img_{uuid.uuid4().hex[:8]}.png"
    save_path = os.path.join(ASSETS_DIR, save_name)
    comfy_download(images[0], save_path)
    return save_path, None

# ============================== Dasiwa MiniMax H3 8步 r2v 视频 ==============================
def load_r2v_workflow():
    with open(os.path.join(WORKFLOWS_DIR, 'h3-dasiwa-8step.json'), 'r', encoding='utf-8') as f:
        return json.load(f)

def get_h3_steps():
    """采样步数 clamp 4~25"""
    try:
        return max(4, min(int(runtime_config().get('h3_steps', 8)), 25))
    except (TypeError, ValueError):
        return 8

def h3_video_size():
    """将界面画幅和像素档位换算为32倍数的H3宽高。"""
    aspect = runtime_config().get('aspect_ratio', '16:9 (Widescreen)')
    try:
        megapixels = max(0.2, min(float(runtime_config().get('megapixels', 0.92)), 2.0))
    except (TypeError, ValueError):
        megapixels = 0.92
    size_ladders = {
        '16:9 (Widescreen)': {
            0.2: (608, 352), 0.3: (736, 416), 0.4: (864, 480),
            0.5: (960, 544), 0.6: (1056, 608), 0.7: (1152, 640),
            0.8: (1216, 672), 0.9: (1280, 736), 0.92: (1280, 720),
            0.98: (1344, 768),
        },
        '9:16 (Portrait)': {
            0.2: (352, 608), 0.3: (416, 736), 0.4: (480, 864),
            0.5: (544, 960), 0.6: (608, 1056), 0.7: (640, 1152),
            0.8: (672, 1216), 0.9: (736, 1280), 0.92: (720, 1280),
            0.98: (768, 1344),
        },
    }
    exact = size_ladders.get(aspect, {}).get(round(megapixels, 2))
    if exact:
        return exact
    ratios = {
        '16:9 (Widescreen)': (16, 9),
        '9:16 (Portrait)': (9, 16),
        '1:1 (Square)': (1, 1),
        '4:3 (Standard)': (4, 3),
    }
    ratio_width, ratio_height = ratios.get(aspect, (16, 9))
    pixel_count = megapixels * 1_000_000
    width = round((pixel_count * ratio_width / ratio_height) ** 0.5 / 32) * 32
    height = round((pixel_count * ratio_height / ratio_width) ** 0.5 / 32) * 32
    return max(32, width), max(32, height)

def h3_frames_from_duration(seconds):
    """H3帧数对齐：17的倍数+5"""
    frames = max(5, round(seconds * 24))
    return frames + (5 - frames % 17) % 17

@dispatch_comfy
def gen_video_r2v(prompt, ref_image_paths, duration=None, seed=None, save_name=None,
                  ref_audio_paths=None, progress_callback=None, video_model=None):
    """MiniMax H3 r2v生成视频。ref_image_paths[0]=Picture 1(角色), [1]=Picture 2(场景)...
    ref_audio_paths: 独立参考音频（角色音色），对应 <Audio 1>~<Audio 3>，最多3段，接到136的 ref_audios.ref_audio_N"""
    prompt = lock_prompt(prompt,runtime_config().get('style'))
    if media_provider() == 'jimeng':
        if not duration:
            duration = runtime_config().get('shot_duration', 8)
        duration = min(max(1, int(duration)), 15)
        if seedance_video_prompt_enabled() and (
            'integrated_multimodal_description:' in str(prompt)
            or '<Picture ' in str(prompt)
            or '<d>[Chinese]' in str(prompt)
        ):
            converted, convert_error = convert_h3_to_seedance_prompt(prompt, ref_image_paths, duration)
            if converted:
                prompt = converted
            elif convert_error:
                print(f"[即梦] H3转Seedance失败，沿用原提示词: {convert_error}")
        ratio = runtime_config().get('jimeng_ratio') or {
            "16:9 (Widescreen)": "16:9", "9:16 (Portrait)": "9:16",
            "1:1 (Square)": "1:1", "4:3 (Standard)": "4:3",
        }.get(runtime_config().get('aspect_ratio'), "16:9")
        try:
            if progress_callback:
                progress_callback({"percent": 3, "elapsed": 0, "eta": 0, "phase": "提交即梦视频"})
            url = 即梦客户端实例.生成视频(
                lock_prompt(filter_slow_motion(prompt),runtime_config().get('style')),
                video_model or runtime_config().get('jimeng_video_model') or "jimeng-video-seedance-2.0-mini",
                ratio,
                duration,
                file_paths=ref_image_paths,
            )
            if progress_callback:
                progress_callback({"percent": 95, "elapsed": 0, "eta": 0, "phase": "下载即梦视频"})
            return {"jimeng_url": url}, save_name or f"shot_{uuid.uuid4().hex[:8]}.mp4"
        except Exception as exc:
            return None, f"即梦视频生成失败: {exc}"
    wf = copy.deepcopy(load_r2v_workflow())
    if not duration:
        cfg_dur = runtime_config().get('shot_duration', 8)
        duration = cfg_dur if isinstance(cfg_dur, (int, float)) else 8
    duration = min(max(8, int(duration)), 15)
    prompt = filter_slow_motion(prompt)

    # Dasiwa 8步工作流的核心参数
    width, height = h3_video_size()
    wf['6']['inputs']['prompt'] = prompt
    wf['6']['inputs']['width'] = width
    wf['6']['inputs']['height'] = height
    wf['8']['inputs']['noise_seed'] = seed if seed is not None else random.randint(1, 2**62)
    frames = h3_frames_from_duration(duration)
    wf['6']['inputs']['length'] = frames
    wf['7']['inputs']['steps'] = get_h3_steps()
    # 参考图：删除模板占位图后统一重建（H3 r2v 官方支持最多9张）
    refs = [p for p in ref_image_paths if p and os.path.exists(p)][:9]
    if not refs:
        return None, "无有效参考图"
    inputs6 = wf['6']['inputs']
    for k in list(inputs6.keys()):
        if k.startswith('ref_images.ref_image_'):
            del inputs6[k]
    next_node_id = 300
    for i, path in enumerate(refs):
        comfy_name = comfy_upload_image(path)
        load_nid = str(next_node_id); next_node_id += 1
        wf[load_nid] = {"inputs": {"image": comfy_name}, "class_type": "LoadImage", "_meta": {"title": f"参考图{i+1}"}}
        inputs6[f'ref_images.ref_image_{i}'] = [load_nid, 0]
    for old in ['20', '21', '22']:
        wf.pop(old, None)
    # 参考音频（角色音色）：<Audio 1>~<Audio N>，最多3段
    auds = [p for p in (ref_audio_paths or []) if p and os.path.exists(p)][:3]
    for k in list(inputs6.keys()):
        if k.startswith('ref_audios.ref_audio_'):
            del inputs6[k]
    for j, a_path in enumerate(auds):
        comfy_a = comfy_upload_audio(a_path)
        load_aid = str(next_node_id); next_node_id += 1
        wf[load_aid] = {"inputs": {"audio": comfy_a}, "class_type": "LoadAudio", "_meta": {"title": f"参考音频{j+1}"}}
        inputs6[f'ref_audios.ref_audio_{j}'] = [load_aid, 0]

    estimated_seconds = max(120, int(duration * 18 + get_h3_steps() * 8))
    history, err = 渲染执行器实例.执行(
        wf,
        task_label=f"MiniMax H3 R2V · {duration}s",
        timeout=1800,
        interval=2,
        estimated_seconds=estimated_seconds,
        progress_callback=progress_callback,
    )
    if err:
        return None, err
    videos = []
    for nid, out in history.get('outputs', {}).items():
        for key in ('videos', 'gifs', 'images'):
            for v in out.get(key, []):
                videos.append(v)
    if not videos:
        return None, "ComfyUI未返回视频"
    if save_name is None:
        save_name = f"shot_{uuid.uuid4().hex[:8]}.mp4"
    return videos[0], save_name  # 由调用方决定保存目录

# ============================== 单镜头生成器（r2v / i2v / t2v） ==============================
SINGLE_SHOT_PROMPT = """你是MiniMax H3视频生成模型的提示词专家。MiniMax H3是全模态视频生成模型：一次生成同时产出画面与原生音频（对白、音效、音乐同出）。用户会给你一段口语化的创作要求，你需要在内部连续完成两步工作，最终只输出第二步的产物——H3{mode_label}提示词。

【内部第一步：需求整理（思考过程，不要输出）】
把用户的口语要求整理成具象拍摄方案：
1. 用户用"图1/图2/第一张图"等任何方式引用参考图时，编号是关键锚点必须保留，统一规范为"图N"写法（与图片上传顺序一致），禁止概括成"一个男人/一个场景"等丢失编号的表达
2. 抽象词必须转成具体可拍摄方案：动作类抽象词→直接设计具体动作序列（谁、用什么武器/招式、如何进攻、对方如何格挡/倒地，写清肢体部位+运动方向+发力方式）；氛围类→具体视觉元素+光影；情绪类→具体面部/肢体表现。禁止输出"炫酷/华丽/震撼/激烈/唯美/霸气"等抽象形容词本身
3. 禁止原文照抄：即使用户输入已比较具体，也必须进一步拆解深化——每个招式/动作拆成"起势→发力→击中→收势"的物理步骤；补充物理反馈细节（衣物飘动/地面尘土/汗水飞溅/受力踉跄/冲击气浪）；把笼统的"镜头切换"落实为具体运镜安排（哪段动作配哪种景别）。整理后的信息量必须明显大于原文
4. 完整保留用户的所有实质性要求（动作、互动关系、场景、环境、台词），只去除口语化语气词

【内部第二步：生成H3提示词（唯一需要输出的内容）】
把整理好的方案写成严格符合H3官方训练格式的提示词，由以下三个字段组成，按此顺序、各起一段（字段名英文一字不差）：

integrated_multimodal_description: 开头一句定调整体风格与初始构图（如"写实电影感，暖色调浅景深"），随后沿时间轴把内容拆成 **2~4 个带标题时间码的镜头段**（[Shot 1] → [Shot 2] → ...），用不同景别/视角/机位呈现动作推进。时长{duration}秒内把切点均匀铺开（首镜头不晚于1秒，末镜头在最后1秒收束）。每个镜头段写清该段画面、主体动作、镜头运动、说话人与台词、同步音效。
overall_soundscape: 用1-3句中文概括全片环境音、物理动作音、非语言人声（风雨/脚步/布料摩擦/撞击/呼吸等）。对白已写在上个字段，此处禁止重复。
non_diegetic_music: 用1-2句中文描述只有观众能听到的配乐（乐器编制、速度、力度起伏）；开头禁止重锤鼓点；无配乐写 N/A。

【硬性规则】
1. 结构标记与固定术语用英文（字段名、[Shot N]、时间码、The camera 运镜句式、(S1)说话人ID、<d>台词标签、<Picture N>引用标签）；画面/动作/场景等描述性文字用中文
2. 🔴台词与身份隔离（最高优先级）：台词逐字保留，禁止遗漏、改写、翻译。开头单独写“人物与声线设定，仅用于身份和声音绑定，不朗读”，将角色姓名、年龄、外观、服装、固定声线和参考音色绑定到 <Subject N> (SN) 与实际对应的 <Picture M>；Subject编号不要求等于Picture编号，不得改变参考图顺序。人物介绍不得放在“说：/开口”之后或说话人标记与台词之间。每次发声必须独立成两行：
<Subject 1> (S1) says:
<d>[Chinese]台词原文</d>
按实际说话人替换编号；says: 后立即换行接 <d>，不得夹入姓名、年龄、服装、声线、情绪或参考音色说明。情绪、动作在对白块前另起句，固定声线及 <Audio N> 音色参照只写在开头人物设定中。声明“仅朗读 <d> 标签内的中文正文，人物设定、动作描述和说话人编号均不发声，无旁白”（原作明确要求的画外对白除外）。无台词不写 <d> 段。不要在环境音字段重复台词。标签是生成约束，不是标签外文字绝不会发声的保证。
3. {pic_rule}
4. 🔄切镜（多镜头是H3的最大优势，必须用足，也是抗"慢动作/slideshow"最强手段）：在 {duration} 秒内策划 **2~4 次干净硬切**（hard cut），写法 "[Shot 2] At 00:03.000, the camera cuts to a close-up of ..."。切镜时机=有**新信息**出现时：景别跃迁（全景切特写）、视角换向（正对切侧打）、主体聚焦（两人同框切单人面部）、动作落点（起跳切落地）、节拍重音（配乐爆发处）等。只在距离/角度微调时用连续运镜过渡，不要为微小变化切镜。🔴**硬切必须干净利落、禁止叠化/淡入淡出("cuts clean and hard, no dissolves")——叠化转场正是产生"飘/慢"观感的重灾区**；每镜一段尽量短（动作片1~2秒/段），切点落在音乐/动作节拍上。每个镜头段标注起始时间码，首段 00:00.000 或省略，后续递增且不超出总时长{duration}秒。切镜不是慢放，切点仍保持动作连续流畅
5. 运镜用 The camera 英文句式自然写入各镜头段：Push In推近 / Pull Out拉远 / Pan Left/Right水平摇 / Truck Left/Right横移 / Tilt Up/Down俯仰 / Arc Shot环绕 / Tracking Shot跟拍 / Static Shot固定 等；每个镜头段一种主运镜，与切镜搭配
6. 动作写成连续流动的一条线：一个动作没结束就长出下一个，任何一帧都不"停住摆姿势"，**every frame in motion / from the first frame（每一帧都在动，首帧即运动）**；【开场即运动】首帧必须是动作正在进行中的瞬间（手已抬起/身体已前倾/武器已挥出），严禁静止站姿开场。【节奏铁律】视频按现实时间正常播放；允许人物缓缓抽手、慢慢转头、轻柔移动等自然表演，动作快慢服从剧情，不将自然缓慢动作当作视频慢放；用**具体动作动词**（猛挥/急冲/连射/反拧/扑/跃/砸/甩——如"急转身/横扫一刀/连发三拳"），不要停在"激烈/爆发"这类抽象词；🔴**环境与主体都在动**：主体运动时，衣物翻飞/尘土溅起/碎屑四溅/水花飞溅/发丝飘动等环境细节要同步写出，防止"主体慢背景僵"的slideshow观感；禁止明确要求视频定格、冻结或静帧；允许蓄势、屏息等自然表演——即使要求写的是"准备、对峙、蓄力"这类静态时刻，也必须改写成正在进行中的动作，否则H3会渲染成冻结帧或慢放
7. 克制聚焦：每个镜头段聚焦该段核心动作/事件，每段2-4句写到位，禁止标签式堆砌细节；总时长内镜头段数量与信息量平衡
8. 节奏恰好适配{duration}秒时长：台词、切点、收尾画面铺满全片；结尾镜头有明确收束画面
9. 绝对禁止"慢动作/慢镜头/升格/子弹时间/slow motion/slo-mo"等一切慢放表述及120fps等高帧率描述
10. 🧩自包含（无上下文）：本镜是独立成片，H3看不见上一镜。凡"在人类看来顺理成章的延续信息"——角色外观/服装/手中物体/所处环境/光线氛围——均须每镜显式写全，不可省略。例：上一镜两人持枪，本镜即使只写"转身对轰"，也必须重申"两人各握黑色手枪"；否则换一镜枪就消失、环境就漂移。禁止用"如前/同上"式省略。只描述本镜画面，不出现"分镜""第N镜"等元语言（[Shot N]与时间码是官方格式标记，允许使用）
11. 直接输出三字段提示词正文，不要任何解释、标题、思考过程或markdown围栏

{refs_block}

【用户创作要求】
{idea}

直接输出提示词："""

def build_single_refs_block(mode, ref_count):
    """按模式构造参考素材说明与图片规则"""
    if mode == 'i2v':
        if ref_count >= 2:
            return ("【参考素材】2张关键帧：<Picture 1>=首帧（视频起始画面），<Picture 2>=尾帧（视频结束画面）",
                    "开头先声明：视频从<Picture 1>的画面开始，保持其构图、主体外貌与场景一致，按动作描述发展，结尾自然过渡到<Picture 2>的画面收束")
        return ("【参考素材】1张首帧图（即<Picture 1>，视频的起始画面）",
                "开头先声明：视频从<Picture 1>的画面开始，保持其构图、主体外貌与场景一致，随后按动作描述发展")
    if mode == 't2v':
        return ("【参考素材】无参考图，纯文本生成",
                "画面描述必须自包含：主体外貌（性别/年龄/发型/服装）、环境、光线全部写清")
    # r2v（最多9张）
    refs = "、".join(f"<Picture {i+1}>" for i in range(max(1, ref_count)))
    return (f"【参考素材】共{ref_count}张参考图：{refs}（图片已附在本消息中，按此顺序，先看图再写提示词）",
            f"开头先声明素材用途与『谁是谁』：使用<Picture 1>作为画面主体身份参考（其余按顺序作为场景/道具/其他角色参考），人物脸、发型、体型、肤色和标志性配饰保持一致；服装以当前镜头 wardrobe 和剧情状态为准，允许换装，场景结构与光线按参考图保持一致；用户要求中的『图1/图2/第一张图』等说法按上传顺序对应<Picture 1>/<Picture 2>…，禁止错位或丢失编号。🎭多人出现时：每个角色始终用同一<Picture N>指代、不中途换称呼，各角色标志性外观要彼此明显区分，并显式写『该角色脸/服装只属于它自己、不与其它角色混合』；避免两角色相近配色。提示词中引用参考图时只允许使用<Picture 1>~<Picture {ref_count}>编号")

def load_h3_workflow(name):
    with open(os.path.join(WORKFLOWS_DIR, f'h3_{name}.json'), 'r', encoding='utf-8') as f:
        return json.load(f)

@dispatch_comfy
def gen_video_single(mode, prompt, ref_paths, duration, seed=None, progress_callback=None):
    """单镜头三模式视频生成。返回(comfy视频元信息dict, err)"""
    prompt = lock_prompt(filter_slow_motion(prompt),runtime_config().get('style'))
    if seed is None:
        seed = random.randint(1, 2**62)
    duration = min(max(8, int(duration)), 15)
    if media_provider() == 'jimeng':
        return gen_video_r2v(
            prompt,
            ref_paths,
            duration=duration,
            seed=seed,
            progress_callback=progress_callback,
        )
    frames = h3_frames_from_duration(duration)
    try:
        if mode == 'r2v':
            # 复用主管线的r2v实现（工作流结构一致）
            vinfo, r2v_err = gen_video_r2v(prompt, ref_paths, duration=duration, seed=seed, progress_callback=progress_callback)
            return (vinfo, None) if vinfo else (None, r2v_err or "r2v生成失败")
        wf = copy.deepcopy(load_h3_workflow(mode))
        if mode == 'i2v':
            if not ref_paths:
                return None, "i2v模式需要上传1张首帧图"
            wf["105:104"]["inputs"]["prompt"] = prompt
            wf["105:104"]["inputs"]["length"] = frames
            wf.pop("105:107", None); wf.pop("105:111", None)
            wf["105:15"]["inputs"]["noise_seed"] = seed
            comfy_name = comfy_upload_image(ref_paths[0])
            wf["114"]["inputs"]["image"] = comfy_name
            # 尾帧（可选）：ref_paths[1] 存在则接入 last_frame
            if len(ref_paths) > 1 and os.path.exists(ref_paths[1]):
                last_name = comfy_upload_image(ref_paths[1])
                wf["900"] = {"inputs": {"image": last_name}, "class_type": "LoadImage", "_meta": {"title": "尾帧"}}
                wf["105:104"]["inputs"]["last_frame"] = ["900", 0]
            # 输出尺寸由115分辨率选择器决定（与全局画幅一致）；119控制首帧缩放像素
            wf["115"]["inputs"]["aspect_ratio"] = runtime_config().get('aspect_ratio', '16:9 (Widescreen)')
            wf["115"]["inputs"]["megapixels"] = runtime_config().get('megapixels', 0.92)
            wf["119"]["inputs"]["megapixels"] = runtime_config().get('megapixels', 0.92)
            wf["105:9"]["inputs"]["steps"] = get_h3_steps()
        else:  # t2v
            wf["105:104"]["inputs"]["prompt"] = prompt
            wf["105:104"]["inputs"]["length"] = frames
            wf.pop("105:107", None); wf.pop("105:111", None)
            wf["105:15"]["inputs"]["noise_seed"] = seed
            wf["115"]["inputs"]["aspect_ratio"] = runtime_config().get('aspect_ratio', '16:9 (Widescreen)')
            wf["115"]["inputs"]["megapixels"] = runtime_config().get('megapixels', 0.92)
            wf["105:9"]["inputs"]["steps"] = get_h3_steps()
        estimated_seconds = max(120, int(duration * 18 + get_h3_steps() * 8))
        history, err = 渲染执行器实例.执行(
            wf,
            task_label=f"MiniMax H3 {mode.upper()} · {duration}s",
            timeout=1800,
            interval=2,
            estimated_seconds=estimated_seconds,
            progress_callback=progress_callback,
        )
        if err:
            return None, err
        videos = []
        for nid, out in history.get('outputs', {}).items():
            for key in ('videos', 'gifs', 'images'):
                for v in out.get(key, []):
                    videos.append(v)
        if not videos:
            return None, "ComfyUI未返回视频"
        return videos[0], None
    except Exception as e:
        return None, str(e)

SINGLE_TASKS = {}  # task_id -> {"status": running/done/error, "msg": str, "video_url": str}
BATCH_RENDER_TASKS = {}
SYNTHESIZING_PROJECTS = set()

def single_shot_worker(task_id, mode, prompt, ref_paths, duration):
    t = SINGLE_TASKS[task_id]
    set_runtime_config(t.get('config') or runtime_config())
    try:
        context = t.get('project_context') or {}
        if context.get('pid'):
            result = _agent_render_selected_shot(context['pid'], int(context['index']), prompt, duration,
                lambda info: t.update(progress=info.get('percent', 0), phase=info.get('phase', '智能体渲染中')),
                allow_disconnected=True)
            t.update(video_url=result['video_url'], local_path=os.path.relpath(result['path'], BASE_DIR),
                     audio_review=result.get('audio_review'), applied=True, msg='智能体重制完成，已放回原镜头', status='done')
            return
        if exclusive_on():
            t['msg'] = "互斥模式：关闭LLM释放显存..."
            stop_local_llm()
        t['msg'] = "检查ComfyUI服务..."
        if not ensure_comfyui():
            t['status'] = 'error'
            t['msg'] = "ComfyUI未运行且内置整合包启动失败"
            return
        t['msg'] = f"MiniMax H3 {mode} 渲染中（约{duration}秒视频，请耐心等待）..."
        def _single_progress(info):
            t['progress'] = info.get('percent', 0)
            t['elapsed'] = info.get('elapsed', 0)
            t['eta'] = info.get('eta', 0)
            t['progress_estimated'] = info.get('estimated', False)
            t['phase'] = info.get('phase', '渲染中')
            t['msg'] = f"{t['phase']} · {t['progress']}%"
            t['updated'] = time.time()
        with (contextlib.nullcontext() if MULTIUSER else GPU_JOB_LOCK):
            vinfo, err = gen_video_single(mode, prompt, ref_paths, duration, progress_callback=_single_progress)
        if err:
            t['status'] = 'error'
            t['msg'] = err
            return
        out_dir = os.path.join(OUTPUTS_DIR, 'single')
        os.makedirs(out_dir, exist_ok=True)
        fname = f"single_{task_id}.mp4"
        save_path = os.path.join(out_dir, fname)
        media_download_video(vinfo, save_path)
        t['status'] = 'done'
        t['msg'] = "生成完成"
        t['video_url'] = f"/file/outputs/single/{fname}"
        t['local_path'] = os.path.join('outputs', 'single', fname)
    except Exception as e:
        t['status'] = 'error'
        t['msg'] = str(e)
    finally:
        clear_runtime_config()

# ============================== 剧本解析（LLM） ==============================
SCRIPT_PARSE_PROMPT = """你是一位顶级短剧编剧兼导演。用户会给你任意形式的创意输入（一句话、故事梗概、场景描述或完整剧本），你必须将其扩写/拆解为一份可直接拍摄的结构化短剧剧本。

【铁律】
1. 动作必须具象化：绝不使用"炫酷、激烈、帅气、霸气"等抽象词，必须写成具体动作（肢体部位+运动方向+发力方式+物理反馈）。例如"打斗激烈"→"他侧身避开直拳，顺势抓住对方手腕反拧到背后，将其压在墙上，地面尘土被脚步带起"
2. 严禁慢放：剧本与描述中绝对禁止"慢动作/慢镜头/升格/子弹时间/slow motion"等任何慢放表述
3. 台词必须中文，口语化、短促有力，符合角色性格
%DURATION_RULE%
%COUNT_RULE%
6. 角色外貌描述必须详细具体（性别、年龄段、人种与面部特征、发型发色、脸型、基础体型、标志性配饰），用于锁定人物身份；服装不是全剧固定制服，必须根据每个镜头的时间、地点、活动和剧情状态变化。特别注意：人种必须根据故事背景明确写出（如中国故事写"中国北方男人，东亚面孔"，欧美故事写"欧美面孔"），不得省略——否则生图模型会默认生成错误人种
7. 每个镜头必须单独填写 wardrobe 字段，写清本镜每个出场角色的具体着装与状态。办公/正式活动穿职业或正式服装，外出按天气和活动换装，居家穿家居服；睡觉、熟睡、卧室夜戏、起床或洗澡后必须穿睡衣/宽松家居服，不得穿西装、皮鞋、领带、工牌或高跟鞋上床。
7. 场景必须细分到具体拍摄点：不要只给一个笼统大场景。若剧情在同一大环境下的不同位置发生（如"街道"与"街道-瓜摊角落"、"房间"与"房间-窗边"），必须拆成多个独立场景条目分别描述，每个场景的构图、光线、关键陈设要具体到可直接出图
8. 关键道具：剧情中反复出现或推动剧情的具体物件（如凶器、信物、食物、交通工具等），必须列入props数组并给出外观描述，后续要生成道具参考图

【输出格式】严格输出一个JSON对象（不要输出其他任何文字、不要用markdown代码块包裹）：
{
  "title": "剧名",
  "synopsis": "一句话剧情简介",
  "characters": [
    {"name": "角色名", "appearance": "详细身份外貌描述（脸型、五官、发型、体型、人种、标志性配饰；不要把单套服装写成全剧固定制服）", "personality": "性格关键词"}
  ],
  "scenes": [
    {"name": "场景名", "description": "纯环境描述：明确室内或室外，具体位置、时间、光线、氛围、建筑风格、关键陈设与静物。场景参考图统一16:9横向宽屏；室内用平视全景，室外用高空鸟瞰全景。只允许环境元素，画面禁止出现任何人物、人群、人影、人体局部及人物倒影，不写人物活动。"}
  ],
  "props": [
    {"name": "道具名", "description": "外观详细描述：材质、颜色、大小、特征（用于生成道具参考图）；无关键道具则输出空数组[]"}
  ],
  "shots": [
    {
      "index": 1,
      "scene": "场景名（必须与scenes中的name一致）",
      "characters": ["本镜所有出场角色名（出场几个写几个）"],
      "props": ["本镜实际使用/特写的道具名（必须与props中的name一致，无则[]）"],
      "wardrobe": "本镜每个出场角色的具体着装、鞋子和穿脱状态；必须与时间、地点、活动一致",
      "camera": "一种运镜（如：固定中景/跟随镜头/环绕镜头/推近特写，只选一种）",
      "action": "该镜头发生的具体动作与画面内容（具象！含表情、肢体、环境互动）",
      "dialogue": [{"speaker": "角色名", "line": "台词", "tone": "语气"}],
      "duration": 8
    }
  ]
}

用户输入：
"""

DIRECTOR_MATCH_OPTIONS = {
    "platform": ["抖音", "快手", "视频号", "小红书", "YouTube Shorts", "通用短视频"],
    "length": ["30", "45", "60", "90", "120"],
    "genre": ["爽剧 / 逆袭", "系统流", "悬疑反转", "都市情感", "搞笑反差", "甜宠", "复仇", "动作冲突", "自定义"],
    "pace": ["快：2~5秒一信息点", "中快：4~7秒一信息点", "剧情：6~10秒一信息点", "电影感：允许长镜头"],
    "hook": ["先给结果，再解释原因", "直接爆发冲突", "一句反常识台词", "巨大金额/身份反差", "危险/悬念瞬间", "情绪崩溃瞬间"],
    "reversal": ["轻：1次小反转", "中：至少2次认知变化", "强：前后身份/局势翻盘"],
    "ending": ["卡在最大悬念，逼追下一集", "本集闭环 + 新危机", "强爽点收尾", "情绪余韵"],
    "dialogue": ["低：画面叙事为主", "中：对白推动剧情", "高：强对白/短句交锋", "无对白"],
    "shot_count": ["auto", "3", "4", "5", "6", "8", "10", "12", "15"],
    "shot_duration": ["auto", "8", "10", "12", "15"],
    "aspect_ratio": ["9:16 (Portrait)", "16:9 (Widescreen)"],
    "style": ["电影写实", "3D动漫", "日漫二次元", "国风水墨", "赛博朋克", "港风胶片"],
}

DIRECTOR_MATCH_DEFAULTS = {
    "platform": "抖音",
    "length": "60",
    "genre": "爽剧 / 逆袭",
    "pace": "中快：4~7秒一信息点",
    "hook": "直接爆发冲突",
    "reversal": "中：至少2次认知变化",
    "ending": "本集闭环 + 新危机",
    "dialogue": "中：对白推动剧情",
    "shot_count": "10",
    "shot_duration": "auto",
    "aspect_ratio": "9:16 (Portrait)",
    "style": "电影写实",
}

def normalize_director_match(data):
    data = data if isinstance(data, dict) else {}
    result = {}
    for key, options in DIRECTOR_MATCH_OPTIONS.items():
        value = str(data.get(key) or "").strip()
        result[key] = value if value in options else DIRECTOR_MATCH_DEFAULTS[key]
    result["payoff"] = str(data.get("payoff") or "").strip()[:240]
    raw_series_mode = data.get("series_mode", False)
    if isinstance(raw_series_mode, str):
        result["series_mode"] = raw_series_mode.strip().lower() in ("1", "true", "yes", "y", "是")
    else:
        result["series_mode"] = bool(raw_series_mode)
    result["reason"] = str(data.get("reason") or "").strip()[:300]
    return result

def parse_json_from_text(text):
    """从LLM输出中提取JSON对象"""
    if not isinstance(text, str):
        return None
    text = text.strip()
    text = re.sub(r'^```(?:json)?\s*', '', text)
    text = re.sub(r'\s*```$', '', text)
    start = text.find('{')
    if start < 0:
        return None
    try:
        value, _ = json.JSONDecoder().raw_decode(text[start:])
        return value if isinstance(value, dict) else None
    except (ValueError, TypeError):
        return None

H3_PROMPT_TEMPLATE = """你是MiniMax H3视频生成模型的提示词专家。MiniMax H3是全模态视频生成模型：一次生成同时产出画面与原生音频（对白、音效、音乐同出）。用户消息里会给你短剧剧本中的一个分镜和它的参考图片（r2v参考图生视频模式）。你需要在内部连续完成两步工作，最终只输出第二步的产物——该镜头的H3提示词。

【参考素材对应关系】（严格遵守编号；图片已附在用户消息中，按此顺序，先看图再写）
{refs_desc}

{audio_bind}

{combat_guidance}

【内部第一步：分镜整理（思考过程，不要输出）】
把分镜信息整理成具象拍摄方案：
1. 动作描述若偏抽象（如"打斗激烈""气氛紧张"），必须转成具体可拍摄方案：谁、用什么武器/招式、如何进攻、对方如何格挡/倒地，写清肢体部位+运动方向+发力方式；招式拆成"起势→发力→击中→收势"的物理步骤；补充物理反馈（衣物飘动/地面尘土/汗水飞溅/受力踉跄/冲击气浪）
2. 禁止照抄分镜原文：即使分镜已比较具体，也要补充细节维度——材质纹理、光影层次、微观细节（汗水/呼吸/衣料摩擦）
3. 分镜中的每句台词及其说话人、语气必须逐字保留，禁止遗漏/改写/翻译
4. 服装连续性必须服从当前镜头的 wardrobe 和剧情状态：人物身份特征连续，但服装可随时间、地点、活动自然更换。若本镜发生在卧室夜晚、睡觉、熟睡、起床、洗澡后或明确居家状态，必须穿睡衣/家居服；禁止把西装、领带、皮鞋、工牌、高跟鞋带入床上睡眠画面
5. 运镜若只写了类型名称，落实为具体执行方式（景别+运动方向+时机）

【内部第二步：生成H3提示词（唯一需要输出的内容）】
把整理好的方案写成严格符合H3官方训练格式的提示词，由以下三个字段组成，按此顺序、各起一段（字段名英文一字不差）：

integrated_multimodal_description: 开头一句定调整体风格与初始构图，随后沿时间轴把本分镜拆成 **2~4 个带标题时间码的镜头段**（[Shot 1] → [Shot 2] → ...），用不同景别/视角/机位呈现动作的推进与关键信息。时长{duration}秒内把切点均匀铺开（首镜头不晚于1秒，末镜头在最后1秒收束）。每个镜头段写清该段画面、主体动作、镜头运动、说话人与台词、同步音效。
overall_soundscape: 用1-3句中文概括本镜环境音、物理动作音、非语言人声（风雨/脚步/布料摩擦/撞击/呼吸等）。对白已写在上个字段，此处禁止重复。
non_diegetic_music: 用1-2句中文描述只有观众能听到的配乐（乐器编制、速度、力度起伏）；开头禁止重锤鼓点；无配乐写 N/A。

【硬性规则】
1. 结构标记与固定术语用英文（字段名、[Shot 1]、时间码、The camera 运镜句式、(S1)说话人ID、<d>台词标签、<Picture N>引用标签）；画面/动作/场景等描述性文字用中文
2. 🔴台词与身份隔离（最高优先级）：台词逐字保留，禁止遗漏、改写、翻译。开头单独写“人物与声线设定，仅用于身份和声音绑定，不朗读”，将角色姓名、年龄、外观、服装、固定声线和参考音色绑定到 <Subject N> (SN) 与实际对应的 <Picture M>；Subject编号不要求等于Picture编号，不得改变参考图顺序。人物介绍不得放在“说：/开口”之后或说话人标记与台词之间。每次发声必须独立成两行：
<Subject 1> (S1) says:
<d>[Chinese]台词原文</d>
按实际说话人替换编号；says: 后立即换行接 <d>，不得夹入姓名、年龄、服装、声线、情绪或参考音色说明。情绪、动作在对白块前另起句，固定声线及 <Audio N> 音色参照只写在开头人物设定中。声明“仅朗读 <d> 标签内的中文正文，人物设定、动作描述和说话人编号均不发声，无旁白”（原作明确要求的画外对白除外）。无台词不写 <d> 段。不要在环境音字段重复台词。标签是生成约束，不是标签外文字绝不会发声的保证。
3. 🎭身份锚定（防止多个角色形象互相污染/混淆）：开头先声明素材用途与"谁是谁"（如"<Picture 1>是角色××、<Picture 2>是角色△△、<Picture 3>是场景"），**同一角色在整条提示词里始终用同一个 <Picture N>/称呼指代，绝不中途更换称呼**。参考图主要锁定该角色的脸、发型、体型、肤色和标志性配饰；本镜服装以 wardrobe 和剧情状态为准，允许且应当随场景换装。🔴**多个角色出现时：每个角色的标志性外观特征要写出且彼此明显区分，并显式写"该角色的脸/服装只属于它自己、不与其它角色混合(do not blend with the other character)"**；避免两个角色穿相近配色/相似服装。每当角色首次出现给足身份特征和本镜服装；正文只补充参考图看不清的细节。编号不得超出素材表范围
4. 🔄切镜（多镜头是H3的最大优势，必须用足，也是抗"慢动作/slideshow"最强手段）：在 {duration} 秒内策划 **2~4 次干净硬切**（hard cut），写法 "[Shot 2] At 00:03.000, the camera cuts to a close-up of ..."。切镜时机=有**新信息**出现时：景别跃迁（全景切特写）、视角换向（正对切侧打）、主体聚焦（两人同框切单人面部）、动作落点（起跳切落地）、节拍重音（配乐爆发处）等。只在距离/角度微调时用连续运镜过渡，不要为微小变化切镜。🔴**硬切必须干净利落、禁止叠化/淡入淡出("cuts clean and hard, no dissolves")——叠化转场正是产生"飘/慢"观感的重灾区**；每镜一段尽量短（动作片1~2秒/段），切点落在音乐/动作节拍上。每个镜头段标注起始时间码，首段时间码为 00:00.000 或省略，后续段时间码必须递增且不超出总时长{duration}秒。切镜不是慢放，切点仍保持动作连续流畅
5. 运镜用 The camera 英文句式自然写入各镜头段：Push In推近 / Pull Out拉远 / Pan Left/Right水平摇 / Truck Left/Right横移 / Tilt Up/Down俯仰 / Arc Shot环绕 / Tracking Shot跟拍 / Static Shot固定 等；每个镜头段一种主运镜，与切镜搭配
6. 动作写成连续流动的一条线：一个动作没结束就长出下一个，任何一帧都不"停住摆姿势"，**every frame in motion / from the first frame（每一帧都在动，首帧即运动）**；【开场即运动】首帧必须是动作正在进行中的瞬间（手已抬起/身体已前倾/武器已挥出），严禁静止状态开场——r2v模型在提示词未明确起始运动时会让开头贴近参考图静止构图，必须规避。【节奏铁律】视频按现实时间正常播放；允许人物缓缓抽手、慢慢转头、轻柔移动等自然表演，动作快慢服从剧情，不将自然缓慢动作当作视频慢放；用**具体动作动词**（猛挥/急冲/连射/反拧/扑/跃/砸/甩——如"急转身/横扫一刀/连发三拳"），不要停在"激烈/爆发"这类抽象词；🔴**环境与主体都在动**：主体运动时，衣物翻飞/尘土溅起/碎屑四溅/水花飞溅/发丝飘动等环境细节要同步写出，防止"主体慢背景僵"的slideshow观感；禁止明确要求视频定格、冻结或静帧；允许蓄势、屏息等自然表演——即使分镜写的是"准备、对峙、蓄力、瞄准"这类静态时刻，也必须改写成正在进行中的动作（脚步已在逼近/武器已在挥舞/身体已在转动/水花正在飞溅），否则H3会渲染成冻结帧或慢放
7. 克制聚焦：每个镜头段聚焦该段核心动作/事件，每段2-4句写到位，禁止标签式堆砌细节；总时长内镜头段数量与信息量平衡
8. 节奏恰好适配{duration}秒时长：台词、切点、收尾画面铺满全片；结尾镜头有明确收束画面
9. 绝对禁止"慢动作/慢镜头/升格/子弹时间/slow motion/slo-mo"等一切慢放表述及120fps等高帧率描述
10. 🧩自包含（无上下文）：本镜是独立成片，H3看不见上一镜。凡"在人类看来顺理成章的延续信息"——角色身份、本镜服装/穿脱状态、手中物体、所处环境、光线氛围——均须每镜显式写全，不可省略。服装以本镜 wardrobe 为准，不要机械复制角色参考图或上一镜服装。若是睡眠场景，必须明确写穿睡衣/家居服、脱下外套鞋子，且无西装、领带、皮鞋、工牌、高跟鞋。禁止用"如前/同上"式省略。只描述本镜画面，不出现"分镜""第N镜"等元语言（[Shot N]与时间码是官方格式标记，允许使用）
11. 直接输出三字段提示词正文，不要任何解释、标题、思考过程或markdown围栏
"""

SEEDANCE_PROMPT_TEMPLATE = """你是 Seedance 2.0 视频生成模型的提示词导演。请把一个短剧分镜整理成可以直接提交给 Seedance 的单条视频提示词。

【参考图顺序，必须完整保留】
{refs_desc}
视频请求会按上述顺序上传全部参考图。提示词中必须明确：
1. 角色参考图只锁定对应角色的脸、发型、体型、肤色、标志性配饰和可见装备；服装以当前镜头 wardrobe 为准，允许按剧情换装；
2. 场景参考图只锁定建筑、空间布局、光线、材质和环境；
3. 道具参考图只锁定对应道具的外形、材质、颜色和位置；
4. 不得把角色、场景、道具相互混合，不得遗漏任何已上传参考图。

【输出格式】
只输出以下中文结构，不要解释、不要 Markdown 围栏：

视频时长：{duration}秒
画面比例：{ratio}
整体风格：...
参考图设定：...
主体与场景：...
动作与表演：...
镜头语言：...
时间线：
00:00-00:XX：...
00:XX-00:XX：...
声音与对白：...
连续性与限制：...

【Seedance 提示词规则】
1. 时间线必须覆盖完整视频时长，至少分成2个连续阶段；每个阶段写清景别、机位、主体动作、镜头运动和环境反馈。
2. 首帧直接进入动作或表演，不写空镜、站立摆拍或无意义等待。
3. 每个角色首次出现必须绑定对应参考图编号；场景和道具也必须绑定对应编号。
4. 角色身份、发型、道具持握、空间方位和光线在时间线中保持连续；服装按当前镜头 wardrobe 和剧情状态连续，允许自然换装。
5. 睡觉、熟睡、卧室夜戏、起床和洗澡后场景必须明确写睡衣或宽松家居服；不得出现穿西装、领带、皮鞋、工牌或高跟鞋躺在床上睡觉。
6. 台词逐字保留，格式为“角色名说：台词”；没有台词就写“无对白”。
7. 动作使用具体动词和因果链：起势、发力、接触、受力、位移、后续动作；禁止只写“很快、很震撼、很激烈”。
8. 运镜使用 Seedance 易执行的自然语言，例如推近、拉远、横移、跟拍、环绕、俯拍、仰拍、切到特写，并说明镜头跟随对象。
9. 不得输出 H3 专属字段 integrated_multimodal_description、overall_soundscape、non_diegetic_music、<d>[Chinese]、<Picture N> 或 The camera。
10. 不得写慢动作、升格、子弹时间、定格、静帧或 slideshow。

【分镜信息】
场景：{scene}
角色：{characters}
道具：{props}
本镜服装与状态：{wardrobe}
运镜：{camera}
动作：{action}
台词：{dialogue}
画风：{style}

请直接输出 Seedance 格式提示词。"""

def load_image_parts(paths, limit=9):
    """读取本地图片构造多模态content parts（data URL），读取失败的跳过"""
    import base64
    parts = []
    for p in (paths or [])[:limit]:
        try:
            ap = p if os.path.isabs(p) else os.path.join(BASE_DIR, p)
            with open(ap, 'rb') as fp:
                b64 = base64.b64encode(fp.read()).decode()
            ext = os.path.splitext(ap)[1].lower().lstrip('.')
            mime = {'png': 'image/png', 'webp': 'image/webp'}.get(ext, 'image/jpeg')
            parts.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}})
        except Exception as e:
            print(f"[H3提示词] 参考图读取失败 {p}: {e}")
    return parts

def enforce_dialogue_boundary(sys_text, user_content, content):
    from infrastructure.dialogue_boundary import dialogue_boundary_errors, normalize_dialogue_boundaries
    content = normalize_dialogue_boundaries(content)
    if not dialogue_boundary_errors(content):
        return content, None
    original_lines = re.findall(r"<d>\s*\[Chinese\](.*?)</d>", content, re.S)
    fixed, error = llm_chat([
        {"role": "system", "content": sys_text},
        {"role": "user", "content": user_content},
        {"role": "assistant", "content": content},
        {"role": "user", "content": "修复对白边界：把姓名、年龄、服装、固定声线与音色参照移到开头独立的不朗读人物设定段，保留Subject/S与Picture实际绑定关系。每句对白严格独立两行：<Subject N> (SN) says: 后立即换行接 <d>[Chinese]台词原文</d>。中间不得插入介绍。逐字保留所有台词及其顺序、说话人和其余镜头内容，输出完整三字段提示词。"},
    ], max_tokens=5000, temperature=0.2)
    if fixed:
        fixed = normalize_dialogue_boundaries(fixed)
        problems = dialogue_boundary_errors(fixed)
        if re.findall(r"<d>\s*\[Chinese\](.*?)</d>", fixed, re.S) != original_lines:
            problems.append("修复结果改写、遗漏或调整了台词顺序")
        if not problems:
            return fixed.strip(), None
        reason = "；".join(problems)
    else:
        reason = error or "模型未返回修复结果"
    # 保存失败正文以便复现，避免只能看到通用报错；不保存图片或请求凭据。
    try:
        diagnostic_dir = os.path.join(BASE_DIR, 'runtime', 'diagnostics', 'dialogue-boundary')
        os.makedirs(diagnostic_dir, mode=0o700, exist_ok=True)
        diagnostic_id = uuid.uuid4().hex[:12]
        diagnostic_path = os.path.join(diagnostic_dir, diagnostic_id + '.json')
        fd = os.open(diagnostic_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as diagnostic:
            json.dump({'original': content, 'repair': fixed, 'reason': reason}, diagnostic, ensure_ascii=False)
        print(f"[H3提示词] 对白失败诊断：{diagnostic_id}")
    except OSError:
        pass
    print(f"[H3提示词] 对白边界修复失败：{reason}")
    return None, f"对白边界修复失败：{reason}。请重新生成本镜提示词"


def repair_missing_dialogue(sys_text, user_content, content, missing):
    """台词缺失时发起一次低温修复调用；修复有效返回新文本，否则保留初稿"""
    fixed, _ = llm_chat([
        {"role": "system", "content": sys_text},
        {"role": "user", "content": user_content},
        {"role": "assistant", "content": content},
        {"role": "user", "content": f"你漏掉了必须逐字保留的台词：{'、'.join(missing)}。请把每句台词逐字用 <d>[Chinese] 台词原文</d> 补入 integrated_multimodal_description 中对应说话人开口的时刻（每句必须由独立的 <Subject N> (SN) says: 行引出，立即换行接 <d>；编号按原说话人保持一致，不得夹入人物介绍），其余内容保持不变，重新输出完整的三字段提示词。"}
    ], max_tokens=4096, temperature=0.3)
    if fixed and all(m in fixed for m in missing):
        return fixed.strip()
    print("[H3提示词] 台词修复后仍缺失，保留初稿")
    return content

def assemble_shot_ref_paths(shot, assets):
    """组装参考图，缺失文件提前报错，避免 Picture 编号错位。"""
    keys = [f"char_{ch}" for ch in shot.get('characters', [])]
    if shot.get('scene'):
        keys.append(f"scene_{shot['scene']}")
    keys.extend(f"prop_{pn}" for pn in shot.get('props', []))
    # 分镜编辑器允许在本镜追加独立参考图。它们按用户添加顺序排在
    # 角色/场景/道具之后，并参与后续提示词和视频渲染。
    keys.extend(str(key) for key in (shot.get('reference_images') or []) if key)
    ref_paths = []
    for key in keys:
        if key not in assets:
            raise ValueError(f"镜头引用的素材不存在：{key}，请补齐素材后重试")
        if len(ref_paths) >= 9:
            continue
        entry = assets[key]
        path = entry.get('path') if isinstance(entry, dict) else None
        resolved = (path if os.path.isabs(path) else os.path.join(BASE_DIR, path)) if path else None
        if not resolved or not os.path.isfile(resolved) or os.path.getsize(resolved) == 0:
            raise ValueError(f"参考图文件缺失或为空：{key}，请重新生成或上传该素材")
        ref_paths.append(resolved)
    return ref_paths

def assemble_shot_audio_paths(shot, assets):
    """组装单镜参考音频（角色音色）：从出场角色里取"已上传参考音色"的音频，按出场顺序编号 <Audio 1>~<Audio 3>。最多3段。
    返回 (audio_paths, audio_roles)。audio_roles: {audio_index_1based: 角色名}，与 audio_paths 顺序一一对应。"""
    aud_paths = []
    audio_roles = {}
    for ch in shot.get('characters', []):
        a = assets.get(f"char_{ch}", {})
        ap = a.get('audio_path') if isinstance(a, dict) else None
        if ap and os.path.exists(ap) and len(aud_paths) < 3:
            aud_paths.append(ap)
            audio_roles[len(aud_paths)] = ch
    return aud_paths[:3], audio_roles

def seedance_video_prompt_enabled():
    return (
        media_provider() == 'jimeng'
        and 'seedance' in str(runtime_config().get('jimeng_video_model') or '').lower()
    )

def gen_shot_seedance_prompt(shot, ref_paths):
    """为即梦 Seedance 模型生成专用提示词，参考图编号与上传顺序严格一致。"""
    refs_desc = []
    for index, path in enumerate((ref_paths or [])[:10], 1):
        name = os.path.basename(path)
        if index <= len(shot.get('characters', [])):
            label = f"角色「{shot.get('characters', [])[index - 1]}」"
        elif index == len(shot.get('characters', [])) + 1 and shot.get('scene'):
            label = f"场景「{shot.get('scene')}」"
        else:
            prop_index = index - len(shot.get('characters', [])) - (1 if shot.get('scene') else 0) - 1
            props = shot.get('props', [])
            label = f"道具「{props[prop_index] if 0 <= prop_index < len(props) else '未命名道具'}」"
        refs_desc.append(f"图{index}（{label}，文件 {name}）")
    duration = int(shot.get('duration') or 8)
    ratio = {
        "16:9 (Widescreen)": "16:9",
        "9:16 (Portrait)": "9:16",
        "1:1 (Square)": "1:1",
        "4:3 (Standard)": "4:3",
    }.get(runtime_config().get('aspect_ratio'), "16:9")
    dialogue = "；".join(
        f"{d.get('speaker', '')}说：{d.get('line', '')}"
        for d in shot.get('dialogue', [])
        if isinstance(d, dict) and d.get('line')
    ) or "无对白"
    system_text = SEEDANCE_PROMPT_TEMPLATE.format(
        refs_desc="\n".join(refs_desc) or "无参考图",
        duration=duration,
        ratio=ratio,
        scene=shot.get('scene', ''),
        characters='、'.join(shot.get('characters', [])) or '无',
        props='、'.join(shot.get('props', [])) or '无',
        wardrobe=shot.get('wardrobe') or '未单独指定：根据场景时间、地点和活动推断合理着装；若为睡眠/卧室夜戏必须使用睡衣或宽松家居服',
        camera=shot.get('camera', ''),
        action=shot.get('action', ''),
        dialogue=dialogue,
        style=reference_style_instruction() or runtime_config().get('style', '电影写实'),
    )
    from agents.script.skills.wardrobe import 服装规则
    system_text += "\n" + style_instruction(runtime_config().get('style'))
    system_text += "\n服装执行规则（按本镜计划落实）：\n" + 服装规则 + "\nwardrobe 是输入字段；最终输出保持当前视频提示词格式，不另输出剧本 JSON。"
    from infrastructure.shot_continuity import continuity_instruction, apply_continuity_intro
    system_text += continuity_instruction(shot)
    content_parts = [{"type": "text", "text": system_text}]
    content_parts.extend(load_image_parts(ref_paths, limit=10))
    content, error = llm_chat(
        [{"role": "user", "content": content_parts}],
        max_tokens=5000,
        temperature=0.45,
        timeout=240,
    )
    if not content:
        return None, error or "Seedance提示词生成失败"
    return apply_continuity_intro(shot, lock_prompt(filter_slow_motion(content.strip()),runtime_config().get('style'))), None

def convert_h3_to_seedance_prompt(prompt, ref_paths, duration):
    """把旧项目缓存的 H3 提示词转换成 Seedance 格式，避免续跑仍提交 H3 字段。"""
    refs = "\n".join(f"图{i}: {os.path.basename(path)}" for i, path in enumerate((ref_paths or [])[:10], 1))
    instruction = f"""请把下面这条 H3 视频提示词改写为 Seedance 2.0 可直接使用的中文提示词。
保留所有角色、场景、道具、动作、镜头、时长和逐字对白；删除 integrated_multimodal_description、
overall_soundscape、non_diegetic_music、<d>[Chinese]、<Picture N>、The camera 等 H3 专属格式。
输出格式固定为：视频时长、画面比例、整体风格、参考图设定、主体与场景、动作与表演、镜头语言、时间线、声音与对白、连续性与限制。
时间线覆盖完整 {duration} 秒，必须明确图1、图2等参考图用途，不要输出解释或 Markdown。

参考图上传顺序：
{refs or '无参考图'}

H3 原提示词：
{prompt}"""
    instruction += '\n'+style_instruction(runtime_config().get('style'))
    parts = [{"type": "text", "text": instruction}]
    parts.extend(load_image_parts(ref_paths, limit=10))
    content, error = llm_chat(
        [{"role": "user", "content": parts}],
        max_tokens=5000,
        temperature=0.35,
        timeout=240,
    )
    if not content:
        return prompt, error
    return lock_prompt(filter_slow_motion(content.strip()),runtime_config().get('style')), None

def gen_shot_h3_prompt_with_retry(shot, refs, check_cancel, event):
    """对白格式失败最多生成三次；保留取消能力，不重试其他服务错误。"""
    for attempt in range(3):
        check_cancel()
        prompt, error = gen_shot_h3_prompt(shot, refs)
        if prompt or not (error and '对白边界修复失败' in error):
            return prompt, error
        if attempt < 2:
            event('shot_status', {'index': shot['index'],
                  'msg': f"第{shot['index']}镜对白格式未通过，自动重新生成（{attempt + 2}/3）"})
    return None, error


def gen_shot_h3_prompt(shot, ref_paths=None, audio_roles=None):
    """用LLM为单个镜头撰写H3 r2v提示词（多模态看图+两步合并+台词兜底+音色绑定）。返回(prompt, err)。
    Picture编号规则与实际渲染时的ref_paths组装顺序严格一致（每镜上限9张）：
    全部出场角色（四宫格三视图）→ 场景 → 道具，按顺序编号。
    audio_roles: dict {audio_index1-based: 角色名}，表示 <Audio N> 对应哪个角色的参考音色"""
    if seedance_video_prompt_enabled():
        return gen_shot_seedance_prompt(shot, ref_paths or [])
    refs_desc_lines = []
    shot_chars = shot.get('characters', [])
    for ch in shot_chars:
        if len(refs_desc_lines) < 9:
            refs_desc_lines.append(f"<Picture {len(refs_desc_lines)+1}> = 角色「{ch}」设定参考图（四宫格三视图，含面部特写与正/背/侧面全身）")
    if shot.get('scene') and len(refs_desc_lines) < 9:
        refs_desc_lines.append(f"<Picture {len(refs_desc_lines)+1}> = 场景「{shot.get('scene','')}」参考图")
    for pn in shot.get('props', []):
        if len(refs_desc_lines) < 9:
            refs_desc_lines.append(f"<Picture {len(refs_desc_lines)+1}> = 道具「{pn}」特写参考图")
    dialogue_text = "；".join([f"{d.get('speaker','')}用{d.get('tone','平静')}的语气说：\"{d.get('line','')}\"" for d in shot.get('dialogue', [])]) or "无台词"
    dialogue_lines = [d.get('line', '').strip() for d in shot.get('dialogue', []) if d.get('line', '').strip()]
    duration = shot.get('duration', 8)
    # 参考音色绑定说明（<Audio N> = 某角色的 voice-timbre reference）
    audio_bind_lines = []
    for idx_1b, ch_name in (audio_roles or {}).items():
        audio_bind_lines.append(f"<Audio {idx_1b}> 是角色「{ch_name}」的参考音色（voice-timbre reference），该角色(Sx)的音色必须参照 <Audio {idx_1b}> 保持一致。")
    audio_desc = ("\n".join(audio_bind_lines)) if audio_bind_lines else ""
    combat_text = " ".join([
        str(shot.get('scene', '')),
        str(shot.get('action', '')),
        str(shot.get('camera', '')),
        str(shot.get('dialogue', '')),
    ])
    skill_mode = 获取提示词技能模式(combat_text)
    combat_guidance = 构造提示词技能规则(shot)
    dialogue_guidance = ""
    sys_text = (H3_PROMPT_TEMPLATE
                .replace('{refs_desc}', "\n".join(refs_desc_lines))
                .replace('{audio_bind}', audio_desc)
                .replace('{combat_guidance}', combat_guidance + ("\n\n" + dialogue_guidance if dialogue_guidance else ""))
                .replace('{duration}', str(duration)))
    from agents.script.skills.wardrobe import 服装规则
    sys_text += "\n" + style_instruction(runtime_config().get('style'))
    sys_text += "\n服装执行规则（按本镜计划落实）：\n" + 服装规则 + "\nwardrobe 是输入字段；最终输出保持当前视频提示词格式，不另输出剧本 JSON。"
    user_text = (f"【分镜信息】\n场景：{shot.get('scene', '')}\n出场角色：{'、'.join(shot_chars)}\n"
                 f"本镜服装与状态：{shot.get('wardrobe') or '未单独指定：根据场景时间、地点和活动推断；睡眠/卧室夜戏必须穿睡衣或宽松家居服'}\n"
                 f"运镜：{shot.get('camera', '固定中景')}\n动作：{shot.get('action', '')}\n"
                 f"台词：{dialogue_text}\n时长：{duration}秒\n\n请按系统要求生成该镜头的H3提示词。")
    from infrastructure.shot_continuity import continuity_instruction
    user_text += continuity_instruction(shot)
    user_content = [{"type": "text", "text": user_text}] + load_image_parts(ref_paths)
    content, err = llm_chat([
        {"role": "system", "content": sys_text},
        {"role": "user", "content": user_content}
    ], max_tokens=4096, temperature=0.6)
    if not content:
        return None, err
    content = content.strip()
    missing = [ln for ln in dialogue_lines if ln not in content]
    if missing:
        print(f"[H3提示词] 台词缺失，触发修复: {missing}")
        content = repair_missing_dialogue(sys_text, user_content, content, missing)
    content, error = enforce_dialogue_boundary(sys_text, user_content, content)
    if error:
        return None, error
    from infrastructure.shot_continuity import apply_continuity_intro
    return apply_continuity_intro(shot, lock_prompt(content,runtime_config().get('style'))), None


# ============================== AI自动审片 ==============================
SHOT_REVIEW_PROMPT = """你是短剧视频质检导演。你会看到该分镜生成视频抽取的关键帧，以及少量角色/场景参考图。
请只输出JSON：
{
  "score": 0-100,
  "identity": 0-100,
  "continuity": 0-100,
  "composition": 0-100,
  "action": 0-100,
  "artifacts": 0-100,
  "dialogue_visual_fit": 0-100,
  "problems": ["具体问题"],
  "fix_prompt_addendum": "用于下一次H3重渲染的简短修复约束，禁止写慢动作"
}
服装以本镜 wardrobe 和明确剧情为准；角色参考图只用于核对身份，合理换装不得扣角色一致性分。检查服装是否适合时间、活动和故事年代，同一镜内款式、颜色和污损状态不得无因跳变。修复约束写明正确的本镜着装，禁止强制恢复参考图服装。
画风检查：对照参考图分别检查男女角色与环境是否保持同一种渲染媒介；3D项目检查动画建模比例、皮肤着色、发束和道具材质，防止一人动画一人真人或后段转写实。角色身份和年龄不能为增强卡通感而改变；遮挡与证据不足明确说明，不猜测。
评分重点：角色脸/发型是否漂移；服装是否符合本镜计划；多人是否串脸/融脸；手脚/物体是否畸变；动作是否像静帧或幻灯片；
镜头是否符合剧情动作；构图是否清楚；同一镜内场景是否跳变。artifacts分数越高代表瑕疵越少。
不要因为电影风格、景深、运动模糊本身扣分。"""

def extract_review_frames(video_path, count=None):
    count = max(2, min(int(count or runtime_config().get('review_frame_count', 3)), 5))
    ffmpeg = find_ffmpeg()
    if not ffmpeg or not video_path or not os.path.exists(video_path):
        return []
    review_dir = os.path.join(REVIEWS_DIR, uuid.uuid4().hex[:10])
    os.makedirs(review_dir, exist_ok=True)
    # fps=1/count并不可靠知道时长；使用thumbnail均匀抽代表帧
    out_pat = os.path.join(review_dir, 'frame_%02d.jpg')
    vf = "thumbnail=48,setpts=N/TB"
    cmd = [ffmpeg, '-y', '-i', video_path, '-vf', vf, '-frames:v', str(count), '-q:v', '2', out_pat]
    try:
        FFMPEG执行器实例.执行(cmd, timeout=120)
    except Exception:
        return []
    frames = sorted(str(p) for p in Path(review_dir).glob('frame_*.jpg'))
    return frames[:count]

def review_shot_video(shot, video_path, ref_paths=None):
    if not runtime_config().get('auto_review'):
        return None, None
    ap = video_path if os.path.isabs(video_path or '') else _safe_join_under(BASE_DIR, video_path or '')
    frames = extract_review_frames(ap)
    if not frames:
        return None, "抽帧失败"

    switched = False
    # 低显存互斥模式下：审片需要视觉LLM，先释放ComfyUI显存；审完再恢复ComfyUI供后续镜头继续渲染。
    if exclusive_on():
        with SERVICE_SWITCH_LOCK:
            stop_comfyui()
            ok, serr = ensure_local_llm()
            if not ok:
                return None, f"审片LLM启动失败: {serr}"
            switched = True
    try:
        parts = [{"type": "text", "text":
                 f"分镜动作：{shot.get('action','')}\n运镜：{shot.get('camera','')}\n"
                 f"角色：{'、'.join(shot.get('characters',[]))}\n场景：{shot.get('scene','')}\n"
                 f"本镜服装计划：{shot.get('wardrobe') or '未指定，按剧情判断，勿强制照搬参考图'}\n"
                 "前面的图片优先视为生成视频关键帧；后面的图片是参考设定。请按系统评分。"}]
        parts += load_image_parts(frames, limit=5)
        parts += load_image_parts((ref_paths or [])[:3], limit=3)
        content, err = llm_chat([
            {"role": "system", "content": SHOT_REVIEW_PROMPT},
            {"role": "user", "content": parts}
        ], max_tokens=1200, temperature=0.2)
        if not content:
            return None, err
        data = parse_json_from_text(content)
        if not data:
            return None, "审片模型返回非JSON"
        try:
            data['score'] = max(0, min(100, int(float(data.get('score', 0)))))
        except Exception:
            data['score'] = 0
        from infrastructure.audio_review import review as review_audio
        data['audio_review'] = review_audio(sys.modules[__name__], shot, ap)
        return data, None
    finally:
        if switched:
            with SERVICE_SWITCH_LOCK:
                stop_local_llm()
                ensure_comfyui()

def save_shot_review(pid, idx, review):
    proj = load_project(pid)
    if not proj:
        return
    proj.setdefault('reviews', {})[str(idx)] = review
    save_project(proj)

# ============================== 项目管理 ==============================
RACE_KEYWORDS = ['中国', '东亚', '亚洲', '华人', '华裔', '欧美', '西方', '欧洲', '美洲', '美国',
                 '非洲', '黑人', '白人', '拉丁', '印度', '中东', '阿拉伯', '日本', '韩国', '日韩', '东南亚', '俄罗斯']

def ensure_race_desc(appearance):
    """生图模型对未指明人种的角色默认偏欧美面孔。
    外貌描述若未含任何人种关键词，兜底注入东亚面孔（本产品主要面向中文故事）"""
    if any(k in appearance for k in RACE_KEYWORDS):
        return appearance
    return f"东亚面孔（中国人），{appearance}"

# 场景描述人物词清理：T2I模型对"不要人物"中的"人物"反而敏感，需从描述中物理剔除人物相关短句
# 注意：不收"居民"(误伤居民楼)等强建筑相关词；"保安"会误伤保安亭但宁可删细节也不留人物
SCENE_HUMAN_RE = re.compile(
    r'[^，。；、]*?(?:人物|角色|行人|人群|路人|顾客|观众|男人|女人|老人|小孩|男孩|女孩|人们|身影|人影|游客'
    r'|男子|女子|男士|女士|少年|少女|青年|婴儿|孩童|大人|摊主|老板|伙计|司机|店员|工人|农民|医生|护士'
    r'|警察|老师|学生|商人|客人|主人|服务员|厨师|助手|推销员|小贩|骑手|保安)[^，。；、]*[，。；、]?')

def sanitize_scene_text(desc, char_names=None):
    """剔除场景描述中的人物相关短句与角色名，只留纯环境描述（用于场景空镜生图）"""
    if not desc:
        return desc
    cleaned = desc
    for name in (char_names or []):
        if name:
            cleaned = cleaned.replace(name, '')
    cleaned = SCENE_HUMAN_RE.sub('', cleaned)
    cleaned = re.sub(r'[，、]{2,}', '，', cleaned)
    cleaned = re.sub(r'[。]{2,}', '。', cleaned)
    return cleaned.strip('，。 ')

def character_reference_is_landscape(path):
    """Validate actual image pixels, independently of project/video aspect ratio."""
    from PIL import Image
    try:
        with Image.open(path) as image:
            width, height = image.size
            return width > height and abs(width / height - 16 / 9) < 0.06
    except (OSError, ValueError, TypeError):
        return False


SCENE_REFERENCE_RULE = (
    "【场景参考图要求】画布必须为16:9横向宽屏，纯环境空镜。"
    "画面禁止出现任何人物、角色、行人、人群、人影、人体局部以及镜面或玻璃中的人物倒影。"
    "根据当前场景的实际室内外属性选择唯一视角：室内使用平视全景，摄影机保持水平，"
    "清楚呈现空间布局与陈设；室外使用高空鸟瞰全景，俯视展现建筑、地形、道路和环境布局。"
    "只表现环境空间、建筑与静物，不呈现人物活动。以上画幅、无人和视角要求优先于旧提示词中的冲突描述。"
)


def gen_asset_image(kind, name, desc, style, characters=None, seed=None, prompt=None, image_model=None):
    """为单个资产(角色/场景/道具)生成参考图，复用管线内同款prompt逻辑。
    返回 (path, prompt, err)。kind ∈ char/scene/prop；desc 为对应描述(appearance/description)。
    传入 prompt 时沿用用户编辑内容，并补充对应资产的画幅与场景约束；否则自动构造。
    该函数被主管线阶段2与"重新生成单张资产/资产提示词重生成"接口共用，保证产物风格一致。"""
    if not prompt:
        if kind in ('char', 'character'):
            prompt = (f"{style}风格，16:9横屏角色设定参考图，单行四栏排版：画面从左到右均分为4个竖向分格——"
                      f"第1格：角色面部特写（五官清晰、表情中性、直视镜头）；"
                      f"第2格：同一角色全身正面站立照；第3格：同一角色全身背面站立照；第4格：同一角色全身侧面站立照。"
                      f"角色身份设定：{ensure_race_desc(desc)}。"
                      f"四个分格中角色的脸型、发型、体型、肤色和标志性配饰必须完全一致；四栏保持同一套服装，三个全身视图均从头到脚完整入画，纯色素净背景，站姿端正，画质精美，细节丰富。")
        elif kind == 'scene':
            cleaned = sanitize_scene_text(desc, [c.get('name', '') for c in (characters or [])])
            prompt = (f"{style}风格，16:9横向宽屏空场景环境概念设计图，场景：{name}。{cleaned}。"
                      f"完整展现空间的布局与结构，视野开阔，构图大气，"
                      f"光影考究，环境细节丰富，静态陈设清晰完整。画面内容为纯粹的环境空间与静物。画质精美。")
        else:  # prop
            prompt = f"{style}风格，关键道具特写参考图（无人物）。{desc}。纯色素净背景，道具居中完整展示，材质纹理细节清晰，画质精美。"
    reference_path = None
    reference_id = runtime_config().get('asset_reference_id')
    if reference_id:
        try:
            reference_path = GENERATION_REFERENCES.resolve(reference_id, runtime_config().get('_owner_id'))
        except ValueError as exc:
            return None, prompt, str(exc)
        # The supplied image determines visual medium; avoid contradictory global style locks.
        prompt = prompt.replace(f'{style}风格，', '')
        prompt = reference_prompt(kind, name, desc, prompt)
        try:
            prompt = lock_prompt(prompt, style)
        except ValueError as exc:
            return None, prompt, str(exc)
    else:
        prompt = lock_prompt(prompt,style)
    image_size = {'width': 1280, 'height': 720} if kind in ('char', 'character', 'scene') else {}
    if kind in ('char', 'character'):
        prompt += "。画布必须为16:9横向角色参考图，四个视图从左至右单行排列，禁止竖向画布。"
    elif kind == 'scene':
        prompt = prompt.replace(SCENE_REFERENCE_RULE, '').rstrip() + '\n' + SCENE_REFERENCE_RULE
    path, err = gen_image(prompt, seed=seed, image_model=image_model, reference_path=reference_path, **image_size)
    if not err and kind in ('char', 'character') and not character_reference_is_landscape(path):
        return None, prompt, "角色参考图实际尺寸不符合横向16:9要求，未接受该图片，请重新生成"
    if not err and kind == 'scene' and not character_reference_is_landscape(path):
        return None, prompt, "场景参考图实际尺寸不符合横向16:9要求，未接受该图片，请重新生成"
    return path, prompt, err


def _script_asset_description(script, kind, name):
    """从新旧剧本结构中查找资产描述。

    普通项目使用列表格式（[{"name": "...", ...}]），连续剧/智能体
    相关数据也可能使用按名称索引的字典格式（{"角色名": {...}}）。
    """
    pool_map = {'char': 'characters', 'character': 'characters',
                'scene': 'scenes', 'prop': 'props'}
    pool = (script or {}).get(pool_map.get(kind, 'characters'), [])
    if isinstance(pool, dict):
        candidates = list(pool.values())
        direct = pool.get(name)
        if isinstance(direct, dict):
            candidates.insert(0, direct)
    elif isinstance(pool, list):
        candidates = pool
    else:
        candidates = []

    target = str(name or '').strip()
    for item in candidates:
        if not isinstance(item, dict):
            continue
        item_name = str(item.get('name') or '').strip()
        if item_name != target:
            continue
        return str(item.get('appearance') or item.get('description') or '').strip()
    return ''


from core.reference_sync import reference_edit_wait
from core.final_video import available_final, invalidate_final
from core.edit_archive import archive_edit


@reference_edit_wait
def _manual_wait_all_assets(pid, send, assets):
    send('assets_ready', {'assets': assets})
    while True:
        if pipeline_cancelled(pid):
            raise PipelineCancelled()
        project = load_project(pid) or {}
        if (project.get('asset_confirm') or {}).get('__all__', {}).get('continue'):
            return
        time.sleep(1)


@reference_edit_wait
def _manual_wait_asset(pid, key, send):
    """手动模式下，资产生成后暂停等待用户确认/编辑提示词重生成。
    用户满意后点"继续"（asset_confirm[key].continue=True）通过；超时(1小时)视为通过。"""
    a = (load_project(pid) or {}).get('assets', {}).get(key, {})
    send('asset_confirm_wait', {"key": key,
                               "url": f"/file/assets/{os.path.basename(a.get('path', ''))}" if a.get('path') else "",
                               "prompt": a.get('prompt', '')})
    wait_start = time.time()
    while True:
        time.sleep(1.5)
        if pipeline_cancelled(pid):
            raise PipelineCancelled()
        fresh = load_project(pid)
        c = (fresh or {}).get('asset_confirm', {}).get(key)
        if c and c.get('continue'):
            return True
        if time.time() - wait_start > 3600:
            return True  # 等待超时自动放行，不阻塞流程
    return True


@reference_edit_wait
def _manual_wait_shot_prompt(pid, idx, prompt, duration, send):
    """手动模式下：某镜提示词先展示给用户，等待用户修改后确认，再继续真正渲染。
    返回最终确认后的提示词；若等待超时则回退为原提示词自动继续。"""
    camera = next((s.get('camera', '') for s in ((load_project(pid) or {}).get('script') or {}).get('shots', []) if s.get('index') == idx), '')
    send('shot_prompt_ready', {"index": idx, "prompt": prompt, "duration": duration, "camera": camera})
    wait_start = time.time()
    while True:
        time.sleep(1.0)
        if pipeline_cancelled(pid):
            raise PipelineCancelled()
        fresh = load_project(pid) or {}
        conf = (fresh.get('shot_confirm') or {}).get(str(idx))
        if conf and conf.get('confirmed'):
            final_prompt = (conf.get('prompt') or '').strip() or prompt
            return filter_slow_motion(final_prompt)
        if time.time() - wait_start > 86400:
            return prompt  # 24小时仍未确认则沿用原提示词继续，避免流程永久卡住

@reference_edit_wait
def _manual_wait_shot_review(pid, idx, send):
    """手动模式下，分镜视频渲染完成后暂停等待用户复查。
    用户满意后点"满意，下一镜"（shot_confirm[idx].reviewed=True）通过；超时(1小时)视为通过。"""
    proj = load_project(pid)
    if (proj or {}).get('shot_confirm', {}).get(str(idx), {}).get('reviewed'):
        return True
    target = next((s for s in (proj or {}).get('shots', []) if s.get('index') == idx), None) or {}
    send('shot_video_ready', {"index": idx, "video_url": target.get('video_url'), "prompt": target.get('prompt', '')})
    wait_start = time.time()
    while True:
        time.sleep(1.5)
        if pipeline_cancelled(pid):
            raise PipelineCancelled()
        fresh = load_project(pid)
        c = (fresh or {}).get('shot_confirm', {}).get(str(idx))
        if c and c.get('reviewed'):
            return True
        if time.time() - wait_start > 3600:
            return True  # 等待超时自动放行
    return True

def describe_uploaded_asset(img_path, kind, name):
    """用户上传自定义参考图后，用视觉LLM分析图片重写外观描述（后续提示词以图为准而非原文字设计）。
    返回(描述, err)；视觉调用失败时返回(None, err)，调用方保留原描述兜底。"""
    import base64
    try:
        with open(img_path, 'rb') as f:
            b64 = base64.b64encode(f.read()).decode()
    except Exception as e:
        return None, f"读图失败: {e}"
    ext = img_path.rsplit('.', 1)[-1].lower()
    mime = {'png': 'image/png', 'jpg': 'image/jpeg', 'jpeg': 'image/jpeg', 'webp': 'image/webp'}.get(ext, 'image/png')
    if kind in ('char', 'character'):
        ask = (f"这是短剧角色「{name}」的设定参考图。请详细描述图中人物的外貌：人种、年龄段、发型发色、"
               f"面部特征、服装款式与颜色、体型、气质。只输出描述文字本身，100字以内。")
    elif kind == 'scene':
        ask = (f"这是短剧场景「{name}」的参考图。请详细描述图中环境：建筑风格、年代感、光线、色调、"
               f"陈设布局、氛围。只描述环境本身，只输出描述文字本身，80字以内。")
    else:
        ask = (f"这是短剧道具「{name}」的参考图。请详细描述图中物体的外观：形状、颜色、材质、年代感、"
               f"显著细节。只输出描述文字本身，50字以内。")
    messages = [{"role": "user", "content": [
        {"type": "text", "text": ask},
        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}
    ]}]
    desc, err = llm_chat(messages, max_tokens=300, temperature=0.3)
    if err:
        return None, err
    return desc, None


def 提取图片文字(image_path):
    """按图片自然阅读顺序提取文字，专门处理用户上传的长图。

    返回(文字, 错误)。不做总结或改写，模糊字符由模型明确标注。
    """
    import base64

    try:
        with open(image_path, "rb") as image_file:
            image_data = base64.b64encode(image_file.read()).decode("ascii")
    except Exception as exc:
        return None, f"读取图片失败: {exc}"

    ext = os.path.splitext(image_path)[1].lower().lstrip(".")
    mime = {
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "webp": "image/webp",
    }.get(ext, "image/jpeg")
    prompt = """请提取这张图片中的全部可见文字，供用户作为短剧故事梗概继续编辑。
这是可能很长的竖向长图，请从最上方开始，按自然阅读顺序逐段读到最下方，
不要跳过中间区域，也不要重复任何段落。保留标题、段落、列表、对白、数字、
人名、标点和原有换行。只输出识别到的文字，不要总结、翻译、解释或改写。
无法确认的字符请使用[不清]标记，禁止根据上下文猜测。图片边缘被裁切的内容不要补写。"""
    content, error = llm_chat(
        [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {
                    "url": f"data:{mime};base64,{image_data}"
                }},
            ],
        }],
        max_tokens=8000,
        temperature=0.1,
        timeout=240,
    )
    if error:
        return None, error
    text = re.sub(r"^\s*```(?:text|markdown)?\s*|\s*```\s*$", "", content or "", flags=re.I).strip()
    if not text:
        return None, "图片中没有识别到可用文字"
    return text, None

def project_path(pid):
    return 项目服务实例.路径(pid)

def project_assets_dir(pid):
    return 项目服务实例.资产目录(pid)

def asset_file_url(pid, path):
    return 项目服务实例.资产URL(pid, path)


def _asset_version_dir(pid, key):
    safe_key = re.sub(r'[^\w.-]+', '_', str(key or 'asset'), flags=re.UNICODE).strip('._') or 'asset'
    return os.path.join(OUTPUTS_DIR, str(pid), 'assets', 'versions', safe_key)


def _asset_path(path):
    if not path:
        return ''
    candidate = path if os.path.isabs(path) else os.path.join(BASE_DIR, path)
    return os.path.normpath(candidate)


def _archive_asset_version(proj, key, entry, label='图片版本'):
    """把资产当前文件复制到项目专属版本目录，避免重生成后旧图丢失。"""
    source = _asset_path((entry or {}).get('path'))
    if not source or not os.path.isfile(source):
        return None
    version_id = f"v{int(time.time())}_{uuid.uuid4().hex[:6]}"
    version_dir = _asset_version_dir(proj.get('id', ''), key)
    os.makedirs(version_dir, exist_ok=True)
    filename = f"{version_id}{os.path.splitext(source)[1] or '.png'}"
    destination = os.path.join(version_dir, filename)
    try:
        shutil.copyfile(source, destination)
    except (OSError, shutil.Error) as exc:
        print(f"[资产版本] 跳过归档 {proj.get('id')}/{key}: {exc}", flush=True)
        return None
    version = {
        "id": version_id,
        "created": time.time(),
        "label": label,
        "filename": filename,
        "url": f"/file/outputs/{proj.get('id')}/assets/versions/{os.path.basename(version_dir)}/{filename}",
        "path": destination,
        "prompt": (entry or {}).get("prompt", ""),
        "kind": (entry or {}).get("kind", ""),
    }
    versions = proj.setdefault("asset_versions", {}).setdefault(str(key), [])
    versions.append(version)
    return version


def _asset_versions(proj, key):
    versions = list((proj.get('asset_versions') or {}).get(str(key), []))
    return sorted(versions, key=lambda item: item.get('created', 0), reverse=True)

def save_project(proj):
    if MULTIUSER:
        MULTIUSER.bind_document("project", proj)
    result = 项目服务实例.保存(proj)
    if proj.get('previous_final') and not proj.get('final'):
        _sync_series_episode_final(proj)
    return result

def load_project(pid):
    if MULTIUSER and not MULTIUSER.visible("project", pid):
        return None
    return 项目服务实例.加载(pid)


REMAKE_MODES = {
    "full": "完整重做",
    "script": "从剧本开始",
    "asset": "从资产开始",
    "video": "从分镜视频开始",
}

def _remake_mode(value):
    value = str(value or "full").strip().lower()
    return value if value in REMAKE_MODES else "full"

def _remake_title(title):
    title = str(title or "未命名短片").strip() or "未命名短片"
    return f"{title}（重做版）"

def _rewrite_project_output_paths(value, old_root, new_root):
    """复制项目专属 assets 后，把 JSON 中仍指向旧项目目录的路径切到新目录。"""
    if isinstance(value, dict):
        return {key: _rewrite_project_output_paths(item, old_root, new_root) for key, item in value.items()}
    if isinstance(value, list):
        return [_rewrite_project_output_paths(item, old_root, new_root) for item in value]
    if isinstance(value, str) and value.startswith(old_root):
        return new_root + value[len(old_root):]
    return value

def _clone_project_for_remake(source, mode="full", title_suffix=True, series_override=None):
    """复制一个短片项目并按阶段清理生成结果；不会改动源项目。"""
    mode = _remake_mode(mode)
    source_id = str(source.get("id") or "")
    new_id = uuid.uuid4().hex[:12]
    clone = copy.deepcopy(source)
    clone["id"] = new_id
    clone["created"] = time.time()
    clone["updated"] = time.time()
    clone["title"] = _remake_title(source.get("title")) if title_suffix else source.get("title", "")
    clone["remake_of"] = source_id
    clone["remake_mode"] = mode
    clone["run_id"] = None
    clone["final"] = None
    clone.pop("previous_final", None)
    clone["shots"] = []
    clone["reviews"] = {}
    clone["shot_versions"] = {}
    clone["shot_confirm"] = {}
    clone["script_review"] = {}
    clone["运行记录"] = []
    clone["智能体记录"] = []
    clone["优化历史"] = []
    clone["协同状态"] = {}
    clone["智能体通信记录"] = []
    clone["技能调用记录"] = []
    clone["智能体决策记录"] = []

    if mode in ("full", "script"):
        clone["script"] = None
        clone["assets"] = {}
        clone["assets_confirmed"] = False
        render_config = clone.get("render_config") or {}
        clone["script_confirmed"] = False
        clone["script_review_required"] = bool(render_config.get("script_review_mode", True))
    elif mode == "asset":
        clone["assets"] = {}
        clone["assets_confirmed"] = False
        clone["script_confirmed"] = True
        clone["script_review_required"] = False
    else:
        clone["script_confirmed"] = True
        clone["script_review_required"] = False

    if isinstance(clone.get("script"), dict):
        clone["script"]["title"] = clone["title"]
    if series_override:
        clone["series"] = copy.deepcopy(series_override)

    old_output_root = os.path.abspath(os.path.join(OUTPUTS_DIR, source_id))
    new_output_root = os.path.abspath(os.path.join(OUTPUTS_DIR, new_id))
    old_assets_dir = os.path.join(old_output_root, "assets")
    new_assets_dir = os.path.join(new_output_root, "assets")
    preserve_assets = mode in ("video",)
    if preserve_assets and os.path.isdir(old_assets_dir):
        os.makedirs(new_output_root, exist_ok=True)
        shutil.copytree(old_assets_dir, new_assets_dir, dirs_exist_ok=True)
        clone = _rewrite_project_output_paths(clone, old_output_root, new_output_root)

    save_project(clone)
    return clone


def _shot_target(proj, index):
    return 项目服务实例.镜头(proj, index)


def _canonical_shot_path(pid, index):
    return 项目服务实例.当前镜头路径(pid, index)


def _version_file_url(pid, index, filename):
    return 项目服务实例.版本URL(pid, index, filename)


def _archive_current_shot_version(proj, index, label='生成版本', force_new=False):
    return 项目服务实例.归档当前版本(proj, index, label=label, force_new=force_new)


def _archive_before_overwrite(proj, index):
    return 项目服务实例.覆盖前归档(proj, index)


def _archive_after_render(proj, index, label='新生成'):
    return 项目服务实例.渲染后归档(proj, index, label=label)


def _sync_current_shot_metadata(proj, index, prompt=None, duration=None, camera=None):
    return 项目服务实例.同步镜头元数据(
        proj,
        index,
        prompt=prompt,
        duration=duration,
        camera=camera,
    )


def render_project_shot(
    project=None,
    pid=None,
    index=None,
    prompt=None,
    duration=None,
    camera=None,
    progress_callback=None,
    video_model=None,
    allow_disconnected=False,
):
    """渲染并保存一个项目镜头，供渲染 Agent 和外部编排器调用。"""
    if not isinstance(project, dict):
        project = load_project(pid) if pid else None
    if not project:
        raise ValueError("项目不存在")

    pid = str(pid or project.get("id") or "").strip()
    if not pid:
        raise ValueError("项目缺少 id")
    try:
        index = int(index)
    except (TypeError, ValueError):
        raise ValueError("缺少有效的镜头编号")
    if index < 1:
        raise ValueError("镜头编号必须大于 0")

    script_shots = (project.get("script") or {}).get("shots") or []
    script_shot = next((shot for shot in script_shots if shot.get("index") == index), None)
    current_shot = 项目服务实例.镜头(project, index)
    if not current_shot and script_shot:
        current_shot = copy.deepcopy(script_shot)
        project.setdefault("shots", []).append(current_shot)
    if not current_shot:
        raise ValueError(f"镜头{index}不存在")
    # 失败/旧版本镜头记录通常只保存 prompt、refs 和 error，
    # 不一定带有 script 中的 characters/scene/props。渲染续跑时要用
    # 剧本镜头补齐这些引用字段，否则会误报“无可用参考图”。
    shot_for_refs = copy.deepcopy(script_shot or {})
    shot_for_refs.update(current_shot)

    render_prompt = (
        prompt
        or current_shot.get("prompt")
        or (project.get("prompts") or {}).get(str(index))
        or (script_shot or {}).get("prompt")
        or ""
    ).strip()
    if not render_prompt:
        raise ValueError(f"镜头{index}缺少 H3 提示词")
    render_prompt = filter_slow_motion(render_prompt)

    if duration is None:
        duration = current_shot.get("duration", (script_shot or {}).get("duration", 8))
    try:
        duration = max(8, min(int(duration), 15))
    except (TypeError, ValueError):
        duration = 8
    render_camera = camera if camera is not None else current_shot.get("camera", "")
    from core.reference_sync import require_synced
    if not allow_disconnected:
        require_synced(project, [index])
    assets = project.get("assets") or {}
    refs = assemble_shot_ref_paths(shot_for_refs, assets)
    if not refs:
        raise ValueError("无可用参考图（请检查角色/场景参考图是否已生成）")
    audio_paths, _audio_roles = assemble_shot_audio_paths(shot_for_refs, assets)
    from infrastructure.agent_continuity import render_references
    if allow_disconnected:
        handoff = None
    else:
        render_prompt, refs, handoff = render_references(sys.modules[__name__], project, script_shot or {}, render_prompt, refs)


    out_dir = os.path.join(OUTPUTS_DIR, pid)
    video_path = os.path.join(out_dir, f"shot_{index:02d}.mp4")
    os.makedirs(out_dir, exist_ok=True)
    parent_runtime_config = getattr(_RUNTIME, 'config', None)
    set_runtime_config(project_render_config(project))
    try:
        render_lock = (
            contextlib.nullcontext()
            if not runtime_config().get("exclusive_mode") or MULTIUSER or getattr(_RUNTIME, "comfy_server_url", "")
            else GPU_JOB_LOCK
        )
        with render_lock:
            # 在覆盖规范文件前先把当前可用视频保存为历史版本。
            with PROJECT_IO_LOCK:
                project = load_project(pid) or project
                _archive_before_overwrite(project, index)
                save_project(project)

            from infrastructure.style_first_frame import use_first_frame, prepare, i2v_prompt
            first_frame_record = None
            if use_first_frame(runtime_config(), script_shot or {}, audio_paths):
                first_frame_record = prepare(sys.modules[__name__], project, script_shot or {}, render_prompt, refs, out_dir)
                render_prompt = i2v_prompt(render_prompt)
                video_info, save_name = gen_video_single(
                    'i2v', render_prompt, [first_frame_record['path']], duration,
                    progress_callback=progress_callback,
                )
            else:
                video_info, save_name = gen_video_r2v(
                    render_prompt,
                    refs,
                    duration=duration,
                    save_name=f"shot_{index:02d}.mp4",
                    ref_audio_paths=audio_paths,
                    video_model=video_model,
                    progress_callback=progress_callback,
                )
            if video_info is None:
                raise RuntimeError(f"渲染失败: {save_name}")

            media_download_video(video_info, video_path)
            if not os.path.isfile(video_path) or os.path.getsize(video_path) <= 0:
                raise RuntimeError("视频下载失败或文件为空")

            if progress_callback:
                progress_callback({'percent': 99, 'phase': '语音转写与听音质检', 'elapsed': 0, 'eta': 0})
            from infrastructure.audio_review import review as review_audio
            audio_report = review_audio(sys.modules[__name__], script_shot or {}, video_path)
            from infrastructure.agent_continuity import review_boundary
            try:
                boundary = review_boundary(sys.modules[__name__], (load_project(pid) or project), script_shot or {}, video_path)
            except Exception as exc:
                boundary = {"status": "uncertain", "limits": [str(exc)], "needs_human_review": True}
            with PROJECT_IO_LOCK:
                latest = load_project(pid) or project
                target = 项目服务实例.镜头(latest, index)
                if not target:
                    target = copy.deepcopy(current_shot)
                    latest.setdefault("shots", []).append(target)
                target.update({
                    "index": index,
                    "video_url": f"/file/outputs/{pid}/shot_{index:02d}.mp4?t={int(time.time())}",
                    "path": os.path.join("outputs", pid, f"shot_{index:02d}.mp4"),
                    "prompt": render_prompt,
                    "duration": duration,
                    "camera": render_camera,
                    # 保存镜头上下文，供审片、重制和版本追踪复用。
                    "refs": [os.path.relpath(path, BASE_DIR) for path in refs],
                })
                target['audio_review'] = audio_report
                target["style_render"] = first_frame_record or {
                    "mode": "r2v", "reason": "非3D项目、项目/镜头指定R2V、外部提供商或保留参考音色"
                }
                if handoff:
                    target["continuity_handoff"] = handoff
                if boundary:
                    latest.setdefault("continuity_reviews", {})[str(index)] = boundary
                # Text-state successors render independently; only frame consumers become stale.
                from infrastructure.shot_continuity import requires_previous_frame
                for following in (latest.get("script") or {}).get("shots", []):
                    plan = following.get("continuity") or {}
                    if requires_previous_frame(following) and plan.get("previous_index") == index:
                        dependent = 项目服务实例.镜头(latest, following.get("index"))
                        if dependent and dependent.get("video_url"):
                            dependent["continuity_stale"] = True
                        latest.setdefault("prompts", {}).pop(str(following.get("index")), None)
                target.pop("continuity_stale", None)
                target.pop("error", None)
                target.pop("reference_video_stale", None)
                target.pop("final", None)
                _sync_current_shot_metadata(
                    latest,
                    index,
                    prompt=render_prompt,
                    duration=duration,
                    camera=render_camera,
                )
                invalidate_final(latest)
                version = _archive_after_render(latest, index, label="Agent单镜头渲染")
                save_project(latest)
            return {
                "pid": pid,
                "index": index,
                "video_url": target["video_url"],
                "path": video_path,
                "prompt": render_prompt,
                "duration": duration,
                "camera": render_camera,
                "audio_review": audio_report,
                "version_id": (version or {}).get("id", ""),
                "video_info": video_info,
            }
    finally:
        if parent_runtime_config is None:
            clear_runtime_config()
        else:
            set_runtime_config(parent_runtime_config)


# ============================== 连续剧 / Story Bible ==============================
def _series_id_from_name(name):
    name = (name or '未命名系列').strip()
    scope = MULTIUSER.workspace_owner() if MULTIUSER else ''
    if MULTIUSER and scope:
        for path in Path(SERIES_DIR).glob('*.json'):
            if MULTIUSER.store.owner('series',path.stem)==scope:
                existing=load_series(path.stem)
                if existing and str(existing.get('name') or '').strip()==name:
                    return path.stem
    digest = hashlib.sha1((name + (':' + scope if scope else '')).encode('utf-8')).hexdigest()[:10]
    safe = re.sub(r'[^\w一-鿿-]+', '_', name)[:24].strip('_') or 'series'
    return f"{safe}_{digest}"

def series_path(series_id):
    return 系列存储.path(series_id)

def load_series(series_id):
    if MULTIUSER and not MULTIUSER.visible("series", series_id):
        return None
    p = series_path(series_id)
    with SERIES_IO_LOCK:
        data = 系列存储.load(series_id)
        if MULTIUSER and isinstance(data,dict) and isinstance(data.get('episodes'),dict):
            data['episodes']={key:meta for key,meta in data['episodes'].items()
                              if not isinstance(meta,dict) or not meta.get('project_id') or MULTIUSER.series_child(series_id,meta['project_id'])}
        if data is None and os.path.exists(p):
            print(f"[连续剧] 读取失败 {series_id}")
        return data

def save_series(data):
    if MULTIUSER:
        MULTIUSER.bind_document('series', data)
    sid = data['id']
    with SERIES_IO_LOCK:
        系列存储.save(sid, data)


def _final_file_path(project):
    """Return the local final video path when it is a non-empty file."""
    pid = str((project or {}).get('id') or '').strip()
    if not pid:
        return ''
    final = str((project or {}).get('final') or '').strip()
    if not final and (project or {}).get('previous_final'):
        # A known older composition stays downloadable but must not satisfy
        # pipeline completion or suppress composition of the changed shots.
        return ''
    candidates = []
    if final:
        if final.startswith('/file/outputs/'):
            candidates.append(os.path.join(BASE_DIR, final[len('/file/'):].lstrip('/')))
        elif os.path.isabs(final):
            candidates.append(final)
        elif not final.startswith('/'):
            candidates.append(os.path.join(BASE_DIR, final))
    candidates.append(os.path.join(OUTPUTS_DIR, pid, _final_filename(project)))
    candidates.append(os.path.join(OUTPUTS_DIR, pid, 'final.mp4'))
    for path in candidates:
        try:
            if os.path.isfile(path) and os.path.getsize(path) > 0:
                return path
        except OSError:
            continue
    return ''


def _episode_label(project):
    try:
        number = int(((project or {}).get('series') or {}).get('episode'))
    except (TypeError, ValueError):
        number = 0
    return f'第{number}集' if number > 0 else '成片'


def _final_filename(project):
    title = str(((project or {}).get('series') or {}).get('name') or (project or {}).get('title') or '短剧').strip()
    title = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', '_', title).strip(' ._') or '短剧'
    return f'{title}-{_episode_label(project)}.mp4'


def _shot_file_path(shot):
    raw = str((shot or {}).get('path') or (shot or {}).get('local_path') or '').strip()
    if not raw:
        video_url = str((shot or {}).get('video_url') or '')
        match = re.search(r'/outputs/([^/?]+)/((?:shot|video)[^/?]+\.(?:mp4|webm))', video_url)
        if match:
            raw = os.path.join('outputs', match.group(1), match.group(2))
    if not raw:
        return ''
    path = raw if os.path.isabs(raw) else os.path.join(BASE_DIR, raw)
    try:
        return path if os.path.isfile(path) and os.path.getsize(path) > 0 else ''
    except OSError:
        return ''


def _shot_has_current_video(shot):
    return bool((shot or {}).get('video_url') and not (shot or {}).get('error')
                and not (shot or {}).get('continuity_stale')
                and not (shot or {}).get('reference_video_stale')
                and _shot_file_path(shot))


def _project_shots_complete(project):
    script_shots = ((project or {}).get('script') or {}).get('shots') or []
    by_index = {item.get('index'): item for item in ((project or {}).get('shots') or [])}
    # This is the UI completeness signal.  Keep it compatible with historical
    # projects that only persisted a browser URL; composition itself still
    # performs the strict local-file check before creating a final.
    return bool(script_shots) and all(
        bool((by_index.get(item.get('index')) or {}).get('video_url'))
        and not (by_index.get(item.get('index')) or {}).get('error')
        and not (by_index.get(item.get('index')) or {}).get('continuity_stale')
        and not (by_index.get(item.get('index')) or {}).get('reference_video_stale')
        for item in script_shots
    )


def _project_shots_have_files(project):
    script_shots = ((project or {}).get('script') or {}).get('shots') or []
    by_index = {item.get('index'): item for item in ((project or {}).get('shots') or [])}
    return bool(script_shots) and all(_shot_has_current_video(by_index.get(item.get('index'))) for item in script_shots)


def _sync_series_episode_final(project):
    """Persist a verified final video in the owning series episode index."""
    ctx = (project or {}).get('series') or {}
    series_id = ctx.get('id')
    episode = ctx.get('episode')
    if not series_id or episode is None:
        return False
    final_path = _final_file_path(dict(project, final=available_final(project)))
    if not final_path:
        return False
    series = load_series(series_id)
    if not series:
        return False
    key = str(int(episode)) if str(episode).isdigit() else str(episode)
    now = time.time()
    meta = series.setdefault('episodes', {}).setdefault(key, {})
    if not isinstance(meta, dict):
        meta = {}
        series['episodes'][key] = meta
    if meta.get('project_id') and meta['project_id'] != project.get('id'):
        return False
    meta.update({
        'project_id': project.get('id'),
        'title': project.get('title') or ((project.get('script') or {}).get('title') or meta.get('title', '')),
        'final': available_final(project) or f"/file/outputs/{project.get('id')}/{os.path.basename(final_path)}",
        'has_final': True,
        'final_needs_resynth': bool(project.get('previous_final') and not project.get('final')),
        'updated': now,
    })
    series['updated'] = now
    save_series(series)
    return True

def parse_series_context(idea):
    """从V2前端导演简报中识别连续剧信息。"""
    txt = idea or ''
    m = re.search(r'连续剧：是；剧名《([^》]+)》；第(\d+)集', txt)
    if not m:
        return None
    name = m.group(1).strip()
    ep = int(m.group(2))
    prev = ''
    pm = re.search(r'上一集承接：([^\n]+)', txt)
    if pm:
        prev = pm.group(1).strip()
    im = re.search(r'系列ID：([^\s；]+)', txt)
    series_id = im.group(1).strip() if im else _series_id_from_name(name)
    return {"id": series_id, "name": name, "episode": ep, "previous_summary": prev}

def get_or_create_series(ctx):
    if not ctx:
        return None
    s = load_series(ctx['id'])
    if not s:
        s = {
            "id": ctx['id'], "name": ctx['name'], "created": time.time(), "updated": time.time(),
            "premise": "", "characters": {}, "scenes": {}, "props": {}, "assets": {},
            "episodes": {}, "plan": []
        }
        save_series(s)
    return s

def story_bible_prompt(ctx):
    if not ctx or not runtime_config().get('story_bible_enabled', True):
        return ''
    s = get_or_create_series(ctx)
    if not s:
        return ''
    chars = list((s.get('characters') or {}).values())
    scenes = list((s.get('scenes') or {}).values())
    props = list((s.get('props') or {}).values())
    return (
        "\n\n【连续剧Story Bible硬约束】\n"
        f"这是《{ctx['name']}》第{ctx['episode']}集。本剧长期核心设定：{s.get('premise','') or '未填写'}。以下设定来自前集，属于不可随意改写的连续性资产：\n"
        f"角色：{json.dumps(chars, ensure_ascii=False)}\n"
        f"场景：{json.dumps(scenes, ensure_ascii=False)}\n"
        f"道具：{json.dumps(props, ensure_ascii=False)}\n"
        "规则：同名角色的年龄、人种、五官、发型、体型和标志配饰必须保持一致；服装按每个镜头的时间、地点、活动和 wardrobe 自然变化；"
        "同名场景的空间结构和主光线保持一致；同名道具的材质、颜色、形状保持一致。"
        "如果剧情需要角色换装，直接在对应镜头 wardrobe 中写清；只有场景结构发生变化时才需要新资产名称（例如“便利店-后门”）。"
    )

def apply_story_bible(script, ctx, project_id=None):
    """锁定已有设定，并把本集新设定写回系列圣经。"""
    if not ctx or not runtime_config().get('story_bible_enabled', True):
        return script
    s = get_or_create_series(ctx)
    if not s:
        return script

    s.setdefault('characters', {}); s.setdefault('scenes', {}); s.setdefault('props', {})
    for c in script.get('characters', []):
        name = c.get('name')
        if not name: continue
        if name in s['characters']:
            old = s['characters'][name]
            c['appearance'] = old.get('appearance', c.get('appearance', ''))
            if old.get('personality'):
                c['personality'] = old['personality']
        else:
            s['characters'][name] = copy.deepcopy(c)

    for sc in script.get('scenes', []):
        name = sc.get('name')
        if not name: continue
        if name in s['scenes']:
            sc['description'] = s['scenes'][name].get('description', sc.get('description', ''))
        else:
            s['scenes'][name] = copy.deepcopy(sc)

    for pp in script.get('props', []):
        name = pp.get('name')
        if not name: continue
        if name in s['props']:
            pp['description'] = s['props'][name].get('description', pp.get('description', ''))
        else:
            s['props'][name] = copy.deepcopy(pp)

    s.setdefault('episodes', {})
    s['episodes'][str(ctx['episode'])] = {
        "project_id": project_id,
        "title": script.get('title', ''),
        "synopsis": script.get('synopsis', ''),
        "updated": time.time()
    }
    s['updated'] = time.time()
    save_series(s)
    return script

def import_series_assets(proj, ctx):
    """跨集复用同名角色/场景/道具参考图。"""
    if proj.get('remake_mode') in ('full', 'script', 'asset'):
        return
    if not ctx or not runtime_config().get('story_bible_enabled', True):
        return
    s = get_or_create_series(ctx)
    if not s:
        return
    assets = proj.setdefault('assets', {})
    for key, a in (s.get('assets') or {}).items():
        if key in assets:
            continue
        path = a.get('path') if isinstance(a, dict) else None
        if path and os.path.exists(path):
            assets[key] = copy.deepcopy(a)

def sync_series_assets(proj, ctx):
    if not ctx or not runtime_config().get('story_bible_enabled', True):
        return
    s = get_or_create_series(ctx)
    if not s:
        return
    s.setdefault('assets', {})
    for key, a in (proj.get('assets') or {}).items():
        if not isinstance(a, dict):
            continue
        p = a.get('path')
        if p and os.path.exists(p):
            # 只保存真实资产；角色音色也一并复用
            s['assets'][key] = copy.deepcopy(a)
    s['updated'] = time.time()
    save_series(s)

SERIES_PLAN_PROMPT = """你是短剧总编剧。根据用户给出的系列设定，规划一季可连续制作的短剧。
必须严格输出JSON，不要markdown：
{
  "series_name":"剧名",
  "premise":"核心设定",
  "main_characters":[{"name":"角色","arc":"人物弧线"}],
  "episodes":[
    {"episode":1,"title":"集名","hook":"黄金3秒","main_event":"本集核心事件","reversal":"本集反转","payoff":"本集爽点/情绪兑现","ending_hook":"结尾追更钩子","continuity":"需要从上一集继承的信息"}
  ]
}
要求：
- 每集都必须单独成立，同时推动总主线；
- 开头3秒必须有结果前置、冲突、金额/身份反差、危险或反常识信息之一；
- 中段至少一次局势变化；
- 结尾必须留下下一集可执行的具体悬念；
- 不允许连续多集重复同一种冲突；
- 人物能力升级、关系变化、资产变化必须可追踪。
"""

def build_episode_execution_idea(series_obj, ep):
    prev = ''
    n = int(ep.get('episode', 1))
    if n > 1:
        prev_ep = next((x for x in series_obj.get('plan', []) if int(x.get('episode', 0)) == n - 1), None)
        if prev_ep:
            prev = f"{prev_ep.get('main_event','')}；结尾：{prev_ep.get('ending_hook','')}"
    return (
        f"{series_obj.get('premise','')}\n\n"
        "【本集执行卡】\n"
        f"集名：{ep.get('title','')}\n"
        f"黄金3秒：{ep.get('hook','')}\n"
        f"核心事件：{ep.get('main_event','')}\n"
        f"反转：{ep.get('reversal','')}\n"
        f"爽点/情绪兑现：{ep.get('payoff','')}\n"
        f"结尾追更钩子：{ep.get('ending_hook','')}\n"
        f"连续性要求：{ep.get('continuity','')}\n\n"
        "【短剧导演简报】\n"
        "发布平台：抖音\n目标成片：60秒左右\n剧情类型：连续爽剧\n节奏：中快：4~7秒一信息点\n"
        "黄金3秒策略：先给结果，再解释原因\n反转强度：中：至少2次认知变化\n"
        "结尾策略：卡在最大悬念，逼追下一集\n对白密度：中：对白推动剧情\n"
        f"连续剧：是；剧名《{series_obj.get('name') or series_obj.get('series_name') or '未命名系列'}》；第{n}集\n"
        + (f"上一集承接：{prev}\n" if prev else "")
    )

# ============================== SSE 工具 ==============================
def sse(event, data):
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

# ============================== 主管线 ==============================
def build_script_prompt(series_ctx=None, idea=''):
    """根据当前配置(时长模式/镜头数)动态构造剧本解析系统提示词"""
    dur = runtime_config().get('shot_duration', 'auto')
    if isinstance(dur, str) and dur.lower() == 'auto':
        duration_rule = ("4. 每个分镜时长在8~15秒之间，由你根据该镜头的动作复杂度与台词量逐镜自定："
                         "动作较简单或台词较少用8~10秒，复杂动作或多句台词用长时长(12~15秒)；"
                         "全片各镜时长必须有变化、有节奏感，绝不所有镜头一刀切")
    else:
        duration_rule = f"4. 每个分镜固定{int(dur)}秒，一个镜头只承载一个连贯动作或一句核心台词，不贪多"
    cnt = runtime_config().get('shot_count', 'auto')
    if isinstance(cnt, str) and cnt.lower() == 'auto':
        count_rule = "5. 分镜数量完全由故事节奏和信息量决定，自动模式不设镜头数量上限；每个镜头都必须有明确叙事价值，绝不为凑数添加空镜"
    else:
        count_rule = (f"5. 严格生成{int(cnt)}个分镜，不多不少——这是硬性要求；"
                      f"请把故事节奏压缩或展开到恰好{int(cnt)}个镜头，每个镜头都要有存在价值")
    from agents.script.skills.wardrobe import 服装规则
    base = SCRIPT_PARSE_PROMPT.replace('%DURATION_RULE%', duration_rule).replace('%COUNT_RULE%', count_rule)
    base += '\n\n【逐镜服装规划与验收】\n' + 服装规则
    script_skill_id = str(runtime_config().get('script_skill_id') or 'auto')
    script_skill = _阶段技能(script_skill_id, 'script')
    if script_skill:
        base += (
            "\n\n【剧本解析 Skill】\n"
            "以下是当前项目指定的剧本解析 Skill。请在不违反系统 JSON 结构、镜头时长和安全约束的前提下执行：\n"
            + script_skill
        )
    skill_mode = 获取提示词技能模式(idea)
    if skill_mode.startswith(('custom:', 'builtin:')):
        base += (
            "【用户自定义视频提示词技能】\n"
            "以下规则由用户上传，作为本项目的专项创作要求。遵守系统 H3 格式、8~15秒时长、"
            "台词完整性、参考图一致性和安全约束；若与系统基础规则冲突，以系统基础规则为准。\n"
            + _阶段技能(skill_mode, "video_prompt")
        )
    elif skill_mode in ('action', 'anime_action'):
        base += ("\n\n【MiniMax H3 武戏提示词技能：仅在本故事包含动作冲突时应用】\n"
                 "优先依据用户设定和参考图锁定武器、能力、身体结构与移动条件；无依据不得添加武器或超能力。"
                 "动作必须写成起势、攻击线路、接触点、防御、受力、位移、环境反馈和下一招的因果链。"
                 "首帧即运动，按当前8~15秒压缩或展开开战、空间变化、攻守逆转和明确结果。"
                 "每次切镜继承位置、朝向、速度、高度、装备/能力和受击状态中的至少四项。")
        if skill_mode == 'anime_action':
            base += ("\n\n【二次元打戏提示词技能：风格增强】\n"
                 "把打斗写成连续可拍摄的攻防链，明确招式、攻击部位、运动方向、格挡/闪避反馈、局势变化和环境反馈。"
                 "小动作使用近景或中近景，大幅动作使用中景或全景；镜头描述写清景别、视角/角度、运镜和跟随目标。"
                 "首帧即运动，避免空镜和站桩。遵循当前8~15秒与禁止慢放规则，不把本技能中的Seedance专属格式直接输出。")
    elif skill_mode == 'dialogue':
        base += ("\n\n【MiniMax H3 文戏提示词技能：本故事优先应用】\n"
                 "按主场景、一次关系变化、一条主动作链和明确出口划分单元；"
                 "根据当前8~15秒时长匹配台词量，15秒通常36~44字且不超过48字，短反应先检查与相邻剧情合并。"
                 "主要说话人最多S1/S2，台词逐字保留并使用<d>[Chinese]...</d>，单人场景禁止画外音；"
                 "必须恢复官方的说话人显式标注：开头先建立不可变的‘角色名 → Subject → S编号 → Picture → 外观/声线’映射；每一句台词前都单独写‘说话人物：角色名（Subject N / SN），其身份锚点：……’，再紧接‘<Subject N> (SN) says:’和下一行‘<d>[Chinese]台词原文</d>’。说话人物说明只用于身份绑定，不朗读，禁止用‘他/她/某人’代替角色名；同一角色全片不得更换Subject、S编号、Picture或声线。"
                 "每个Shot独占一行，倾听者要有具体反应，拿取、靠近、拥抱等动作写出连续过程，末帧交代位置、视线、接触和道具状态。")
    if series_ctx:
        base += story_bible_prompt(series_ctx)
    return base

def get_shot_count_limit():
    """返回用户指定的镜头数(int)，自动模式返回None"""
    cnt = runtime_config().get('shot_count', 'auto')
    if isinstance(cnt, str) and cnt.lower() == 'auto':
        return None
    try:
        return max(1, int(cnt))
    except (TypeError, ValueError):
        return None

def resynth_pipeline(proj, send, cancel_check=None):
    """合成阶段：合并所有已渲染分镜为成片。供管线末尾与"重新合成"接口反复调用。
    若还有分镜失败，则拒绝合成并明确告知，让用户先重制失败镜。"""
    pid = proj['id']
    if cancel_check:
        cancel_check()
    shot_results = proj.get('shots', [])
    expected_indexes = [s.get('index') for s in ((proj.get('script') or {}).get('shots') or [])]
    by_index = {s.get('index'): s for s in shot_results}
    failed = []
    for idx in expected_indexes:
        shot = by_index.get(idx) or {"index": idx, "error": "尚未生成"}
        raw_path = shot.get('path') or shot.get('local_path') or ''
        # Older projects persisted only the browser URL. Recover the local
        # output path so existing rendered shots can be composed.
        if not raw_path and shot.get('video_url'):
            match = re.search(r'/outputs/([^/?]+)/((?:shot|video)[^/?]+\.(?:mp4|webm))', str(shot.get('video_url')))
            if match:
                raw_path = os.path.join('outputs', match.group(1), match.group(2))
                shot['path'] = raw_path
        abs_path = raw_path if os.path.isabs(raw_path) else os.path.join(BASE_DIR, raw_path) if raw_path else ''
        # 合成入口只要求每个镜头有当前视频文件。连续性/参考图同步标记
        # 用于提示和重制决策，不应阻止用户合成已经生成完成的镜头。
        if shot.get('error') or not shot.get('video_url') or not raw_path or not os.path.isfile(abs_path):
            failed.append(shot)
    if failed:
        send('error', {"stage": 4, "msg": f"仍有{len(failed)}个分镜没有可用于合成的当前片段（镜头：{'、'.join(str(f.get('index')) for f in failed)}），请先生成/重制这些镜头后再合成"})
        return False
    send('stage', {"stage": 4, "name": "视频合成", "status": "running", "msg": "正在合并所有分镜..."})
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        send('error', {"stage": 4, "msg": "未检测到ffmpeg（整合包tools/ffmpeg与系统PATH均无）"})
        return False
    out_dir = os.path.join(OUTPUTS_DIR, pid)
    os.makedirs(out_dir, exist_ok=True)
    ordered = [by_index[index] for index in sorted(expected_indexes)]
    # 以实际 mp4 时长建立字幕时间轴，避免生成时长与帧率取整造成累计偏移。
    timed_ordered = []
    for item in ordered:
        timed_item = dict(item)
        raw_path = timed_item.get('path') or ''
        abs_path = raw_path if os.path.isabs(raw_path) else os.path.join(BASE_DIR, raw_path)
        actual_duration = _video_duration_seconds(abs_path, ffmpeg)
        if actual_duration is not None:
            timed_item['duration'] = actual_duration
        timed_ordered.append(timed_item)
    ordered = timed_ordered
    list_file = os.path.join(out_dir, 'concat.txt')
    with open(list_file, 'w', encoding='utf-8') as f:
        for r in ordered:
            f.write(f"file '{os.path.basename(r['path'])}'\n")
    render_cfg = project_render_config(proj)
    subtitle_enabled = bool(render_cfg.get('subtitle_enabled', False))
    subtitle_path = os.path.join(out_dir, 'subtitles.srt')
    # ASR 逐词时间戳与实际发音同步，优先于按剧本均分时长的估算字幕。
    subtitle_text = (build_asr_subtitle_srt(ordered) or build_subtitle_srt(proj, ordered)) if subtitle_enabled else ""
    if subtitle_enabled:
        with open(subtitle_path, 'w', encoding='utf-8-sig') as f:
            f.write(subtitle_text)
        if subtitle_text:
            send('stage', {"stage": 4, "name": "视频合成", "status": "running", "msg": "正在合并分镜并烧录字幕..."})
        else:
            send('stage', {"stage": 4, "name": "视频合成", "status": "running", "msg": "本项目没有检测到对白，继续合成无字幕视频..."})
    final_name = _final_filename(proj)
    # Compose into a separate file so failed ffmpeg attempts cannot truncate
    # the last downloadable composition.
    working_name = f'.compose_{uuid.uuid4().hex}.mp4'
    final_path = os.path.join(out_dir, working_name)
    all_ok = False
    if subtitle_enabled and subtitle_text:
        # 先生成无字幕母片；最终字幕必须来自成片 ASR，不能在此处烧录
        # 按分镜估算的旧时间轴，否则后续校准不会反映到用户看到的视频。
        commands = (
            [ffmpeg, '-y', '-f', 'concat', '-safe', '0', '-i', 'concat.txt',
             '-c:v', 'libx264', '-preset', 'medium', '-crf', '18', '-c:a', 'aac', '-b:a', '192k', working_name],
            [ffmpeg, '-y', '-f', 'concat', '-safe', '0', '-i', 'concat.txt', '-c:v', 'libx264', '-c:a', 'aac', working_name],
        )
    else:
        commands = (
            [ffmpeg, '-y', '-f', 'concat', '-safe', '0', '-i', 'concat.txt', '-c', 'copy', working_name],
            [ffmpeg, '-y', '-f', 'concat', '-safe', '0', '-i', 'concat.txt', '-c:v', 'libx264', '-c:a', 'aac', working_name],
        )
    for cmd in commands:
        try:
            proc = FFMPEG执行器实例.执行(cmd, cwd=out_dir, timeout=600)
            if proc.returncode == 0:
                all_ok = True
                break
        except Exception:
            continue
    if not all_ok:
        send('error', {"stage": 4, "msg": "ffmpeg合并失败，请检查分镜文件"})
        return False
    # ffmpeg may return success while an output was removed or written to a
    # different working directory.  Do not publish a URL until the file is
    # actually present and non-empty.
    try:
        if not os.path.isfile(final_path) or os.path.getsize(final_path) <= 0:
            send('error', {"stage": 4, "msg": "ffmpeg返回成功但最终视频没有有效落盘文件"})
            return False
    except OSError:
        send('error', {"stage": 4, "msg": "无法确认最终视频文件已落盘"})
        return False
    # 成片完成后重新对整条音轨 ASR，生成与最终视频绝对时间轴一致的外挂字幕。
    final_srt = os.path.join(out_dir, 'final.srt')
    if subtitle_enabled:
        send('stage', {"stage": 4, "name": "字幕校准", "status": "running", "msg": "正在对成片音轨重新听音并生成字幕..."})
        if transcribe_final_to_srt(final_path, final_srt, ffmpeg):
            subtitle_tmp = os.path.join(out_dir, 'final_subtitled.mp4')
            burn_cmd = [ffmpeg, '-y', '-i', working_name, '-vf',
                        "subtitles=final.srt:force_style='FontName=Noto Sans CJK SC,FontSize=12,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,Outline=1,Shadow=0,Alignment=2,MarginV=24,WrapStyle=2'",
                        '-c:v', 'libx264', '-preset', 'medium', '-crf', '18', '-c:a', 'copy', subtitle_tmp]
            try:
                proc = FFMPEG执行器实例.执行(burn_cmd, cwd=out_dir, timeout=600)
                if proc.returncode == 0 and os.path.isfile(subtitle_tmp):
                    os.replace(subtitle_tmp, final_path)
            except Exception as exc:
                print(f'[字幕ASR] 烧录校准字幕失败: {exc}')
    if cancel_check:
        cancel_check()
    os.replace(final_path, os.path.join(out_dir, final_name))
    proj['final'] = f"/file/outputs/{pid}/{final_name}"
    proj.pop('previous_final', None)
    save_project(proj)
    _sync_series_episode_final(proj)
    send('stage', {"stage": 4, "name": "视频合成", "status": "done"})
    send('final', {"video_url": proj['final'], "title": proj.get('title', '短剧')})
    return True


def run_agent_pipeline(pid, idea, send, custom_assets=False, run_id=None):
    """Agent 主导的单项目批量编排入口。

    唯一整集生产入口。这里的编排负责阶段协同和状态，
    具体生成能力由各专业 Agent 执行并验收。
    """
    run_id = run_id or uuid.uuid4().hex[:16]
    project = load_project(pid)
    if project is None:
        project = {
            "id": pid,
            "idea": idea,
            "title": "",
            "script": None,
            "assets": {},
            "shots": [],
            "final": None,
            "created": time.time(),
            "render_config": copy.deepcopy(runtime_config()),
            "script_review_required": bool(runtime_config().get("script_review_mode", True)),
            "script_confirmed": False,
        }
    elif idea:
        project["idea"] = idea
    project["render_config"] = copy.deepcopy(runtime_config())
    project["full_script_import"] = bool(runtime_config().get("full_script_import"))
    if custom_assets:
        project["custom_assets"] = True
    project["run_id"] = run_id
    project.setdefault("运行记录", []).append({
        "run_id": run_id,
        "mode": "agent",
        "started_at": time.time(),
        "status": "running",
    })
    project["运行记录"] = project["运行记录"][-50:]
    初始化任务状态(project)
    save_project(project)

    def check_cancel():
        if pipeline_cancelled(pid):
            raise PipelineCancelled()

    def event(name, payload=None):
        data = dict(payload or {})
        data.setdefault("run_id", run_id)
        send(name, data)

    def stage(number, name, status="running", msg=""):
        event("stage", {"stage": number, "name": name, "status": status, "msg": msg})

    def mark_waiting(reason, message):
        with PROJECT_IO_LOCK:
            latest = load_project(pid) or project
            record = next((r for r in latest.get('运行记录', []) if r.get('run_id') == run_id), None)
            if record:
                record.update(status='waiting', wait_for=reason)
            更新任务状态(latest, 状态='等待确认', 下一步=message)
            save_project(latest)

    def wait_for_confirmation(reason, message):
        mark_waiting(reason, message)
        latest = load_project(pid) or project
        record = next((r for r in latest.get('运行记录', []) if r.get('run_id') == run_id), None)
        if record:
            record['finished_at'] = time.time()
            save_project(latest)
        event('agent_wait', {'wait_for': reason, 'msg': message})

    prompt_batch_pending = False

    def prepare_quality_context(current):
        """补齐旧管线在 Agent 编排中不能遗漏的质量前置。

        Agent 负责判断和验收，旧管线中的确定性数据清洗、连续性资产导入
        和引用补全仍由这里统一执行，避免 Agent 只完成“路由”却丢失生产约束。
        """
        nonlocal project, prompt_batch_pending
        current = current or project
        if not current.get("series"):
            series_ctx = parse_series_context(current.get("idea") or idea or "")
            if series_ctx:
                current["series"] = series_ctx

        script = copy.deepcopy(current.get("script") or {})
        shots = script.get("shots") or []
        characters = script.setdefault("characters", [])
        scenes = script.setdefault("scenes", [])
        props = script.setdefault("props", [])
        char_names = {item.get("name") for item in characters if isinstance(item, dict)}
        scene_names = {item.get("name") for item in scenes if isinstance(item, dict)}
        prop_names = {item.get("name") for item in props if isinstance(item, dict)}

        for position, shot in enumerate(shots, start=1):
            if not isinstance(shot, dict):
                continue
            shot["index"] = position
            try:
                shot["duration"] = max(8, min(int(shot.get("duration", 8)), 15))
            except (TypeError, ValueError):
                shot["duration"] = 8
            shot["action"] = filter_slow_motion(str(shot.get("action") or "").strip())
            shot["camera"] = filter_slow_motion(str(shot.get("camera") or "固定中景").strip())
            shot_chars = [str(value).strip() for value in shot.get("characters") or [] if str(value).strip()]
            shot["characters"] = shot_chars
            for name in shot_chars:
                if name not in char_names:
                    characters.append({
                        "name": name,
                        "appearance": f"{name}，形象与全剧其他角色风格统一",
                        "personality": "",
                    })
                    char_names.add(name)
            scene = str(shot.get("scene") or "").strip()
            if scene and scene not in scene_names:
                scenes.append({
                    "name": scene,
                    "description": f"{scene}，与全剧场景、时间和光线保持一致",
                })
                scene_names.add(scene)
            shot_props = [str(value).strip() for value in shot.get("props") or [] if str(value).strip()]
            shot["props"] = shot_props
            for name in shot_props:
                if name not in prop_names:
                    props.append({
                        "name": name,
                        "description": f"{name}，写实质感，与全剧年代和风格保持一致",
                    })
                    prop_names.add(name)

        series_ctx = current.get("series")
        if series_ctx:
            script = apply_story_bible(script, series_ctx, project_id=pid)
        current["script"] = script
        if script.get("title"):
            current["title"] = script["title"]
        if series_ctx:
            import_series_assets(current, series_ctx)
        project = current
        save_project(current)
        return current

    def prepare_batch_prompts(current):
        nonlocal prompt_batch_pending
        shots = (current.get('script') or {}).get('shots') or []
        if runtime_config().get('manual_mode') and runtime_config().get('batch_prompt_mode', True):
            drafts = []
            for shot in shots:
                check_cancel()
                current = load_project(pid) or current
                index = shot['index']
                existing = next((r for r in current.get('shots', []) if r['index'] == index), {})
                if existing.get('video_url') and not existing.get('continuity_stale'):
                    continue
                refs = assemble_shot_ref_paths(shot, current.get('assets') or {})
                prompt = (current.get('prompts') or {}).get(str(index))
                if not prompt:
                    prompt, error = gen_shot_h3_prompt_with_retry(shot, refs, check_cancel, event)
                    if not prompt:
                        raise ValueError(f"第{index}镜：{error or '提示词草稿生成失败'}")
                draft = dict(index=index, prompt=prompt, duration=shot.get('duration', 8), camera=shot.get('camera', ''))
                current.setdefault('prompts', {})[str(index)] = prompt
                target = next((r for r in current.setdefault('shots', []) if r['index'] == index), None)
                if target is None:
                    current['shots'].append(dict(draft))
                else:
                    target.update(draft)
                save_project(current)
                drafts.append(draft)
                event('shot_prompt_ready', draft)
            if drafts:
                event('prompt_batch_ready', {'shots': drafts, 'total': len(drafts),
                      'msg': '提示词草稿已就绪；选中后逐镜检查前镜实际末帧再渲染。'})
                prompt_batch_pending = True
                return current
        return current

    def dispatch(agent_name, parameters=None):
        check_cancel()
        current = load_project(pid) or project
        result = 协同调度器实例.执行(agent_name, current, parameters or {})
        latest = load_project(pid) or current
        if result.get("成功"):
            latest.setdefault("运行记录", [])
        save_project(latest)
        if not result.get("成功"):
            raise RuntimeError(f"{agent_name}失败: {result.get('错误') or '未知错误'}")
        return result, latest

    try:
        # 1. 剧本
        stage(1, "剧本智能体", msg="总控正在派发剧本任务...")
        current = load_project(pid) or project
        if not current.get("script"):
            result, current = dispatch("剧本智能体", {
                "progress_callback": lambda info: event("script_progress", info),
                "最大重试次数": 2,
                "镜头数量": get_shot_count_limit(),
                "自动确认": not bool(runtime_config().get("script_review_mode", True)),
            })
            current = prepare_quality_context(current)
            event("script_ready", {
                "title": current.get("title", ""),
                "script": current.get("script"),
                "compatibility_prepared": True,
            })
        else:
            current = prepare_quality_context(current)
        event("script_progress", {"done": 7, "total": 7, "phase": "剧本已生成，可以查阅", "status": "done"})
        if current.get("script_review_required") and not current.get("script_confirmed"):
            stage(1, "剧本查阅", "running", "剧本已生成，等待确认后继续")
            wait_for_confirmation("script_confirm", "等待确认剧本")
            return
        stage(1, "剧本智能体", "done", "剧本通过结构验收")

        # 2. 分镜
        stage(2, "剧本结构校验", msg="校验剧本中的镜头结构与资产需求，尚未生成视频提示词")
        _, current = dispatch("分镜智能体")
        current = prepare_quality_context(current)
        stage(2, "剧本结构校验", "done", "剧本结构通过检查，接下来生成参考资产")

        # 3. 资产
        fresh_reference_project = load_project(pid) or project
        cfg = copy.deepcopy(runtime_config())
        cfg['asset_reference_id'] = (fresh_reference_project.get('render_config') or {}).get('asset_reference_id', '')
        set_runtime_config(cfg)
        if current.get("custom_assets") and not current.get("assets_confirmed"):
            stage(3, "资产确认", "running", "等待自定义参考图确认")
            event("wait_assets", {"msg": "请上传并确认参考图，再继续制作"})
            wait_for_confirmation("assets_confirm", "等待自定义参考图确认")
            return
        stage(3, "资产智能体", msg="正在生成或复用参考资产...")
        series_ctx = current.get("series")
        if series_ctx:
            import_series_assets(current, series_ctx)
            save_project(current)
        asset_result, current = dispatch("资产智能体")
        # Agent 管线的资产智能体一次性返回全部结果；逐张转成 SSE，
        # 让前端无需刷新页面就能把已经落盘的图片显示到对应卡片。
        asset_results = ((asset_result.get("数据") or {}).get("results") or [])
        for asset in asset_results:
            path = asset.get("path")
            if not path:
                continue
            event("asset", {
                "type": asset.get("kind", "scene"),
                "name": asset.get("name", ""),
                "url": asset_file_url(pid, path),
                "prompt": asset.get("prompt", ""),
                "cached": bool(asset.get("cached")),
            })
        if asset_results:
            event("progress", {
                "stage": 3,
                "done": len(asset_results),
                "total": len(asset_results),
            })
        if current.get("series"):
            sync_series_assets(current, current["series"])
        stage(3, "资产智能体", "done", "资产文件已验收")
        if runtime_config().get('manual_mode'):
            current = load_project(pid) or current
            if any(not a.get('cached') for a in asset_results):
                current.setdefault('asset_confirm', {}).pop('__all__', None)
                save_project(current)
            if not (current.get('asset_confirm') or {}).get('__all__', {}).get('continue'):
                mark_waiting('assets_confirm', '等待确认参考资产')
                _manual_wait_all_assets(pid, event, asset_results)


        # 4. 每镜提示词、渲染和审片
        from infrastructure.asset_gate import require_assets
        require_assets(load_project(pid) or current, BASE_DIR, bool(runtime_config().get('manual_mode')))
        current = prepare_batch_prompts(load_project(pid) or current)
        # 已有完整视频时跳过提示词草稿阶段，继续进入镜头复查。
        script_shots = ((current.get('script') or {}).get('shots') or [])
        rendered_indexes = {
            item.get('index') for item in (current.get('shots') or [])
            if item.get('video_url') and not item.get('error')
            and not item.get('continuity_stale') and not item.get('reference_video_stale')
        }
        all_rendered = bool(script_shots) and all(s.get('index') in rendered_indexes for s in script_shots)
        if all_rendered:
            prompt_batch_pending = False
        all_shots_confirmed = bool((current.get('shot_confirm') or {}).get('__all__', {}).get('continue'))
        if prompt_batch_pending and not all_shots_confirmed:
            wait_for_confirmation('prompt_batch_confirm', '提示词草稿已就绪，等待选中镜头继续')
            return
        shots = sorted(
            ((current.get("script") or {}).get("shots") or []),
            key=lambda item: int(item.get("index", 0) or 0),
        )
        total = len(shots)
        if not total:
            raise RuntimeError("剧本没有可执行镜头")
        if not runtime_config().get('manual_mode'):
            current = load_project(pid) or current
            pending = [shot['index'] for shot in shots if not any(
                r.get('index') == shot['index'] and r.get('video_url') and not r.get('error')
                and not r.get('continuity_stale') and not r.get('reference_video_stale')
                for r in current.get('shots', []))]
            if pending:
                _render_selected_shots(pid, pending, event)
            shots = []
        for position, shot in enumerate(shots, start=1):
            check_cancel()
            index = int(shot.get("index", position))
            current = load_project(pid) or current
            existing = next(
                (item for item in current.get("shots") or [] if item.get("index") == index),
                None,
            )
            if existing and existing.get("video_url") and not existing.get("error") and not existing.get("continuity_stale"):
                event("shot", {
                    "index": index,
                    "video_url": existing.get("video_url"),
                    "cached": True,
                    "position": position,
                    "total": total,
                })
                continue
            # 断点续跑时，失败镜头可能只是视频节点超时；如果项目里已有
            # 可用提示词，优先沿用它，避免再次经过提示词质量门禁把渲染任务卡死。
            cached_prompt = str(
                (existing or {}).get("prompt")
                or (current.get("prompts") or {}).get(str(index))
                or ""
            ).strip()
            if cached_prompt and (existing or {}).get("error") and not shot.get("continuity"):
                prompt = cached_prompt
                event("shot_status", {
                    "index": index,
                    "status": "prompt_cached",
                    "position": position,
                    "total": total,
                    "msg": f"第{index}镜：沿用已保存提示词，直接重新渲染...",
                    "prompt": prompt,
                })
            else:
                event("shot_status", {
                    "index": index,
                    "status": "prompt",
                    "position": position,
                    "total": total,
                    "msg": f"第{index}镜：提示词智能体正在生成和验收...",
                })
                prompt_result, current = dispatch("提示词智能体", {
                    "index": index,
                    "修复约束": (
                        (current.get("reviews") or {}).get(str(index), {})
                        .get("fix_constraints", "")
                    ),
                    "最大重试次数": 2,
                })
                prompt_data = prompt_result.get("数据") or {}
                prompt = prompt_data.get("prompt", "")
            if runtime_config().get("manual_mode") and not (
                cached_prompt and (existing or {}).get("error")
            ):
                mark_waiting('shot_prompt_confirm', f'等待确认第{index}镜提示词')
                prompt = _manual_wait_shot_prompt(pid, index, prompt, shot.get("duration", 8), event)
            event("shot_status", {
                "index": index,
                "status": "render",
                "position": position,
                "total": total,
                "msg": f"第{index}镜：渲染智能体正在生成视频...",
                "prompt": prompt,
            })
            render_result, current = dispatch("渲染智能体", {
                "index": index,
                "prompt": prompt,
                "duration": shot.get("duration", 8),
                "progress_callback": lambda info, idx=index: event(
                    "shot_render_progress", {"index": idx, **info}
                ),
            })
            render_data = render_result.get("数据") or {}
            # Some render backends persist the shot before returning their
            # response. Read it back so the final shot cannot lose its URL
            # when the adapter omits video_url in the response payload.
            persisted = next(
                (item for item in (load_project(pid) or {}).get("shots", [])
                 if item.get("index") == index),
                {},
            )
            video_url = render_data.get("video_url") or persisted.get("video_url")
            if not video_url:
                raise RuntimeError(f"第{index}镜渲染完成但未返回视频文件")
            event("shot", {
                "index": index,
                "video_url": video_url,
                "prompt": render_data.get("prompt", prompt),
                "audio_review": render_data.get("audio_review"),
                "position": position,
                "total": total,
            })
            if runtime_config().get("auto_review"):
                event("shot_status", {
                    "index": index,
                    "status": "review",
                    "msg": f"第{index}镜：审片智能体正在检查...",
                })
                review_result, current = dispatch("审片智能体", {
                    "index": index,
                    "阈值": runtime_config().get("review_threshold", 72),
                    "自动反馈": True,
                    "最大次数": runtime_config().get("max_auto_rerenders", 1),
                })
                event("shot_review", {
                    "index": index,
                    **(review_result.get("数据") or {}),
                })
            event("progress", {"stage": 4, "done": position, "total": total})
        stage(4, "提示词/渲染/审片智能体", "done", "所有镜头已完成")

        current = load_project(pid) or current
        if runtime_config().get('manual_mode') and not (current.get('shot_confirm') or {}).get('__all__', {}).get('continue'):
            event('shots_ready', {'shots': current.get('shots', []), 'msg': '全部镜头已生成，请复查满意后继续合成'})
            wait_for_confirmation('shots_review_confirm', '等待确认全部镜头')
            return

        # 5. 合成.  The selected-shot path may already have synthesized the
        # final while recovering a completed batch; avoid composing twice.
        current = load_project(pid) or current
        if _final_file_path(current):
            _sync_series_episode_final(current)
        else:
            stage(5, "合成智能体", msg="正在执行合成前置校验并生成成片...")
            _, current = dispatch("合成智能体")
            # The composition agent only returns success after resynth_pipeline
            # has verified the file.  Keep the URL check here for lightweight
            # integrations/tests that provide a mocked composition agent.
            if not current.get("final"):
                raise RuntimeError("合成智能体返回成功，但项目没有最终视频")
        stage(5, "合成智能体", "done", "最终视频已生成")
        event("final", {"video_url": current.get("final"), "title": current.get("title", "")})
        latest = load_project(pid) or current
        record = next((item for item in latest.get("运行记录", []) if item.get("run_id") == run_id), None)
        if record:
            record.update({"status": "done", "finished_at": time.time(), "mode": "agent"})
        更新任务状态(latest, 状态='已完成', 下一步='')
        latest["运行记录"] = latest.get("运行记录", [])[-50:]
        save_project(latest)
    except PipelineCancelled:
        latest = load_project(pid) or project
        record = next((item for item in latest.get("运行记录", []) if item.get("run_id") == run_id), None)
        if record:
            record.update({"status": "cancelled", "finished_at": time.time()})
        更新任务状态(latest, 状态="已暂停", 下一步="继续生成")
        save_project(latest)
        event("cancelled", {"msg": "Agent 编排已停止，已生成内容保留"})
        raise
    except Exception as exc:
        latest = load_project(pid) or project
        record = next((item for item in latest.get("运行记录", []) if item.get("run_id") == run_id), None)
        if record:
            record.update({"status": "failed", "error": str(exc), "finished_at": time.time()})
        更新任务状态(latest, 状态="失败")
        save_project(latest)
        event("error", {"msg": str(exc)})
        raise


# ============================== 单镜头生成器 API ==============================
@app.route('/api/single_shot/upload', methods=['POST'])
def single_shot_upload():
    """上传参考图到 assets/uploads/，返回本地路径与预览URL"""
    f = request.files.get('file')
    if not f or not f.filename:
        return jsonify({"error": "缺少文件"}), 400
    ext = os.path.splitext(f.filename)[1].lower() or '.png'
    if ext not in ('.png', '.jpg', '.jpeg', '.webp'):
        return jsonify({"error": "仅支持 png/jpg/webp 图片"}), 400
    up_dir = os.path.join(ASSETS_DIR, 'uploads')
    os.makedirs(up_dir, exist_ok=True)
    fname = f"up_{uuid.uuid4().hex[:8]}{ext}"
    f.save(os.path.join(up_dir, fname))
    rel = os.path.join('assets', 'uploads', fname)
    return jsonify({"path": rel, "url": f"/file/{rel}"})

@app.route('/api/single_shot/prompt', methods=['POST'])
def single_shot_prompt():
    """AI整理：把用户的粗略要求改写为H3提示词"""
    data = request.get_json(silent=True) or {}
    mode = data.get('mode', 'r2v')
    if mode not in ('r2v', 'i2v', 't2v'):
        mode = 'r2v'
    idea = (data.get('idea') or '').strip()
    if not idea:
        return jsonify({"error": "请先输入创作要求"}), 400
    try:
        duration = max(8, min(int(data.get('duration', 8)), 15))
    except (TypeError, ValueError):
        duration = 8
    ref_count = max(0, min(int(data.get('ref_count', 1) or 1), 9))
    # 读取已上传的参考图（r2v=各槽位图，i2v=首帧/尾帧），喂给多模态LLM直接看图
    images = load_image_parts(data.get('ref_paths') or []) if mode in ('r2v', 'i2v') else []
    if images:
        ref_count = len(images)
    if exclusive_on():
        stop_comfyui()
    ok, llm_err = ensure_local_llm()
    if not ok:
        return jsonify({"error": f"LLM服务未就绪: {llm_err}"}), 503
    mode_label = {'r2v': '参考生视频(r2v)', 'i2v': '图生视频(i2v)', 't2v': '文生视频(t2v)'}[mode]
    refs_block, pic_rule = build_single_refs_block(mode, ref_count)
    prompt_text = (SINGLE_SHOT_PROMPT
                   .replace('{mode_label}', mode_label)
                   .replace('{refs_block}', refs_block)
                   .replace('{pic_rule}', pic_rule)
                   .replace('{duration}', str(duration))
                   .replace('{idea}', idea[:2000]))
    prompt_text += '\n'+style_instruction(runtime_config().get('style'))
    # 图片只能附加在user消息（system保持纯文本）
    user_content = [{"type": "text", "text": "请按系统要求生成H3提示词。"}] + images
    content, err = llm_chat([
        {"role": "system", "content": prompt_text},
        {"role": "user", "content": user_content}
    ], max_tokens=4096, temperature=0.7)
    if not content:
        return jsonify({"error": f"提示词生成失败: {err}"}), 500
    content = filter_slow_motion(content.strip())
    # 台词兜底校验：用户明确要求说出的台词必须逐字出现在提示词中，缺失则让LLM修复一次
    spoken = re.findall(r'说[：:]?\s*["\'「『]([^"\'」』\n]{2,60})["\'」』]', idea)
    spoken += re.findall(r'说[：:]\s*([^，。,.\n"\'「』]{2,60})', idea)
    missing = [s.strip() for s in spoken if s.strip() and s.strip() not in content]
    if missing:
        print(f"[单镜头] 台词缺失，触发修复: {missing}")
        content = filter_slow_motion(repair_missing_dialogue(prompt_text, user_content, content, missing))
    content, error = enforce_dialogue_boundary(prompt_text, user_content, content)
    if error:
        return jsonify({"error": error}), 500
    return jsonify({"prompt": lock_prompt(content,runtime_config().get('style'))})

@app.route('/api/single_shot/generate', methods=['POST'])
def single_shot_generate():
    """启动单镜头视频生成任务（后台线程），返回task_id供轮询"""
    data = request.get_json(silent=True) or {}
    mode = data.get('mode', 'r2v')
    if mode not in ('r2v', 'i2v', 't2v'):
        mode = 'r2v'
    prompt = (data.get('prompt') or '').strip()
    if not prompt:
        return jsonify({"error": "提示词为空"}), 400
    ref_paths = [p for p in (data.get('ref_paths') or []) if isinstance(p, str)]
    # 安全校验：只允许项目目录内的路径；统一转绝对路径（避免依赖启动时的CWD）
    max_refs = {'r2v': 9, 'i2v': 2, 't2v': 0}[mode]
    safe_paths = []
    for p in ref_paths[:max_refs]:
        ap = _safe_join_under(BASE_DIR, p)
        if ap and os.path.exists(ap):
            safe_paths.append(ap)
    if mode in ('r2v', 'i2v') and not safe_paths:
        return jsonify({"error": f"{mode}模式需要至少1张参考图"}), 400
    try:
        duration = max(8, min(int(data.get('duration', 8)), 15))
    except (TypeError, ValueError):
        duration = 8
    task_id = uuid.uuid4().hex[:12]
    SINGLE_TASKS[task_id] = {"status": "running", "msg": "已加入队列", "video_url": "", "mode": mode, "config": copy.deepcopy(runtime_config()), "progress": 0, "elapsed": 0, "eta": 0, "phase": "排队中", "created": time.time(), "updated": time.time()}
    context = data.get('project_context') or {}
    if context.get('pid'):
        if MULTIUSER:
            MULTIUSER.require('project', context['pid'])
        project = load_project(context['pid'])
        if not project or not any(s.get('index') == context.get('index') for s in project.get('script', {}).get('shots', [])):
            SINGLE_TASKS.pop(task_id, None)
            return jsonify(error='重制项目或镜头不存在'), 400
        SINGLE_TASKS[task_id]['config'] = project_render_config(project)
    SINGLE_TASKS[task_id]['project_context'] = context
    threading.Thread(target=single_shot_worker,
                     args=(task_id, mode, prompt, safe_paths, duration), daemon=True).start()
    return jsonify({"task_id": task_id})

@app.route('/api/single_shot/status/<task_id>')
def single_shot_status(task_id):
    t = SINGLE_TASKS.get(task_id)
    if not t:
        return jsonify({"status": "error", "msg": "任务不存在"}), 404
    return jsonify(t)

@app.route('/api/project/<pid>/shot/<int:index>/references')
def project_shot_references(pid, index):
    proj = load_project(pid)
    if not proj:
        return jsonify(ok=False, msg='项目不存在'), 404
    shot = next((s for s in (proj.get('script') or {}).get('shots', []) if s.get('index') == index), None)
    if not shot:
        return jsonify(ok=False, msg='镜头不存在'), 404
    refs = assemble_shot_ref_paths(shot, proj.get('assets') or {})
    if not refs or any(not os.path.isfile(p if os.path.isabs(p) else os.path.join(BASE_DIR, p)) for p in refs):
        return jsonify(ok=False, msg='当前参考图缺失，请先上传参考图'), 400
    return jsonify(ok=True, refs=[os.path.relpath(p, BASE_DIR) if os.path.isabs(p) else p for p in refs])


@app.route('/api/project/<pid>/shot/<int:index>/reference-images', methods=['POST'])
def project_shot_reference_image_upload(pid, index):
    """向单个分镜追加一张独立参考图，并把绑定关系持久化到剧本镜头。"""
    if not re.fullmatch(r'[0-9a-zA-Z_-]{1,64}', str(pid or '')):
        return jsonify(ok=False, msg='非法项目ID'), 400
    proj = load_project(pid)
    if not proj:
        return jsonify(ok=False, msg='项目不存在'), 404
    upload = request.files.get('file')
    if not upload:
        return jsonify(ok=False, msg='请选择图片'), 400
    ext = os.path.splitext(upload.filename or '')[1].lower() or '.png'
    if ext not in ('.png', '.jpg', '.jpeg', '.webp'):
        return jsonify(ok=False, msg='仅支持 png/jpg/webp 图片'), 400
    script = proj.setdefault('script', {})
    shot = next((item for item in (script.get('shots') or []) if int(item.get('index', -1)) == int(index)), None)
    if not shot:
        return jsonify(ok=False, msg='镜头不存在'), 404
    existing = [str(key) for key in (shot.get('reference_images') or []) if key]
    base_count = len([f"char_{n}" for n in shot.get('characters', [])]) + (1 if shot.get('scene') else 0) + len(shot.get('props', []))
    key = str(request.form.get('key') or '').strip()
    replacing = bool(key and key in existing)
    if not replacing and base_count + len(existing) >= 9:
        return jsonify(ok=False, msg='每个镜头最多使用 9 张参考图'), 400
    if not replacing:
        key = f"shotref_{int(index)}_{uuid.uuid4().hex[:12]}"
    save_dir = project_assets_dir(pid)
    os.makedirs(save_dir, exist_ok=True)
    safe = re.sub(r'[^\w一-鿿-]', '_', key)
    save_path = os.path.join(save_dir, f"upload_{safe}{ext}")
    upload.save(save_path)
    proj.setdefault('assets', {})[key] = {
        'path': save_path,
        'kind': 'shot_reference',
        'uploaded': True,
    }
    shot['reference_images'] = existing if replacing else existing + [key]
    save_project(proj)
    return jsonify(ok=True, key=key, url=asset_file_url(pid, save_path),
                   reference={'key': key, 'kind': 'shot_reference', 'url': asset_file_url(pid, save_path)})


@app.route('/api/project/<pid>/shot/<int:index>/bridge', methods=['POST'])
def project_shot_bridge(pid, index):
    from core.continuity_clip import insert_bridge
    data = request.get_json(silent=True) or {}
    description = str(data.get('description') or '').strip()
    if not description or len(description) > 4000:
        return jsonify(ok=False, msg='请填写衔接要求（最多4000字）'), 400
    try:
        duration = int(data.get('duration', 8))
    except (TypeError, ValueError):
        duration = 0
    if duration not in (8, 10, 12, 15):
        return jsonify(ok=False, msg='请选择8、10、12或15秒'), 400
    with PROJECT_IO_LOCK:
        proj = load_project(pid)
        if not proj:
            return jsonify(ok=False, msg='项目不存在'), 404
        if pid in PIPELINE_CANCEL_EVENTS or pid in SYNTHESIZING_PROJECTS or any(
            t.get('pid') == pid and t.get('status') == 'running'
            for tasks in (RERENDER_TASKS, BATCH_RENDER_TASKS) for t in tasks.values()
        ):
            return jsonify(ok=False, msg='请等待当前生成任务结束，再插入衔接片段'), 409
        try:
            bridge = insert_bridge(proj, index, description, duration, OUTPUTS_DIR, save_project)
        except ValueError as exc:
            return jsonify(ok=False, msg=str(exc)), 400
    return jsonify(ok=True, index=bridge['index'])


@app.route('/api/project/<pid>/shot/<int:index>/replace', methods=['POST'])
def project_shot_replace(pid, index):
    """用单镜头生成器重制项目中的某个分镜：复制新视频覆盖该镜记录"""
    proj = load_project(pid)
    if not proj:
        return jsonify({"error": "项目不存在"}), 404
    data = request.get_json(silent=True) or {}
    src_rel = data.get('src_path', '')  # outputs/single/xxx.mp4
    src_abs = _safe_join_under(BASE_DIR, src_rel)
    if not src_abs or not os.path.exists(src_abs):
        return jsonify({"error": "源视频不存在"}), 400
    shots = proj.get('shots', [])
    target = next((s for s in shots if s.get('index') == index), None)
    if not target:
        return jsonify({"error": f"分镜{index}不存在"}), 404
    out_dir = os.path.join(OUTPUTS_DIR, pid)
    os.makedirs(out_dir, exist_ok=True)
    new_name = f"shot_{index:02d}.mp4"
    _archive_before_overwrite(proj, index)
    shutil.copyfile(src_abs, os.path.join(out_dir, new_name))
    target.pop('reference_video_stale', None)
    target['video_url'] = f"/file/outputs/{pid}/{new_name}?t={int(time.time())}"
    target['path'] = os.path.join('outputs', pid, new_name)
    if data.get('prompt'):
        _sync_current_shot_metadata(proj, index, prompt=data['prompt'])
    # 重制成功即清除失败标记，让"重新合成"能合并该镜
    target.pop('error', None)
    # 保留上一版成片入口，并让当前镜头进入待合成状态。
    invalidate_final(proj)
    _archive_after_render(proj, index, label='单镜头替换')
    save_project(proj)
    return jsonify({"ok": True, "shot": target})

@app.route('/api/project/<pid>/shot/<int:index>/versions')
def project_shot_versions(pid, index):
    """列出某镜头所有历史生成版本；旧项目首次访问时自动归档当前版本。"""
    proj = load_project(pid)
    if not proj:
        return jsonify({"ok": False, "msg": "项目不存在"}), 404
    target = _shot_target(proj, index)
    if not target:
        return jsonify({"ok": False, "msg": f"镜头{index}不存在"}), 404
    if target.get('video_url') and not target.get('error'):
        _archive_current_shot_version(proj, index, label='当前版本')
        save_project(proj)
    versions = list((proj.get('shot_versions') or {}).get(str(index), []))
    versions.sort(key=lambda version: version.get('created', 0), reverse=True)
    return jsonify({"ok": True, "index": index, "current_version_id": target.get('current_version_id'), "versions": versions})

@app.route('/api/project/<pid>/shot/<int:index>/select_version', methods=['POST'])
def project_shot_select_version(pid, index):
    """选择历史版本作为当前正式片段，并同步相关提示词缓存。"""
    proj = load_project(pid)
    if not proj:
        return jsonify({"ok": False, "msg": "项目不存在"}), 404
    data = request.get_json(force=True, silent=True) or {}
    version_id = (data.get('version_id') or '').strip()
    target = _shot_target(proj, index)
    if not target:
        return jsonify({"ok": False, "msg": f"镜头{index}不存在"}), 404
    selected, version = 项目服务实例.选择版本(proj, index, version_id)
    if selected is None:
        return jsonify({"ok": False, "msg": version}), 404
    save_project(proj)
    return jsonify({"ok": True, "shot": selected, "version": version})

@app.route('/api/project/<pid>/shot/<int:index>/confirm', methods=['POST'])
def project_shot_confirm(pid, index):
    """手动确认模式：用户在某镜提示词就绪后确认/编辑，写入存档让管线继续渲染。
    body: {prompt: "编辑后的提示词", skip: true}  skip为true表示不修改直接用AI结果。"""
    proj = load_project(pid)
    if not proj:
        return jsonify({"error": "项目不存在"}), 404
    data = request.get_json(force=True, silent=True) or {}
    cur = proj.get('prompts', {}).get(str(index), '')
    prompt = (data.get('prompt') or '').strip() or cur
    try:
        duration = max(8, min(int(data.get('duration', 8)), 15))
    except (TypeError, ValueError):
        duration = 8
    camera = (data.get('camera') or '').strip()
    confs = proj.get('shot_confirm', {})
    confs[str(index)] = {"prompt": prompt, "confirmed": True, "skip": bool(data.get('skip')), "duration": duration, "camera": camera}
    if data.get('reviewed'):
        confs[str(index)]['reviewed'] = True
    proj['shot_confirm'] = confs
    script = proj.get('script') or {}
    for sh in script.get('shots', []):
        if sh.get('index') == index:
            sh['duration'] = duration
            if camera:
                sh['camera'] = camera
            break
    proj['script'] = script
    for sh in proj.get('shots', []):
        if sh.get('index') == index:
            sh['duration'] = duration
            if camera:
                sh['camera'] = camera
            break
    save_project(proj)
    return jsonify({"ok": True, "duration": duration, "camera": camera})

@app.route('/api/project/<pid>/shot/confirm_all', methods=['POST'])
def project_shot_confirm_all(pid):
    """手动模式（环节级）：全部分镜视频已复查满意，标记 shot_confirm.__all__.continue=True，让管线进入合成阶段。"""
    proj = load_project(pid)
    if not proj:
        return jsonify({"error": "项目不存在"}), 404
    confs = proj.get('shot_confirm', {})
    confs['__all__'] = {"continue": True}
    proj['shot_confirm'] = confs
    save_project(proj)
    print(f"[分镜] 环节全部确认 {pid}")
    return jsonify({"ok": True})

@app.route('/api/project/<pid>/shots/batch_update', methods=['POST'])
def api_batch_update_shots(pid):
    """批量提示词编辑：保存全部镜头的提示词/时长/景别草稿，供后续选择镜头批量渲染。"""
    proj = load_project(pid)
    if not proj:
        return jsonify({"ok": False, "msg": "项目不存在"}), 404
    data = request.get_json(force=True, silent=True) or {}
    shots_payload = data.get('shots') or []
    prompts = proj.get('prompts', {})
    confs = proj.get('shot_confirm', {})
    script = proj.get('script') or {}
    result_shots = proj.get('shots', [])
    for item in shots_payload:
        try:
            idx = int(item.get('index'))
        except Exception:
            continue
        prompt = (item.get('prompt') or '').strip()
        try:
            duration = max(8, min(int(item.get('duration', 8)), 15))
        except Exception:
            duration = 8
        camera = (item.get('camera') or '').strip()
        if prompt:
            prompts[str(idx)] = filter_slow_motion(prompt)
        c = confs.get(str(idx), {})
        c.update({"prompt": prompts.get(str(idx), prompt), "duration": duration, "camera": camera})
        confs[str(idx)] = c
        for sh in script.get('shots', []):
            if sh.get('index') == idx:
                sh['duration'] = duration
                if camera:
                    sh['camera'] = camera
                break
        target = next((s for s in result_shots if s.get('index') == idx), None)
        if target is None:
            target = {"index": idx}
            result_shots.append(target)
        target['prompt'] = prompts.get(str(idx), prompt)
        target['duration'] = duration
        if camera:
            target['camera'] = camera
    proj['prompts'] = prompts
    proj['shot_confirm'] = confs
    proj['script'] = script
    proj['shots'] = result_shots
    save_project(proj)
    return jsonify({"ok": True, "updated": len(shots_payload)})

def _agent_render_selected_shot(pid, index, prompt=None, duration=None, progress_callback=None, video_model=None, planned=False, allow_disconnected=False):
    """All project render entry points share planning, preflight and visual handoff."""
    project = load_project(pid)
    if not project:
        raise ValueError("项目不存在")
    set_runtime_config(project_render_config(project))
    from infrastructure.asset_gate import require_assets
    require_assets(project, BASE_DIR, bool(runtime_config().get('manual_mode')))
    def dispatch(name, params=None):
        current = load_project(pid)
        result = 协同调度器实例.执行(name, current, params or {})
        if not result.get("成功"):
            raise ValueError(result.get("错误") or name + "失败")
        return result.get("数据") or {}
    if not planned:
        with PROJECT_IO_LOCK:
            dispatch("分镜智能体")
    project = load_project(pid)
    shot = next(s for s in project['script']['shots'] if s['index'] == index)
    if prompt:
        from infrastructure.agent_continuity import check_prompt, visual_handoff
        from infrastructure.shot_continuity import apply_continuity_intro
        if not allow_disconnected:
            prompt = apply_continuity_intro(shot, prompt)
        handoff = None if allow_disconnected else visual_handoff(sys.modules[__name__], project, shot)
        prompt, report = check_prompt(sys.modules[__name__], shot, prompt, handoff)
        if not allow_disconnected:
            prompt = apply_continuity_intro(shot, prompt)
        with PROJECT_IO_LOCK:
            project = load_project(pid)
            project.setdefault("continuity_prompt_checks", {})[str(index)] = report
            project.setdefault("prompts", {})[str(index)] = prompt
            project.setdefault("shot_confirm", {}).setdefault(str(index), {})["prompt"] = prompt
            for rendered_shot in project.get("shots", []):
                if rendered_shot.get("index") == index:
                    rendered_shot["prompt"] = prompt
            save_project(project)
    else:
        prompt = dispatch("提示词智能体", {"index": index}).get("prompt")
    result = dispatch("渲染智能体", {"index": index, "prompt": prompt,
                        "duration": duration or shot.get("duration", 8),
                        "progress_callback": progress_callback, "video_model": video_model,
                        "allow_disconnected": allow_disconnected})
    return result


def _render_selected_shots(pid, indexes, send, task=None, exact_selection=False):
    from infrastructure.dependency_scheduler import run as schedule, resolve_selection, render_groups
    from infrastructure.agent_continuity import previous_video
    config = copy.deepcopy(runtime_config())
    with PROJECT_IO_LOCK:
        result = 协同调度器实例.执行('分镜智能体', load_project(pid), {})
        if not result.get('成功'):
            raise ValueError(result.get('错误') or '镜头交接规划失败')
    project = load_project(pid)
    requested_indexes = sorted(set(indexes))
    if exact_selection:
        # Explicit bridge generation must never silently rerender earlier shots.
        # A missing/stale reference is reported before any rendering starts.
        indexes = requested_indexes
    else:
        indexes = resolve_selection(project['script']['shots'], requested_indexes,
            lambda shot: previous_video(sys.modules[__name__], project, shot))
    added_indexes = sorted(set(indexes) - set(requested_indexes))
    if task is not None:
        task.update(indexes=indexes, requested_indexes=requested_indexes)
    if added_indexes:
        send('shot_status', {'index': requested_indexes[0], 'status': 'waiting',
             'msg': '为保持连续动作，自动补齐前置镜头：' + '、'.join(map(str, added_indexes)) + '；按依赖顺序生成'})
    groups = render_groups(project['script']['shots'])
    send('render_groups', {'groups': groups})
    selected = set(indexes)
    for group in groups:
        members = [i for i in group['indexes'] if i in selected]
        if members:
            send('shot_status', {'index': members[0], 'status': 'queued',
                 'msg': f"渲染组{group['id']}：" + ' → '.join(map(str, members))
                        + '；仅尾帧依赖按顺序等待，文字状态衔接可跨组并行。分组依据：' + group['reason']})
    workers = max(1, len(enabled_comfy_servers()))
    event_lock = threading.Lock()
    count = 0
    def emit(name, data):
        with event_lock:
            send(name, data)
    def worker(index):
        set_runtime_config(config)
        receipt = None
        if task is not None:
            receipt_id = f"{task.get('id', uuid.uuid4().hex[:12])}_{int(index)}"
            current_for_receipt = load_project(pid) or {}
            confirm_for_receipt = (current_for_receipt.get('shot_confirm') or {}).get(str(index), {})
            receipt = {
                'id': receipt_id,
                'kind': 'batch',
                'status': 'running',
                'pid': pid,
                'index': int(index),
                'prompt': confirm_for_receipt.get('prompt') or (current_for_receipt.get('prompts') or {}).get(str(index), ''),
                'duration': confirm_for_receipt.get('duration') or 8,
                'camera': confirm_for_receipt.get('camera') or '',
                'created': time.time(),
                'updated': time.time(),
            }
            rerender_store(PROJECTS_DIR, pid).save(receipt_id, receipt)
            _RUNTIME.batch_render_receipt = receipt
        try:
            current = load_project(pid) or {}
            conf = (current.get('shot_confirm') or {}).get(str(index), {})
            stored_shot = next((s for s in current.get('shots', []) if s.get('index') == index), {})
            prompt = conf.get('prompt') or (current.get('prompts') or {}).get(str(index)) or stored_shot.get('prompt')
            emit('shot_status', {'index': index, 'status': 'render', 'msg': f'第{index}镜：依赖已就绪，智能体检查与渲染'})
            result = _agent_render_selected_shot(pid, index, prompt=prompt, duration=conf.get('duration'), planned=True,
                progress_callback=lambda info: emit('shot_render_progress', dict(info, index=index)))
            if receipt is not None:
                receipt.update(status='done', video_url=result.get('video_url', ''), updated=time.time())
            if config.get('auto_review'):
                # Run review off the scheduler thread; the agent commits only shot-local fields.
                reviewed = 协同调度器实例.执行('审片智能体', load_project(pid),
                    {'index': index, '自动反馈': False, '阈值': config.get('review_threshold', 72)})
                if not reviewed.get('成功'):
                    raise ValueError(reviewed.get('错误') or '审片失败')
                emit('shot_review', {'index': index, **(reviewed.get('数据') or {})})
            return result
        except Exception as exc:
            if receipt is not None:
                receipt.update(status='error', msg=str(exc), updated=time.time())
            raise
        finally:
            if receipt is not None:
                rerender_store(PROJECTS_DIR, pid).save(receipt['id'], receipt)
                try:
                    delattr(_RUNTIME, 'batch_render_receipt')
                except AttributeError:
                    pass
            clear_runtime_config()
    def completed(index, result):
        nonlocal count
        count += 1
        emit('shot', result)
        emit('progress', {'done': count, 'total': len(indexes)})
        if task is not None:
            task.update(progress=round(count*100/max(1,len(indexes))), msg=f'已完成 {count}/{len(indexes)} 镜')
    schedule(project['script']['shots'], indexes, worker, completed,
             lambda shot: previous_video(sys.modules[__name__], load_project(pid), shot),
             workers=workers, cancelled=lambda: pipeline_cancelled(pid))
    project = load_project(pid) or {}
    complete = _project_shots_complete(project)
    final_ready = bool(_final_file_path(project))
    if not exact_selection and complete and _project_shots_have_files(project) and not final_ready:
        send('stage', {'stage': 5, 'name': '视频合成', 'status': 'running',
                       'msg': '所有分镜已完成，正在自动合成成片...'})
        if not resynth_pipeline(project, send, cancel_check=lambda: None):
            if task is not None:
                task.update(status='error', phase='合成失败', msg='分镜已完成，但最终视频合成失败')
            send('render_selected_done', {'selected': indexes, 'done': len(indexes),
                                          'all_rendered': True, 'final_ready': False})
            return
        project = load_project(pid) or project
        final_ready = bool(_final_file_path(project))
    if task is not None:
        # Test doubles and legacy browser-only records may have no local files;
        # keep the shot task result visible while clearly reporting that a
        # final must still be synthesized once files are available.
        remaining = [s['index'] for s in (project.get('script') or {}).get('shots', [])
                     if not _shot_has_current_video(next((r for r in project.get('shots', []) if r.get('index') == s['index']), {}))]
        task.update(status='done', progress=100,
                    phase='已完成' if final_ready else ('分镜完成，等待成片文件' if complete else '本批完成，仍有未生成镜头'),
                    msg='智能体批量生成完成' if final_ready else ('分镜已完成，等待有效文件后自动合成' if complete else
                        f'本批 {count}/{len(indexes)} 镜完成；全剧还缺 {len(remaining)} 镜：' + '、'.join(map(str, remaining))))
    send('render_selected_done', {'selected': indexes, 'done': len(indexes),
                                  'all_rendered': complete, 'final_ready': final_ready})


@app.route('/api/project/<pid>/shots/render_selected_stream')
@serialized_queue
def api_render_selected_stream(pid):
    raw = (request.args.get('indexes') or '').strip()
    indexes = []
    for x in raw.split(','):
        x = x.strip()
        if not x:
            continue
        try:
            n = int(x)
        except Exception:
            continue
        if n not in indexes:
            indexes.append(n)
    proj = load_project(pid)
    if not proj:
        return jsonify({"ok": False, "msg": "项目不存在"}), 404
    if request.args.get('scope') == 'missing':
        rendered = {s.get('index'): s for s in proj.get('shots', [])}
        indexes = [s['index'] for s in (proj.get('script') or {}).get('shots', [])
                   if not _shot_has_current_video(rendered.get(s['index'], {}))]
    if not indexes:
        return jsonify({"ok": False, "msg": "没有待生成镜头"}), 400
    # Reconnecting stream clients must not submit an overlapping batch twice.
    # Durable receipts also protect jobs still running on ComfyUI after restart.
    in_flight = {i for t in BATCH_RENDER_TASKS.values()
                 if t.get('pid') == pid and t.get('status') == 'running'
                 for i in t.get('indexes', [])}
    for receipt_path in (Path(PROJECTS_DIR) / pid / 'rerender_tasks').glob('*.json'):
        try:
            receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        if receipt.get('status') == 'running' and receipt.get('prompt_id') and receipt.get('node_url'):
            in_flight.add(receipt.get('index'))
    indexes = [i for i in indexes if i not in in_flight]
    if not indexes:
        return Response(sse('end', {'ok': True, 'already_running': True,
                                    'msg': '所选镜头已提交或正在调度，继续跟踪原任务'}),
                        mimetype='text/event-stream')
    from core.reference_sync import require_synced
    try:
        require_synced(proj, indexes)
    except ValueError as exc:
        return jsonify(ok=False, msg=str(exc), code='reference_sync_required'), 409
    exact_selection = request.args.get('exact') == '1'
    task_id = uuid.uuid4().hex[:12]
    task = {
        "id": task_id,
        "status": "running",
        "msg": "已加入视频队列",
        "pid": pid,
        "indexes": indexes,
        "progress": 0,
        "phase": "排队中",
        "created": time.time(),
        "updated": time.time(),
    }
    BATCH_RENDER_TASKS[task_id] = task
    render_cfg = project_render_config(proj)
    # 小样分支：使用临时项目和低规格参数，绝不写回正式项目。
    preview = request.args.get('preview') == '1'
    if preview:
        try:
            preview_pid = f"preview_{pid}_{uuid.uuid4().hex[:8]}"
            preview_proj = copy.deepcopy(proj)
            preview_proj['id'] = preview_pid
            preview_proj['title'] = f"{proj.get('title', pid)} · 小样"
            preview_proj['render_config'] = copy.deepcopy(render_cfg)
            preview_proj['render_config'].update({'megapixels': 0.2, 'h3_steps': 8})
            preview_proj['series'] = {}
            save_project(preview_proj)
            # 记录最近一次小样分支，重新打开正式项目时可继续查看。
            proj['preview_project_id'] = preview_pid
            save_project(proj)
            pid = preview_pid
            render_cfg = project_render_config(preview_proj)
        except Exception as exc:
            app.logger.exception('preview project creation failed')
            return jsonify({'ok': False, 'msg': f'小样项目创建失败：{exc}'}), 500
    def stream():
        queue = []
        last_emit = time.monotonic()
        def push(event, data):
            if event == "stage" and data.get("status") == "running":
                task["phase"] = data.get("name") or "批量渲染中"
                task["msg"] = data.get("msg") or task["phase"]
            elif event == "error":
                task["status"] = "error"
                task["msg"] = data.get("msg") or "批量生成失败"
                task["phase"] = "失败"
            task["updated"] = time.time()
            queue.append(sse(event, data))
        yield sse('start', {"pid": pid, "indexes": indexes, "total": len((proj.get('script') or {}).get('shots', []))})
        def worker():
            try:
                set_runtime_config(render_cfg)
                _render_selected_shots(pid, indexes, push, task=task, exact_selection=exact_selection)
                push('end', {"ok": True})
            except Exception as e:
                import traceback; traceback.print_exc()
                task["status"] = "error"
                task["msg"] = str(e) or f"{type(e).__name__}（未提供详细信息）"
                task["phase"] = "失败"
                task["updated"] = time.time()
                push('error', {"msg": task["msg"]})
            finally:
                clear_runtime_config()
        t = threading.Thread(target=worker, daemon=True)
        t.start()
        while True:
            if queue:
                yield queue.pop(0)
                last_emit = time.monotonic()
            elif not t.is_alive():
                break
            else:
                if time.monotonic() - last_emit >= 10:
                    yield ": keep-alive\n\n"
                    last_emit = time.monotonic()
                time.sleep(0.3)
        while queue:
            yield queue.pop(0)
    return Response(stream(), mimetype='text/event-stream', headers={'Cache-Control': 'no-cache, no-transform', 'X-Accel-Buffering': 'no'})

# 分镜重渲染后台任务（手动模式下"编辑提示词→重新渲染该镜"用）
from core.rerender_state import store as rerender_store, recover as recover_rerender
RERENDER_TASKS = {}
SUBMITTED_RENDER_RECEIPTS = set()
SUBMITTED_RENDER_RECEIPTS_LOCK = threading.RLock()

def _recover_submitted_render_receipts_once():
    """把服务重启前已提交、但尚未下载的 ComfyUI 结果接回项目。"""
    recovered = 0
    for task_path in Path(PROJECTS_DIR).glob('*/rerender_tasks/*.json'):
        pid = task_path.parent.parent.name
        task_id = task_path.stem
        with SUBMITTED_RENDER_RECEIPTS_LOCK:
            if task_id in SUBMITTED_RENDER_RECEIPTS:
                continue
        task = rerender_store(PROJECTS_DIR, pid).load(task_id)
        if not isinstance(task, dict) or task.get('status') != 'running':
            continue
        # A receipt is written before submission; wait until set_prompt has
        # persisted the prompt_id and node URL instead of turning a queued
        # in-process task into a false error.
        if not task.get('prompt_id') or not task.get('node_url'):
            continue
        with SUBMITTED_RENDER_RECEIPTS_LOCK:
            SUBMITTED_RENDER_RECEIPTS.add(task_id)
        try:
            result = recover_rerender(task, sys.modules[__name__])
            rerender_store(PROJECTS_DIR, pid).save(task_id, result)
            if result.get('status') == 'done':
                recovered += 1
        except Exception as exc:
            print(f'[渲染回执] 恢复失败 {pid}/{task_id}: {exc}', flush=True)
        finally:
            with SUBMITTED_RENDER_RECEIPTS_LOCK:
                SUBMITTED_RENDER_RECEIPTS.discard(task_id)
    return recovered

def _render_receipt_recovery_loop():
    while True:
        try:
            _recover_submitted_render_receipts_once()
        except Exception as exc:
            print(f'[渲染回执] 扫描失败: {exc}', flush=True)
        time.sleep(5)

def _rerender_worker(task_id, pid, index, prompt, video_model=None, duration_override=None):
    task = RERENDER_TASKS[task_id]
    with SUBMITTED_RENDER_RECEIPTS_LOCK:
        SUBMITTED_RENDER_RECEIPTS.add(task_id)
    _RUNTIME.rerender_receipt = task
    try:
        def progress(info):
            task.update(progress=info.get('percent', 0), phase=info.get('phase', '渲染中'),
                        elapsed=info.get('elapsed', 0), eta=info.get('eta', 0), updated=time.time())
        result = _agent_render_selected_shot(pid, index, prompt, duration_override, progress, video_model,
                                             allow_disconnected=True)
        task.update(status='done', msg='重渲染完成', video_url=result['video_url'])
    except Exception as exc:
        task.update(status='error', msg=str(exc))
    finally:
        rerender_store(PROJECTS_DIR, pid).save(task_id, task)
        _RUNTIME.rerender_receipt = None
        with SUBMITTED_RENDER_RECEIPTS_LOCK:
            SUBMITTED_RENDER_RECEIPTS.discard(task_id)
        clear_runtime_config()


@app.route('/api/project/<pid>/shot/<int:index>/rerender', methods=['POST'])
def project_shot_rerender(pid, index):
    """手动确认模式：用新提示词在流程内重新渲染某个已生成的分镜。返回 task_id 供轮询。"""
    proj = load_project(pid)
    if not proj:
        return jsonify({"error": "项目不存在"}), 404
    target = next((s for s in proj.get('shots', []) if s.get('index') == index), None)
    if not target:
        return jsonify({"error": f"分镜{index}不存在"}), 404
    data = request.get_json(force=True, silent=True) or {}
    prompt = (data.get('prompt') or '').strip() or target.get('prompt', '')
    if not prompt:
        return jsonify({"error": "提示词为空"}), 400
    video_model = str(data.get('video_model') or '').strip() or None
    if video_model and media_provider() != 'jimeng':
        return jsonify({"error": "只有启用即梦 API 时才能选择视频模型"}), 400
    try:
        duration = int(data.get('duration') or target.get('duration') or 8)
    except (TypeError, ValueError):
        return jsonify({"error": "视频时长必须是 8、10、12 或 15 秒"}), 400
    if duration not in (8, 10, 12, 15):
        return jsonify({"error": "视频时长必须是 8、10、12 或 15 秒"}), 400
    task_id = uuid.uuid4().hex[:12]
    RERENDER_TASKS[task_id] = {"status": "running", "msg": "已加入队列", "pid": pid, "index": index, "video_url": "", "progress": 0, "elapsed": 0, "eta": 0, "phase": "排队中", "created": time.time(), "updated": time.time()}
    RERENDER_TASKS[task_id]['id'] = task_id
    RERENDER_TASKS[task_id]['prompt'] = prompt
    rerender_store(PROJECTS_DIR, pid).save(task_id, RERENDER_TASKS[task_id])
    with PROJECT_IO_LOCK:
        latest = load_project(pid)
        latest.setdefault('rerender_latest', {})[str(index)] = task_id
        save_project(latest)
    threading.Thread(
        target=_rerender_worker,
        args=(task_id, pid, index, prompt, video_model, duration),
        daemon=True,
    ).start()
    return jsonify({"task_id": task_id})

@app.route('/api/project/<pid>/shot/<int:index>/prompt-chat', methods=['POST'])
def project_shot_prompt_chat(pid, index):
    """用多轮对话修改并保存当前分镜 H3 提示词，不直接触发渲染。"""
    proj = load_project(pid)
    if not proj:
        return jsonify({"ok": False, "error": "项目不存在"}), 404
    target = _shot_target(proj, index)
    script_shot = next((s for s in ((proj.get("script") or {}).get("shots") or [])
                        if int(s.get("index", 0) or 0) == index), None)
    if not target and not script_shot:
        return jsonify({"ok": False, "error": f"分镜{index}不存在"}), 404
    data = request.get_json(silent=True) or {}
    current_prompt = str(data.get("prompt") or (target or {}).get("prompt") or "").strip()
    message = str(data.get("message") or "").strip()
    if not current_prompt:
        return jsonify({"ok": False, "error": "当前分镜还没有提示词"}), 400
    if not message:
        return jsonify({"ok": False, "error": "请先告诉 AI 想怎么修改"}), 400

    shot = script_shot or {}
    old_cfg = project_render_config(proj)
    set_runtime_config(old_cfg)
    skill_rules = 构造提示词技能规则(shot)
    dialogue = "；".join(
        f"{d.get('speaker', '')}：{d.get('line', '')}"
        for d in (shot.get("dialogue") or []) if isinstance(d, dict)
    ) or "无台词"
    history = (target or {}).get("chat_history", [])
    clean_history = []
    for item in history[-10:]:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        content = str(item.get("content") or "").strip()
        if role in ("user", "assistant") and content and len(content) <= 2000:
            clean_history.append({"role": role, "content": content})

    system_prompt = f"""你是短剧视频提示词导演，负责通过对话修改一个已经可用于 MiniMax H3 的视频提示词。
你必须严格遵守：
1. 只修改用户要求涉及的部分，其他内容尽量保持。
2. 不得删除、改写、翻译原分镜台词。人物介绍与固定声线移到开头不朗读的设定段；开头必须建立“角色名→Subject→S编号→Picture→外观/声线”的固定映射。每次发声前必须单独写“说话人物：角色名（Subject N / SN），其身份锚点：……”（仅用于身份绑定，不朗读），随后才写 <Subject N> (SN) says:，并立即换行接 <d>[Chinese]台词原文</d>；不得用“他/她/某人”代替角色名，且 says 与 <d> 之间禁止插入姓名、年龄、服装、声线或动作。Subject与Picture编号分别绑定，不得混淆。
3. 不得改变角色身份、参考图 Picture 编号含义；服装可按用户要求和本镜剧情状态调整，尤其要修正不合场景的睡眠着装。
4. 保持 H3 提示词的时间轴、镜头运动、动作连续性和正常播放速度；允许自然缓慢动作，禁止明确的视频慢放、定格、静帧。
5. 输出必须是 JSON 对象，字段为 reply 和 prompt。reply 用简短中文说明改了什么，prompt 只放完整的新 H3 提示词，不要 Markdown 代码块。

【本次必须使用的提示词 Skill 规则】
{skill_rules}
"""
    user_prompt = f"""【当前分镜结构】
场景：{shot.get('scene', '')}
角色：{'、'.join(shot.get('characters') or [])}
动作：{shot.get('action', '')}
运镜：{shot.get('camera', '')}
时长：{shot.get('duration', 8)}秒
台词：{dialogue}

【当前 H3 提示词】
{current_prompt}

【用户这次修改要求】
{message}

请返回完整的新提示词。"""
    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(clean_history)
    messages.append({"role": "user", "content": user_prompt})
    try:
        content, err = llm_chat(messages, max_tokens=5000, temperature=0.35, timeout=240, model=str(data.get('model') or '').strip() or None)
    finally:
        clear_runtime_config()
    if not content:
        return jsonify({"ok": False, "error": f"AI修改失败: {err or '模型无返回'}"}), 502
    result = parse_json_from_text(content)
    if not isinstance(result, dict) or not str(result.get("prompt") or "").strip():
        return jsonify({"ok": False, "error": "AI返回格式异常，请重试"}), 502
    from infrastructure.dialogue_boundary import dialogue_boundary_errors
    if dialogue_boundary_errors(str(result["prompt"])):
        return jsonify({"ok": False, "error": "对白格式不符合人物介绍与台词隔离规则，请重试"}), 502
    new_prompt = filter_slow_motion(str(result.get("prompt") or "").strip())
    reply = str(result.get("reply") or "已按要求修改提示词。").strip()
    # Persist the edited prompt immediately.  The browser field is only a
    # draft; reloads and rerender workers read these project records.
    with PROJECT_IO_LOCK:
        latest = load_project(pid)
        if not latest:
            return jsonify(ok=False, error="项目已不存在，请重新载入"), 409
        latest.setdefault("prompts", {})[str(index)] = new_prompt
        shot_record = next((item for item in latest.setdefault("shots", [])
                            if int(item.get("index", 0) or 0) == index), None)
        if shot_record is None:
            shot_record = {"index": index}
            latest["shots"].append(shot_record)
        archive_edit(shot_record, current_prompt, new_prompt, message, reply, data.get("model"))
        shot_record["prompt"] = new_prompt
        latest.setdefault("shot_confirm", {}).setdefault(str(index), {})["prompt"] = new_prompt
        script_record = next((item for item in (latest.get("script") or {}).get("shots", [])
                              if int(item.get("index", 0) or 0) == index), None)
        if script_record is not None:
            script_record["prompt"] = new_prompt
        invalidate_final(latest)
        save_project(latest)
    return jsonify({
        "ok": True,
        "reply": reply,
        "prompt": new_prompt,
        "chat_history": shot_record["chat_history"],
        "edit_revisions": shot_record["edit_revisions"],
    })

@app.route('/api/project/<pid>/asset/<path:key>/prompt-chat', methods=['POST'])
def project_asset_prompt_chat(pid, key):
    """通过对话修改资产图片提示词。"""
    proj = load_project(pid)
    if not proj:
        return jsonify({"ok": False, "error": "项目不存在"}), 404
    if not re.match(r'^(char|scene|prop)_[^/]+$', key):
        return jsonify({"ok": False, "error": "非法资产标识"}), 400
    data = request.get_json(silent=True) or {}
    prompt = str(data.get('prompt') or '').strip()
    message = str(data.get('message') or '').strip()
    model = str(data.get('model') or '').strip() or None
    if not prompt or not message:
        return jsonify({"ok": False, "error": "请提供当前提示词和修改要求"}), 400
    asset = (proj.get('assets') or {}).get(key)
    if not isinstance(asset, dict):
        return jsonify(ok=False, error='资产不存在'), 404
    history = asset.get('chat_history', [])
    clean = [{"role": x.get('role'), "content": str(x.get('content') or '')[:2000]}
             for x in history[-10:] if isinstance(x, dict) and x.get('role') in ('user','assistant') and x.get('content')]
    system = "你是短剧资产图片提示词编辑。只按用户要求修改提示词，保留未提及内容和主体身份。输出JSON对象，字段reply（简短中文说明）和prompt（完整图片生成提示词，不要Markdown）。"
    if key.startswith('scene_'):
        system += '\n' + SCENE_REFERENCE_RULE + '根据场景内容在最终提示词中明确写出室内平视或室外鸟瞰中的一种，删除冲突的旧视角和人物描写。'
    user = f"【当前资产提示词】\n{prompt}\n\n【用户修改要求】\n{message}"
    try:
        content, err = llm_chat([{"role":"system","content":system}, *clean, {"role":"user","content":user}], max_tokens=2500, temperature=0.35, timeout=180, model=model)
    except Exception as exc:
        return jsonify({"ok": False, "error": f"AI修改失败: {exc}"}), 502
    if not content:
        return jsonify({"ok": False, "error": f"AI修改失败: {err or '模型无返回'}"}), 502
    result = parse_json_from_text(content)
    if not isinstance(result, dict) or not str(result.get('prompt') or '').strip():
        return jsonify({"ok": False, "error": "AI返回格式异常，请重试"}), 502
    new_prompt = str(result['prompt']).strip()
    reply = str(result.get('reply') or '已按要求修改提示词。').strip()
    with PROJECT_IO_LOCK:
        latest = load_project(pid)
        asset = (latest or {}).get('assets', {}).get(key)
        if not isinstance(asset, dict):
            return jsonify(ok=False, error='资产已不存在，请重新载入'), 409
        archive_edit(asset, prompt, new_prompt, message, reply, model)
        asset['prompt'] = new_prompt
        save_project(latest)
    return jsonify(ok=True, reply=reply, prompt=new_prompt,
                   chat_history=asset['chat_history'], edit_revisions=asset['edit_revisions'])

@app.route('/api/project/<pid>/rerender/status/<task_id>')
def project_rerender_status(pid, task_id):
    if not load_project(pid):
        return jsonify(status='error', msg='项目不存在'), 404
    t = RERENDER_TASKS.get(task_id)
    if t and t.get('pid') != pid:
        return jsonify(status='error', msg='任务不存在'), 404
    if not t:
        with PROJECT_IO_LOCK:
            t = rerender_store(PROJECTS_DIR, pid).load(task_id)
            if not t:
                return jsonify(status='error', msg='任务回执不存在，不能以旧视频代替新结果'), 404
            if t.get('status') == 'running':
                t = recover_rerender(t, sys.modules[__name__])
                rerender_store(PROJECTS_DIR, pid).save(task_id, t)
    return jsonify(t)

@app.route('/api/project/<pid>/resynth')
def project_resynth(pid):
    """用户重制完失败镜后，重新合成成片。返回 SSE 流推送合成进度。"""
    proj = load_project(pid)
    if not proj:
        return jsonify({"ok": False, "msg": "项目不存在"}), 404
    # 允许成片页一键重新合成并烧录字幕；配置写回项目，后续重新合成仍沿用该选择。
    subtitle_requested = request.args.get('subtitle', '').lower() in ('1', 'true', 'yes')
    subtitle_only = subtitle_requested and request.args.get('only', '').lower() in ('1', 'true', 'yes')
    with PROJECT_IO_LOCK:
        if pid in SYNTHESIZING_PROJECTS:
            return jsonify(ok=False, msg='该项目正在合成'), 409
        SYNTHESIZING_PROJECTS.add(pid)
    def stream():
        queue = []
        last_emit = time.monotonic()
        def push(event, data):
            queue.append(sse(event, data))
        yield sse('start', {"pid": pid, "resynth": True})
        def worker():
            try:
                current = load_project(pid) or proj
                if subtitle_only:
                    if not reburn_existing_final_subtitles(current, push):
                        raise RuntimeError('现有成片字幕重新生成失败')
                    push('final', {'video_url': available_final(current) or f'/file/outputs/{pid}/{_final_filename(current)}', 'title': current.get('title', '短剧'), 'needs_resynth': bool(current.get('previous_final') and not current.get('final'))})
                    return
                if subtitle_requested:
                    cfg = copy.deepcopy(current.get('render_config') or {})
                    cfg['subtitle_enabled'] = True
                    current['render_config'] = cfg
                    save_project(current)
                resynth_pipeline(current, push)
            except Exception as e:
                import traceback
                traceback.print_exc()
                push('error', {"msg": f"重新合成异常: {e}"})
            finally:
                SYNTHESIZING_PROJECTS.discard(pid)
            push('end', {})
        t = threading.Thread(target=worker, daemon=True)
        t.start()
        while True:
            if queue:
                yield queue.pop(0)
                last_emit = time.monotonic()
            elif not t.is_alive():
                break
            else:
                # Keep long asset/LLM calls alive through browsers and reverse proxies.
                # SSE comments are ignored by EventSource but reset idle timeouts.
                if time.monotonic() - last_emit >= 10:
                    yield ": keep-alive\n\n"
                    last_emit = time.monotonic()
                time.sleep(0.3)
        while queue:
            yield queue.pop(0)
    return Response(stream(), mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache, no-transform', 'X-Accel-Buffering': 'no'})

# ============================== API ==============================
@app.route('/')
def index():
    if MULTIUSER:
        template = 'static/admin-console.html' if request.environ.get('drama.admin_portal') and MULTIUSER.is_admin() else 'index.html'
        page = Path(BASE_DIR, template).read_text(encoding='utf-8')
        response = Response(page.replace('<!-- PLATFORM_BOOTSTRAP -->', MULTIUSER.bootstrap_html()), mimetype='text/html')
    else:
        response = send_file(os.path.join(BASE_DIR, 'index.html'))
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    return response

@app.route('/static/<path:filename>')
def serve_static(filename):
    return send_from_directory(os.path.join(BASE_DIR, 'static'), filename)

@app.route('/file/<folder>/<path:filename>')
def serve_file(folder, filename):
    if folder == 'assets':
        return send_from_directory(ASSETS_DIR, filename)
    if folder == 'outputs':
        return send_from_directory(OUTPUTS_DIR, filename)
    return "Not Found", 404


def 番茄下载器地址():
    return os.environ.get('TOMATO_WEB_ADDR', '0.0.0.0:18423').rsplit(':', 1)[-1]


def 番茄下载器在线():
    try:
        response = requests.get('http://127.0.0.1:18423/', timeout=1.5)
        return response.status_code < 500
    except requests.RequestException:
        return False


def 番茄下载器访问地址():
    """按当前短剧系统的访问主机生成下载器局域网地址。"""
    主机 = request.host.split(':', 1)[0]
    if 主机 in ('0.0.0.0', '::', '[::]', 'localhost'):
        主机 = '127.0.0.1'
    return f'http://{主机}:18423/'


def 启动番茄下载器():
    """启动项目内置的番茄小说下载器 Web UI，重复调用不会重复拉起进程。"""
    global 番茄下载器进程
    with 番茄下载器锁:
        if 番茄下载器在线():
            return True, '番茄小说下载器已经在运行'
        if not os.path.isfile(番茄下载器程序):
            return False, f'下载器程序不存在：{番茄下载器程序}'
        os.makedirs(番茄下载器数据目录, exist_ok=True)
        os.makedirs(os.path.dirname(番茄下载器日志), exist_ok=True)
        try:
            环境 = os.environ.copy()
            环境['TOMATO_WEB_ADDR'] = '0.0.0.0:18423'
            启动选项 = ({'creationflags': subprocess.CREATE_NO_WINDOW}
                        if os.name == 'nt' else {'start_new_session': True})
            with open(番茄下载器日志, 'a', encoding='utf-8') as 日志文件:
                番茄下载器进程 = subprocess.Popen(
                    [番茄下载器程序, '--server', '--data-dir', 番茄下载器数据目录],
                    cwd=番茄下载器数据目录,
                    env=环境,
                    stdin=subprocess.DEVNULL,
                    stdout=日志文件,
                    stderr=subprocess.STDOUT,
                    **启动选项,
                )
        except OSError as exc:
            return False, f'启动下载器失败：{exc}'
        for _ in range(20):
            if 番茄下载器在线():
                return True, '番茄小说下载器已启动'
            if 番茄下载器进程.poll() is not None:
                return False, f'下载器启动后退出，请查看日志：{番茄下载器日志}'
            time.sleep(0.5)
        return False, '下载器启动超时，请查看日志'


@app.route('/api/tomato-downloader/status')
def api_tomato_downloader_status():
    online = 番茄下载器在线()
    return jsonify({
        'ok': True,
        'online': online,
        'url': 番茄下载器访问地址(),
        'port': 18423,
        'installed': os.path.isfile(番茄下载器程序),
        'data_dir': os.path.relpath(番茄下载器数据目录, BASE_DIR),
    })


@app.route('/api/tomato-downloader/start', methods=['POST'])
def api_tomato_downloader_start():
    ok, message = 启动番茄下载器()
    if not ok:
        return jsonify({'ok': False, 'msg': message}), 503
    return jsonify({
        'ok': True,
        'msg': message,
        'url': 番茄下载器访问地址(),
    })


class 小说HTML文字解析器(HTMLParser):
    """把 EPUB XHTML 转成阅读器可用的纯文本。"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.文字 = []
        self.标题 = ''
        self.忽略深度 = 0

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'):
            self.忽略深度 += 1
        if tag in ('h1', 'h2', 'h3', 'p', 'li', 'br', 'div'):
            self.文字.append('\n')

    def handle_endtag(self, tag):
        if tag in ('script', 'style') and self.忽略深度:
            self.忽略深度 -= 1
        if tag in ('h1', 'h2', 'h3', 'p', 'li', 'div'):
            self.文字.append('\n')

    def handle_data(self, data):
        if not self.忽略深度:
            self.文字.append(data)

    def 结果(self):
        text = html_lib.unescape(''.join(self.文字))
        text = re.sub(r'[ \t\f\v]+', ' ', text)
        text = re.sub(r'\n[ \t]+', '\n', text)
        text = re.sub(r'\n{3,}', '\n\n', text)
        return text.strip()


def 小说文件安全路径(file_name):
    """只允许读取番茄下载器独立数据目录中的 EPUB/TXT 文件。"""
    name = os.path.basename(str(file_name or ''))
    if not name or os.path.splitext(name)[1].lower() not in ('.epub', '.txt'):
        return None
    path = os.path.abspath(os.path.join(番茄下载器数据目录, name))
    root = os.path.abspath(番茄下载器数据目录)
    try:
        if os.path.commonpath([path, root]) != root or not os.path.isfile(path):
            return None
    except ValueError:
        return None
    return path


def 解析小说文件(file_path):
    """解析 EPUB/TXT，返回书籍元数据和章节内容。"""
    cache_key = (file_path, os.path.getmtime(file_path), os.path.getsize(file_path))
    with 小说查看器锁:
        if cache_key in 小说查看器缓存:
            return copy.deepcopy(小说查看器缓存[cache_key])
    ext = os.path.splitext(file_path)[1].lower()
    if ext == '.txt':
        with open(file_path, 'r', encoding='utf-8', errors='replace') as book_file:
            raw = book_file.read()
        title = os.path.splitext(os.path.basename(file_path))[0]
        blocks = re.split(r'(?m)(?=^\s*(?:第[0-9零一二三四五六七八九十百千万]+[章节回集].{0,80}|卷[一二三四五六七八九十百千万0-9].{0,80})\s*$)', raw)
        chapters = []
        for block in blocks:
            block = block.strip()
            if not block:
                continue
            lines = block.splitlines()
            chapter_title = lines[0].strip() if len(lines) > 1 and len(lines[0].strip()) <= 100 else f'第{len(chapters) + 1}章'
            content = '\n'.join(lines[1:] if chapter_title != f'第{len(chapters) + 1}章' else lines).strip()
            chapters.append({'index': len(chapters) + 1, 'title': chapter_title, 'text': content})
        if not chapters:
            chapters = [{'index': 1, 'title': title, 'text': raw.strip()}]
        result = {'title': title, 'author': '', 'description': '', 'chapters': chapters}
    else:
        chapters = []
        title = os.path.splitext(os.path.basename(file_path))[0]
        author = ''
        description = ''
        with zipfile.ZipFile(file_path) as archive:
            opf_name = 'OEBPS/content.opf'
            try:
                container = ElementTree.fromstring(archive.read('META-INF/container.xml'))
                rootfile = next(iter(container.iter('{*}rootfile')))
                opf_name = rootfile.attrib.get('full-path') or opf_name
            except Exception:
                pass
            opf_dir = posixpath.dirname(opf_name)
            opf = ElementTree.fromstring(archive.read(opf_name))
            metadata = next(iter(opf.findall('{*}metadata')), None)
            if metadata is not None:
                title_node = next(iter(metadata.findall('{*}title')), None)
                author_node = next(iter(metadata.findall('{*}creator')), None)
                desc_node = next(iter(metadata.findall('{*}description')), None)
                title = (title_node.text or '').strip() if title_node is not None else title
                author = (author_node.text or '').strip() if author_node is not None else ''
                description = (desc_node.text or '').strip() if desc_node is not None else ''
            manifest = {
                item.attrib.get('id'): item.attrib
                for item in opf.findall('.//{*}manifest/{*}item')
            }
            spine = opf.find('{*}spine')
            ordered_ids = [
                node.attrib.get('idref')
                for node in (spine.findall('{*}itemref') if spine is not None else [])
            ]
            for item_id in ordered_ids:
                item = manifest.get(item_id) or {}
                href = item.get('href', '')
                if not href.lower().endswith(('.xhtml', '.html', '.htm')):
                    continue
                member = posixpath.normpath(posixpath.join(opf_dir, href))
                try:
                    parser = 小说HTML文字解析器()
                    parser.feed(archive.read(member).decode('utf-8', errors='replace'))
                    text = parser.结果()
                except KeyError:
                    continue
                if not text:
                    continue
                chapter_title = text.splitlines()[0].strip() if text.splitlines() else f'第{len(chapters) + 1}章'
                if not re.match(r'^(第|卷|楔子|序章|番外|后记|尾声)', chapter_title):
                    chapter_title = f'第{len(chapters) + 1}章'
                chapters.append({'index': len(chapters) + 1, 'title': chapter_title, 'text': text})
        result = {'title': title, 'author': author, 'description': description, 'chapters': chapters}
    with 小说查看器锁:
        小说查看器缓存[cache_key] = copy.deepcopy(result)
    return result


def 小说列表():
    os.makedirs(番茄下载器数据目录, exist_ok=True)
    result = []
    for name in sorted(os.listdir(番茄下载器数据目录)):
        path = 小说文件安全路径(name)
        if not path:
            continue
        try:
            parsed = 解析小说文件(path)
            result.append({
                'file_name': name,
                'title': parsed['title'],
                'author': parsed['author'],
                'description': parsed['description'][:240],
                'chapter_count': len(parsed['chapters']),
                'format': os.path.splitext(name)[1].lower().lstrip('.'),
                'size': os.path.getsize(path),
                'modified': os.path.getmtime(path),
            })
        except Exception as exc:
            result.append({'file_name': name, 'title': name, 'error': str(exc)})
    return result


@app.route('/api/novel-viewer/books')
def api_novel_viewer_books():
    try:
        return jsonify({'ok': True, 'books': 小说列表()})
    except Exception as exc:
        return jsonify({'ok': False, 'msg': f'读取小说库失败：{exc}'}), 500


@app.route('/api/novel-viewer/book')
def api_novel_viewer_book():
    path = 小说文件安全路径(request.args.get('file'))
    if not path:
        return jsonify({'ok': False, 'msg': '小说文件不存在或格式不支持'}), 404
    try:
        parsed = 解析小说文件(path)
        return jsonify({
            'ok': True,
            'book': {key: value for key, value in parsed.items() if key != 'chapters'},
            'chapters': [
                {'index': item['index'], 'title': item['title'], 'length': len(item['text'])}
                for item in parsed['chapters']
            ],
        })
    except Exception as exc:
        return jsonify({'ok': False, 'msg': f'解析小说失败：{exc}'}), 500


@app.route('/api/novel-viewer/chapter')
def api_novel_viewer_chapter():
    path = 小说文件安全路径(request.args.get('file'))
    try:
        chapter_index = max(1, int(request.args.get('chapter', 1)))
    except (TypeError, ValueError):
        chapter_index = 1
    if not path:
        return jsonify({'ok': False, 'msg': '小说文件不存在或格式不支持'}), 404
    try:
        parsed = 解析小说文件(path)
        if chapter_index > len(parsed['chapters']):
            return jsonify({'ok': False, 'msg': '章节不存在'}), 404
        chapter = parsed['chapters'][chapter_index - 1]
        return jsonify({'ok': True, 'book': parsed['title'], 'chapter': chapter})
    except Exception as exc:
        return jsonify({'ok': False, 'msg': f'读取章节失败：{exc}'}), 500


@app.route('/api/novel-viewer/queue-series', methods=['POST'])
def api_novel_viewer_queue_series():
    """把小说章节批量建立为连续剧项目，并交给完整自动化管线。"""
    data = request.get_json(force=True, silent=True) or {}
    file_name = str(data.get('file') or '').strip()
    series_id = str(data.get('series_id') or '').strip()
    template_series_id = str(data.get('template_series_id') or '').strip()
    try:
        chapter_indexes = [int(x) for x in (data.get('chapters') or [])]
        start_episode = max(1, int(data.get('start_episode', 1)))
    except (TypeError, ValueError):
        return jsonify({'ok': False, 'msg': '章节或起始集数格式不正确'}), 400
    if not file_name or not series_id or not chapter_indexes:
        return jsonify({'ok': False, 'msg': '请提供小说、章节和剧项目'}), 400
    s = load_series(series_id)
    path = 小说文件安全路径(file_name)
    if not s:
        return jsonify({'ok': False, 'msg': '剧项目不存在'}), 404
    if not path:
        return jsonify({'ok': False, 'msg': '小说文件不存在或格式不支持'}), 404
    try:
        parsed = 解析小说文件(path)
    except Exception as exc:
        return jsonify({'ok': False, 'msg': f'解析小说失败：{exc}'}), 500

    selected = []
    for index in chapter_indexes:
        if 1 <= index <= len(parsed.get('chapters', [])):
            selected.append(parsed['chapters'][index - 1])
    if not selected:
        return jsonify({'ok': False, 'msg': '所选章节不存在'}), 400

    # 默认沿用目标剧集的最新项目；调用方也可以明确指定另一部剧作为参数模板。
    # 这样新建小说剧集时，可以稳定复用《都重生了》的画风、时长、镜头数和节点配置。
    template = None
    template_series = load_series(template_series_id) if template_series_id else s
    for meta in (template_series.get('episodes') or {}).values():
        candidate = load_project(meta.get('project_id')) if isinstance(meta, dict) else None
        if candidate and int((candidate.get('series') or {}).get('episode', 0) or 0) == 4:
            template = candidate
            break
    if not template:
        for meta in (template_series.get('episodes') or {}).values():
            candidate = load_project(meta.get('project_id')) if isinstance(meta, dict) else None
            if candidate:
                template = candidate
                break
    base_cfg = project_render_config(template) if template else copy.deepcopy(runtime_config())
    base_cfg.update({
        'manual_mode': False,
        'batch_prompt_mode': False,
        'script_review_mode': False,
    })
    previous_summary = ''
    created = []
    skipped = []
    queue = load_render_queue()
    existing_queue = {str(item.get('pid')): item for item in queue.get('items', [])}
    episodes = s.setdefault('episodes', {})
    for offset, chapter in enumerate(selected):
        episode = start_episode + offset
        key = str(episode)
        old_meta = episodes.get(key) if isinstance(episodes.get(key), dict) else {}
        pid = old_meta.get('project_id')
        project = load_project(pid) if pid else None
        if not project:
            pid = uuid.uuid4().hex[:12]
            title = f"{s.get('name') or parsed.get('title') or '连续剧'} · 第{episode}集"
            chapter_title = chapter.get('title') or f"第{chapter.get('index')}章"
            idea = (
                f"《{parsed.get('title') or s.get('name') or '小说'}》·{chapter_title}\n\n"
                f"{chapter.get('text') or ''}\n\n"
                f"【短剧导演简报】\n"
                f"连续剧：是；剧名《{s.get('name') or parsed.get('title') or '连续剧'}》；第{episode}集\n"
                f"系列ID：{series_id}\n"
                f"上一集承接：{previous_summary}\n"
            )
            project = {
                'id': pid,
                'idea': idea,
                'title': title,
                'script': None,
                'assets': {},
                'shots': [],
                'final': None,
                'created': time.time(),
                'render_config': copy.deepcopy(base_cfg),
                'script_review_required': False,
                'script_confirmed': True,
                'novel_batch_source': {
                    'file': file_name,
                    'chapter': chapter.get('index'),
                    'chapter_title': chapter.get('title', ''),
                },
                'series': {
                    'id': series_id,
                    'name': s.get('name') or parsed.get('title') or '连续剧',
                    'episode': episode,
                    'previous_summary': previous_summary,
                },
            }
            save_project(project)
            created.append(pid)
        else:
            skipped.append({'episode': episode, 'pid': pid, 'msg': '项目已存在'})
        synopsis = (project.get('script') or {}).get('synopsis') or chapter.get('text', '')[:240]
        episodes[key] = {
            'project_id': pid,
            'title': project.get('title') or f"{s.get('name') or parsed.get('title')} · 第{episode}集",
            'synopsis': synopsis,
            'updated': time.time(),
        }
        item = existing_queue.get(str(pid))
        if item and item.get('status') not in ('done', 'removed'):
            continue
        if project.get('final'):
            continue
        queue.setdefault('items', []).append({
            'id': f"rq_{uuid.uuid4().hex[:12]}",
            'pid': pid,
            'title': project.get('title') or f"{s.get('name') or parsed.get('title')} · 第{episode}集",
            'series': project.get('series'),
            'status': 'queued',
            'progress': 0,
            'message': '等待自动化管线',
            'error': '',
            'created': time.time(),
            'updated': time.time(),
            'pipeline_mode': 'full_auto',
        })
        previous_summary = synopsis
    s['updated'] = time.time()
    save_series(s)
    save_render_queue(queue)
    ensure_render_queue_worker()
    return jsonify({
        'ok': True,
        'created': created,
        'skipped': skipped,
        'episodes': [start_episode + i for i in range(len(selected))],
        **render_queue_snapshot(),
    })


def 小说AI输入(parsed, chapter_indexes=None, max_chars=28000):
    chapters = parsed.get('chapters', [])
    if chapter_indexes:
        selected = [chapters[i - 1] for i in chapter_indexes if 1 <= i <= len(chapters)]
    else:
        selected = chapters
    pieces = []
    used = 0
    for chapter in selected:
        piece = f"\n\n【{chapter['title']}】\n{chapter['text']}"
        if used + len(piece) > max_chars:
            piece = piece[:max(0, max_chars - used)]
        pieces.append(piece)
        used += len(piece)
        if used >= max_chars:
            break
    return ''.join(pieces), [item['index'] for item in selected[:len(pieces)]]


def 小说片段定位材料(parsed, chapter_indexes, highlight, max_chars=16000):
    """在指定章节中优先寻找精彩片段线索附近的原文，减少长文本等待。"""
    chapters = parsed.get('chapters', [])
    selected = [chapters[i - 1] for i in chapter_indexes if 1 <= i <= len(chapters)] if chapter_indexes else chapters
    clue = ' '.join(str(highlight.get(key) or '') for key in ('title', 'excerpt', 'hook'))
    keywords = [word for word in re.findall(r'[\u4e00-\u9fff]{2,}|[A-Za-z0-9]{3,}', clue) if len(word) >= 2]
    candidates = []
    for chapter in selected:
        text = chapter['text']
        positions = [text.find(word) for word in keywords if text.find(word) >= 0]
        if positions:
            center = min(positions)
            start = max(0, center - 3500)
            candidates.append(f"【{chapter['title']}】\n{text[start:start + 9000]}")
    if not candidates:
        return 小说AI输入(parsed, chapter_indexes, max_chars=max_chars)
    material = '\n\n'.join(candidates)
    return material[:max_chars], [item['index'] for item in selected if item['index'] in {
        chapter['index'] for chapter in selected if chapter['text'] in material
    }]


def 小说全书AI材料(parsed):
    """为长篇小说分段提炼全书脉络，再交给最终编剧使用。"""
    chapters = parsed.get('chapters', [])
    full_text = '\n\n'.join(f"【{item['title']}】\n{item['text']}" for item in chapters)
    if len(full_text) <= 36000:
        return full_text, list(range(1, len(chapters) + 1))
    chunks = [full_text[i:i + 14000] for i in range(0, len(full_text), 14000)]
    summaries = []
    for index, chunk in enumerate(chunks, 1):
        summary, error = llm_chat([
            {'role': 'system', 'content': '你是小说责任编辑，只输出准确的中文剧情梗概，不要虚构。'},
            {'role': 'user', 'content': f"""请概括这部长篇小说第{index}部分的剧情信息，保留人物关系、关键事件、
冲突升级、反转、重要道具、代表性对白和这一部分结尾状态。不要点评，不要漏掉主要事件。
小说名：{parsed['title']}
原文：
{chunk}"""},
        ], max_tokens=2400, temperature=0.25)
        if error:
            raise RuntimeError(f'第{index}/{len(chunks)}段摘要失败：{error}')
        summaries.append(f'【全书剧情摘要第{index}段】\n{summary}')
    return '\n\n'.join(summaries), list(range(1, len(chapters) + 1))


@app.route('/api/novel-viewer/highlights', methods=['POST'])
def api_novel_viewer_highlights():
    data = request.get_json(silent=True) or {}
    path = 小说文件安全路径(data.get('file'))
    if not path:
        return jsonify({'ok': False, 'msg': '小说文件不存在或格式不支持'}), 404
    try:
        parsed = 解析小说文件(path)
        scope = str(data.get('scope') or 'current')
        indexes = data.get('chapters') if isinstance(data.get('chapters'), list) else []
        if scope == 'all':
            all_text = '\n\n'.join(f"【{item['title']}】\n{item['text']}" for item in parsed['chapters'])
            if len(all_text.strip()) < 80:
                return jsonify({'ok': False, 'msg': '整本小说内容太少，无法提取精彩片段'}), 400
            chunks = [all_text[i:i + 14000] for i in range(0, len(all_text), 14000)]
            candidates = []
            for segment_index, chunk in enumerate(chunks, 1):
                segment_prompt = f"""你是短剧编剧，请从小说第{segment_index}段原文中提取0到3个适合改编为短视频的精彩片段。
只基于原文，不要编造。每个片段包含标题、原文摘录、精彩原因、视频钩子。
严格输出JSON：{{"highlights":[{{"title":"","excerpt":"","reason":"","hook":""}}]}}
小说名：{parsed['title']}
原文：
{chunk}"""
                segment_content, segment_error = llm_chat([
                    {'role': 'system', 'content': '你只输出严格JSON，不要使用Markdown代码块。'},
                    {'role': 'user', 'content': segment_prompt},
                ], max_tokens=2200, temperature=0.35)
                if segment_error:
                    return jsonify({'ok': False, 'msg': f'整本小说第{segment_index}段提取失败：{segment_error}'}), 502
                segment_result = parse_json_from_text(segment_content)
                if isinstance(segment_result, dict) and isinstance(segment_result.get('highlights'), list):
                    candidates.extend(segment_result['highlights'][:3])
            source = json.dumps(candidates, ensure_ascii=False)
            used_chapters = list(range(1, len(parsed['chapters']) + 1))
            segment_count = len(chunks)
            prompt = f"""你是短剧总编，请从下面各段提取结果中筛选并去重，保留最适合改编的3到8个精彩片段。
不得虚构，不要重复相似片段。严格输出JSON：{{"highlights":[{{"title":"","excerpt":"","reason":"","hook":""}}]}}
小说名：{parsed['title']}
各段候选：
{source}"""
        else:
            source, used_chapters = 小说AI输入(parsed, indexes)
            if len(source.strip()) < 80:
                return jsonify({'ok': False, 'msg': '选中的章节内容太少，无法提取精彩片段'}), 400
            segment_count = 1
            prompt = f"""你是短剧编剧，请从下面小说原文中提取适合改编为短视频的精彩片段。
只基于原文，不要编造人物、事件或台词。输出3到8个片段，每个片段包含：
标题、原文范围、精彩原因、适合的视频钩子。保留关键原文台词，不要把整章重复输出。
严格输出JSON：{{"highlights":[{{"title":"","excerpt":"","reason":"","hook":""}}]}}
小说名：{parsed['title']}
原文：{source}"""
        content, error = llm_chat([
            {'role': 'system', 'content': '你只输出严格JSON，不要使用Markdown代码块。'},
            {'role': 'user', 'content': prompt},
        ], max_tokens=5000, temperature=0.35)
        if error:
            return jsonify({'ok': False, 'msg': f'AI提取失败：{error}'}), 502
        result = parse_json_from_text(content)
        if not isinstance(result, dict) or not isinstance(result.get('highlights'), list):
            return jsonify({'ok': False, 'msg': 'AI返回格式异常，请重试'}), 502
        return jsonify({'ok': True, 'highlights': result['highlights'][:8], 'chapters': used_chapters, 'scope': scope, 'segment_count': segment_count})
    except Exception as exc:
        return jsonify({'ok': False, 'msg': f'提取精彩片段失败：{exc}'}), 500


@app.route('/api/novel-viewer/trailer-script', methods=['POST'])
def api_novel_viewer_trailer_script():
    data = request.get_json(silent=True) or {}
    path = 小说文件安全路径(data.get('file'))
    if not path:
        return jsonify({'ok': False, 'msg': '小说文件不存在或格式不支持'}), 404
    mode = str(data.get('mode') or '先导片').strip()
    if mode not in ('先导片', '预告片'):
        mode = '先导片'
    try:
        parsed = 解析小说文件(path)
        source, used_chapters = 小说全书AI材料(parsed)
        if len(source.strip()) < 120:
            return jsonify({'ok': False, 'msg': '小说内容太少，无法生成剧本'}), 400
        prompt = f"""你是影视项目开发编剧。请根据小说全书材料，为《{parsed['title']}》创作一份{mode}剧本。
目标是让观众理解核心人物、世界/关系和最大悬念，但不能把全书剧情讲完。
只基于全书材料，不得虚构主要人物或改变人物关系。保留材料中最有代表性的对白，必要时用旁白串联。
输出结构：片名、定位、时长、核心卖点、人物引入、镜头脚本（镜头号/时长/画面/旁白或对白/声音）、结尾悬念。
总时长建议：先导片60到90秒，预告片30到60秒。用中文输出，适合后续交给短剧生成系统继续拆分。
以下是经过分段整理的全书材料：
{source}"""
        content, error = llm_chat([
            {'role': 'system', 'content': '你是严谨的影视编剧，只输出可执行的中文剧本。'},
            {'role': 'user', 'content': prompt},
        ], max_tokens=7000, temperature=0.55)
        if error:
            return jsonify({'ok': False, 'msg': f'AI生成失败：{error}'}), 502
        return jsonify({'ok': True, 'mode': mode, 'script': content, 'chapters': used_chapters})
    except Exception as exc:
        return jsonify({'ok': False, 'msg': f'生成先导片/预告片剧本失败：{exc}'}), 500


@app.route('/api/novel-viewer/excerpt-script', methods=['POST'])
def api_novel_viewer_excerpt_script():
    """使用原小说章节内容生成片段剧本，尽量保留原文叙述和对白。"""
    data = request.get_json(silent=True) or {}
    path = 小说文件安全路径(data.get('file'))
    if not path:
        return jsonify({'ok': False, 'msg': '小说文件不存在或格式不支持'}), 404
    try:
        parsed = 解析小说文件(path)
        indexes = data.get('chapters') if isinstance(data.get('chapters'), list) else []
        highlight = data.get('highlight') if isinstance(data.get('highlight'), dict) else {}
        source, used_chapters = 小说片段定位材料(parsed, indexes, highlight, max_chars=16000)
        if len(source.strip()) < 80:
            return jsonify({'ok': False, 'msg': '原小说片段内容太少，无法生成剧本'}), 400
        prompt = f"""你是小说影视化编剧。请从【原小说内容】中找出与【精彩片段线索】对应的真实段落，
把它整理成可以直接拍摄的短剧片段剧本。必须以原小说内容为唯一事实来源。

硬性要求：
1. 不得添加原文没有的人物、事件、关系、地点或结局。
2. 原文对白必须逐字保留，不得改写、润色、翻译或替换；找不到的对白不要自行补写。
3. 原文叙述可以整理成“场景/动作/情绪”，但不能改变事件顺序和事实。
4. 输出应包含：片段标题、出场人物、场景、剧情目的、镜头脚本。
5. 镜头脚本每条包含：镜头号、画面动作、原文旁白或对白、声音/氛围。
6. 对无法确定的内容写“原文未说明”，不要猜测。
7. 只输出剧本正文，不要解释你做了哪些改编。

【精彩片段线索】
标题：{highlight.get('title', '')}
AI识别摘录：{highlight.get('excerpt', '')}
视频钩子：{highlight.get('hook', '')}

【原小说内容】
{source}"""
        content, error = llm_chat([
            {'role': 'system', 'content': '你必须忠实使用原小说内容，尤其严格保留原文对白。'},
            {'role': 'user', 'content': prompt},
        ], max_tokens=4500, temperature=0.2, timeout=120)
        if error:
            return jsonify({'ok': False, 'msg': f'原文剧本生成失败：{error}'}), 502
        return jsonify({'ok': True, 'script': content, 'chapters': used_chapters, 'source_based': True})
    except Exception as exc:
        return jsonify({'ok': False, 'msg': f'按原文生成剧本失败：{exc}'}), 500


@app.route('/api/config', methods=['GET', 'POST'])
def api_config():
    global CONFIG
    if request.method == 'POST':
        try:
            data = request.get_json(force=True) or {}
            if not isinstance(data, dict):
                raise ValueError('设置必须是 JSON 对象')
            cfg = copy.deepcopy(runtime_config())
            cfg.update(data)
            if 'llm_profiles' in data and not data['llm_profiles']:
                cfg.update(custom_base_url='',custom_api_key='',custom_model='',active_llm_profile_id='')
            if 'comfyui_servers' in data and not data['comfyui_servers']:
                cfg['comfyui_url']=''
            if cfg.get('llm_mode') not in ('local', 'custom'):
                raise ValueError('无效的大语言模型来源')
            if cfg.get('media_provider', 'comfyui') not in ('comfyui', 'jimeng'):
                raise ValueError('无效的图片/视频生成服务商')
            if cfg.get('media_provider') == 'jimeng':
                base = str(cfg.get('jimeng_base_url') or '').strip()
                key = str(cfg.get('jimeng_api_key') or '').strip()
                if not base or not key:
                    raise ValueError('启用即梦 API 时必须填写 Base URL 和 API Key')
                parsed = urlparse(base)
                if parsed.scheme not in ('http', 'https') or not parsed.netloc:
                    raise ValueError('即梦 Base URL 必须是有效的 http 或 https 地址')
                if not str(cfg.get('jimeng_image_model') or '').strip() or not str(cfg.get('jimeng_video_model') or '').strip():
                    raise ValueError('请填写即梦图片模型和视频模型')
            profiles = data.get('llm_profiles', cfg.get('llm_profiles', []))
            if not isinstance(profiles, list):
                raise ValueError('LLM API 配置必须是列表')
            ids = set()
            for p in profiles:
                if not isinstance(p, dict):
                    raise ValueError('LLM API 配置格式错误')
                for field in ('name', 'base_url', 'api_key', 'model'):
                    if not isinstance(p.get(field, ''), str):
                        raise ValueError('LLM API 配置字段必须是文本')
                if not p.get('name', '').strip() or not p.get('base_url', '').strip() or not p.get('model', '').strip():
                    raise ValueError('请填写每组 API 的名称、Base URL 和模型名')
                parsed = urlparse(p['base_url'].strip())
                if parsed.scheme not in ('http', 'https') or not parsed.netloc:
                    raise ValueError('LLM Base URL 必须是有效的 http 或 https 地址')
                if p.get('id') in ids:
                    raise ValueError('LLM API 配置 ID 不能重复')
                ids.add(p.get('id'))
            servers = data.get('comfyui_servers', cfg.get('comfyui_servers', []))
            if not isinstance(servers, list):
                raise ValueError('ComfyUI 节点配置必须是列表')
            for s in servers:
                if not isinstance(s, dict) or not s.get('url', '').strip():
                    raise ValueError('请填写每个 ComfyUI 节点地址')
                parsed = urlparse(s['url'].strip())
                if parsed.scheme not in ('http', 'https') or not parsed.netloc:
                    raise ValueError('ComfyUI 地址必须是有效的 http 或 https 地址')
            with CONFIG_IO_LOCK:
                result = normalize_config(cfg)
                if MULTIUSER:
                    MULTIUSER.user_config.save(MULTIUSER.actor_id(), result)
                    result.pop('_owner_id',None)
                else:
                    CONFIG = result
                    save_config(CONFIG)
                result = copy.deepcopy(result)
            return jsonify({"ok": True, "config": result})
        except ValueError as e:
            return jsonify({"ok": False, "error": str(e)}), 400
    with CONFIG_IO_LOCK:
        result = copy.deepcopy(runtime_config())
        result.pop('_owner_id',None)
        return jsonify(result)

def _temporary_jimeng_client(data):
    base_url = str((data or {}).get('base_url') or '').strip().rstrip('/')
    api_key = str((data or {}).get('api_key') or '').strip()
    parsed = urlparse(base_url)
    if parsed.scheme not in ('http', 'https') or not parsed.netloc:
        raise ValueError('即梦 Base URL 必须是有效的 http 或 https 地址')
    if not api_key:
        raise ValueError('请填写完整的即梦 API Key')
    return 即梦客户端(lambda: base_url, lambda: api_key, logger=print)

@app.route('/api/jimeng/test', methods=['POST'])
def api_jimeng_test():
    try:
        client = _temporary_jimeng_client(request.get_json(force=True) or {})
        ok, error = client.检查()
        if not ok:
            return jsonify({"ok": False, "error": error or "即梦服务不可用"}), 502
        return jsonify({"ok": True, "message": "即梦服务在线"})
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 502

@app.route('/api/jimeng/models', methods=['POST'])
def api_jimeng_models():
    try:
        data = request.get_json(force=True) or {}
        client = _temporary_jimeng_client(data)
        return jsonify({"ok": True, "models": client.模型(data.get("type"))})
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 502


def project_generation_reference(project):
    token = (project.get('render_config') or {}).get('asset_reference_id')
    if not token:
        return None
    try:
        cfg = project_render_config(project)
        return GENERATION_REFERENCES.describe(token, cfg.get('_owner_id'))
    except ValueError:
        return {'id': token, 'missing': True}


@app.post('/api/generation-reference', endpoint='api_generation_reference_upload')
def api_generation_reference_upload():
    upload = request.files.get('image')
    if not upload:
        return jsonify(ok=False, msg='请选择一张图片'), 400
    try:
        reference = GENERATION_REFERENCES.save(upload.stream.read(10 * 1024 * 1024 + 1), runtime_config().get('_owner_id'))
        return jsonify(ok=True, reference=reference)
    except ValueError as exc:
        return jsonify(ok=False, msg=str(exc)), 400


@app.post('/api/project/<pid>/generation-reference', endpoint='api_project_generation_reference')
def api_project_generation_reference(pid):
    project = load_project(pid)
    if not project:
        return jsonify(ok=False, msg='项目不存在'), 404
    if pid in PIPELINE_CANCEL_EVENTS:
        return jsonify(ok=False, msg='请等待当前生成任务结束后更换参考图'), 409
    data = request.get_json(silent=True) or {}
    token = data.get('reference_id') or ''
    try:
        reference = GENERATION_REFERENCES.describe(token, project_render_config(project).get('_owner_id')) if token else None
    except ValueError as exc:
        return jsonify(ok=False, msg=str(exc)), 400
    project.setdefault('render_config', {})['asset_reference_id'] = token
    save_project(project)
    return jsonify(ok=True, reference=reference)

@app.route('/api/image-models')
def api_image_models():
    """返回当前图片服务商可用的图片模型列表。"""
    provider = media_provider()
    if provider == 'jimeng':
        try:
            models = 即梦客户端实例.模型('image')
            return jsonify({"ok": True, "provider": provider, "models": models,
                            "current": runtime_config().get('jimeng_image_model', '')})
        except Exception as exc:
            return jsonify({"ok": False, "provider": provider,
                            "error": f"获取即梦图片模型失败：{exc}"}), 502

    url = comfy_url()
    try:
        response = requests.get(f"{url}/object_info", timeout=15)
        response.raise_for_status()
        info = response.json()
        node = info.get('UNETLoader') or info.get('UNETLoaderGGUF') or {}
        required = ((node.get('input') or {}).get('required') or {})
        values = required.get('unet_name') or []
        models = values[0] if isinstance(values, list) and values and isinstance(values[0], list) else []
        default_model = QWEN_IMAGE_MODEL
        models = [name for name in models if name == QWEN_IMAGE_MODEL]
        return jsonify({"ok": True, "provider": provider, "models": models,
                        "current": default_model, "endpoint": url})
    except Exception as exc:
        return jsonify({"ok": False, "provider": provider,
                        "error": f"获取 ComfyUI 图片模型失败：{exc}"}), 502

@app.route('/api/custom-skills', methods=['GET', 'POST'])
def api_custom_skills():
    """列出或上传用户自定义的视频提示词 Skill。"""
    os.makedirs(CUSTOM_SKILLS_DIR, exist_ok=True)
    if request.method == 'GET':
        return jsonify({"ok": True, "skills": 自定义技能列表()})
    upload = request.files.get('file')
    if not upload or not upload.filename:
        return jsonify({"ok": False, "msg": "请选择一个 Skill 文件"}), 400
    original = os.path.basename(upload.filename)
    ext = os.path.splitext(original)[1].lower()
    if ext not in ('.md', '.txt'):
        return jsonify({"ok": False, "msg": "自定义 Skill 仅支持 .md 或 .txt 文件"}), 400
    raw = upload.read()
    if not raw:
        return jsonify({"ok": False, "msg": "Skill 文件不能为空"}), 400
    if len(raw) > 1024 * 1024:
        return jsonify({"ok": False, "msg": "Skill 文件不能超过 1MB"}), 400
    try:
        raw.decode('utf-8-sig')
    except UnicodeDecodeError:
        return jsonify({"ok": False, "msg": "Skill 文件必须使用 UTF-8 编码"}), 400
    original_base = os.path.splitext(original)[0]
    safe_base = re.sub(r'[^\w.-]+', '_', original_base, flags=re.UNICODE).strip('._')[:60] or '自定义技能'
    filename = f"custom_{uuid.uuid4().hex[:12]}_{safe_base}{ext}"
    with open(os.path.join(CUSTOM_SKILLS_DIR, filename), 'wb') as f:
        f.write(raw)
    return jsonify({
        "ok": True,
        "skill": {"id": filename, "name": os.path.splitext(original)[0], "filename": original},
        "skills": 自定义技能列表(),
    })

@app.route('/api/skills', methods=['GET', 'POST'])
def api_skills():
    """统一 Skills 注册中心：查询或创建文本 Skill。"""
    if request.method == 'GET':
        include_content = request.args.get('content') in ('1', 'true', 'yes')
        return jsonify({"ok": True, "skills": skills_catalog(include_content)})
    data = request.get_json(silent=True) or {}
    name = str(data.get('name') or '').strip()
    content = str(data.get('content') or '')
    stages = [str(x) for x in (data.get('stages') or []) if str(x) in ('script', 'video_prompt', 'asset', 'review', 'compose')]
    if not name or not content.strip():
        return jsonify({"ok": False, "msg": "Skill 名称和内容不能为空"}), 400
    if len(content.encode('utf-8')) > 1024 * 1024:
        return jsonify({"ok": False, "msg": "Skill 内容不能超过 1MB"}), 400
    safe_name = re.sub(r'[^\\w.-]+', '_', name, flags=re.UNICODE).strip('._')[:60] or 'skill'
    filename = f"custom_{uuid.uuid4().hex[:12]}_{safe_name}.md"
    with open(os.path.join(CUSTOM_SKILLS_DIR, filename), 'w', encoding='utf-8') as f:
        f.write(content)
    index = _读取技能索引()
    index[filename] = {"name": name, "description": str(data.get('description') or '').strip()[:300], "stages": stages or ["video_prompt"], "updated_at": time.time()}
    _保存技能索引(index)
    return jsonify({"ok": True, "skill": next(x for x in skills_catalog() if x["id"] == f"custom:{filename}")})

@app.route('/api/skills/import', methods=['POST'])
def api_skills_import():
    """导入 .md/.txt Skill 文件，并写入统一注册中心。"""
    upload = request.files.get('file')
    if not upload or not upload.filename:
        return jsonify({"ok": False, "msg": "请选择一个 Skill 文件"}), 400
    ext = os.path.splitext(upload.filename)[1].lower()
    if ext not in ('.md', '.txt'):
        return jsonify({"ok": False, "msg": "仅支持 .md 或 .txt 文件"}), 400
    try:
        content = upload.read().decode('utf-8-sig')
    except UnicodeDecodeError:
        return jsonify({"ok": False, "msg": "Skill 文件必须使用 UTF-8 编码"}), 400
    if not content.strip():
        return jsonify({"ok": False, "msg": "Skill 文件不能为空"}), 400
    name = str(request.form.get('name') or os.path.splitext(os.path.basename(upload.filename))[0]).strip()
    description = str(request.form.get('description') or '').strip()
    stages_raw = str(request.form.get('stages') or 'video_prompt')
    stages = [x for x in stages_raw.split(',') if x in ('script', 'video_prompt', 'asset', 'review', 'compose')]
    safe_name = re.sub(r'[^\\w.-]+', '_', name, flags=re.UNICODE).strip('._')[:60] or 'skill'
    filename = f"custom_{uuid.uuid4().hex[:12]}_{safe_name}{ext}"
    with open(os.path.join(CUSTOM_SKILLS_DIR, filename), 'w', encoding='utf-8') as f:
        f.write(content)
    index = _读取技能索引()
    index[filename] = {"name": name, "description": description[:300], "stages": stages or ["video_prompt"], "updated_at": time.time()}
    _保存技能索引(index)
    return jsonify({"ok": True, "skill": next(x for x in skills_catalog() if x["id"] == f"custom:{filename}")})

@app.route('/api/skills/<path:skill_id>', methods=['GET', 'PUT', 'DELETE'])
def api_skill_detail(skill_id):
    """查询、编辑或删除单个 Skill；内置 Skill 只读。"""
    sid = str(skill_id or '')
    item = next((x for x in skills_catalog() if x["id"] == sid), None)
    if not item:
        return jsonify({"ok": False, "msg": "Skill 不存在"}), 404
    if request.method == 'GET':
        item["content"] = _技能内容(sid)
        return jsonify({"ok": True, "skill": item})
    if item.get("builtin"):
        return jsonify({"ok": False, "msg": "内置 Skill 只读，请复制后新建自定义 Skill"}), 403
    filename = os.path.basename(sid[7:] if sid.startswith('custom:') else sid)
    path = os.path.join(CUSTOM_SKILLS_DIR, filename)
    if request.method == 'DELETE':
        if os.path.isfile(path):
            os.remove(path)
        index = _读取技能索引()
        index.pop(filename, None)
        _保存技能索引(index)
        for key in ('video_skill_id', 'script_skill_id'):
            if CONFIG.get(key) == sid:
                CONFIG[key] = 'auto'
        if CONFIG.get('prompt_skill_mode') == sid:
            CONFIG['prompt_skill_mode'] = 'auto'
        save_config(CONFIG)
        return jsonify({"ok": True, "skills": skills_catalog()})
    data = request.get_json(silent=True) or {}
    name = str(data.get('name') or item["name"]).strip()
    content = str(data.get('content') or '')
    if not name or not content.strip():
        return jsonify({"ok": False, "msg": "Skill 名称和内容不能为空"}), 400
    stages = [str(x) for x in (data.get('stages') or item.get('stages') or []) if str(x) in ('script', 'video_prompt', 'asset', 'review', 'compose')]
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    index = _读取技能索引()
    index[filename] = {"name": name, "description": str(data.get('description') or item.get('description') or '').strip()[:300], "stages": stages or ["video_prompt"], "updated_at": time.time()}
    _保存技能索引(index)
    return jsonify({"ok": True, "skill": next(x for x in skills_catalog() if x["id"] == sid)})

@app.route('/api/custom-skills/<skill_id>', methods=['DELETE'])
def api_delete_custom_skill(skill_id):
    filename = os.path.basename(str(skill_id or ''))
    if filename != skill_id or not filename.lower().endswith(('.md', '.txt')):
        return jsonify({"ok": False, "msg": "无效的 Skill"}), 400
    path = os.path.join(CUSTOM_SKILLS_DIR, filename)
    if not os.path.isfile(path):
        return jsonify({"ok": False, "msg": "Skill 不存在"}), 404
    os.remove(path)
    if CONFIG.get('prompt_skill_mode') == f'custom:{filename}':
        CONFIG['prompt_skill_mode'] = 'auto'
        save_config(CONFIG)
    return jsonify({"ok": True, "skills": 自定义技能列表()})

@app.route('/api/llm/test', methods=['POST'])
def api_llm_test():
    data = request.get_json(force=True, silent=True) or {}
    base = str(data.get('base_url', '')).strip().rstrip('/')
    key = str(data.get('api_key', '') or 'EMPTY')
    if not base:
        return jsonify({"ok": False, "error": "请填写 Base URL"}), 400
    try:
        parsed = urlparse(base)
        if parsed.scheme not in ('http', 'https') or not parsed.netloc:
            raise ValueError('Base URL 必须是有效的 http 或 https 地址')
        r = requests.get(f"{base}/models", headers={"Authorization": f"Bearer {key}"}, timeout=2)
        payload = r.json() if 'json' in r.headers.get('content-type', '') else {}
        models = [m.get('id') for m in payload.get('data', []) if isinstance(m, dict) and m.get('id')]
        return jsonify({"ok": r.ok, "status": r.status_code, "models": models,
                        "message": "连接成功" if r.ok else f"服务返回 HTTP {r.status_code}"})
    except Exception as e:
        return jsonify({"ok": False, "error": f"连接失败：{e}"}), 502

@app.route('/api/llm/models', methods=['GET','POST'])
def api_llm_models():
    if request.method == 'GET':
        base, key, current = get_llm_endpoint()
        models = [current] if current else []
        try:
            r = requests.get(f"{base}/models", headers={"Authorization": f"Bearer {key}"}, timeout=8)
            payload = r.json() if r.ok else {}
            models.extend(m.get('id') for m in payload.get('data', []) if isinstance(m, dict) and m.get('id'))
        except Exception:
            pass
        # 本地 Qwen 服务有时不暴露完整 /models 列表，保留已安装的 Qwen3.8 作为可选项。
        if runtime_config().get('llm_mode') == 'local':
            models.extend(['qwen3.8', 'qwen3.8-27b'])
        return jsonify(ok=True, current=current or '', models=list(dict.fromkeys(models)))
    result = api_llm_test()
    return result

@app.get('/api/llm/available-models')
def api_llm_available_models():
    base, key, current = get_llm_endpoint()
    models = [current] if current else []
    try:
        r = requests.get(f"{base}/models", headers={"Authorization": f"Bearer {key}"}, timeout=8)
        payload = r.json() if r.ok else {}
        models.extend(m.get('id') for m in payload.get('data', []) if isinstance(m, dict) and m.get('id'))
    except Exception:
        pass
    return jsonify(ok=True, current=current or '', models=list(dict.fromkeys(models)))

@app.get('/api/comfy/nodes-status')
def api_comfy_nodes_status():
    cfg=runtime_config()
    nodes=(MULTIUSER.user_config.get(MULTIUSER.actor_id()) if MULTIUSER else cfg).get('comfyui_servers',[])
    return jsonify(ok=True,nodes=node_statuses(nodes),interval=5)

@app.route('/api/comfy/test', methods=['POST'])
def api_comfy_test():
    data = request.get_json(force=True, silent=True) or {}
    base = str(data.get('url', '')).strip().rstrip('/')
    if not base:
        return jsonify({"ok": False, "error": "请填写 ComfyUI 地址"}), 400
    try:
        parsed = urlparse(base)
        if parsed.scheme not in ('http', 'https') or not parsed.netloc:
            raise ValueError('ComfyUI 地址必须是有效的 http 或 https 地址')
        r = requests.get(f"{base}/system_stats", timeout=10)
        return jsonify({"ok": r.ok, "status": r.status_code,
                        "message": "在线" if r.ok else f"服务返回 HTTP {r.status_code}"})
    except Exception as e:
        return jsonify({"ok": False, "error": f"连接失败：{e}"}), 502

@app.route('/api/comfy/start', methods=['POST'])
def api_comfy_start():
    global COMFY_SERVICE_BLOCKED
    with COMFY_SERVICE_LOCK:
        COMFY_SERVICE_BLOCKED = False
    online = ensure_comfyui(max_wait=300)
    return jsonify({
        "ok": online,
        "online": online,
        "blocked": False,
        "msg": "ComfyUI 已激活" if online else "ComfyUI 激活失败，请检查内置服务或节点地址",
    }), (200 if online else 503)

@app.route('/api/comfy/stop', methods=['POST'])
def api_comfy_stop():
    global COMFY_SERVICE_BLOCKED
    queue_snapshot = render_queue_snapshot()
    if queue_snapshot.get("running"):
        return jsonify({"ok": False, "msg": "视频队列正在运行，请先暂停队列后再关闭 ComfyUI"}), 409
    with PIPELINE_CANCEL_LOCK:
        if PIPELINE_CANCEL_EVENTS:
            return jsonify({"ok": False, "msg": "当前有制作任务正在运行，请先停止制作后再关闭 ComfyUI"}), 409
    with COMFY_SERVICE_LOCK:
        COMFY_SERVICE_BLOCKED = True
    stop_comfyui()
    online = comfy_check()
    return jsonify({
        "ok": not online,
        "online": online,
        "blocked": True,
        "msg": "ComfyUI 已关闭" if not online else "关闭请求已发送，但服务仍在线",
    }), (200 if not online else 503)

@app.route('/api/comfy/server/toggle', methods=['POST'])
def api_comfy_server_toggle():
    """只切换单台 ComfyUI 节点是否参与任务分发，不操作服务器进程。"""
    global CONFIG
    data = request.get_json(silent=True) or {}
    server_id = str(data.get("id") or "").strip()
    if not server_id:
        return jsonify({"ok": False, "error": "缺少节点 ID"}), 400
    cfg = copy.deepcopy(runtime_config())
    servers = copy.deepcopy(cfg.get("comfyui_servers") or [])
    target = next((s for s in servers if str(s.get("id")) == server_id), None)
    if not target:
        return jsonify({"ok": False, "error": "ComfyUI 节点不存在"}), 404
    target["enabled"] = bool(data.get("enabled", True))
    cfg["comfyui_servers"] = servers
    first = next((s for s in servers if s.get("enabled") and s.get("url")), None)
    if first:
        cfg["comfyui_url"] = first["url"]
    else:
        cfg["comfyui_url"] = ""
    if MULTIUSER:
        MULTIUSER.user_config.save(MULTIUSER.actor_id(),cfg)
    else:
        CONFIG = cfg
        save_config(CONFIG)
    return jsonify({
        "ok": True,
        "id": server_id,
        "enabled": target["enabled"],
        "servers": cfg["comfyui_servers"],
    })

@app.route('/api/comfy/monitor')
def api_comfy_monitor():
    """当前ComfyUI运行工作流的轻量监控数据：节点图、当前节点、进度、时间。"""
    return jsonify(comfy_monitor_snapshot())

@app.route('/api/status')
def api_status():
    base, key, model = get_llm_endpoint()
    try:
        r = requests.get(f"{base}/models", headers={"Authorization": f"Bearer {key}"}, timeout=10)
        llm_ok = r.status_code == 200
    except Exception:
        llm_ok = False
    with COMFY_SERVICE_LOCK:
        comfy_blocked = bool(COMFY_SERVICE_BLOCKED)
    return jsonify({
        "llm_online": llm_ok, "llm_endpoint": base, "llm_model": model,
        "comfyui_online": comfy_check(), "comfyui_url": comfy_url(), "comfyui_blocked": comfy_blocked,
        "media_provider": media_provider(),
        "media_endpoint": jimeng_base_url() if media_provider() == "jimeng" else comfy_url(),
        "ffmpeg": bool(find_ffmpeg())
    })


def startup_diagnostics():
    """只检查本地运行条件，不主动连接 LLM 或 ComfyUI。"""
    directories = {
        "projects": PROJECTS_DIR,
        "series": SERIES_DIR,
        "assets": ASSETS_DIR,
        "outputs": OUTPUTS_DIR,
        "reviews": REVIEWS_DIR,
    }
    directory_checks = {}
    for name, path in directories.items():
        try:
            os.makedirs(path, exist_ok=True)
            directory_checks[name] = {
                "exists": True,
                "writable": os.access(path, os.W_OK),
            }
        except OSError as exc:
            directory_checks[name] = {
                "exists": False,
                "writable": False,
                "error": str(exc),
            }
    config_ok = isinstance(CONFIG, dict) and bool(CONFIG.get("comfyui_servers"))
    queue_ok = os.path.isfile(RENDER_QUEUE_PATH) or os.access(BASE_DIR, os.W_OK)
    checks = {
        "directories": directory_checks,
        "config": config_ok,
        "render_queue": queue_ok,
        "ffmpeg": bool(find_ffmpeg()),
        "pipeline": {
            "wardrobe_policy": "scene-aware-v1",
            "mode": "agent",
            "legacy_fallback": False,
        },
    }
    ready = (
        config_ok
        and queue_ok
        and all(item["exists"] and item["writable"] for item in directory_checks.values())
    )
    return {"ready": ready, "checks": checks}


@app.route('/api/health')
def api_health():
    diagnostics = startup_diagnostics()
    return jsonify(diagnostics), (200 if diagnostics["ready"] else 503)

@app.route('/api/story/chat', methods=['POST'])
def api_story_chat():
    """修改生成前的故事草稿，不创建项目或启动制作流程。"""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(ok=False, msg='请求格式无效'), 400
    idea, message = data.get('idea'), data.get('message')
    model = data.get('model') or None
    if model is not None and not isinstance(model, str):
        return jsonify(ok=False, msg='对话模型格式无效'), 400
    model = model.strip() or None if model is not None else None
    if not isinstance(idea, str) or not idea.strip():
        return jsonify(ok=False, msg='请先输入故事正文'), 400
    if not isinstance(message, str) or not message.strip():
        return jsonify(ok=False, msg='请输入修改要求'), 400
    if len(idea) > 60000 or len(message) > 4000:
        return jsonify(ok=False, msg='故事正文最多60000字，修改要求最多4000字'), 400
    history = data.get('history', [])
    history = history if isinstance(history, list) else []
    history = [{'role': item['role'], 'content': item['content'][:2000]}
               for item in history[-8:] if isinstance(item, dict)
               and item.get('role') in ('user', 'assistant')
               and isinstance(item.get('content'), str)]
    content, error = llm_chat([
        {'role': 'system', 'content': '''你是故事编辑，通过多轮对话修改用户当前的故事正文。
以当前正文为准，只修改用户要求的部分，保留未要求改动的人物、剧情和细节。
保持原文语言和文本形式，输出完整修改后的正文，不要省略或使用“其余不变”。
如果用户仅咨询，回答问题并原样返回正文。不要生成结构化分镜或导演参数。
严格输出JSON：{"reply":"简短说明改动或回答问题","story":"完整故事正文"}。'''},
        {'role': 'user', 'content': json.dumps({'当前正文': idea, '此前对话': history,
                                               '本次要求': message}, ensure_ascii=False)},
    ], max_tokens=16000, temperature=0.55, retries=1, timeout=180, model=model)
    if not content:
        return jsonify(ok=False, msg=f"AI修改失败：{error or '模型没有返回内容'}"), 502
    result = parse_json_from_text(content)
    if not isinstance(result, dict) or not isinstance(result.get('story'), str) or not result['story'].strip():
        return jsonify(ok=False, msg='AI返回的故事格式无效，请重试'), 502
    if len(result['story']) > 60000:
        return jsonify(ok=False, msg='修改后的故事超过60000字，请分段修改'), 502
    reply = result.get('reply')
    return jsonify(ok=True, story=result['story'].strip(),
                   reply=reply if isinstance(reply, str) and reply.strip() else '已按要求修改故事。')


@app.route('/api/director/match', methods=['POST'])
def api_director_match():
    """根据故事梗概匹配导演台参数，不生成剧本。"""
    data = request.get_json(silent=True) or {}
    idea = str(data.get('idea') or '').strip()
    if len(idea) < 6:
        return jsonify({"ok": False, "msg": "故事梗概太短，请至少写清人物和主要事件"}), 400
    ok, err = ensure_local_llm()
    if not ok:
        return jsonify({"ok": False, "msg": f"LLM服务不可用: {err}"}), 503
    option_text = json.dumps(DIRECTOR_MATCH_OPTIONS, ensure_ascii=False)
    prompt = f"""你是短剧项目的AI导演。请分析故事梗概，只负责匹配制作参数，不要续写剧本。

必须从以下候选值中原样选择，不得创造新选项：
{option_text}

另外输出：
- payoff：一句具体的核心爽点或必须拍到的桥段，不超过80字
- series_mode：故事是否明显适合连续剧，布尔值
- reason：不超过100字的匹配理由

严格只输出一个JSON对象，字段必须完整：
{{"platform":"","length":"","genre":"","pace":"","hook":"","reversal":"","ending":"","dialogue":"","payoff":"","series_mode":false,"shot_count":"","shot_duration":"","aspect_ratio":"","style":"","reason":""}}

故事梗概：
{idea}"""
    content, llm_err = llm_chat([
        {"role": "system", "content": "你只输出严格JSON，不要使用Markdown代码块。"},
        {"role": "user", "content": prompt},
    ], max_tokens=1200, temperature=0.25)
    if not content:
        return jsonify({"ok": False, "msg": f"导演参数匹配失败: {llm_err}"}), 502
    parsed = parse_json_from_text(content)
    if not isinstance(parsed, dict):
        return jsonify({"ok": False, "msg": "AI返回的导演参数格式异常，请重试"}), 502
    return jsonify({"ok": True, "director": normalize_director_match(parsed)})

@app.route('/api/pipeline/run', methods=['GET', 'POST'])
def api_pipeline_run():
    body = request.get_json(silent=True) or {} if request.is_json else {}
    idea = str((request.form.get('idea') if request.method == 'POST' and not request.is_json else body.get('idea')) or request.args.get('idea') or '').strip()
    full_script_import = request.method == 'POST' and (request.form.get('full_script_import') if not request.is_json else body.get('full_script_import')) == '1'
    pid = request.args.get('pid') or uuid.uuid4().hex[:12]
    # 每次请求只修改自身配置快照，不改动平台默认值。
    with CONFIG_IO_LOCK:
        request_cfg = copy.deepcopy(runtime_config())
        if request.args.get('style'):
            request_cfg['style'] = request.args['style']
        if request.args.get('aspect_ratio') in ASPECT_IMG_SIZE:
            request_cfg['aspect_ratio'] = request.args['aspect_ratio']
        mp_arg = request.args.get('megapixels')
        if mp_arg:
            try:
                request_cfg['megapixels'] = max(0.1, min(float(mp_arg), 4.0))
            except ValueError:
                pass
        steps_arg = request.args.get('h3_steps')
        if steps_arg:
            try:
                request_cfg['h3_steps'] = max(4, min(int(steps_arg), 25))
            except ValueError:
                pass
        dur_arg = request.args.get('shot_duration')
        if dur_arg:
            if dur_arg.lower() == 'auto':
                request_cfg['shot_duration'] = 'auto'
            else:
                try:
                    request_cfg['shot_duration'] = max(8, min(int(dur_arg), 15))
                except ValueError:
                    pass
        cnt_arg = request.args.get('shot_count')
        if cnt_arg:
            if cnt_arg.lower() == 'auto':
                request_cfg['shot_count'] = 'auto'
            else:
                try:
                    request_cfg['shot_count'] = max(1, int(cnt_arg))
                except ValueError:
                    pass
        skill_arg = str(request.args.get('skill_mode') or '').strip().lower()
        if skill_arg in ('auto', 'dialogue', 'action', 'anime_action', 'none') or (
            skill_arg.startswith('custom:') and _阶段技能(skill_arg, 'video_prompt')
        ) or any(item["id"] == skill_arg and "video_prompt" in (item.get("stages") or []) for item in skills_catalog()):
            request_cfg['prompt_skill_mode'] = skill_arg
            request_cfg['video_skill_id'] = skill_arg
        script_skill_arg = str(request.args.get('script_skill') or '').strip()
        if script_skill_arg in ('auto', 'none') or _阶段技能(script_skill_arg, 'script') or any(
            item["id"] == script_skill_arg and "script" in (item.get("stages") or []) for item in skills_catalog()
        ):
            request_cfg['script_skill_id'] = script_skill_arg
        subtitle_arg = request.args.get('subtitle')
        if subtitle_arg is not None:
            request_cfg['subtitle_enabled'] = subtitle_arg in ('1', 'true', 'True', 'yes')
        man_arg = request.args.get('manual')
        if man_arg is not None:
            request_cfg['manual_mode'] = (man_arg in ('1', 'true', 'True'))
        pb_arg = request.args.get('prompt_batch')
        if pb_arg is not None:
            request_cfg['batch_prompt_mode'] = (pb_arg in ('1', 'true', 'True'))
        sr_arg = request.args.get('script_review')
        if sr_arg is not None:
            request_cfg['script_review_mode'] = (sr_arg in ('1', 'true', 'True'))
        if MULTIUSER:
            MULTIUSER.owner_for("project", pid)
            request_cfg["_owner_id"] = MULTIUSER.store.owner("project", pid)
    custom_assets = (request.args.get('custom_assets') == '1')
    # 每次启动创建线程级配置快照，后续即使其他请求修改全局CONFIG，本项目也不会被串参数
    existing_proj = load_project(pid)
    if existing_proj and isinstance(existing_proj.get('render_config'), dict):
        # 断点续跑优先沿用项目自身配置，再合并本次页面明确传入后的CONFIG
        merged_cfg = project_render_config(existing_proj)
        for k in ('style','aspect_ratio','megapixels','h3_steps','shot_duration','shot_count','prompt_skill_mode','video_skill_id','script_skill_id','subtitle_enabled','manual_mode','batch_prompt_mode','script_review_mode','agent_pipeline_enabled',
                  'media_provider','jimeng_base_url','jimeng_api_key','jimeng_image_model','jimeng_video_model','jimeng_image_resolution','jimeng_ratio'):
            merged_cfg[k] = request_cfg.get(k, merged_cfg.get(k))
        request_cfg = merged_cfg
    if MULTIUSER:
        owner = MULTIUSER.store.owner('project', pid)
        from team.user_config import CONNECTION_KEYS
        owner_cfg = MULTIUSER.user_config.get(owner)
        request_cfg.update({k:copy.deepcopy(owner_cfg.get(k)) for k in CONNECTION_KEYS if k in owner_cfg})
        request_cfg['_owner_id'] = owner
        request_cfg['_project_id'] = pid
    # Removal is explicit through the project reference endpoint. A stale page
    # must never clear the saved reference by sending an empty query parameter.
    if request.args.get('asset_reference_id'):
        reference_id = request.args.get('asset_reference_id', '')
        if reference_id:
            try:
                GENERATION_REFERENCES.resolve(reference_id, request_cfg.get('_owner_id'))
            except ValueError as exc:
                return jsonify(ok=False, msg=str(exc)), 400
        request_cfg['asset_reference_id'] = reference_id
    if not idea and not load_project(pid):
        return jsonify({"ok": False, "msg": "请输入创作内容"}), 400
    if full_script_import:
        request_cfg['full_script_import'] = True
    try:
        pipeline_event = register_pipeline(pid)
    except ValueError as exc:
        return Response(sse('error', {'msg': str(exc)}), mimetype='text/event-stream')
    run_id = uuid.uuid4().hex[:16]
    def stream():
        queue = []
        last_heartbeat = time.monotonic()
        def push(event, data):
            queue.append(sse(event, data))
        yield sse('start', {"pid": pid, "run_id": run_id})
        # 在线程中跑管线，主线程吐队列
        def worker():
            try:
                set_runtime_config(request_cfg)
                run_agent_pipeline(pid, idea, push, custom_assets=custom_assets, run_id=run_id)
            except PipelineCancelled:
                push('cancelled', {"pid": pid, "msg": "制作已终止，已生成的资产和分镜已保留，可稍后继续生成"})
            except Exception as e:
                import traceback
                traceback.print_exc()
                failed = load_project(pid)
                if failed:
                    failed["run_id"] = run_id
                    failed.setdefault("运行记录", []).append({
                        "run_id": run_id,
                        "status": "failed",
                        "error": str(e),
                        "started_at": time.time(),
                        "finished_at": time.time(),
                    })
                    failed["运行记录"] = failed["运行记录"][-50:]
                    更新任务状态(failed, 状态="失败")
                    save_project(failed)
                push('error', {"msg": f"管线异常: {e}"})
            finally:
                clear_runtime_config()
                clear_pipeline(pid, pipeline_event)
            push('end', {})
        t = threading.Thread(target=worker, daemon=True)
        t.start()
        while True:
            if queue:
                yield queue.pop(0)
            elif not t.is_alive():
                break
            else:
                now = time.monotonic()
                if now - last_heartbeat >= 10:
                    yield ': heartbeat\n\n'
                    last_heartbeat = now
                time.sleep(0.3)
        while queue:
            yield queue.pop(0)
    return Response(stream(), mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache, no-transform', 'X-Accel-Buffering': 'no'})

@app.route('/api/script/import-text', methods=['POST'])
def api_script_import_text():
    uploaded = request.files.get('file')
    if not uploaded or not uploaded.filename:
        return jsonify(ok=False, msg='请选择剧本文件'), 400
    filename = uploaded.filename.lower()
    try:
        if filename.endswith('.docx'):
            with zipfile.ZipFile(uploaded.stream) as archive:
                root = ElementTree.fromstring(archive.read('word/document.xml'))
            ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
            blocks = []
            body = root.find('w:body', ns)
            for paragraph in body.findall('.//w:p', ns) if body is not None else []:
                blocks.append(''.join(node.text or '' for node in paragraph.findall('.//w:t', ns)))
            text = '\n'.join(blocks)
        elif filename.endswith(('.txt', '.md')):
            text = uploaded.read().decode('utf-8-sig')
        else:
            return jsonify(ok=False, msg='仅支持 TXT、Markdown 或 DOCX 文件'), 400
    except UnicodeDecodeError:
        return jsonify(ok=False, msg='文本文件请使用 UTF-8 编码'), 400
    except Exception as exc:
        return jsonify(ok=False, msg=f'无法读取剧本文件：{exc}'), 400
    text = text.replace('\r\n', '\n').replace('\r', '\n').strip()
    if len(text) < 20:
        return jsonify(ok=False, msg='剧本内容过短，请检查文件'), 400
    return jsonify(ok=True, text=text)

@app.route('/api/pipeline/<pid>/cancel', methods=['POST'])
def api_pipeline_cancel(pid):
    if cancel_pipeline(pid):
        return jsonify({"ok": True, "msg": "已发送终止请求，当前调用完成后会停止"})
    return jsonify({"ok": False, "msg": "当前没有正在运行的制作任务"}), 404

@app.route('/api/render-queue', methods=['GET'])
def api_render_queue():
    return jsonify({"ok": True, **render_queue_snapshot()})

@app.route('/api/render-queue/add', methods=['POST'])
@serialized_queue
def api_render_queue_add():
    data = request.get_json(silent=True) or {}
    pids = data.get("pids") or ([data.get("pid")] if data.get("pid") else [])
    if not isinstance(pids, list):
        pids = [pids]
    queue = load_render_queue()
    existing = {str(x.get("pid")): x for x in queue.get("items", []) if x.get("status") not in ("done", "removed")}
    added, skipped, errors = [], [], []
    for raw_pid in pids:
        pid = str(raw_pid or "").strip()
        project = load_project(pid)
        if not project:
            errors.append({"pid": pid, "msg": "项目不存在"})
            continue
        if not project.get("script"):
            errors.append({"pid": pid, "msg": "请先生成剧本和分镜"})
            continue
        if not project.get("assets"):
            errors.append({"pid": pid, "msg": "请先生成参考资产"})
            continue
        if project.get("final"):
            # 历史上可能留下“失败”的旧队列记录，但项目后来已经合成成功。
            # 点击重新排队时直接把队列记录纠正为已完成，避免前端一直显示失败。
            old_item = existing.get(pid)
            if old_item and old_item.get("status") == "error":
                old_item.update({
                    "status": "done",
                    "progress": 100,
                    "message": "视频已生成",
                    "error": "",
                    "finished": time.time(),
                    "updated": time.time(),
                })
                skipped.append({"pid": pid, "msg": "项目已有成片，已自动修正为已完成"})
                continue
            skipped.append({"pid": pid, "msg": "已经有成片"})
            continue
        if pid in existing:
            if existing[pid].get("status") == "error":
                existing[pid].update({"status": "queued", "error": "", "message": "等待重试", "progress": 0, "updated": time.time()})
                added.append(existing[pid]["id"])
                continue
            skipped.append({"pid": pid, "msg": "已经在队列中"})
            continue
        item = {
            "id": f"rq_{uuid.uuid4().hex[:12]}",
            "pid": pid,
            "title": project.get("title") or pid,
            "series": project.get("series"),
            "status": "queued",
            "progress": 0,
            "message": "等待生成",
            "error": "",
            "created": time.time(),
            "updated": time.time(),
        }
        queue.setdefault("items", []).append(item)
        existing[pid] = item
        added.append(item["id"])
    save_render_queue(queue)
    if added and data.get("start", True):
        ensure_render_queue_worker()
    return jsonify({"ok": True, "added": added, "skipped": skipped, "errors": errors, **render_queue_snapshot()})

@app.route('/api/render-queue/<item_id>', methods=['DELETE'])
@serialized_queue
def api_render_queue_remove(item_id):
    if item_id.startswith("single_"):
        task = SINGLE_TASKS.get(item_id[len("single_"):])
        if task is not None:
            task["status"] = "removed"
        return jsonify({"ok": True, **render_queue_snapshot()})
    if item_id.startswith("rerender_"):
        task = RERENDER_TASKS.get(item_id[len("rerender_"):])
        if task is not None:
            task["status"] = "removed"
        return jsonify({"ok": True, **render_queue_snapshot()})
    if item_id.startswith("batch_"):
        task = BATCH_RENDER_TASKS.get(item_id[len("batch_"):])
        if task is not None:
            task["status"] = "removed"
        return jsonify({"ok": True, **render_queue_snapshot()})
    data = load_render_queue()
    item = next((x for x in data.get("items", []) if x.get("id") == item_id), None)
    if not item:
        return jsonify({"ok": False, "msg": "队列项不存在"}), 404
    if item.get("status") == "running":
        return jsonify({"ok": False, "msg": "正在生成的任务不能移除，请先暂停"}), 409
    item["status"] = "removed"
    item["updated"] = time.time()
    save_render_queue(data)
    return jsonify({"ok": True, **render_queue_snapshot()})

@app.route('/api/render-queue/start', methods=['POST'])
@serialized_queue
def api_render_queue_start():
    data = load_render_queue()
    for item in data.get("items", []):
        if item.get("status") == "paused" and (not MULTIUSER or MULTIUSER.visible("project", item.get("pid"))):
            item["status"] = "queued"
            item["error"] = ""
    save_render_queue(data)
    ensure_render_queue_worker()
    return jsonify({"ok": True, **render_queue_snapshot()})

@app.route('/api/render-queue/pause', methods=['POST'])
@serialized_queue
def api_render_queue_pause():
    if MULTIUSER and not MULTIUSER.is_admin():
        with RENDER_QUEUE_LOCK:
            data = load_render_queue()
            for item in data.get('items', []):
                if not MULTIUSER.visible('project', item.get('pid')):
                    continue
                if item.get('status') == 'running':
                    item['pause_requested'] = True
                    cancel_pipeline(item.get('pid'))
                elif item.get('status') in ('queued', 'retry'):
                    item['status'] = 'paused'
            save_render_queue(data)
        return jsonify({'ok': True, **render_queue_snapshot()})
    RENDER_QUEUE_STATE["pause_requested"] = True
    data = load_render_queue()
    running = [x for x in data.get("items", []) if x.get("status") == "running"]
    for item in running:
        item['pause_requested'] = True
        cancel_pipeline(item.get("pid"))
    for item in data.get("items", []):
        if item.get("status") in ("queued", "retry"):
            item["status"] = "paused"
            item["message"] = "已暂停，等待继续"
            item["updated"] = time.time()
    save_render_queue(data)
    return jsonify({"ok": True, **render_queue_snapshot()})

work_archive = WorkArchive(os.path.join(BASE_DIR, 'work_archive.sqlite3'))

@app.post('/api/project/<pid>/archive')
def api_archive_project(pid):
    project = load_project(pid)
    if not project:
        return jsonify(ok=False, msg='作品不存在'), 404
    archived = (request.get_json(silent=True) or {}).get('archived')
    if not isinstance(archived, bool):
        return jsonify(ok=False, msg='归档状态无效'), 400
    work_archive.set('project', pid, archived)
    return jsonify(ok=True)

@app.post('/api/series/<series_id>/archive')
def api_archive_series(series_id):
    series = load_series(series_id)
    if not series:
        return jsonify(ok=False, msg='作品不存在'), 404
    archived = (request.get_json(silent=True) or {}).get('archived')
    if not isinstance(archived, bool):
        return jsonify(ok=False, msg='归档状态无效'), 400
    children = []
    if archived:
        for pid in 项目存储.keys():
            if MULTIUSER and not MULTIUSER.series_child(series_id, pid):
                continue
            project = load_project(pid)
            if project and str((project.get('series') or {}).get('id')) == series_id:
                children.append(pid)
    work_archive.set('series', series_id, archived, children)
    return jsonify(ok=True)

@app.route('/api/projects')
def api_projects():
    archived_ids = work_archive.ids('project')
    archived_only = request.args.get('archived') == '1'
    items = []
    for p in 项目服务实例.列表(可见=lambda pid: ((pid in archived_ids) == archived_only) and (not MULTIUSER or MULTIUSER.visible("project", pid))):
        if MULTIUSER and not MULTIUSER.visible("project", p["id"]):
            continue
        shots = (p.get("shots") or []) if isinstance(p, dict) else []
        failed_shots = sum(1 for shot in shots if isinstance(shot, dict) and (shot.get("error") or shot.get("continuity_stale") or not shot.get("video_url")))
        rendered_shots = sum(1 for shot in shots if isinstance(shot, dict) and shot.get("video_url") and not shot.get("error"))
        items.append({
            "id": p["id"],
            "title": p.get("title") or (p.get("script") or {}).get("title") or p.get("idea", "")[:20],
            "idea": p.get("idea", ""),
            "final": available_final(p),
            "final_needs_resynth": bool(p.get('previous_final') and not p.get('final')),
            "created": p.get("created", 0),
            "updated": p.get("updated", p.get("created", 0)),
            "failed_shots": failed_shots,
            "rendered_shots": rendered_shots,
            "shot_count": len(shots),
            "series": p.get("series"),
        })
    return jsonify(items)

@app.route('/api/project/<pid>/remake', methods=['POST'])
def api_project_remake(pid):
    """复制短片为新版本，原项目保留不变。"""
    source = load_project(pid)
    if not source:
        return jsonify({"ok": False, "msg": "项目不存在"}), 404
    data = request.get_json(silent=True) or {}
    mode = _remake_mode(data.get("mode"))
    clone = _clone_project_for_remake(source, mode=mode)
    series_ctx = source.get("series") or {}
    series_id = series_ctx.get("id")
    episode = series_ctx.get("episode")
    if series_id and episode is not None:
        series = load_series(series_id)
        if series:
            meta = (series.setdefault("episodes", {})).setdefault(str(episode), {})
            versions = meta.setdefault("versions", [])
            versions.append({
                "project_id": pid,
                "title": source.get("title") or f"第{episode}集",
                "final": source.get("final"),
                "created": source.get("created", time.time()),
                "remake_mode": mode,
            })
            meta["project_id"] = clone["id"]
            meta["title"] = clone.get("title") or meta.get("title", "")
            meta["updated"] = time.time()
            series["updated"] = time.time()
            save_series(series)
    return jsonify({
        "ok": True,
        "mode": mode,
        "mode_label": REMAKE_MODES[mode],
        "project": {
            "id": clone["id"],
            "title": clone.get("title"),
            "remake_of": pid,
            "series": clone.get("series"),
        },
    })

@app.route('/api/project/<pid>')
def api_project(pid):
    if request.args.get('active_only') == '1' and pid in work_archive.ids('project'):
        return jsonify(ok=False, msg='作品已归档，请在作品管理中恢复'), 409
    p = load_project(pid)
    if not p:
        return jsonify({"ok": False, "msg": "项目不存在"}), 404
    # 转换资产路径为URL
    assets_view = []
    for k, a in p.get('assets', {}).items():
        raw_kind = a.get('kind')
        kind = "character" if raw_kind in ("char", "character") else ("prop" if raw_kind == "prop" else ("shot_reference" if raw_kind == "shot_reference" else "scene"))
        av = {"key": k, "kind": kind, "chat_history": a.get("chat_history", []), "edit_revisions": a.get("edit_revisions", [])}
        if a.get('path'):
            av["url"] = asset_file_url(p['id'], a['path'])
        if a.get('audio_path'):
            av["audio"] = True
        if a.get('prompt'):
            av["prompt"] = a['prompt']
        assets_view.append(av)
    shots_view = copy.deepcopy(p.get('shots', []))
    for shot in shots_view:
        if not isinstance(shot, dict):
            continue
        path = shot.get('local_path') or shot.get('path')
        if path and os.path.isfile(os.path.join(BASE_DIR, path)):
            shot['video_url'] = f"/file/outputs/{quote(os.path.relpath(os.path.join(BASE_DIR, path), OUTPUTS_DIR).replace(os.sep, '/'))}" + f"?v={os.stat(os.path.join(BASE_DIR, path)).st_mtime_ns}"
    preview_project_id = p.get('preview_project_id')
    # 兼容旧记录和最近一次空的小样分支：始终选择实际含视频的最近分支。
    candidates = []
    for candidate in Path(PROJECTS_DIR).glob(f'preview_{pid}_*/project.json'):
        try:
            preview = json.loads(candidate.read_text(encoding='utf-8'))
            if any((s.get('video_url') or s.get('path')) for s in preview.get('shots', []) if isinstance(s, dict)):
                candidates.append((candidate.stat().st_mtime, candidate.parent.name))
        except (OSError, ValueError, TypeError):
            continue
    if candidates and (not preview_project_id or not (Path(PROJECTS_DIR) / preview_project_id / 'project.json').is_file() or
                       preview_project_id not in {item[1] for item in candidates}):
        preview_project_id = max(candidates)[1]
    return jsonify({"ok": True, "project": {
        "id": p['id'], "title": p.get('title'), "idea": p.get('idea'), "bridge_supported": True, "reference_sync": p.get("reference_sync", {}),
        "script": p.get('script'), "script_edit_archive": p.get("script_edit_archive", {}), "assets": assets_view,
        "render_groups": p.get('render_groups', []), "prompt_failures": p.get('prompt_failures', {}),
        "shots": shots_view, "final": p.get('final'), "previous_final": p.get('previous_final'),
        "custom_assets": p.get('custom_assets'), "assets_confirmed": p.get('assets_confirmed'),
        "generation_reference": project_generation_reference(p),
        "series": p.get("series"), "reviews": p.get("reviews", {}), "render_config": p.get("render_config"),
        "preview_project_id": preview_project_id,
        "shot_confirm": p.get("shot_confirm", {}), "asset_confirm": p.get("asset_confirm", {}),
        "script_review_required": p.get("script_review_required", False),
        "script_confirmed": p.get("script_confirmed", True),
        "script_review": p.get("script_review", {}),
        "run_id": p.get("run_id"),
        "运行记录": p.get("运行记录", []),
        "智能体记录": p.get("智能体记录", []),
        "优化历史": p.get("优化历史", []),
        "协同状态": p.get("协同状态", {}),
        "智能体通信记录": p.get("智能体通信记录", []),
        "技能调用记录": p.get("技能调用记录", []),
        "智能体决策记录": p.get("智能体决策记录", [])
    }})

@app.route('/api/project/<pid>/rename', methods=['POST'])
def api_project_rename(pid):
    """重命名普通项目或连续剧单集。"""
    project = load_project(pid)
    if not project:
        return jsonify({"ok": False, "msg": "项目不存在"}), 404
    title = str((request.get_json(silent=True) or {}).get('title') or '').strip()
    if not title:
        return jsonify({"ok": False, "msg": "单集片名不能为空"}), 400
    project['title'] = title
    if isinstance(project.get('script'), dict):
        project['script']['title'] = title
    save_project(project)

    series_ctx = project.get('series') or {}
    series_id = series_ctx.get('id')
    episode = series_ctx.get('episode')
    if series_id and episode is not None:
        series = load_series(series_id)
        if series:
            meta = (series.setdefault('episodes', {})).setdefault(str(int(episode)), {})
            if isinstance(meta, dict):
                meta['project_id'] = pid
                meta['title'] = title
                meta['updated'] = time.time()
                series['updated'] = time.time()
                save_series(series)
    return jsonify({"ok": True, "project": {
        "id": pid, "title": project.get('title'),
        "series": project.get('series'),
    }})

@app.route('/api/project/<pid>/script/confirm', methods=['POST'])
def api_project_script_confirm(pid):
    """确认当前剧本，让等待中的管线进入资产生成。"""
    project = load_project(pid)
    if not project:
        return jsonify({"ok": False, "msg": "项目不存在"}), 404
    if not project.get('script'):
        return jsonify({"ok": False, "msg": "当前项目还没有可确认的剧本"}), 400
    project['script_confirmed'] = True
    project.setdefault('script_review', {}).update({
        "action": "confirm",
        "confirmed_at": time.time(),
    })
    save_project(project)
    return jsonify({"ok": True, "msg": "剧本已确认，开始生成资产"})

@app.route('/api/project/<pid>/script/regenerate', methods=['POST'])
def api_project_script_regenerate(pid):
    """清空尚未进入资产阶段的剧本，以调整后的导演台参数重新生成。"""
    project = load_project(pid)
    if not project:
        return jsonify({"ok": False, "msg": "项目不存在"}), 404
    if project.get('assets') or project.get('shots') or project.get('final'):
        return jsonify({"ok": False, "msg": "项目已进入资产或视频阶段，不能直接覆盖剧本"}), 409
    data = request.get_json(silent=True) or {}
    idea = str(data.get('idea') or '').strip()
    if not idea:
        return jsonify({"ok": False, "msg": "缺少调整后的故事和导演简报"}), 400
    project['idea'] = idea
    project['script'] = None
    project['title'] = ""
    project['script_confirmed'] = False
    project['script_review_required'] = True
    project.setdefault('script_review', {}).update({
        "action": "regenerate",
        "requested_at": time.time(),
    })
    save_project(project)
    return jsonify({"ok": True, "msg": "旧剧本已清空，可以按新的导演台参数重新生成"})

@app.route('/api/project/<pid>/script/chat', methods=['POST'])
def api_project_script_chat(pid):
    """在剧本确认前，通过对话修改当前剧本并立即保存。"""
    project = load_project(pid)
    if not project:
        return jsonify({"ok": False, "msg": "项目不存在"}), 404
    script = project.get('script')
    if not isinstance(script, dict) or not script.get('shots'):
        return jsonify({"ok": False, "msg": "当前项目还没有可修改的剧本"}), 400
    if project.get('assets') or project.get('shots') or project.get('final'):
        return jsonify({"ok": False, "msg": "项目已经进入资产或视频阶段，不能再直接修改剧本；请从导演台重新生成"}), 409

    data = request.get_json(silent=True) or {}
    message = str(data.get('message') or '').strip()
    if not message:
        return jsonify({"ok": False, "msg": "请输入想修改的内容"}), 400
    history = project.get("script_edit_archive", {}).get("chat_history", [])
    history = [
        {
            "role": "user" if item.get("role") == "user" else "assistant",
            "content": str(item.get("content") or "")[:1200],
        }
        for item in history[-8:]
        if isinstance(item, dict) and str(item.get("content") or "").strip()
    ]
    system_prompt = """你是短剧剧本总编剧，负责根据用户意见修改当前结构化短剧剧本。
必须保留原有JSON结构，至少包含title、synopsis、characters、scenes、props、shots。
只修改用户要求的部分，未提及的内容尽量保留；镜头必须有index、duration、camera、scene、action，
duration限制在8到15秒，shots的index从1连续编号。角色、场景、道具的名称必须与shots中的引用一致。
输出严格JSON，不要Markdown代码块，不要额外解释，格式：
{"reply":"用中文简短说明本次改动","script":{完整修改后的剧本JSON}}"""
    user_prompt = (
        "【当前剧本】\n" + json.dumps(script, ensure_ascii=False, indent=2) +
        "\n\n【此前对话】\n" + json.dumps(history, ensure_ascii=False) +
        "\n\n【本次修改要求】\n" + message
    )
    content, error = llm_chat(
        [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
        max_tokens=9000,
        temperature=0.55,
        retries=1,
        timeout=180,
    )
    if not content:
        return jsonify({"ok": False, "msg": f"AI修改失败: {error or '模型没有返回内容'}"}), 502
    result = parse_json_from_text(content)
    edited_script = result.get("script") if isinstance(result, dict) else None
    if not isinstance(edited_script, dict) or not edited_script.get("shots"):
        return jsonify({"ok": False, "msg": "AI返回的剧本格式无法解析，请换一种说法重试"}), 502
    try:
        edited_script = 剧本智能体._规范化剧本(edited_script)
        edited_script = apply_story_bible(
            edited_script,
            parse_series_context(project.get("idea", "")),
            project_id=pid,
        )
    except Exception as exc:
        return jsonify({"ok": False, "msg": f"剧本校验失败: {exc}"}), 502
    reply = str((result or {}).get("reply") or "已按你的要求更新剧本，请继续查阅。").strip()
    with PROJECT_IO_LOCK:
        latest = load_project(pid)
        if not latest or latest.get('script') != script:
            return jsonify(ok=False, msg='剧本已被修改，请重新载入后再试'), 409
        project = latest
        archive_edit(project.setdefault("script_edit_archive", {}), script, edited_script, message, reply)
        project["script"] = edited_script
        project["title"] = edited_script.get("title") or project.get("title") or "未命名短剧"
        project["script_confirmed"] = False
        project.setdefault("script_review", {}).update({
            "action": "chat_edit",
            "message": message[:500],
            "edited_at": time.time(),
        })
        save_project(project)
    return jsonify({"ok": True, "reply": reply, "script": edited_script, "chat_history": project["script_edit_archive"]["chat_history"]})

@app.route('/api/project/<pid>/agent/next')
def api_agent_next(pid):
    """由总控智能体根据当前项目状态判断下一步动作。"""
    project = load_project(pid)
    if not project:
        return jsonify({"ok": False, "msg": "项目不存在"}), 404
    decision_result = 协同调度器实例.执行("总控智能体", project, {
        "来源": "项目下一步接口",
    })
    if not decision_result.get("成功"):
        return jsonify({"ok": False, "msg": decision_result.get("错误")}), 500
    decision = decision_result.get("数据") or {}
    project.setdefault("智能体记录", []).append({
        "时间": time.time(),
        "智能体": "总控智能体",
        "动作": decision.get("动作"),
        "阶段": decision.get("阶段"),
        "来源": "api/project/agent/next",
    })
    save_project(project)
    return jsonify({"ok": True, "decision": decision})

@app.route('/api/agents/capabilities')
def api_agents_capabilities():
    """返回当前已接入的智能体和技能，供界面或外部编排器读取。"""
    return jsonify({
        "ok": True,
        "agents": [
            {
                "name": item.get("名称"),
                "status": item.get("状态", "未知"),
                "role": item.get("说明", ""),
                "stage": item.get("阶段", ""),
                "skills": item.get("技能清单", []),
                "missing_skills": item.get("缺失技能", []),
                "config_complete": item.get("配置完整", False),
                "real_integration": item.get("真实接入", False),
                "config_version": item.get("版本", ""),
                "collaboration_mode": item.get("协作模式", ""),
                "inputs": item.get("输入", []),
                "outputs": item.get("输出", []),
                "timeout_seconds": item.get("超时秒数", 0),
                "max_retries": item.get("最大重试次数", 0),
            }
            for item in 协同调度器实例.列表()
        ],
        "skills": [
            {"name": name, "status": "已注册"}
            for name in 技能注册表实例.列表()
        ],
    })

@app.route('/api/project/<pid>/agents/dispatch', methods=['POST'])
def api_dispatch_agent(pid):
    """向指定 Agent 派发一次项目任务，并保存协同记录。"""
    project = load_project(pid)
    if not project:
        return jsonify({"ok": False, "msg": "项目不存在"}), 404
    body = request.get_json(silent=True) or {}
    agent_name = str(body.get("agent") or body.get("智能体") or "").strip()
    parameters = body.get("parameters")
    if parameters is None:
        parameters = body.get("参数") or {}
    if not agent_name:
        return jsonify({"ok": False, "msg": "缺少 agent/智能体"}), 400
    if not isinstance(parameters, dict):
        return jsonify({"ok": False, "msg": "parameters/参数必须是对象"}), 400

    sender = str(body.get("sender") or body.get("发送者") or "总控智能体")
    task_type = str(body.get("task_type") or body.get("任务类型") or "协同任务")
    receiver = agent_name
    sender_agent = 协同调度器实例.获取智能体(sender)
    if sender_agent:
        消息 = sender_agent.发送(
            project, receiver, task_type, 数据=parameters, 状态="执行中",
        )
    else:
        消息 = 协同总控智能体.发送(
            project, receiver, task_type, 数据=parameters, 状态="执行中",
        )

    result = 协同调度器实例.执行(agent_name, project, parameters)
    # 技能执行期间可能已经保存了项目（例如单镜渲染会写入视频和版本）。
    # 重新加载最新快照，避免用派发前的旧对象覆盖技能产物。
    project = 项目服务实例.加载(pid) or project
    更新任务状态(
        project,
        智能体=agent_name,
        状态="已完成" if result.get("成功") else "失败",
    )
    project.setdefault("智能体记录", []).append({
        "时间": time.time(),
        "智能体": agent_name,
        "动作": task_type,
        "参数": copy.deepcopy(parameters),
        "结果": copy.deepcopy(result),
        "消息编号": 消息.get("消息编号"),
        "来源": "api/project/agents/dispatch",
    })
    save_project(project)
    return jsonify({
        "ok": bool(result.get("成功")),
        "message": 消息,
        "result": result,
    }), (200 if result.get("成功") else 400)

@app.route('/api/project/<pid>/delete', methods=['POST'])
def api_delete_project(pid):
    """删除历史项目：存档 json + 该项目 outputs 视频目录"""
    if not re.fullmatch(r'[0-9a-zA-Z_-]{1,64}', pid):
        return jsonify({"ok": False, "msg": "非法项目ID"}), 400
    if not 项目服务实例.加载(pid):
        return jsonify({"ok": False, "msg": "项目不存在"}), 404
    项目服务实例.删除(pid)
    print(f"[项目] 已删除 {pid}")
    return jsonify({"ok": True})

@app.route('/api/project/<pid>/asset/<path:key>/prompt-chat', methods=['POST'])
def api_asset_prompt_chat(pid, key):
    return project_asset_prompt_chat(pid, key)

@app.route('/api/project/<pid>/asset/<path:key>/regenerate', methods=['POST'])
def api_asset_regenerate(pid, key):
    """按指定提示词（或AI自动构造，若不传）重新生成单张资产参考图；供用户"编辑提示词→重生成"。
    重新生成后清空提示词缓存（H3提示词依赖角色外观，需按新图重写）。"""
    proj = load_project(pid)
    if not proj:
        return jsonify({"error": "项目不存在"}), 404
    set_runtime_config(project_render_config(proj))
    kind = key.split('_', 1)[0] if '_' in key else 'char'
    if kind not in ('char', 'scene', 'prop'):
        return jsonify({"error": "非法资产类型"}), 400
    script = proj.get('script') or {}
    name = key.split('_', 1)[1]
    data = request.get_json(silent=True) or {}
    manual_prompt = (data.get('prompt') or '').strip() or None
    image_model = str(data.get('image_model') or '').strip() or None
    desc = _script_asset_description(script, kind, name)
    # 手动提示词已经包含完整生成指令时，不需要依赖剧本中的旧描述。
    # 这也兼容早期项目中剧本被清理、但资产图片仍然可以继续修改的情况。
    if not desc and not manual_prompt:
        return jsonify({"error": f"未在剧本中找到资产「{name}」的描述"}), 400
    if not ensure_comfyui():
        return jsonify({"error": "ComfyUI不可用且自动启动失败"}), 503
    style = runtime_config().get('style', '电影写实')
    provider = media_provider()
    print(f"[资产] 请求重生成 {pid}/{key}，媒体服务商={provider}", flush=True)
    with (contextlib.nullcontext() if MULTIUSER else GPU_JOB_LOCK):
        path, aprompt, err = gen_asset_image(
            kind, name, desc, style,
            characters=script.get('characters', []),
            prompt=manual_prompt,
            image_model=image_model,
        )
    if err:
        return jsonify({"error": f"重新生成失败: {err}"}), 500
    assets = proj.get('assets', {})
    old = assets.get(key, {})
    if isinstance(old, dict):
        _archive_asset_version(proj, key, old, label='修改前版本')
    new_entry = {"path": path, "kind": ('character' if kind in ('char', 'character') else kind), "prompt": aprompt}
    if isinstance(old, dict):
        if old.get('uploaded'):
            new_entry['uploaded'] = old['uploaded']
        if old.get('audio_path'):
            new_entry['audio_path'] = old['audio_path']
        if old.get('desc_done'):
            new_entry['desc_done'] = True
    new_version = _archive_asset_version(proj, key, new_entry, label='修改后版本')
    if new_version:
        new_entry['current_version_id'] = new_version['id']
    assets[key] = new_entry
    proj['assets'] = assets
    # 重生成资产后旧提示词作废：需按新图重新撰写
    proj.pop('prompts', None)
    proj.pop('shot_confirm', None)
    save_project(proj)
    print(f"[资产] 重新生成 {pid}/{key}")
    return jsonify({
        "ok": True,
        "url": f"/file/assets/{os.path.basename(path)}",
        "versions": _asset_versions(proj, key),
        "prompt": aprompt,
        "provider": provider,
        "image_model": image_model or (
            runtime_config().get('jimeng_image_model')
            if provider == 'jimeng'
            else QWEN_IMAGE_MODEL
        ),
    })


@app.route('/api/project/<pid>/asset/<path:key>/versions')
def api_asset_versions(pid, key):
    proj = load_project(pid)
    if not proj:
        return jsonify({"error": "项目不存在"}), 404
    if key not in (proj.get('assets') or {}):
        return jsonify({"error": "资产不存在"}), 404
    versions = _asset_versions(proj, key)
    return jsonify({
        "ok": True,
        "key": key,
        "current_version_id": (proj.get('assets') or {}).get(key, {}).get('current_version_id'),
        "versions": versions,
    })


@app.route('/api/project/<pid>/asset/<path:key>/select_version', methods=['POST'])
def api_asset_select_version(pid, key):
    proj = load_project(pid)
    if not proj:
        return jsonify({"error": "项目不存在"}), 404
    assets = proj.get('assets') or {}
    current = assets.get(key)
    if not isinstance(current, dict):
        return jsonify({"error": "资产不存在"}), 404
    data = request.get_json(silent=True) or {}
    version_id = str(data.get('version_id') or '').strip()
    versions = (proj.get('asset_versions') or {}).get(str(key), [])
    version = next((item for item in versions if item.get('id') == version_id), None)
    if not version:
        return jsonify({"error": "图片历史版本不存在"}), 404
    version_dir = _asset_version_dir(pid, key)
    source = os.path.join(version_dir, os.path.basename(version.get('filename', '')))
    if not os.path.isfile(source):
        return jsonify({"error": "图片历史文件不存在"}), 404
    ext = os.path.splitext(source)[1] or '.png'
    selected_path = os.path.join(ASSETS_DIR, f"asset_{uuid.uuid4().hex[:12]}{ext}")
    try:
        shutil.copyfile(source, selected_path)
    except (OSError, shutil.Error) as exc:
        return jsonify({"error": f"恢复图片失败: {exc}"}), 500
    selected = copy.deepcopy(current)
    selected['path'] = selected_path
    selected['prompt'] = version.get('prompt', selected.get('prompt', ''))
    selected['current_version_id'] = version_id
    assets[key] = selected
    proj['assets'] = assets
    proj.pop('prompts', None)
    proj.pop('shot_confirm', None)
    save_project(proj)
    return jsonify({
        "ok": True,
        "url": f"/file/assets/{os.path.basename(selected_path)}",
        "prompt": selected.get('prompt', ''),
        "version": version,
    })

@app.route('/api/project/<pid>/asset/<path:key>/confirm', methods=['POST'])
def api_asset_confirm(pid, key):
    """手动模式下：用户对某张资产参考图满意后，标记 asset_confirm[key].continue=True，让管线进入下一步。"""
    proj = load_project(pid)
    if not proj:
        return jsonify({"error": "项目不存在"}), 404
    data = request.get_json(silent=True) or {}
    prompt = str(data.get('prompt') or '').strip()
    if prompt:
        asset = (proj.setdefault('assets', {})).get(key)
        if isinstance(asset, dict):
            asset['prompt'] = prompt
    confs = proj.get('asset_confirm', {})
    confs[key] = {"continue": True}
    proj['asset_confirm'] = confs
    save_project(proj)
    print(f"[资产] 确认通过 {pid}/{key}")
    return jsonify({"ok": True})

@app.route('/api/project/<pid>/asset/confirm_all', methods=['POST'])
def api_asset_confirm_all(pid):
    """手动模式：全部参考图已浏览满意，标记 asset_confirm.__all__.continue=True，让管线进入分镜环节。"""
    proj = load_project(pid)
    if not proj:
        return jsonify({"error": "项目不存在"}), 404
    confs = proj.get('asset_confirm', {})
    confs['__all__'] = {"continue": True}
    proj['asset_confirm'] = confs
    save_project(proj)
    print(f"[资产] 环节全部确认 {pid}")
    return jsonify({"ok": True})

@app.route('/api/upload_asset', methods=['POST'])
def api_upload_asset():
    """自定义参考图上传：保存到项目专属目录并登记进项目存档。"""
    pid = request.form.get('pid', '')
    key = request.form.get('key', '')
    f = request.files.get('file')
    if not pid or not key or not f:
        return jsonify({"ok": False, "msg": "参数缺失"}), 400
    if not re.fullmatch(r'[0-9a-zA-Z_-]{1,64}', pid):
        return jsonify({"ok": False, "msg": "非法项目ID"}), 400
    proj = load_project(pid)
    if not proj:
        return jsonify({"ok": False, "msg": "项目不存在"}), 404
    kind = key.split('_', 1)[0] if '_' in key else 'character'
    if kind not in ('char', 'scene', 'prop'):
        return jsonify({"ok": False, "msg": "非法资产类型"}), 400
    ext = os.path.splitext(f.filename or '')[1].lower() or '.png'
    if ext not in ('.png', '.jpg', '.jpeg', '.webp'):
        return jsonify({"ok": False, "msg": "仅支持 png/jpg/webp 图片"}), 400
    safe = re.sub(r'[^\w一-鿿-]', '_', key)
    save_dir = project_assets_dir(pid)
    os.makedirs(save_dir, exist_ok=True)
    save_path = os.path.join(save_dir, f"upload_{safe}_{uuid.uuid4().hex[:12]}{ext}")
    old = (proj.get('assets') or {}).get(key) or {}
    old_path = old.get('path') if isinstance(old, dict) else ''
    f.save(save_path)
    assets = proj.get('assets', {})
    new_entry = {"path": save_path, "kind": kind, "uploaded": True}
    if isinstance(old, dict):
        for field in ("audio_path",):
            if old.get(field):
                new_entry[field] = old[field]
    assets[key] = new_entry
    proj['assets'] = assets
    # 保留旧描述用于预览对比，确认同步前阻止受影响镜头生成。
    from core.reference_sync import affected
    if affected(proj, key):
        proj.setdefault('reference_sync', {})[key] = uuid.uuid4().hex
    proj.pop('reference_sync_draft', None)
    save_project(proj)
    # 保留旧资产文件供历史版本追溯；新上传使用独立文件名。
    print(f"[上传] {pid}/{key} -> {os.path.basename(save_path)}")
    return jsonify({"ok": True, "url": asset_file_url(pid, save_path), "sync_required": bool(proj.get("reference_sync"))})

@app.route('/api/upload_role_audio', methods=['POST'])
def api_upload_role_audio():
    """上传角色参考音色：音频文件绑定到项目的角色资产（char_xxx.audio_path）。
    该角色在分镜出现时，其台词音色以该音频为 voice-timbre reference。非必传，不传则AI自动生成音色。"""
    pid = request.form.get('pid', '')
    key = request.form.get('key', '')
    f = request.files.get('file')
    if not pid or not key or not f:
        return jsonify({"ok": False, "msg": "参数缺失"}), 400
    if not re.fullmatch(r'[0-9a-zA-Z_-]{1,64}', pid):
        return jsonify({"ok": False, "msg": "非法项目ID"}), 400
    if not key.startswith('char_'):
        return jsonify({"ok": False, "msg": "仅角色资产支持绑定参考音色"}), 400
    proj = load_project(pid)
    if not proj:
        return jsonify({"ok": False, "msg": "项目不存在"}), 404
    ext = os.path.splitext(f.filename or '')[1].lower()
    if ext not in ('.wav', '.mp3', '.flac', '.ogg', '.m4a', '.aac'):
        return jsonify({"ok": False, "msg": "仅支持 wav/mp3/flac/ogg/m4a 音频"}), 400
    safe = re.sub(r'[^\w一-鿿-]', '_', key)
    save_path = os.path.join(ASSETS_DIR, f"audio_{pid}_{safe}{ext}")
    f.save(save_path)
    assets = proj.get('assets', {})
    base = assets.get(key, {})
    if not isinstance(base, dict):
        base = {"kind": "character"}
    base['audio_path'] = save_path
    assets[key] = base
    proj['assets'] = assets
    save_project(proj)
    print(f"[上传音色] {pid}/{key} -> {os.path.basename(save_path)}")
    return jsonify({"ok": True, "audio_path": save_path})

@app.route('/api/confirm_assets', methods=['POST'])
def api_confirm_assets():
    """用户确认参考图就绪：对上传图用视觉LLM重写外观描述（以图为准），置确认标志让管线继续"""
    d = request.get_json(force=True, silent=True) or {}
    pid = d.get('pid', '')
    proj = load_project(pid)
    if not proj:
        return jsonify({"ok": False, "msg": "项目不存在"}), 404
    assets = proj.get('assets', {})
    script = proj.get('script') or {}
    rewritten, failed = 0, 0
    for key, a in assets.items():
        if not a.get('uploaded') or a.get('desc_done'):
            continue
        name = key.split('_', 1)[1] if '_' in key else key
        kind = a.get('kind', 'char')
        new_desc, derr = describe_uploaded_asset(a['path'], kind, name)
        if new_desc:
            pool_map = {'char': 'characters', 'character': 'characters', 'scene': 'scenes', 'prop': 'props'}
            pool = script.get(pool_map.get(kind, 'characters'), [])
            if isinstance(pool, dict):
                item = pool.get(name)
                if isinstance(item, dict):
                    if kind in ('char', 'character'):
                        item['appearance'] = new_desc
                    else:
                        item['description'] = new_desc
            elif isinstance(pool, list):
                for item in pool:
                    if isinstance(item, dict) and item.get('name') == name:
                        if kind in ('char', 'character'):
                            item['appearance'] = new_desc
                        else:
                            item['description'] = new_desc
                        break
            a['desc_done'] = True
            rewritten += 1
        else:
            failed += 1
            print(f"[确认资产] {key} 视觉重写失败(保留原描述): {derr}")
    proj['script'] = script
    proj['assets'] = assets
    proj['assets_confirmed'] = True
    save_project(proj)
    print(f"[确认资产] {pid} 重写{rewritten}条 失败{failed}条")
    return jsonify({"ok": True, "rewritten": rewritten, "failed": failed})


# ============================== 连续剧工厂 API ==============================
SERIES_BATCH_TASKS = {}

def _series_episode_project_candidates(series_id, episode, preferred_pid=None):
    """找出同一剧同一集的所有项目，兼容历史上重复登记导致的项目指针错误。"""
    candidates = []
    seen = set()
    candidate_ids = [preferred_pid] if preferred_pid else []
    try:
        candidate_ids.extend(项目存储.keys())
    except OSError:
        pass
    archived_ids = work_archive.ids('project')
    archived_series = series_id in work_archive.ids('series')
    for pid in candidate_ids:
        if pid in archived_ids and not archived_series:
            continue
        if not pid or pid in seen:
            continue
        seen.add(pid)
        if MULTIUSER and not MULTIUSER.series_child(series_id,pid):
            continue
        project = load_project(pid)
        if not project:
            continue
        ctx = project.get('series') or {}
        try:
            same_episode = int(ctx.get('episode', 0) or 0) == int(episode)
        except (TypeError, ValueError):
            same_episode = False
        same_series = str(ctx.get('id') or '') == str(series_id)
        if not same_series or not same_episode:
            continue
        video_count = len([
            shot for shot in (project.get('shots') or [])
            if shot.get('video_url') and not shot.get('error')
        ])
        candidates.append((project, video_count))
    return candidates

def _pick_series_episode_project(series_id, episode, preferred_pid=None, candidates=None):
    if candidates is None:
        candidates = _series_episode_project_candidates(series_id, episode, preferred_pid)
    if not candidates:
        if MULTIUSER and not MULTIUSER.series_child(series_id,preferred_pid):
            return None
        return load_project(preferred_pid) if preferred_pid else None
    # 已登记的当前版本优先，重做中的草稿不能被旧成片覆盖。
    for project, _ in candidates:
        if project.get("id") == preferred_pid:
            return project
    # 仅当当前引用失效时，兼容历史数据选择可用版本。
    candidates.sort(key=lambda item: (
        bool(item[0].get('final')),
        item[1],
        bool(item[0].get('script')),
        float(item[0].get('updated', item[0].get('created', 0)) or 0),
    ), reverse=True)
    return candidates[0][0]

def _series_episode_status(series_obj):
    """聚合剧项目下每一集的实际生成状态，供项目列表/项目详情展示。"""
    result = {}
    episodes = series_obj.get('episodes') or {}
    for ep_key, meta in episodes.items():
        try:
            ep_no = int(ep_key)
        except Exception:
            continue
        meta = meta if isinstance(meta, dict) else {}
        old_pid = meta.get('project_id')
        candidates = _series_episode_project_candidates(series_obj.get('id'), ep_no, old_pid)
        proj = _pick_series_episode_project(series_obj.get('id'), ep_no, old_pid, candidates)
        pid = proj.get('id') if proj else old_pid
        versions = [{
            "project_id": item.get("id"), "title": item.get("title", ""),
            "created": item.get("created", 0), "has_final": bool(available_final(item)),
            "is_current": item.get("id") == pid,
        } for item, _ in sorted(candidates, key=lambda pair: float(pair[0].get("created", 0) or 0))]
        result[str(ep_no)] = {
            "episode": ep_no,
            "versions": versions,
            "project_id": pid,
            "title": (proj or {}).get('title') or meta.get('title', ''),
            "has_script": bool((proj or {}).get('script')),
            "has_final": bool(available_final(proj)),
            "final": available_final(proj),
            "final_needs_resynth": bool((proj or {}).get('previous_final') and not (proj or {}).get('final')),
            "failed_shots": len([x for x in ((proj or {}).get('shots') or []) if x.get('error')]),
            "updated": meta.get('updated', 0),
        }
    return result

def _series_summary(series_obj):
    statuses = _series_episode_status(series_obj)
    episode_count = len(statuses)
    generated = len([x for x in statuses.values() if x.get('has_script')])
    finals = len([x for x in statuses.values() if x.get('has_final')])
    failed = len([x for x in statuses.values() if x.get('failed_shots')])
    return {
        "id": series_obj.get('id'), "name": series_obj.get('name'), "premise": series_obj.get('premise',''),
        "episode_count": episode_count, "generated_count": generated, "final_count": finals,
        "failed_episode_count": failed, "updated": series_obj.get('updated', series_obj.get('created', 0)),
        "created": series_obj.get('created', 0),
        "episodes": statuses,
    }

def _series_list_summary(series_obj):
    """轻量剧集列表摘要。列表页只需要计数，避免逐集扫描全部项目文件。"""
    episodes = series_obj.get('episodes') or {}
    rows = [m for m in episodes.values() if isinstance(m, dict)]
    episode_status = {}
    for ep_key, meta in episodes.items():
        if not isinstance(meta, dict):
            continue
        try:
            ep_no = int(ep_key)
        except (TypeError, ValueError):
            continue
        pid = meta.get('project_id')
        episode_status[str(ep_no)] = {
            'episode': ep_no,
            'project_id': pid,
            'title': meta.get('title', ''),
            'has_script': bool(pid),
            'has_final': bool(meta.get('has_final') or meta.get('final')),
            'final': meta.get('final'),
            'final_needs_resynth': bool(meta.get('final_needs_resynth')),
            'failed_shots': 0,
            'updated': meta.get('updated', 0),
            'versions': meta.get('versions') or ([{
                'project_id': pid,
                'title': meta.get('title', ''),
                'has_final': bool(meta.get('has_final') or meta.get('final')),
                'is_current': True,
            }] if pid else []),
        }
    generated = sum(bool(m.get('project_id')) for m in rows)
    finals = sum(bool(m.get('final') or m.get('has_final')) for m in rows)
    return {
        "id": series_obj.get('id'), "name": series_obj.get('name'), "premise": series_obj.get('premise',''),
        "episode_count": len(rows), "generated_count": generated, "final_count": finals,
        "failed_episode_count": 0, "updated": series_obj.get('updated', series_obj.get('created', 0)),
        "created": series_obj.get('created', 0), "episodes": episode_status,
    }

def _batch_project_id(series_id, episode):
    digest = hashlib.sha1(f"{series_id}:{episode}".encode('utf-8')).hexdigest()[:6]
    return f"ser_{hashlib.sha1(series_id.encode('utf-8')).hexdigest()[:6]}_e{int(episode):03d}_{digest}"

@app.route('/api/series', methods=['GET'])
def api_series_list():
    archived_ids = work_archive.ids('series')
    archived_only = request.args.get('archived') == '1'
    items = []
    os.makedirs(SERIES_DIR, exist_ok=True)
    for fn in os.listdir(SERIES_DIR):
        if not fn.endswith('.json'):
            continue
        try:
            if ((fn[:-5] in archived_ids) != archived_only):
                continue
            s = load_series(fn[:-5])
            if not s:
                continue
            items.append(_series_list_summary(s))
        except Exception as e:
            print(f"[剧项目] 列表读取失败 {fn}: {e}")
            continue
    items.sort(key=lambda x: x.get('updated', 0), reverse=True)
    return jsonify(items)

@app.route('/api/series/create', methods=['POST'])
def api_series_create():
    """新建一个空的剧项目，不调用LLM；后续由用户逐集创作，Story Bible负责跨集一致性。"""
    data = request.get_json(force=True, silent=True) or {}
    name = (data.get('name') or data.get('series_name') or '').strip()
    premise = (data.get('premise') or '').strip()
    if not name:
        return jsonify({"ok": False, "msg": "请填写剧名"}), 400
    sid = _series_id_from_name(name)
    existing = load_series(sid)
    if existing:
        return jsonify({"ok": False, "msg": "同名剧项目已存在", "series": existing}), 409
    now = time.time()
    s = {
        "id": sid, "name": name, "premise": premise, "created": now, "updated": now,
        "characters": {}, "scenes": {}, "props": {}, "assets": {}, "episodes": {},
        "plan": [], "main_characters": []
    }
    save_series(s)
    return jsonify({"ok": True, "series": s})

@app.route('/api/series/<series_id>', methods=['GET'])
def api_series_get(series_id):
    s = load_series(series_id)
    if not s:
        return jsonify({"ok": False, "msg": "剧项目不存在"}), 404
    view = copy.deepcopy(s)
    view['episode_status'] = _series_episode_status(s)
    view['summary'] = _series_summary(s)
    return jsonify({"ok": True, "series": view})

@app.route('/api/series/<series_id>/remake', methods=['POST'])
def api_series_remake(series_id):
    """复制整部剧集为新版本，包含 Story Bible 和已有单集结构。"""
    source = load_series(series_id)
    if not source:
        return jsonify({"ok": False, "msg": "剧项目不存在"}), 404
    data = request.get_json(silent=True) or {}
    mode = _remake_mode(data.get("mode"))
    base_name = str(source.get("name") or "未命名剧").strip()
    new_name = _remake_title(base_name)
    if load_series(_series_id_from_name(new_name)):
        new_name = f"{new_name} {int(time.time())}"
    new_series_id = _series_id_from_name(new_name)
    now = time.time()
    cloned_series = copy.deepcopy(source)
    cloned_series.update({
        "id": new_series_id,
        "name": new_name,
        "created": now,
        "updated": now,
        "remake_of": series_id,
        "remake_mode": mode,
        "episodes": {},
    })

    for episode_key, source_meta in (source.get("episodes") or {}).items():
        if not isinstance(source_meta, dict):
            continue
        episode_no = int(episode_key) if str(episode_key).isdigit() else episode_key
        source_pid = source_meta.get("project_id")
        new_meta = copy.deepcopy(source_meta)
        new_meta["updated"] = now
        if source_pid:
            source_project = load_project(source_pid)
            if source_project:
                series_context = {
                    "id": new_series_id,
                    "name": new_name,
                    "episode": episode_no,
                    "previous_summary": (source_project.get("series") or {}).get("previous_summary", ""),
                }
                cloned_project = _clone_project_for_remake(
                    source_project,
                    mode=mode,
                    series_override=series_context,
                )
                new_meta["project_id"] = cloned_project["id"]
                new_meta["title"] = cloned_project.get("title") or new_meta.get("title", "")
        cloned_series["episodes"][str(episode_key)] = new_meta

    save_series(cloned_series)
    view = copy.deepcopy(cloned_series)
    view["episode_status"] = _series_episode_status(cloned_series)
    view["summary"] = _series_summary(cloned_series)
    return jsonify({
        "ok": True,
        "mode": mode,
        "mode_label": REMAKE_MODES[mode],
        "series": view,
    })

@app.route('/api/series/<series_id>/update', methods=['POST'])
def api_series_update(series_id):
    """更新剧名和长期核心设定；不做AI整季规划。"""
    s = load_series(series_id)
    if not s:
        return jsonify({"ok": False, "msg": "剧项目不存在"}), 404
    data = request.get_json(force=True, silent=True) or {}
    if 'name' in data:
        name = str(data.get('name') or '').strip()
        if not name:
            return jsonify({"ok": False, "msg": "剧名不能为空"}), 400
        for fn in os.listdir(SERIES_DIR):
            if not fn.endswith('.json') or fn == f'{series_id}.json':
                continue
            if MULTIUSER and MULTIUSER.store.owner('series',fn[:-5]) != MULTIUSER.store.owner('series',series_id):
                continue
            other = load_series(fn[:-5])
            if other and str(other.get('name') or '').strip() == name:
                return jsonify({"ok": False, "msg": "同名剧项目已存在"}), 409
        old_name = s.get('name') or ''
        s['name'] = name
        # 保留系列 ID，只同步子项目中的显示名，确保改名不会影响历史文件。
        for meta in (s.get('episodes') or {}).values():
            if not isinstance(meta, dict):
                continue
            child = load_project(meta.get('project_id')) if meta.get('project_id') else None
            if not child:
                continue
            child_series = child.get('series') or {}
            child_series['id'] = series_id
            child_series['name'] = name
            child['series'] = child_series
            if child.get('idea') and old_name:
                child['idea'] = re.sub(
                    r'连续剧：是；剧名《[^》]+》；第',
                    f'连续剧：是；剧名《{name}》；第',
                    child['idea'],
                )
            save_project(child)
    if 'premise' in data:
        s['premise'] = (data.get('premise') or '').strip()
    s['updated'] = time.time()
    save_series(s)
    view = copy.deepcopy(s)
    view['episode_status'] = _series_episode_status(s)
    view['summary'] = _series_summary(s)
    return jsonify({"ok": True, "series": view})

@app.route('/api/series/<series_id>/episode/<int:episode>/rename', methods=['POST'])
def api_series_episode_rename(series_id, episode):
    """重命名连续剧中的单集，并同步项目标题。"""
    s = load_series(series_id)
    if not s:
        return jsonify({"ok": False, "msg": "剧项目不存在"}), 404
    title = str((request.get_json(silent=True) or {}).get('title') or '').strip()
    if not title:
        return jsonify({"ok": False, "msg": "单集片名不能为空"}), 400
    meta = (s.get('episodes') or {}).get(str(episode))
    if not isinstance(meta, dict):
        return jsonify({"ok": False, "msg": "该单集不存在"}), 404
    meta['title'] = title
    meta['updated'] = time.time()
    pid = meta.get('project_id')
    project = load_project(pid) if pid else None
    if project:
        project['title'] = title
        if isinstance(project.get('script'), dict):
            project['script']['title'] = title
        project['series'] = dict(project.get('series') or {})
        project['series']['id'] = series_id
        project['series']['episode'] = episode
        save_project(project)
    s['updated'] = time.time()
    save_series(s)
    view = copy.deepcopy(s)
    view['episode_status'] = _series_episode_status(s)
    view['summary'] = _series_summary(s)
    return jsonify({"ok": True, "series": view, "episode": episode, "title": title})

@app.route('/api/series/<series_id>/episode/register', methods=['POST'])
def api_series_episode_register(series_id):
    """手动建立某一集占位；本集剧情由用户自己写。"""
    s = load_series(series_id)
    if not s:
        return jsonify({"ok": False, "msg": "剧项目不存在"}), 404
    data = request.get_json(force=True, silent=True) or {}
    try:
        episode = max(1, min(int(data.get('episode', 1)), 9999))
    except Exception:
        episode = 1
    eps = s.setdefault('episodes', {})
    key = str(episode)
    old = eps.get(key) if isinstance(eps.get(key), dict) else {}
    eps[key] = {"project_id": old.get('project_id'), "title": old.get('title') or f"第{episode}集", "synopsis": old.get('synopsis', ''), "updated": time.time()}
    s['updated'] = time.time()
    save_series(s)
    view = copy.deepcopy(s)
    view['episode_status'] = _series_episode_status(s)
    view['summary'] = _series_summary(s)
    return jsonify({"ok": True, "series": view, "episode": episode})

@app.route('/api/series/<series_id>/delete', methods=['POST'])
def api_series_delete(series_id):
    """删除剧项目。delete_children=1 时同时删除该剧下所有单集项目与输出。"""
    s = load_series(series_id)
    if not s:
        return jsonify({"ok": False, "msg": "剧项目不存在"}), 404
    data = request.get_json(silent=True) or {}
    delete_children = bool(data.get('delete_children'))
    deleted_projects = 0
    if delete_children:
        for meta in (s.get('episodes') or {}).values():
            if not isinstance(meta, dict):
                continue
            pid = meta.get('project_id')
            if not pid or not re.fullmatch(r'[0-9a-zA-Z_-]{1,64}', str(pid)):
                continue
            if MULTIUSER and not MULTIUSER.series_child(series_id,pid):
                continue
            if 项目服务实例.删除(pid):
                deleted_projects += 1
    sp = series_path(series_id)
    if os.path.exists(sp):
        os.remove(sp)
    return jsonify({"ok": True, "deleted_projects": deleted_projects})

@app.route('/api/series/plan', methods=['POST'])
def api_series_plan():
    """兼容旧调用：V3.5已关闭整季AI规划。"""
    return jsonify({"ok": False, "msg": "整季AI规划已关闭。请在剧项目中逐集新建并自己填写本集剧情。"}), 410

@app.route('/api/series/<series_id>/episode/<int:episode>/idea', methods=['GET'])
def api_series_episode_idea(series_id, episode):
    s = load_series(series_id)
    if not s:
        return jsonify({"ok": False, "msg": "剧项目不存在"}), 404
    return jsonify({"ok": False, "msg": "本集剧情由你自己填写，不再从AI整季规划生成。"}), 410

@app.route('/api/series/<series_id>/batch/run')
def api_series_batch_run(series_id):
    """V3.5不再按整季规划批量生成。"""
    return jsonify({"ok": False, "msg": "整季批量生成已关闭，请逐集创作和生成。"}), 410

@app.route('/api/project/<pid>/review', methods=['GET'])
def api_project_reviews(pid):
    p = load_project(pid)
    if not p:
        return jsonify({"ok": False, "msg": "项目不存在"}), 404
    reviews = p.get('reviews', {})
    vals = [r.get('score') for r in reviews.values() if isinstance(r, dict) and isinstance(r.get('score'), (int,float))]
    avg = round(sum(vals)/len(vals), 1) if vals else None
    return jsonify({"ok": True, "reviews": reviews, "average_score": avg})

@app.route('/api/project/<pid>/shot/<int:index>/review', methods=['POST'])
def api_review_one_shot(pid, index):
    p = load_project(pid)
    if not p:
        return jsonify({"ok": False, "msg": "项目不存在"}), 404
    shot_meta = next((s for s in (p.get('script') or {}).get('shots', []) if int(s.get('index',0)) == index), None)
    result = next((s for s in p.get('shots', []) if int(s.get('index',0)) == index), None)
    if not shot_meta or not result or not result.get('path'):
        return jsonify({"ok": False, "msg": "该镜头尚无可审片视频"}), 400
    refs = [r if os.path.isabs(r) else os.path.join(BASE_DIR, r) for r in result.get('refs', [])]
    old_cfg = project_render_config(p)
    # 手动审片无论全局开关如何都执行，同时沿用该项目自身配置
    set_runtime_config({**old_cfg, "auto_review": True})
    video_path = result.get('path')
    if video_path and not os.path.isabs(video_path):
        video_path = _safe_join_under(BASE_DIR, video_path)
    try:
        review, err = review_shot_video(shot_meta, video_path, refs)
    finally:
        clear_runtime_config()
    if not review:
        return jsonify({"ok": False, "msg": err or "审片失败"}), 500
    save_shot_review(pid, index, review)
    return jsonify({"ok": True, "review": review})


from infrastructure.episode_export import register_episode_export
register_episode_export(app, load_series, _series_episode_status, OUTPUTS_DIR, find_ffmpeg)
from infrastructure.jianying_export import register_jianying_export
register_jianying_export(app, load_series, _series_episode_status, load_project, OUTPUTS_DIR)

from infrastructure.image_inspiration import register_image_inspiration
register_image_inspiration(app, lambda *args, **kwargs: llm_chat(*args, **kwargs),
                           lambda raw: GENERATION_REFERENCES.save(raw, runtime_config().get("_owner_id")))

if os.environ.get('SHORT_DRAMA_MULTIUSER', '1') == '1':
    from team.platform import TeamPlatform
    MULTIUSER = TeamPlatform(app, globals(), BASE_DIR)
    MULTIUSER.migrate_existing()



from core.reference_sync import register_reference_sync
register_reference_sync(globals())

if __name__ == '__main__':
    try:
        from waitress import serve
    except ImportError:
        print("[X] 缺少 Waitress 正式服务器，请运行 start_fixed.bat，或执行: python -m pip install waitress")
        sys.exit(1)

    service_port = int(os.environ.get('SHORT_DRAMA_PORT', '7860'))
    # 端口预检：同一端口已有服务时不重复拉起，避免多个实例抢端口导致前端事件错乱。
    import socket
    _port_used = False
    try:
        _s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        _s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        _s.bind(('0.0.0.0', service_port))
        _s.close()
    except OSError:
        _port_used = True
    if _port_used:
        print("=" * 50)
        print(f"  智创 · 已检测到 {service_port} 端口上已有服务在运行")
        print("  为避免多实例抢端口导致异常，本次不会重复启动，请直接访问该地址")
        print("=" * 50)
        sys.exit(0)
    admin_port = int(os.environ.get('SHORT_DRAMA_ADMIN_PORT', '7861'))
    admin_server = None
    if MULTIUSER:
        from waitress import create_server
        from team.admin_portal import AdminListener
        # Bind before starting any workers: a busy admin port must fail visibly.
        admin_server = create_server(AdminListener(app), host='0.0.0.0', port=admin_port, threads=8)
    migration = 项目存储.migrate_existing()
    print(f"[项目目录迁移] {json.dumps(migration, ensure_ascii=False)}")
    diagnostics = startup_diagnostics()
    print(f"[自检] {'通过' if diagnostics['ready'] else '存在问题'}: {json.dumps(diagnostics['checks'], ensure_ascii=False)}")
    NODE_MONITOR.start(monitored_nodes)
    recover_render_queue_on_startup()
    threading.Thread(target=_render_receipt_recovery_loop, name='render-receipt-recovery', daemon=True).start()
    print("=" * 50)
    print("  智创 · 全自动短剧生成系统（自包含整合包）")
    print(f"  访问: http://0.0.0.0:{service_port}（局域网请使用本机局域网 IP）")
    print("=" * 50)
    threading.Timer(1.5, lambda: webbrowser.open(f'http://127.0.0.1:{service_port}')).start()
    if admin_server:
        threading.Thread(target=admin_server.run, name='admin-http', daemon=True).start()
        print(f"  管理后台: http://0.0.0.0:{admin_port}/admin/", flush=True)
    serve(app, host='0.0.0.0', port=service_port, threads=16, channel_timeout=14400)
