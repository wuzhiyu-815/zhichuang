"""Agent continuity planning, visual handoffs and conservative boundary review."""
import copy
import hashlib
import json
import os
import re
import subprocess
import unicodedata

from infrastructure.shot_continuity import validate_continuity, requires_previous_frame, apply_continuity_intro

LEGACY_RULES = '''你是镜头连续性规划师。只返回一个扁平JSON对象，所有值都是字符串，禁止嵌套对象或数组。
必须包含action,transition,reason,camera_mode,start_location,start_characters,start_props,end_location,end_characters,end_props。
对白原文、顺序和说话人以dialogue数组为唯一依据；action如与之矛盾，必须修正action中的发言顺序。
action保留当前镜头事件、人物、台词含义、服装和道具，补齐起身、转身、换手、放物等必要过渡；只返回本镜完整可拍摄动作，不拆镜、不续写，不使用占位文字，不重复前镜已完成动作。
transition为opening/continuous/cut；首镜opening，后续不允许opening。同一时空连续动作必须continuous；cut表示可以独立建立首帧的新渲染组：换场、时间跳转、空镜、插入镜头，或同场景中动作已经结束且下一镜能用明确首态独立建立的剪辑点。不能仅因同场景或相邻镜号就判continuous；换机位本身也不足以判cut。接续进行中的动作、交接道具或必须匹配前镜实际姿势的镜头必须continuous。reason必须说明是否依赖前镜实际尾帧及依据，不能为了并行破坏动作衔接。
camera_mode为same/changed，只有真正延续原机位才same。
start/end的location使用固定空间地标；characters字符串按本名描述所有角色的位置/姿势/朝向/双手/情绪/服装/动作进度；props字符串按名称描述道具数量、位置、外观、包装、覆盖与开合，无道具时描述环境物件。
previous_shot是已验收前镜。连续镜start由程序精确继承前镜end，三个start字段输出空字符串；必须根据前镜end补齐本镜动作过渡并规划end。cut和opening必须完整填写start与end。未入镜不等于物品消失，不能无故重置衣着、持物、左右手、姿势或位置。
'''

HANDOFF_RULES = '''采用宽松的剪辑衔接策略，把剧情连续和渲染依赖分开：
continuous只表示同一剧情的状态延续，并不默认依赖上一镜实际尾帧。
handoff_mode为none/state/frame；opening和cut为none；continuous通常为state，只有确需实际尾帧才为frame。
state适用：同场景对白轮次、反应镜头、换景别或换机位后的独立起拍、一个动作已经完成后的新动作、可用明确姿势/站位/衣着/持物描述复现的开场。即使同场、同一场打斗、时间连续，也优先拆成可独立起拍的state镜头。
frame仅用于真正不可拆分的跨镜瞬间：同一动作尚在半途且需精确匹配肢体接触、交接物仍在两人之间、持续碰撞/旋转/腾空轨迹跨越剪辑边界，或用户明确要求逐帧无缝接续。
“上一镜站着/持刀/面朝门，本镜冲出/挥刀”是state，不得因为接着动作或前镜有姿势就判frame。
不能只凭“同一时空”“连续打斗”“接上一镜”“要保持人物一致”判frame；reason必须指出不可拆分的具体动作和为什么文字首态不足。无法指出时选state。
cut可用于换场、时间跳转、空镜、插入镜头，以及同场景可独立建立的剪辑点。每镜都要保持剧情因果，不能为了并行删动作、改台词或改写故事。'''

RULES = '\n'.join(line for line in LEGACY_RULES.splitlines() if not line.startswith('transition为'))
RULES += '\ntransition为opening/continuous/cut；首镜opening，后续不允许opening。必须额外返回handoff_mode字符串。\n' + HANDOFF_RULES
PLAN_FIELDS = ('action', 'transition', 'reason', 'camera_mode', 'handoff_mode',
               'start_location', 'start_characters', 'start_props',
               'end_location', 'end_characters', 'end_props')
RULES += (f'\n必须返回全部{len(PLAN_FIELDS)}个字段：' + ','.join(PLAN_FIELDS)
          + '。opening和cut的三个start字段必须是非空字符串；只有continuous允许start为空。'
          '空镜也必须明确填写人物状态为“无人入镜”，不可省略characters字段或返回数组/null。')


