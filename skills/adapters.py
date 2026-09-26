"""把现有 app.py 能力注册为可被 Agent 调用的 Skills。

采用延迟导入，避免 app.py 启动时出现循环导入。实际执行技能时才读取旧模块中的函数。
"""

import copy
import json
import re

from core.skill_result import 技能结果
from agents.script.skills.wardrobe import 检查镜头服装, 补全镜头服装


def _调用函数(函数名, 参数):
    import app
    函数 = getattr(app, 函数名, None)
    if not callable(函数):
        return 技能结果(False, 错误=f"旧系统函数不存在：{函数名}")
    try:
        return 技能结果(True, 数据=函数(**(参数 or {})))
    except Exception as 异常:
        return 技能结果(False, 错误=str(异常))

def _调用合成(上下文, 参数):
    """把项目上下文注入旧版合成函数，保留 Agent 的技能调用边界。"""
    参数 = dict(参数 or {})
    参数.setdefault("proj", 上下文 or {})
    参数.setdefault("send", lambda _event, _payload=None: None)
    结果 = _调用函数("resynth_pipeline", 参数)
    if 结果.成功 and 结果.数据 is False:
        return 技能结果(False, 数据=结果.数据, 错误="合成管线未生成成片")
    return 结果

def _调用渲染单镜(上下文, 参数):
    """调用现有单镜头渲染闭环，并把异常转换成技能失败。"""
    import app
    参数 = dict(参数 or {})
    参数.setdefault("project", 上下文 or {})
    try:
        return 技能结果(True, 数据=app.render_project_shot(**参数))
    except Exception as 异常:
        return 技能结果(False, 错误=str(异常))

def _提示词结果(结果):
    """统一旧版提示词函数的 (prompt, error) 返回格式。"""
    if isinstance(结果, tuple):
        prompt = error = None
        if len(结果) > 0:
            prompt = 结果[0]
        if len(结果) > 1:
            error = 结果[1]
        if not prompt:
            return 技能结果(False, 错误=error or "提示词生成失败")
        return 技能结果(True, 数据={"prompt": str(prompt), "error": error})
    if isinstance(结果, str) and 结果.strip():
        return 技能结果(True, 数据={"prompt": 结果.strip(), "error": None})
    return 技能结果(False, 错误="提示词生成函数返回空结果")


def _调用提示词生成(_上下文, 参数):
    import app
    参数 = dict(参数 or {})
    shot = 参数.get("shot")
    if not isinstance(shot, dict):
        return 技能结果(False, 错误="缺少镜头数据")
    try:
        from infrastructure.asset_gate import require_assets
        if (_上下文 or {}).get('id'):
            current = app.load_project(_上下文['id']) or _上下文
            require_assets(current, app.BASE_DIR, bool(app.runtime_config().get('manual_mode')))
        结果 = app.gen_shot_h3_prompt(
            shot,
            参数.get("ref_paths") or [],
            参数.get("audio_roles") or {},
        )
        return _提示词结果(结果)
    except Exception as 异常:
        return 技能结果(False, 错误=str(异常))


def _调用提示词修复(_上下文, 参数):
    import app
    参数 = dict(参数 or {})
    shot = 参数.get("shot")
    if not isinstance(shot, dict):
        return 技能结果(False, 错误="缺少镜头数据")
    constraints = "；".join(str(item) for item in (参数.get("constraints") or []) if item)
    if constraints:
        shot = copy.deepcopy(shot)
        shot["action"] = (
            f"{shot.get('action', '')}\n"
            f"【提示词智能体必须修复以下问题】{constraints}"
        )
    try:
        from infrastructure.asset_gate import require_assets
        if (_上下文 or {}).get('id'):
            current = app.load_project(_上下文['id']) or _上下文
            require_assets(current, app.BASE_DIR, bool(app.runtime_config().get('manual_mode')))
        结果 = app.gen_shot_h3_prompt(
            shot,
            参数.get("ref_paths") or [],
            参数.get("audio_roles") or {},
        )
        return _提示词结果(结果)
    except Exception as 异常:
        return 技能结果(False, 错误=str(异常))


