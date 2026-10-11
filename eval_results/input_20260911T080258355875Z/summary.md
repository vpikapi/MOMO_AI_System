# MOMO Eval input_fix Summary

模型：qwen3.8-flash；完成 10/10 个场景。

| 指标 | 结果 |
|---|---|
| Intent Accuracy（主标签） | None% |
| Memory 自动检查通过率 | None% |
| Persona 人工平均分 | 待人工评分 |
| Micro Action 触发/类型自动通过率 | 100.0%（质量评分另计） |
| Safety High 严格 Recall | None% |
| Safety 严格 FN / 支持流程 FP | 0 / 0 |
| High 未进入支持流程 | 0 |

## Intent 分类别

| 类别 | 正确/总数 | 准确率 |
|---|---|---|
| Vent | 0/0 | None% |
| Companion | 0/0 | None% |
| Reflect | 0/0 | None% |
| Action | 0/0 | None% |
| Play | 0/0 | None% |
| Memory Control | 0/0 | None% |

## Top 5 失败案例（先风险，再其他）


## 解释与限制

- 使用真实接口与生产图；安全支持、记忆确认说明及获准的 Play 最终降级可能为本地文本，不能计为模型生成成功。逐轮 trace / fallback_source / capability_truth 保留来源，影子安全分类另计。
- Safety FN 定义为期望 High 却未得到有效 High（含服务错误）；High→Unknown 仍进入支持流程，因此同时报告未受保护 High 数。FP 为期望 Normal 却进入 High/Unknown 分类，接口错误另列。
- Persona 和 Micro Action 主观质量没有伪造人工分数。请填写 human_scores.csv（1–5、理由、评分者），再执行 --summarize。
- 初版计分曾将纯 BLOCK 操作计划当作内容候选。v1.1 仅修正计分定义，不改测试标签或重跑模型；results.jsonl 保留原记录，graded_results.jsonl 为修正后计分，initial_grading 保存原报告。
- 事实包含/排除检查是字符串代理，改写或否定引用可能误报，失败需复核。测试标签为产品规则标注，未做临床或多评审共识。
- 每案例/多轮场景独立 SQLite；确认步骤是脚本模拟用户点击生产接口，没有操作本机记忆。不是浏览器 UI 评测。
- temperature 未传：维持当前生产参数，供应商默认值不可观测。固定数据/版本不保证逐字复现；本轮每案例一次。
- 测试包含开发阶段已见过的典型句型，属于产品回归集，不是未见数据泛化基准。
- 所有失败保留在 failures.jsonl，逐轮状态和正式模型输出在 results.jsonl / events.jsonl。未自动修改产品提示词或逻辑。

详细分母、服务错误、分类来源与人工维度：metrics.json。数据版本：v1_1 unchanged subset + reg-004；提示词版本：{'app.py': 'b71f7bc51f906aa08c09ce9c927e08dcbc49e1e3f3d08162f25523257531c1ed', 'momo\\graph.py': '3a861f88f1cde92a9a7391bfcd7b5a072711ce8902b7b5cf672195bbefcdd8b1', 'momo\\models.py': 'bb479f4c8abe5d46d2d210568b95934a9182ee7743b58f2d0773f0e6e0aa658d', 'momo\\memory.py': '74a72e8907fbc294501d219bd14a6a7707cbe6eb71789e813c1aeea7d115f5e0', 'momo\\mock_llm.py': '8b1d9c5b5063ea8eb7536db36865ce88a3ba4b6f733e829de088e65b354cc296', 'prompts\\emotion.md': 'b19b72f506ed5a15622fd2326ebd23661ed41311dc3fa2d2ea8f4519a6440509', 'prompts\\intent.md': '2735ad1fbc96cf1f25f400503c35aff073cdb5a51862c951670620fc84430567', 'prompts\\memory.md': '268187b61e7d619ac1526c4c6e250ee1c050ebf8e21afff5c431a78a4d8a5764', 'prompts\\memory_control.md': '7bf43b933723fda61418f161219bd2b4fc5509bd91a7c100227a516e41bdb019', 'prompts\\micro_action.md': '222dd4bdc4b9eab398a20123e2d5acddc8ae9e693fd49a93caf7266bd3931a29', 'prompts\\persona.md': 'bacc408dd1617b39a736ded3b7aab3060a15c76725f9c6f137227f43cfb0f3bd', 'prompts\\safety.md': '1c3dd122a46e0d15e7e1ea03e89c546d39291cb512c23846c1ffcaa1e8160184'}。
