"""Reviewed 3D first-frame generation for agent rendering. No silent identity fallback."""
import hashlib
import json
import os
import re
from infrastructure.style_lock import is_3d_animation, style_instruction


def use_first_frame(config, shot, audio_paths):
    return (is_3d_animation(config.get('style')) and config.get('style_first_frame_enabled', True)
            and config.get('media_provider', 'comfyui') != 'jimeng' and not audio_paths
            and shot.get('style_render_mode') != 'r2v')


def prepare(engine, project, shot, prompt, refs, directory):
    config = engine.runtime_config()
    fingerprint = {'shot': shot, 'prompt': prompt, 'style': config.get('style'),
                   'refs': [(p, os.stat(p).st_mtime_ns, os.path.getsize(p)) for p in refs]}
    key = hashlib.sha256(json.dumps(fingerprint, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:24]
    record_path = os.path.join(directory, f'first-frame-{key}.json')
    if os.path.isfile(record_path):
        with open(record_path, encoding='utf-8') as cached:
            record = json.load(cached)
        if os.path.isfile(record.get('path', '')) and record.get('review', {}).get('passed') is True:
            return record
    parts = [{'type': 'text', 'text': style_instruction(config.get('style')) + '''
根据附图的角色身份、衣着、道具、空间与以下镜头信息，写一段完整镜头开场静态画面的生图提示词。不要四宫格，不要动作序列、对白或可读文字。
描述可见脸型/年龄/发型/服装，不能只用人物名。保留原美术造型，不重新设计人物；男女主、环境与道具统一动画媒介。
若最后一张标为上一镜末帧，继承已完成的姿态和持物；若换场不要沿用旧空间。只输出生图正文。
''' + json.dumps({'shot': shot, 'video_prompt': prompt}, ensure_ascii=False)}] + engine.load_image_parts(refs)
    brief, error = engine.llm_chat([{'role': 'user', 'content': parts}], max_tokens=2000, temperature=.2)
    if not brief:
        raise ValueError(error or '首帧规划失败')
    for attempt in range(2):
        path, error = engine.gen_image(brief, seed=int(key[:8], 16)+attempt,
                                      save_name=f'first-frame-{key}-{attempt}.png')
        if not path:
            raise ValueError(error or '首帧生成失败')
        review_parts = [{'type': 'text', 'text': '''最后一张是候选首帧，前面是身份/场景/道具参考。核对：是否统一风格化3D，是否保留每个角色脸型年龄身份/衣服、人物数、空间与左右手持物、道具外观和数量，是否出现重复方向盘等错误。不能只因3D感强就通过，不允许幼态化或擅自变欧美卡通。遮挡或不能确认身份则不通过。返回JSON {"passed":true/false,"issues":[],"limits":[]}。
镜头要求：''' + json.dumps(shot, ensure_ascii=False)}] + engine.load_image_parts(refs + [path], limit=10)
        text, error = engine.llm_chat([{'role': 'user', 'content': review_parts}], max_tokens=1500, temperature=.1)
        review = engine.parse_json_from_text(text or '')
        record = {'path': path, 'brief': brief, 'review': review, 'mode': 'i2v', 'source_refs': refs,
                  'fingerprint': key, 'identity_check': 'automated_not_guaranteed'}
        with open(record_path, 'w') as f:
            json.dump(record, f, ensure_ascii=False, indent=2)
        if isinstance(review, dict) and review.get('passed') is True:
            return record
        brief += '\n修正以下问题，保留已正确的身份与构图：' + json.dumps(review or {'error': error}, ensure_ascii=False)
    raise ValueError('3D首帧未通过身份/画风/构图检查，已保留候选及报告：' + record_path)


def i2v_prompt(prompt):
    # Reference numbers now name the composed first frame; keep speech byte-for-byte.
    pieces = re.split(r'(<d>.*?</d>)', prompt, flags=re.S)
    for i in range(0, len(pieces), 2):
        pieces[i] = re.sub(r'<Picture\s+\d+>', '首帧中的对应视觉元素', pieces[i])
    result = ''.join(pieces)
    rule = ' <Picture 1>是完整镜头首帧，继承其人物身份、衣着、动画建模、材质、空间与持物，按以下动作继续；不重置姿态，不复制参考图分格。\n'
    marker = 'integrated_multimodal_description:'
    return result.replace(marker, marker+rule, 1) if marker in result else rule+result
