"""Explicit shot handoffs; only opt-in shots receive continuity instructions."""
import json
import re


def requires_previous_frame(shot):
    """Story continuity is separate from a render dependency; legacy plans stay strict."""
    plan = shot.get('continuity') or {}
    return plan.get('transition') == 'continuous' and plan.get('handoff_mode', 'frame') == 'frame'


def validate_continuity(shots):
    errors = []
    previous = None
    for shot in shots:
        index = shot.get('index')
        plan = shot.get('continuity') or {}
        start, end = plan.get('start'), plan.get('end')
        if not isinstance(start, dict) or not start or not isinstance(end, dict) or not end:
            errors.append(f'第{index}镜缺少首尾状态')
            previous = shot
            continue
        for label, state in [('start', start), ('end', end)]:
            if not all(state.get(k) for k in ('location', 'characters', 'props')):
                errors.append(f'第{index}镜{label}缺少空间/人物/道具状态')
        mode = plan.get('transition')
        handoff = plan.get('handoff_mode')
        if handoff is not None and handoff not in ('none', 'state', 'frame'):
            errors.append(f'第{index}镜衔接依赖类型无效')
        if handoff is not None and ((mode == 'continuous' and handoff == 'none')
                                    or (mode != 'continuous' and handoff != 'none')):
            errors.append(f'第{index}镜衔接依赖与转场类型冲突')
        if mode not in ('opening', 'continuous', 'cut'):
            errors.append(f'第{index}镜转场类型无效')
        if previous is None:
            if mode != 'opening':
                errors.append(f'第{index}镜须为opening')
        elif mode == 'opening':
            errors.append(f'第{index}镜不能再次opening')
        elif mode == 'continuous':
            if plan.get('previous_index') != previous.get('index'):
                errors.append(f'第{index}镜前镜编号错误')
            if start != (previous.get('continuity') or {}).get('end'):
                errors.append(f'第{index}镜首态不等于前镜尾态')
        elif mode == 'cut' and not plan.get('reason'):
            errors.append(f'第{index}镜缺少时空跳转说明')
        previous = shot
    return errors


def continuity_instruction(shot):
    plan = shot.get('continuity')
    if not plan:
        return ''
    return ('\n【镜头交接状态：必须执行，仅作画面约束，不朗读】\n'
            + json.dumps(plan, ensure_ascii=False)
            + '\n首帧从start开始，最后画面准确达到end。continuous表示剧情与状态连续，不等于必须串行渲染；handoff_mode=state用文字首态独立起拍，frame才依赖上一镜实际尾帧。cut表示剪辑切换，按reason和start建立当前画面，同场换机位不必换场。'
            '除opening外，在视觉描述开头写“接上一镜头”，随后明确本镜起始位置、人物姿势朝向、衣着、持物和情绪；不可只写“同上”或假设模型看过前镜。转场时写“接上一镜头剧情，切至……”并说明地点或时间变化。'
            '位置以房间/货架/桌椅等固定地标描述，画面左右随机位变化不等于人物换位；保持轴线和视线方向。'
            '任何坐起、站起、换手、放物、移步均需可见过渡动作；已完成动作不重复。不得朗读状态表，不输出状态表字段。')


def apply_continuity_intro(shot, prompt):
    """Keep manual/cached/repaired prompts self-contained without altering spoken lines."""
    plan = shot.get('continuity') or {}
    if not prompt or not plan:
        return prompt
    # A cached rendered prompt may contain our previous runtime-only tail-frame
    # binding. Remove that exact managed block before choosing this run's refs.
    prompt = re.sub(
        r'\n实际衔接参考（不朗读）：<Picture \d+>为上一镜实际末帧，只约束空间、起始姿态、持物和动作进度；'
        r'.*?(?:保持末帧机位和初始构图。|允许指定的新机位，保持世界位置与视线关系，不把画面左右当成真实换位。)\s*',
        '\n', prompt, flags=re.S,
    )
    prompt = re.sub(r'【接镜说明（不朗读）】.*?【接镜说明结束】\s*', '', prompt, flags=re.S)
    if plan.get('transition') == 'opening':
        return prompt
    start = plan.get('start') or {}
    if not all(start.get(k) for k in ('location', 'characters', 'props')):
        raise ValueError('接镜提示词缺少完整起始状态')
    lead = ('接上一镜头剧情，按本镜剪辑点切入当前画面。' if plan.get('transition') == 'cut'
            else '接上一镜头，延续已完成的剧情和人物状态，不重复前镜动作。')
    mode = ('以附加的上一镜实际末帧校准开场姿态与持物。' if requires_previous_frame(shot)
            else '依据下述明确首态独立起拍，无需等待或假设已看到上一镜实际画面。')
    instruction = ('【接镜说明（不朗读）】' + lead + mode
                   + f"开场位置：{start['location']}。人物状态：{start['characters']}。道具状态：{start['props']}。"
                   + '机位变化按本镜镜头设计执行，保持空间关系、视线和动作因果；本段仅作画面约束，不作为对白、旁白或字幕。'
                   + '【接镜说明结束】\n')
    marker = re.search(r'integrated_multimodal_description\s*[:：]', prompt, re.I)
    if marker:
        return prompt[:marker.end()] + '\n' + instruction + prompt[marker.end():].lstrip()
    return instruction + prompt
