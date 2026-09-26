# 官方依据与本地适配

核对日期：2026-09-19。

## 官方建议

- [Krea 2 Turbo 官方指南](https://www.krea.ai/docs/user-guide/features/krea-2-turbo)：Getting Started 建议简洁提示词，同时明确画风、配色、构图；Prompting Tips 建议主体清楚、风格用语靠前、用视觉参考表达身份、对比多张结果。Turbo 侧重快速探索，不能把提示词优化等同于最终一致性保证。
- [Krea 2 官方指南](https://www.krea.ai/docs/user-guide/features/krea-2)：说明主体、环境、氛围与风格；托管产品提供风格参考、moodboards、LoRA 与 Creativity。Raw 不扩写，Low 仅少量补全，High 允许更多创作。这里的 Raw 控件不要和 Krea 2 RAW 基础权重混淆。
- [官方 API 概览](https://www.krea.ai/docs/developers/krea-2/overview)：creativity、image_style_references 等是托管 API 参数，不能仅把参数名字写入本地提示词来获得对应能力。

以上文档未提出“必须英文”“必须某个字数”“堆质量词”或通用负向词模板。英文段落与字数目标属于本项目适配。

## 本项目实际路径

`workflows/z-image.json` 文件名沿用旧名，实际加载 krea2_turbo_fp8_scaled.safetensors、Qwen3-VL 文本编码器，8 步、CFG 1。30:19 输入 → 30:18 技能指令 + 30:17 拼接 → 30:16 Qwen 扩写 → 30:21 开关 → 编码 → 采样。扩写上限沿用 512，保留开关设置。技能不改变模型或采样参数。

负向条件为 ConditioningZeroOut。LoRA 的开关 30:23 默认 false，因此不能把 darkbrush LoRA 认定为当前画风问题的原因。未接入官网 Srefs、moodboards 或 creativity 参数。

发现的风险是旧扩写指令要求考虑多种风格，角色描述同时使用“四宫格”和“横向四栏”，并包含后续视频换装指令。它们是可核实的提示词冲突，尚不能证明所有坏图的原因。技能与模板修正解决这些冲突，但多视图解剖、精确身份仍需查看生成结果。竖屏四栏空间较小；保留现有视图顺序以兼容视频参考说明，不私自删减视图。

## 本地示例（不是官方模板）

### 二次元角色四栏参考图

输入：日漫二次元；成年女性；黑色齐肩发；棕眼；蓝色夹克、白色上衣、黑裤；面部、正面全身、背面全身、侧面全身。

输出：Hand-drawn 2D anime character reference sheet with clean linework and flat cel shading. One row of four distinct panels shows the same adult woman with shoulder-length black hair and brown eyes, wearing the same blue jacket, white top, and black trousers throughout. From left to right: a neutral face close-up looking forward, a full-body front view, a full-body back view, and a full-body side view. The three full-body views include the head and feet entirely within their panels. Consistent body proportions, hairstyle, and clothing colors across all views, against a plain light background with simple illustrated shading.

### 二次元空场景

Hand-drawn 2D anime background with clean architectural lines and flat cel-shaded colors. An unoccupied school classroom viewed diagonally from the rear corner, with orderly wooden desks facing a green chalkboard and windows along the left wall. Soft morning light forms broad painted shadow shapes across the floor. The desks, windows, and chalkboard have clear spatial relationships in a wide composition.

### 二次元道具

Hand-drawn 2D anime prop illustration with crisp outlines and flat cel shading. A single closed red folding umbrella with a curved black handle, centered and fully visible against a plain pale background. Simple painted highlights describe the fabric folds and handle while preserving the illustrated surface.