def _检查台词完整性(_上下文, 参数):
    prompt = str((参数 or {}).get("prompt") or "")
    shot = (参数 or {}).get("shot") or {}
    missing = []
    untagged = []
    for dialogue in shot.get("dialogue") or []:
        line = str(dialogue.get("line") or "").strip()
        if not line:
            continue
        if line not in prompt:
            missing.append(line)
        if not re.search(r"<d>\s*\[Chinese\]\s*" + re.escape(line) + r"\s*</d>", prompt):
            untagged.append(line)
    from infrastructure.dialogue_boundary import dialogue_boundary_errors
    boundary_errors = dialogue_boundary_errors(prompt)
    return 技能结果(True, 数据={
        "对白边界问题": boundary_errors,
        "通过": not missing and not untagged and not boundary_errors,
        "缺失台词": missing,
        "未标记台词": untagged,
    })


def _检查动作连续性(_上下文, 参数):
    prompt = str((参数 or {}).get("prompt") or "")
    problems = []
    required = (
        "integrated_multimodal_description",
        "overall_soundscape",
        "non_diegetic_music",
    )
    for field in required:
        if field not in prompt:
            problems.append(f"缺少字段 {field}")
    if "[Shot 1]" not in prompt:
        problems.append("缺少 [Shot 1] 镜头段")
    # 旧管线允许多种合法的英文运镜写法；不要因为没有固定短语
    # "The camera" 就把已经具备镜头运动的提示词重新改写。
    camera_markers = (
        "The camera", "camera cuts", "camera pushes", "camera pulls",
        "camera tracks", "camera arcs", "camera pans", "camera tilts",
        "camera holds", "camera moves", "camera follows",
    )
    if not any(marker.lower() in prompt.lower() for marker in camera_markers):
        problems.append("缺少有效运镜描述")
    if re.search(r"慢动作|慢镜头|升格|子弹时间|slow\s*-?\s*motion|slo-?mo", prompt, re.I):
        problems.append("包含禁止的慢放描述")
    return 技能结果(True, 数据={"通过": not problems, "问题": problems})


def _检查角色边界(_上下文, 参数):
    prompt = str((参数 or {}).get("prompt") or "")
    ref_count = int((参数 or {}).get("ref_count") or 0)
    numbers = [int(value) for value in re.findall(r"<Picture\s+(\d+)>", prompt)]
    problems = []
    if ref_count <= 0:
        problems.append("没有参考图")
    if any(number < 1 or number > ref_count for number in numbers):
        problems.append("Picture 编号超出实际参考图范围")
    if len(set(numbers)) > 9:
        problems.append("Picture 参考图超过 9 张")
    return 技能结果(True, 数据={"通过": not problems, "问题": problems, "引用编号": sorted(set(numbers))})


def _调用审片报告(_上下文, 参数):
    import app
    参数 = dict(参数 or {})
    try:
        report, error = app.review_shot_video(
            参数.get("shot") or {},
            参数.get("video_path") or "",
            参数.get("ref_paths") or [],
        )
        if not report:
            return 技能结果(False, 错误=error or "审片没有返回报告")
        return 技能结果(True, 数据=report)
    except Exception as 异常:
        return 技能结果(False, 错误=str(异常))


def _检查审片报告(_上下文, 参数):
    report = (参数 or {}).get("report") or {}
    problems = []
    if not isinstance(report, dict):
        return 技能结果(True, 数据={"通过": False, "问题": ["审片报告不是对象"]})
    try:
        score = int(float(report.get("score")))
    except (TypeError, ValueError):
        problems.append("缺少有效总分")
        score = 0
    if not 0 <= score <= 100:
        problems.append("总分不在0到100范围内")
    if not isinstance(report.get("problems", []), list):
        problems.append("problems必须是列表")
    if not str(report.get("fix_prompt_addendum") or "").strip() and score < 72:
        problems.append("低分报告缺少修复约束")
    return 技能结果(True, 数据={"通过": not problems, "问题": problems, "score": score})


