# 提示词技能

- 生成 H3 提示词
- 编排 Picture 编号
- 检查台词完整性
- 检查动作连续性
- 检查角色边界
- 修复提示词

## 服装规则

读取并落实本镜 wardrobe，明确各角色的服装与状态。角色参考图锁定身份，不能覆盖服装计划；同一场连续戏保持服装连续，跨时间和活动允许合理换装。缺失服装时返回分镜补全，不能静默照搬参考图。

## 项目内打斗技能

- [fight-choreography-director](fight-choreography-director/SKILL.md)
- [fight-prompt-director](fight-prompt-director/SKILL.md)
- [fight-scene-director](fight-scene-director/SKILL.md)
- [high-density-fight-prompt](high-density-fight-prompt/SKILL.md)
- [lark-yelaoshi](lark-yelaoshi/SKILL.md)
- [minimax-h3-action-director](minimax-h3-action-director/SKILL.md)

完整技能和参考资料随项目保存。网页阶段选项由 app.py 注册，通过 skills/agent_documents.py 按 agent 加载正文和 references 下的文本资料；图片资料保留在技能目录中。剧本阶段仍以系统 JSON 结构为准，视频阶段仍以系统 H3 输出契约为准。
