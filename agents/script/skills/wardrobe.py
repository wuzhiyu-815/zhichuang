"""服装字段门禁及旧剧本的定向补全；不改写剧情或已指定的服装。"""

import copy
import json

from core.skill_result import 技能结果


服装规则 = """人物身份（脸、年龄、发型、体型）保持一致，服装按剧情时间、天气、活动和身份设计。
同一场连续戏保持衣服款式、颜色及污损状态连续，不为多样性逐镜换衣；换天、换活动或明确换装时合理变化，单纯换机位或走到另一房间不要求换装。
每个有角色的镜头必须填写 wardrobe 字符串，逐人用“角色名：具体服装款式、颜色、鞋子及穿脱/污损状态”描述，不写同上、沿用参考图或根据场景推断。
睡眠通常穿睡衣或家居服，正式活动按身份着装；以故事年代和用户明确剧情为准，例如明确写明和衣而睡时保留剧情例外。
不同角色按身份、性格区分服装，制服场景允许相同制服。参考图用于辨认人物，不要求全剧复制同一套衣服。"""


def 检查镜头服装(_上下文, 参数):
    problems = []
    for pos, shot in enumerate(((参数 or {}).get("script") or {}).get("shots") or [], 1):
        if not isinstance(shot, dict):
            problems.append(f"镜头{pos}不是对象")
            continue
        names = shot.get("characters") or []
        if not names:
            continue
        wardrobe = shot.get("wardrobe")
        if not isinstance(wardrobe, str) or not wardrobe.strip():
            problems.append(f"镜头{pos}缺少逐角色 wardrobe 服装描述")
            continue
        missing = [str(name) for name in names if str(name) not in wardrobe]
        if missing:
            problems.append(f"镜头{pos} wardrobe 未注明角色：{'、'.join(missing)}")
        if any(marker in wardrobe for marker in ("同上", "如前", "沿用参考图", "根据场景推断")):
            problems.append(f"镜头{pos} wardrobe 必须填写具体服装")
    return 技能结果(True, 数据={"通过": not problems, "问题": problems})


def 补全镜头服装(_上下文, 参数):
    import app
    script = copy.deepcopy((参数 or {}).get("script") or {})
    shots = script.get("shots") or []
    targets = [i for i, shot in enumerate(shots, 1)
               if not 检查镜头服装(None, {"script": {"shots": [shot]}}).数据["通过"]]
    if not targets:
        return 技能结果(True, 数据={"script": script})
    # 只接收目标镜头的服装映射，模型不能重写台词、动作、顺序或已有有效服装。
    errors = []
    for _ in range(2):
        content, error = app.llm_chat([
            {"role": "system", "content": 服装规则 + '\n只输出 JSON：{"wardrobes":[{"index":镜头位置,"wardrobe":"逐角色服装"}]}。'},
            {"role": "user", "content": json.dumps({
                "script": script, "需补全的镜头位置": targets,
                "要求": "根据全剧时间和活动补全目标镜头，与已有服装保持剧情连续；只改服装。",
                "上次问题": errors,
            }, ensure_ascii=False)},
        ], max_tokens=4000, temperature=0.35)
        try:
            data = app.parse_json_from_text(content or "")
            mapping = {item["index"]: item["wardrobe"] for item in data["wardrobes"]}
            candidate = copy.deepcopy(script)
            for i in targets:
                candidate["shots"][i - 1]["wardrobe"] = mapping.get(i)
            check = 检查镜头服装(None, {"script": candidate})
            if check.数据["通过"]:
                return 技能结果(True, 数据={"script": candidate})
            errors = check.数据["问题"]
        except (TypeError, KeyError, ValueError):
            errors = [error or "服装补全未返回有效的镜头服装映射"]
    return 技能结果(False, 错误="；".join(errors))