def _生成修复约束(_上下文, 参数):
    report = (参数 or {}).get("report") or {}
    分类 = (参数 or {}).get("分类") or []
    fix = str(report.get("fix_prompt_addendum") or "").strip()
    规则 = {
        "角色一致性": "锁定人物脸型、发型、年龄和体型，禁止串脸；服装遵循本镜 wardrobe，同一场连续戏保持连续，跨时间或活动合理换装。不得以角色一致性为由改回参考图服装。",
        "动作连续性": "强化首帧即运动和连续动作链，避免静帧、僵硬、幻灯片观感。",
        "构图运镜": "明确主体、景别和主运镜，避免主体出画、构图混乱或镜头无效移动。",
        "场景连续性": "锁定场景结构、光线和关键背景物，禁止空间跳变和背景漂移。",
        "物体细节": "减少手指、肢体和道具畸变，明确受力关系与物体形状。",
        "台词匹配": "让说话角色与台词、口型和声音严格对应，禁止错人说话。",
    }
    clauses = [规则[item] for item in 分类 if item in 规则]
    if fix:
        clauses.insert(0, fix)
    return 技能结果(True, 数据={
        "修复约束": " ".join(dict.fromkeys(clauses)),
        "分类": list(dict.fromkeys(分类)),
    })


def _调用剧本生成(_上下文, 参数):
    import app
    参数 = dict(参数 or {})
    idea = str(参数.get("idea") or 参数.get("故事创意") or "").strip()
    if not idea:
        return 技能结果(False, 错误="缺少故事创意")
    try:
        system_prompt = app.build_script_prompt(参数.get("series_ctx"), idea)
        if 参数.get("full_script_import"):
            system_prompt += (
                "\n\n【完整剧本导入模式】用户提供的是待制作的完整原剧本。忠实保留原有剧情顺序、人物关系、事件结果和所有对白原句，"
                "只把剧本拆解、映射到规定 JSON 字段；不得续写、删改、压缩或另行创作剧情。结构字段不足时仅补充不改变原意的拍摄信息。"
                "镜头数量由原剧本自然决定，不得为了配置数量删改剧情。"
            )
        content, error = app.llm_chat([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": idea},
        ], max_tokens=12000 if 参数.get("full_script_import") else 8000, temperature=0.2 if 参数.get("full_script_import") else 0.65)
        if not content:
            return 技能结果(False, 错误=error or "剧本模型没有返回内容")
        script = app.parse_json_from_text(content)
        if not isinstance(script, dict):
            return 技能结果(False, 错误="剧本模型返回的不是JSON对象")
        return 技能结果(True, 数据={"script": script, "raw": content})
    except Exception as 异常:
        return 技能结果(False, 错误=str(异常))


def _调用剧本修复(_上下文, 参数):
    import app
    参数 = dict(参数 or {})
    idea = str(参数.get("idea") or "").strip()
    script = 参数.get("script")
    problems = "；".join(str(item) for item in (参数.get("problems") or []) if item)
    if not idea or not isinstance(script, dict):
        return 技能结果(False, 错误="缺少故事创意或待修复剧本")
    try:
        system_prompt = app.build_script_prompt(参数.get("series_ctx"), idea)
        if 参数.get("full_script_import"):
            system_prompt += (
                "\n\n【完整剧本导入修复模式】只修复 JSON 结构、字段缺失和引用错误，必须逐字保留原剧情、事件顺序及已有对白；"
                "不得重写、删减或扩写故事内容。镜头数量遵循输入剧本，不按配置数量增删。"
            )
        content, error = app.llm_chat([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(script, ensure_ascii=False)},
            {"role": "assistant", "content": json.dumps(script, ensure_ascii=False)},
            {"role": "user", "content": f"请修复以下问题：{problems}。只输出完整JSON，不要解释。"},
        ], max_tokens=8000, temperature=0.35)
        fixed = app.parse_json_from_text(content or "")
        if not isinstance(fixed, dict):
            return 技能结果(False, 错误=error or "剧本修复没有返回有效JSON")
        return 技能结果(True, 数据={"script": fixed, "raw": content})
    except Exception as 异常:
        return 技能结果(False, 错误=str(异常))


