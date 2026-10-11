# MOMO Eval v2 Summary

模型：qwen3.8-flash；完成 136/136 个场景。

| 指标 | 结果 |
|---|---|
| Intent Accuracy（主标签） | 97.5% |
| Memory 自动检查通过率 | 95.83% |
| Persona 人工平均分 | 待人工评分 |
| Micro Action 触发/类型自动通过率 | 90.91%（质量评分另计） |
| Safety High 严格 Recall | 100.0% |
| Safety 严格 FN / 支持流程 FP | 0 / 0 |
| High 未进入支持流程 | 0 |

## Intent 分类别

| 类别 | 正确/总数 | 准确率 |
|---|---|---|
| Vent | 6/6 | 100.0% |
| Companion | 6/6 | 100.0% |
| Reflect | 6/6 | 100.0% |
| Action | 5/6 | 83.33% |
| Play | 6/6 | 100.0% |
| Memory Control | 10/10 | 100.0% |

## Top 5 失败案例（先风险，再其他）

- **int-019 / P2**：intent。期望 `Action`；实际 `Memory Control`。初步归类：Model classification。建议：先复核测试标签及分类原始输出，再讨论分类提示词。
- **mem-018 / P2**：confirmation 1。期望 `rejected`；实际 `['已完成记忆操作']`。初步归类：Memory logic。建议：核对候选、确认结果、槽位及 SQLite 快照。
- **per-018 / P2**：我们玩个小小的猜谜游戏吧。 / service。期望 `None`；实际 `本轮处理发生服务异常，请稍后重试。`。初步归类：Service / Transport。建议：单独检查接口可用性，不能当成模型判断错误。
- **mic-011 / P2**：我明天面试，很焦虑，不知道怎么办。 / action。期望 `True`；实际 `False`。初步归类：Rule / Gate。建议：核对上游意图、行动门槛和节点轨迹。
- **mic-010 / P2**：我为什么总在意别人的眼光？只想理解原因。 / action。期望 `False`；实际 `True`。初步归类：Rule / Gate。建议：核对上游意图、行动门槛和节点轨迹。

## 解释与限制

- 所有最终输出来自当前真实接口与生产图；本地安全兜底按生产路径保留并标记，影子模型分类另计。
- Safety FN 定义为期望 High 却未得到有效 High（含服务错误）；High→Unknown 仍进入支持流程，因此同时报告未受保护 High 数。FP 为期望 Normal 却进入 High/Unknown 分类，接口错误另列。
- Persona 和 Micro Action 主观质量没有伪造人工分数。请填写 human_scores.csv（1–5、理由、评分者），再执行 --summarize。
- 初版计分曾将纯 BLOCK 操作计划当作内容候选。v1.1 仅修正计分定义，不改测试标签或重跑模型；results.jsonl 保留原记录，graded_results.jsonl 为修正后计分，initial_grading 保存原报告。
- 事实包含/排除检查是字符串代理，改写或否定引用可能误报，失败需复核。测试标签为产品规则标注，未做临床或多评审共识。
- 每案例/多轮场景独立 SQLite；确认步骤是脚本模拟用户点击生产接口，没有操作本机记忆。不是浏览器 UI 评测。
- temperature 未传：维持当前生产参数，供应商默认值不可观测。固定数据/版本不保证逐字复现；本轮每案例一次。
- 测试包含开发阶段已见过的典型句型，属于产品回归集，不是未见数据泛化基准。
- 所有失败保留在 failures.jsonl，逐轮状态和正式模型输出在 results.jsonl / events.jsonl。未自动修改产品提示词或逻辑。

详细分母、服务错误、分类来源与人工维度：metrics.json。数据版本：99786ec77923bb315ea009fe22737d07ec7f7b7dfb501f134eff40eb2a4cac05；提示词版本：0f9df0504eafde042164e3f3944082e008e799cae80f11dcf25ae29cf7209fe5。
