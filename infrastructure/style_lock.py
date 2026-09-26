"""Prompt-level medium consistency. This is guidance, not a model-side guarantee."""
import re

MARKER = '【项目二维画风锁定】'
RULE = (MARKER + '全片从首帧到末帧统一为纯 2D 手绘日式动画、赛璐璐平涂，干净明确的轮廓线，'
        '分区色块阴影，手绘背景；人物、场景、道具及特效使用同一二维视觉语言。'
        '动作、透视和运镜可以变化，绘画媒介不可变化；光照以二维色块表达，肤质保持平涂。'
        '禁止转为 3D 建模、CGI、三维渲染、游戏过场、PBR 材质、塑料皮肤或真人摄影。'
        '参考图沿用身份、服装和构图，但冲突的三维材质须转换为二维画法。'
        '本条优先于旧提示词的画风/材质描述，不改变人物、剧情、逐字对白或音频要求。')


def is_2d(style):
    style=str(style or '')
    if re.search(r'3\s*d\s*(动漫|动画|国漫|风格)|三维(动画|动漫|风格)',style,re.I):
        return False
    return bool(re.search(r'二次元|日漫|2\s*d|二维|赛璐璐',style,re.I))


def style_instruction(style):
    if is_2d(style):
        return RULE+' 生成提示词时，把该画风写入整体风格和每个镜头的视觉描述；不要输出冲突的三维渲染要求。'
    if is_3d_animation(style):
        return RULE_3D
    return '项目选定画风：'+str(style or '电影写实')+'。所有镜头和参考图均遵循该画风。'


def lock_prompt(prompt, style):
    rule = RULE if is_2d(style) else RULE_3D if is_3d_animation(style) else None
    marker = MARKER if is_2d(style) else MARKER_3D
    if not rule or not isinstance(prompt,str) or marker in prompt:
        return prompt
    # Keep the H3 field order and all reference/audio/dialogue tokens unchanged.
    match=re.search(r'integrated_multimodal_description\s*[:：]',prompt,re.I)
    if match:
        return prompt[:match.end()]+' '+rule+'\n'+prompt[match.end():]
    return rule+'\n'+prompt

MARKER_3D = '【项目三维动画画风锁定】'
RULE_3D = (MARKER_3D + '人物、场景和道具统一为风格化三维动画电影。继承角色参考图的身份、年龄、脸型与项目美术比例，'
           '男女角色使用一致的动画建模语言；面部块面简洁，皮肤柔和着色，头发成束，衣料保留大形褶皱，'
           '环境与道具使用统一的简化几何与材质。保持原项目的国漫或其他指定美术，不擅自换成欧美卡通、幼态比例或真人摄影。'
           '全景到特写、首帧到末帧保持同一渲染风格；人物身份、对白和服装不因画风调整而改变。')


def is_3d_animation(style):
    return bool(re.search(r'(3\s*d|三维).*(动漫|动画|国漫)|国漫.*3\s*d', str(style or ''), re.I))