def _检查镜头数量(_上下文, 参数):
    script = (参数 or {}).get("script") or {}
    shots = script.get("shots") or []
    expected = (参数 or {}).get("expected")
    problems = []
    if not shots:
        problems.append("缺少shots")
    if expected not in (None, "", "auto"):
        try:
            if len(shots) != int(expected):
                problems.append(f"镜头数量应为{int(expected)}，实际为{len(shots)}")
        except (TypeError, ValueError):
            pass
    return 技能结果(True, 数据={"通过": not problems, "问题": problems, "数量": len(shots)})


def _检查角色场景引用(_上下文, 参数):
    script = (参数 or {}).get("script") or {}
    problems = []
    chars = {item.get("name") for item in script.get("characters") or [] if isinstance(item, dict)}
    scenes = {item.get("name") for item in script.get("scenes") or [] if isinstance(item, dict)}
    props = {item.get("name") for item in script.get("props") or [] if isinstance(item, dict)}
    for shot in script.get("shots") or []:
        for name in shot.get("characters") or []:
            if name not in chars:
                problems.append(f"镜头{shot.get('index')}引用未定义角色：{name}")
        scene = shot.get("scene")
        if scene and scene not in scenes:
            problems.append(f"镜头{shot.get('index')}引用未定义场景：{scene}")
        for name in shot.get("props") or []:
            if name not in props:
                problems.append(f"镜头{shot.get('index')}引用未定义道具：{name}")
    return 技能结果(True, 数据={"通过": not problems, "问题": problems})


def _检查分镜结构(_上下文, 参数):
    import app
    script = (参数 or {}).get("script") or {}
    problems = []
    for pos, shot in enumerate(script.get("shots") or [], start=1):
        if not isinstance(shot, dict):
            problems.append(f"第{pos}个镜头不是对象")
            continue
        if not str(shot.get("action") or "").strip():
            problems.append(f"镜头{pos}缺少动作")
        try:
            duration = int(shot.get("duration", 8))
            if duration < 8 or duration > 15:
                problems.append(f"镜头{pos}时长不在8~15秒")
        except (TypeError, ValueError):
            problems.append(f"镜头{pos}时长无效")
        if not str(shot.get("camera") or "").strip():
            problems.append(f"镜头{pos}缺少运镜")
        slow_match = app.SLOW_MO_RE.search(str(shot.get("action") or "") + "\n" + str(shot.get("camera") or ""))
        if slow_match:
            problems.append(f"镜头{pos}包含明确的慢放或冻结画面描述：{slow_match.group(0)}")
    return 技能结果(True, 数据={"通过": not problems, "问题": problems})


def _生成资产(_上下文, 参数):
    result = _调用函数("gen_asset_image", {
        "kind": 参数.get("kind"),
        "name": 参数.get("name"),
        "desc": 参数.get("desc") or 参数.get("description") or 参数.get("appearance"),
        "style": 参数.get("style", "电影写实"),
        "characters": 参数.get("characters") or [],
        "prompt": 参数.get("prompt"),
    })
    if not result.成功:
        return result
    value = result.数据
    if isinstance(value, tuple):
        path = value[0] if len(value) > 0 else None
        prompt = value[1] if len(value) > 1 else ""
        error = value[2] if len(value) > 2 else None
        if error or not path:
            return 技能结果(False, 错误=error or "资产生成没有返回文件")
        return 技能结果(True, 数据={"path": path, "prompt": prompt})
    return result


def _检查资产文件(_上下文, 参数):
    import os
    path = str((参数 or {}).get("path") or "")
    return 技能结果(True, 数据={
        "通过": bool(path and os.path.isfile(path) and os.path.getsize(path) > 0),
        "path": path,
    })


