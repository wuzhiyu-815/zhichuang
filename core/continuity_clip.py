"""插入衔接镜头，同时迁移按编号保存的视频及历史版本。"""
import copy
import os
import re
from core.final_video import invalidate_final


def insert_bridge(project, before, description, duration, outputs_dir, save):
    result = copy.deepcopy(project)
    shots = result.get('script', {}).get('shots', [])
    shots.sort(key=lambda shot: shot['index'])
    position = next((i for i, shot in enumerate(shots) if shot['index'] == before), -1)
    if position < 0:
        raise ValueError('请选择有效镜头位置')
    following = copy.deepcopy(shots[position])
    # 第1镜允许补“片头衔接”：没有本集前一镜时，以第1镜的场景/人物作为
    # 连续性锚点，具体前置动作由用户描述补充（通常承接上一集末帧）。
    previous = copy.deepcopy(shots[position - 1]) if position > 0 else copy.deepcopy(following)
    rendered = {shot['index']: shot for shot in result.get('shots', [])}
    if any(not rendered.get(s['index'], {}).get('video_url') or rendered[s['index']].get('error')
           for s in (previous, following)):
        raise ValueError('前后两个镜头都生成完成后，才能补衔接片段')
    mapping = {s['index']: s['index'] + 1 for s in shots[position:]}
    for collection in (shots, result.get('shots', [])):
        for shot in collection:
            shot['index'] = mapping.get(shot['index'], shot['index'])
            plan = shot.get('continuity') or {}
            if plan.get('previous_index') in mapping:
                plan['previous_index'] = mapping[plan['previous_index']]
    for key in ('prompts', 'shot_confirm', 'shot_versions', 'reviews',
                'continuity_prompt_checks', 'continuity_reviews', 'prompt_failures'):
        if key in result:
            # These maps also contain project-level keys such as __all__.
            result[key] = {
                str(mapping.get(int(k), int(k))) if str(k).isdigit() else k: v
                for k, v in result[key].items()
            }
    # Adding a shot requires another whole-episode confirmation and a fresh
    # handoff plan; cached groups/drafts still refer to the old shot numbers.
    result.get('shot_confirm', {}).pop('__all__', None)
    for key in ('continuity_plan_signature', 'render_groups', 'reference_sync_draft'):
        result.pop(key, None)
    prefix = 'outputs/' + project['id'] + '/'
    pattern = re.compile(re.escape(prefix) + r'(versions/)?shot_(\d+)(?=\.mp4|/)')
    def rewrite(value):
        if isinstance(value, dict):
            return {k: rewrite(v) for k, v in value.items()}
        if isinstance(value, list):
            return [rewrite(v) for v in value]
        if isinstance(value, str):
            return pattern.sub(lambda m: prefix + (m[1] or '') + f'shot_{mapping.get(int(m[2]), int(m[2])):02d}', value)
        return value
    result = rewrite(result)
    bridge = {
        'index': before, 'duration': duration, 'scene': previous.get('scene', ''),
        'characters': list(dict.fromkeys(previous.get('characters', []) + following.get('characters', []))),
        'props': list(dict.fromkeys(previous.get('props', []) + following.get('props', []))),
        'wardrobe': previous.get('wardrobe', ''), 'camera': '自然连续运镜', 'dialogue': [],
        'is_bridge': True,
        'action': (f'新增衔接镜头。用户要求：{description}\n'
                   f'承接上一镜结尾：场景={previous.get("scene", "")}；动作={previous.get("action", "")}；服装={previous.get("wardrobe", "")}\n'
                   f'过渡到下一镜开头：场景={following.get("scene", "")}；动作={following.get("action", "")}；服装={following.get("wardrobe", "")}\n'
                   '只表现两镜之间缺失的动作或转场，保持人物、道具、视线和运动方向连贯，不重复前后完整剧情。'),
    }
    result['script']['shots'].insert(position, bridge)
    invalidate_final(result)
    moved = []
    try:
        for old, new in sorted(mapping.items(), reverse=True):
            for relative in (f'shot_{old:02d}.mp4', f'versions/shot_{old:02d}'):
                source = os.path.join(outputs_dir, project['id'], relative)
                destination = os.path.join(outputs_dir, project['id'], relative.replace(f'shot_{old:02d}', f'shot_{new:02d}'))
                if os.path.exists(source):
                    if os.path.exists(destination):
                        raise ValueError('目标镜头文件已存在，请先检查项目文件')
                    os.rename(source, destination)
                    moved.append((source, destination))
        save(result)
    except Exception:
        for source, destination in reversed(moved):
            os.rename(destination, source)
        raise
    return bridge
