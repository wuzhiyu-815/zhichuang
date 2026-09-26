# 剧本技能

- 解析故事创意
- 生成剧本结构
- 检查镜头数量
- 检查角色引用
- 检查场景引用
- 检查剧情节奏
- 修复剧本 JSON

## 服装规则

逐镜规划 wardrobe，逐角色写清款式、颜色、鞋子与状态。身份保持一致，同一场戏服装连续；按时间、活动和年代合理换装，避免全剧固定一套衣服。缺失服装或漏角色必须修复后再接受剧本。

- 检查镜头服装
- 补全镜头服装

## 项目内打斗技能

- [fight-choreography-director](fight-choreography-director/SKILL.md)
- [fight-scene-director](fight-scene-director/SKILL.md)
- [high-density-fight-prompt](high-density-fight-prompt/SKILL.md)
- [lark-yelaoshi](lark-yelaoshi/SKILL.md)
- [minimax-h3-action-director](minimax-h3-action-director/SKILL.md)

完整技能和参考资料随项目保存。网页阶段选项由 app.py 注册，通过 skills/agent_documents.py 按 agent 加载正文和 references 下的文本资料；图片资料保留在技能目录中。剧本阶段仍以系统 JSON 结构为准，视频阶段仍以系统 H3 输出契约为准。