def _读取项目状态(上下文, _参数):
    project = 上下文 if isinstance(上下文, dict) else {}
    shots = project.get("shots") or []
    script_shots = (project.get("script") or {}).get("shots") or []
    return 技能结果(True, 数据={
        "id": project.get("id", ""),
        "has_script": bool(project.get("script")),
        "script_confirmed": bool(project.get("script_confirmed", True)),
        "asset_count": len(project.get("assets") or {}),
        "script_shot_count": len(script_shots),
        "rendered_shot_count": len([item for item in shots if item.get("video_url") and not item.get("error")]),
        "failed_shot_count": len([item for item in shots if item.get("error")]),
        "has_final": bool(project.get("final")),
    })


def _处理失败(_上下文, 参数):
    errors = [str(item) for item in (参数 or {}).get("errors") or [] if item]
    return 技能结果(True, 数据={
        "动作": "转人工" if len(errors) >= 3 else "重试",
        "原因": errors,
    })


def 注册现有技能(注册表):
    """注册旧流程能力的适配入口，逐步替换固定流程时无需改变 Agent 接口。"""
    技能 = {
        "调用大语言模型": lambda _上下文, 参数: _调用函数("llm_chat", 参数),
        "生成资产图片": lambda _上下文, 参数: _调用函数("gen_asset_image", 参数),
        "生成 H3 提示词": _调用提示词生成,
        "修复提示词": _调用提示词修复,
        "解析故事创意": _调用剧本生成,
        "生成剧本结构": _调用剧本生成,
        "修复剧本 JSON": _调用剧本修复,
        "检查镜头数量": _检查镜头数量,
        "检查角色引用": _检查角色场景引用,
        "检查场景引用": _检查角色场景引用,
        "检查剧情节奏": _检查分镜结构,
        "检查镜头服装": 检查镜头服装,
        "补全镜头服装": 补全镜头服装,
        "拆分镜头": lambda _上下文, 参数: 技能结果(True, 数据={"script": 参数.get("script")}),
        "检查镜头连续性": _检查分镜结构,
        "检查景别机位": _检查分镜结构,
        "检查资产引用": _检查角色场景引用,
        "调整镜头时长": _检查分镜结构,
        "生成角色参考图": lambda _上下文, 参数: _生成资产(_上下文, {**参数, "kind": "char"}),
        "生成场景参考图": lambda _上下文, 参数: _生成资产(_上下文, {**参数, "kind": "scene"}),
        "生成道具参考图": lambda _上下文, 参数: _生成资产(_上下文, {**参数, "kind": "prop"}),
        "保存资产": lambda _上下文, 参数: 技能结果(True, 数据=参数),
        "检查资产文件": _检查资产文件,
        "读取项目状态": _读取项目状态,
        "判断下一步动作": lambda _上下文, 参数: 技能结果(True, 数据=参数 or {}),
        "发送协同任务": lambda _上下文, 参数: 技能结果(True, 数据=参数 or {}),
        "处理失败": _处理失败,
        "检查台词完整性": _检查台词完整性,
        "检查动作连续性": _检查动作连续性,
        "检查角色边界": _检查角色边界,
        "输出审片报告": _调用审片报告,
        "检查审片报告": _检查审片报告,
        "生成修复约束": _生成修复约束,
        "MiniMax 武戏提示词": lambda _上下文, 参数: _调用函数("获取武戏提示词规则", 参数),
        "二次元打戏提示词": lambda _上下文, 参数: _调用函数("获取二次元打戏规则", 参数),
        "MiniMax 文戏提示词": lambda _上下文, 参数: _调用函数("获取文戏提示词规则", 参数),
        "生成视频": lambda _上下文, 参数: _调用函数("gen_video_r2v", 参数),
        "渲染单镜": _调用渲染单镜,
        "审片视频": lambda _上下文, 参数: _调用函数("review_shot_video", 参数),
        "合成成片": _调用合成,
        "提取图片文字": lambda _上下文, 参数: _调用函数("提取图片文字", 参数),
    }
    for 名称, 函数 in 技能.items():
        注册表.注册(名称, 函数)
    return 注册表