def enabled(project):
    return (project.get('render_config') or {}).get('continuity_enabled', True)


def source_signature(script, rules=None):
    clean = copy.deepcopy(script)
    for shot in clean.get('shots', []):
        shot.pop('continuity', None)
    return hashlib.sha256(json.dumps({'script': clean, 'planning_rules': RULES if rules is None else rules}, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def upgrade_handoffs(engine, script):
    """Reclassify old dependencies without changing accepted actions or boundary states."""
    planned = copy.deepcopy(script)
    for offset, shot in enumerate(planned['shots']):
        plan = shot['continuity']
        if plan['transition'] != 'continuous':
            plan['handoff_mode'] = 'none'
            continue
        error = ''
        for _ in range(2):
            text, error = engine.llm_chat([
                {'role': 'system', 'content': HANDOFF_RULES + '\n仅复核当前镜头是否依赖前镜实际尾帧。旧reason可能过于严格，须重新判断。只返回JSON对象，含handoff_mode（state或frame）和reason（具体依据）。不得修改剧情或首尾状态。'},
                {'role': 'user', 'content': json.dumps({'previous_shot': planned['shots'][offset-1], 'shot': shot}, ensure_ascii=False)},
            ], max_tokens=800, temperature=.1, timeout=240, response_format={'type': 'json_object'})
            try:
                result = engine.parse_json_from_text(text or '')
            except (ValueError, TypeError):
                result = None
            if (isinstance(result, dict) and result.get('handoff_mode') in ('state', 'frame')
                    and isinstance(result.get('reason'), str) and result['reason'].strip()):
                plan.update(handoff_mode=result['handoff_mode'], reason=result['reason'].strip())
                break
        else:
            raise ValueError(f'第{shot["index"]}镜并行衔接复核失败：' + (error or '返回格式无效'))
    return planned


def _decode_flat_plan(result, index):
    # LLMs occasionally surround enum values with whitespace or use casing;
    # normalize before deciding whether inherited start fields are required.
    if isinstance(result.get('transition'), str):
        result['transition'] = result['transition'].strip().lower()
    if isinstance(result.get('camera_mode'), str):
        result['camera_mode'] = result['camera_mode'].strip().lower()
    if isinstance(result.get('handoff_mode'), str):
        result['handoff_mode'] = result['handoff_mode'].strip().lower()
    required = ('action', 'transition', 'reason', 'camera_mode', 'end_location', 'end_characters', 'end_props')
    if result.get('transition') != 'continuous':
        required += ('start_location', 'start_characters', 'start_props')
    required += ('handoff_mode',)
    for key in required:
        if not isinstance(result.get(key), str) or not result[key].strip():
            raise ValueError(f'连续性计划缺少有效字段：{key}')
    if result['camera_mode'] not in ('same', 'changed'):
        raise ValueError('连续性计划机位类型无效')
    if result['handoff_mode'] not in ('none', 'state', 'frame'):
        raise ValueError('连续性计划衔接依赖类型无效')
    plan = {key: result[key] for key in ('transition', 'reason', 'camera_mode', 'handoff_mode')}
    for boundary in ('start', 'end'):
        if boundary == 'start' and result['transition'] == 'continuous':
            continue
        plan[boundary] = {key: result[f'{boundary}_{key}'] for key in ('location', 'characters', 'props')}
    return {'index': index, 'action': result['action'], 'continuity': plan}


def _repair_start(engine, result, context):
    """Repair only missing independent opening state, without changing events."""
    if not isinstance(result, dict) or result.get('transition', '').strip().lower() not in ('opening', 'cut'):
        return result
    fields = ('start_location', 'start_characters', 'start_props')
    missing = [key for key in fields if not isinstance(result.get(key), str) or not result[key].strip()]
    if not missing:
        return result
    text, _ = engine.llm_chat([
        {'role': 'system', 'content': '只修复当前镜头缺失的开场状态。依据原镜头场景、动作和前镜状态，返回JSON，仅含start_location、start_characters、start_props三个非空字符串。位置用明确空间地标，人物写本名、站位和姿态，道具写位置和持有者。无人时写无人入镜，无道具时描述已有环境物件。开场必须在本镜动作发生之前，不得复制结尾状态，不得改变剧情或把cut改为continuous，不编造无依据的新地点或物品。'},
        {'role': 'user', 'content': json.dumps({'context': context, 'plan': result, 'missing': missing}, ensure_ascii=False)},
    ], max_tokens=1200, temperature=.1, timeout=240, response_format={'type': 'json_object'})
    patch = engine.parse_json_from_text(text or '')
    repaired = copy.deepcopy(result)
    if isinstance(patch, dict):
        for key in missing:
            if isinstance(patch.get(key), str) and patch[key].strip():
                repaired[key] = patch[key].strip()
    return repaired


def plan_script(engine, script, cached_signature=None):
    if cached_signature == source_signature(script) and not validate_continuity(script.get('shots', [])):
        return script
    if (cached_signature == source_signature(script, LEGACY_RULES)
            and not validate_continuity(script.get('shots', []))):
        return upgrade_handoffs(engine, script)
    planned = copy.deepcopy(script)
    # Bound JSON nesting/output size; preserve the accepted handoff across batches.
    for offset in range(0, len(script['shots']), 1):
        original = script['shots'][offset:offset + 1]
        context = {k: v for k, v in script.items() if k != 'shots'}
        context['shots'] = original
        context['previous_shot'] = planned['shots'][offset - 1] if offset else None
        errors = ''
        messages = [
            {'role': 'system', 'content': RULES},
            {'role': 'user', 'content': json.dumps(context, ensure_ascii=False)
             + f'\n只规划当前第{original[0]["index"]}镜；返回以下{len(PLAN_FIELDS)}个扁平字符串字段：'
             + ','.join(PLAN_FIELDS) + '。不返回shots数组。'},
        ]
        for attempt in range(2):
            text, error = engine.llm_chat(copy.deepcopy(messages), max_tokens=4000, temperature=.1,
                                          timeout=600, response_format={'type': 'json_object'})
            try:
                result = engine.parse_json_from_text(text or '')
                if isinstance(result, dict) and 'shots' not in result:
                    if attempt == 1:
                        result = _repair_start(engine, result, context)
                    result = {'shots': [_decode_flat_plan(result, original[0]['index'])]}
                if not isinstance(result, dict) or not isinstance(result.get('shots'), list):
                    raise ValueError(error or '模型未返回完整有效的连续性JSON')
                plans = result['shots']
                if [s['index'] for s in plans] != [s['index'] for s in original]:
                    raise ValueError('镜头编号、数量或顺序被改变')
                candidate = copy.deepcopy(planned)
                for shot, plan in zip(candidate['shots'][offset:offset + 1], plans):
                    shot['continuity'] = copy.deepcopy(plan['continuity'])
                    if offset and shot['continuity'].get('transition') == 'continuous':
                        previous = candidate['shots'][offset - 1]
                        shot['continuity']['start'] = copy.deepcopy(previous['continuity']['end'])
                        shot['continuity']['previous_index'] = previous['index']
                    if not isinstance(plan.get('action'), str) or not plan['action'].strip() or plan['action'].strip() == '原动作补全必要过渡':
                        raise ValueError('缺少完整动作，不能使用模板占位文字')
                    shot['action'] = plan['action']
                    if shot['continuity'].get('handoff_mode') not in ('none', 'state', 'frame'):
                        raise ValueError('连续性计划缺少有效handoff_mode')
                    if requires_previous_frame(shot) and len(shot.get('characters', [])) + bool(shot.get('scene')) + len(shot.get('props', [])) > 8:
                        raise ValueError('连续镜原参考图最多8张，须为末帧保留名额')
                errors = '；'.join(validate_continuity(candidate['shots'][:offset + len(original)]))
                if errors:
                    raise ValueError(errors)
                planned = candidate
                break
            except (ValueError, KeyError, TypeError, AttributeError) as exc:
                errors = str(exc) or error or '连续性计划无效'
                if text:
                    messages.append({'role': 'assistant', 'content': text})
                messages.append({'role': 'user', 'content': '校验错误：' + errors
                    + '\n请修复上次结果，检查并补齐全部字段，返回完整JSON，不只返回修正字段。'
                    'opening/cut必须明确描述开场人物位置、姿势、持物等状态；'
                    '无人入镜时明确写“无人入镜”。不得用结束状态代替开始状态。'})
        else:
            raise ValueError(f'镜头交接规划失败（第{original[0]["index"]}镜起）：' + errors)
    return planned


def previous_video(engine, project, shot):
    plan = shot.get('continuity') or {}
    if not requires_previous_frame(shot):
        return None
    prev = next((s for s in project.get('shots', []) if s.get('index') == plan.get('previous_index')), {})
    path = prev.get('path')
    if not path or prev.get('error') or prev.get('reference_video_stale') or prev.get('continuity_stale'):
        raise ValueError('连续镜头须先完成上一镜，且上一镜参考图不能过期')
    path = path if os.path.isabs(path) else os.path.join(engine.BASE_DIR, path)
    if not os.path.isfile(path):
        raise ValueError('上一镜视频文件不存在')
    return path


def boundary_frame(engine, path, tail):
    stamp = f'{path}:{os.stat(path).st_mtime_ns}:{os.path.getsize(path)}:{tail}'
    name = hashlib.sha256(stamp.encode()).hexdigest()[:24] + '.jpg'
    directory = os.path.join(engine.REVIEWS_DIR, 'continuity')
    os.makedirs(directory, exist_ok=True)
    output = os.path.join(directory, name)
    if not os.path.isfile(output):
        seek = ['-sseof', '-0.15'] if tail else ['-ss', '0.15']
        subprocess.run([engine.find_ffmpeg() or 'ffmpeg', '-y', '-loglevel', 'error', *seek,
                        '-i', path, '-frames:v', '1', output], check=True, timeout=60,
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        if not os.path.isfile(output):
            raise ValueError('无法提取镜头交接帧')
    return output


def visual_handoff(engine, project, shot):
    path = previous_video(engine, project, shot)
    if not path:
        return None
    return boundary_frame(engine, path, True)


def check_prompt(engine, shot, prompt, frame=None, _repair_attempt=0):
    """Semantic preflight; never allow a repair to rewrite dialogue."""
    expected = [str(d.get('line', '')).strip() for d in shot.get('dialogue', []) if d.get('line')]
    # Only an explicitly marked supplemental/bridge shot may carry dialogue
    # that is written in its transition action rather than in the script's
    # canonical dialogue list. An ordinary silent shot must still reject any
    # spoken lines accidentally added by the prompt model.
    bridge_without_script_dialogue = bool(shot.get('is_bridge')) and not expected
    request = {'plan': shot.get('continuity'), 'action': shot.get('action'),
               'dialogue': shot.get('dialogue'), 'prompt': prompt}
    instructions = '''检查提示词是否保持交接首尾状态、空间地标、动作进度、左右手、服装、道具数量/包装/覆盖状态、台词顺序和说话人绑定。若附图，它是上一镜实际末帧，当前开场必须继承可见状态，不能重复转身/放物；不可见物品仍以身份与道具参考为准。换机位导致画面左右不同不等于换位。只返回JSON对象，含passed布尔值及issues问题列表。修正不得增加/删除/改写台词，不改变Picture编号。人物介绍和声线只在开头不朗读的设定中；发声严格两行<Subject N> (SN) says: 后换行<d>[Chinese]台词原文</d>。'''
    if bridge_without_script_dialogue:
        instructions += '\n这是补充衔接镜头，剧本dialogue为空；action中若包含过渡对白，视为用户对衔接动作的明确要求，可以保留，不要把它判定为台词不一致。'
    else:
        instructions += '\n对白原文、顺序和说话人以dialogue数组为唯一依据；action中的发言先后或回应措辞若与dialogue冲突，以dialogue为准，不得要求提示词恢复action中的错误顺序。'
    instructions += '\n本次只做检查，不输出prompt修复正文。只返回一个JSON对象，含passed布尔值和issues数组；最多3条互不重复的真实矛盾，每条不超过80字，不列出一致项。不因遮挡臆测道具消失，不要求重复已完成的动作。修复正文由下一次调用单独生成。'
    parts = [{'type': 'text', 'text': instructions + '\n' + json.dumps(request, ensure_ascii=False)}]
    if frame:
        parts += engine.load_image_parts([frame])
    result = None
    for attempt in range(2):
        messages = [{'role': 'user', 'content': parts}]
        if attempt:
            messages.append({'role': 'user', 'content': '上次报告格式无效。只返回完整JSON：{"passed":true,"issues":[]}，有真实矛盾时passed为false，issues最多3条简短描述。'})
        text, error = engine.llm_chat(messages, max_tokens=1200, temperature=.1, timeout=240,
                                      response_format={'type': 'json_object'})
        result = engine.parse_json_from_text(text or '')
        if isinstance(result, dict) and isinstance(result.get('passed'), bool):
            break
    if not isinstance(result, dict) or not isinstance(result.get('passed'), bool):
        raise ValueError(error or '衔接预审未返回有效报告')
    candidate = prompt if result['passed'] else result.get('prompt', '')
    if not result['passed'] and not candidate:
        # Some reviewers return only findings. Ask for the repair separately so
        # a long H3 prompt does not have to be escaped inside a JSON report.
        repair_instructions = ('修复H3提示词中的衔接问题。只输出完整提示词正文，不输出JSON或解释。'
            '台词原文、顺序和说话人必须以shot.dialogue为准，不能沿用错误提示词的顺序。'
            '保留Picture编号和三个H3字段。若对白顺序错误，连同说话人和对应画面段一起调整，重新安排递增时间戳，'
            '禁止只交换台词造成说话人错绑。每句台词必须由独立的<Subject N> (SN) says:行引出，下一行<d>[Chinese]原台词</d>。'
            '只补齐必要动作过渡，不重复已经完成的动作。')
        if bridge_without_script_dialogue:
            repair_instructions += ('这是明确标记的补充衔接镜头，shot.dialogue为空；原提示词中已经出现、且与action一致的<d>台词属于本镜过渡动作，'
                                    '必须原样保留并保留其说话人绑定，不能因为dialogue数组为空而删除或改写。')
        candidate, repair_error = engine.llm_chat([
            {'role': 'system', 'content': repair_instructions},
            {'role': 'user', 'content': json.dumps({'shot':shot,'issues':result.get('issues',[]),'original_prompt':prompt},ensure_ascii=False)},
        ], max_tokens=6000, temperature=.1, timeout=240)
        if not candidate:
            raise ValueError(repair_error or '衔接修复未返回提示词')
    from infrastructure.dialogue_boundary import dialogue_boundary_errors, normalize_dialogue_boundaries
    candidate = normalize_dialogue_boundaries(candidate)
    # Models occasionally add harmless spaces/newlines around the XML payload.
    # Compare the spoken text itself after removing wrapper whitespace, while
    # keeping every character inside the dialogue immutable.
    candidate = re.sub(r'(<d>\s*\[Chinese\])\s*', r'\1', candidate)
    candidate = re.sub(r'\s*(</d>)', r'\1', candidate)
    def _dialogue_compare_text(value):
        # LLMs may emit zero-width marks, NBSP, or line wrapping around the
        # spoken text. Remove only those layout artifacts; keep punctuation and
        # every spoken character significant.
        value = unicodedata.normalize('NFC', str(value))
        value = value.replace('\r', '').replace('\n', ' ' ).replace('\u200b', '').replace('\ufeff', '')
        return re.sub(r'\s+', ' ', value, flags=re.UNICODE).strip()
    actual = [_dialogue_compare_text(x)
              for x in re.findall(r'<d>\s*\[Chinese\](.*?)</d>', candidate, re.S)]
    expected = [_dialogue_compare_text(x) for x in expected]
    if not candidate:
        raise ValueError('衔接预审提示词为空')
    # 衔接镜头本身没有剧本对白时，允许提示词携带用户在过渡动作中
    # 指定的对白；普通镜头仍严格逐句校验台词、顺序和说话人。
    if not bridge_without_script_dialogue and actual != expected:
        differences = [{'line': i + 1, 'expected': expected[i] if i < len(expected) else None,
                        'actual': actual[i] if i < len(actual) else None}
                       for i in range(max(len(expected), len(actual)))
                       if (expected[i] if i < len(expected) else None) !=
                          (actual[i] if i < len(actual) else None)]
        if not _repair_attempt:
            repaired, repair_error = engine.llm_chat([
                {'role': 'system', 'content': '修正提示词对白。只输出完整提示词正文。严格按剧本逐字保留每句台词、顺序及说话人绑定，保持衔接首尾状态和Picture编号；顺序错误时允许调整对应说话人的完整画面段和时间戳，不得只交换台词而保留错误的说话人。每句使用独立的<Subject N> (SN) says:行，下一行<d>[Chinese]台词原文</d>。'},
                {'role': 'user', 'content': json.dumps({'dialogue': shot.get('dialogue', []),
                    'differences': differences, 'prompt': candidate}, ensure_ascii=False)},
            ], max_tokens=6000, temperature=.1, timeout=240)
            if isinstance(repaired, str) and repaired.strip():
                # Re-run semantic review as well as the immutable-dialogue checks.
                fixed, report = check_prompt(engine, shot, repaired, frame, _repair_attempt=1)
                if set(re.findall(r'<Picture \d+>', prompt)) != set(re.findall(r'<Picture \d+>', fixed)):
                    raise ValueError('衔接修复改变参考图编号')
                return fixed, report
        first = differences[0]
        raise ValueError(f'衔接预审第{first["line"]}句台词不一致：剧本={first["expected"]!r}；提示词={first["actual"]!r}（自动修复未通过）')
    boundary_errors = dialogue_boundary_errors(candidate)
    if boundary_errors:
        raise ValueError('衔接预审对白边界无效：' + '；'.join(boundary_errors))
    if set(re.findall(r'<Picture \d+>', prompt)) != set(re.findall(r'<Picture \d+>', candidate)):
        raise ValueError('衔接修复改变参考图编号')
    return candidate, result


def render_references(engine, project, shot, prompt, refs):
    if not enabled(project) or not shot.get('continuity'):
        return prompt, refs, None
    prompt = apply_continuity_intro(shot, prompt)
    frame = visual_handoff(engine, project, shot)
    if not frame:
        return prompt, refs, None
    if len(refs) >= 9:
        raise ValueError('连续镜需为实际末帧保留一个参考图名额（现有角色/场景/道具最多8张）')
    number = len(refs) + 1
    instruction = (f'\n实际衔接参考（不朗读）：<Picture {number}>为上一镜实际末帧，只约束空间、起始姿态、持物和动作进度；'
                   '角色身份、衣着、道具外观仍由原有参考图锁定，不以末帧替换它们。继承已完成动作，不重演转身或放物；'
                   '遮挡或未入帧的物品按状态表和道具参考保留。')
    instruction += ('保持末帧机位和初始构图。' if shot['continuity'].get('camera_mode') == 'same'
                    else '允许指定的新机位，保持世界位置与视线关系，不把画面左右当成真实换位。')
    marker = prompt.find('[Shot 1]')
    prompt = prompt[:marker] + instruction + '\n\n' + prompt[marker:] if marker >= 0 else prompt + instruction
    return prompt, [*refs, frame], {'frame': frame, 'picture': number, 'mode': 'r2v_auxiliary'}


def review_boundary(engine, project, shot, video_path):
    if not enabled(project):
        return None
    previous = previous_video(engine, project, shot)
    if not previous:
        return None
    frames = [boundary_frame(engine, previous, True), boundary_frame(engine, video_path, False)]
    instruction = '''比较两张实际视频帧：第一张是前镜末帧，第二张是后镜首帧。只根据可见证据检查姿势/动作回退、左右手持物、包装外观、覆盖/开合、世界位置和衣着。换机位本身不是瞬移，遮挡记uncertain，不要求后镜结束动作在开头完成，不臆测不可见物品。返回JSON {"status":"pass|issue|uncertain","observations":[],"issues":[{"description":"断点","evidence":"两帧可见依据","suggested_fix":"修复建议"}],"limits":[]}。本结果只作待复核提示，不能自动判定或触发重渲染。'''
    text, error = engine.llm_chat([{'role': 'user', 'content': [{'type': 'text', 'text': instruction}] + engine.load_image_parts(frames)}], max_tokens=2000, temperature=.1, timeout=240)
    report = engine.parse_json_from_text(text or '')
    if not isinstance(report, dict) or report.get('status') not in ('pass', 'issue', 'uncertain'):
        report = {'status': 'uncertain', 'issues': [], 'limits': [error or '模型报告无效']}
    report.update(frames=frames, needs_human_review=True, automatic_rerender=False)
    return report
