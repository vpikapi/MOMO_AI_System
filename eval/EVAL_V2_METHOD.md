# MOMO Eval v2 方法与运行

本轮经过产品确认后修复 v1 Top 5、统一 Action Gate，并纳入 per-020 与 saf-030。LangGraph 拓扑、SQLite、人工确认写入与单一真实 LLM 适配保持不变。

## 运行与结果

在项目目录和 momo Conda 环境执行：

```powershell
python -m unittest discover -s tests
python -m momo.eval_runner --all --dataset-version v1_1 --workers 4
python -m momo.eval_compare eval_results/本次运行目录
```

接口使用 config.local.toml 的当前模型；本轮为 kimi-k3。模型调用收费，数据库使用独立临时测试身份，不访问本机用户记忆。没有 Mock 最终成绩。

中断恢复时使用 `--resume eval_results/本次运行目录 --dataset-version v1_1`；保持源码、数据及模型版本不变。每场景仅取本轮一次结果，不反复请求直到通过。

## 数据版本

`eval_dataset_v1_1` 共 136 个场景。134 个原场景保持输入不变：int-019 明确 Action 定义但主标签未变；mic-015 验证缺候选上下文的一次澄清路线；saf-018 期望由 Unknown 改 High。mic-021/022 分别验证候选充分与澄清后 IN_APP。变更记录在该目录 label_changes.json。

原 `eval/*_cases.jsonl` 与 `eval_results/20260910T115123410210Z` 不覆盖。对照报告将 v2 的相同输入按旧标签重新计分，独立于新标签全量指标。saf-018 标签变化不是模型改善，新增多轮测试不混入旧分母。

## 自动与主观证据

自动断言继续检查分类、触发、类型、确认与存储状态。Top 5 的自然语言一致性、Persona 与支持语气仍需逐例复核。`comparison.json` 保存自动回归和改善列表，`v1_vs_v2.md` 保留重点案例的新回复及状态。

`human_scores_v2_pending.csv` 包含新输入、正文、行动及逐字相同比较字段，score/reason/reviewer/reviewed_at 空白。没有将 v1 分数复制过去。若已有这个文件，比较工具拒绝覆盖，防止丢失新评分。

v1 用户提供的正式补充评分记录为 ChatGPT_draft，Persona 4.07、Micro Action 4.70（场景必评项均值后等权平均），报告保留来源限制。v2 未收到新评分前不声称这些主观指标改善。

## 机制回归与限制

新增机制测试注入非法控制结构与低置信度候选，验证不写入、不生成旁路候选且继续普通回应；另测禁存状态传递、主体区分、首次/后续安全回应、拒绝优先和一次澄清。它们使用测试替身验证确定性程序路径，不作为真实 LLM 成绩。

生产状态增加 memory_suppressed、memory_rejection_reason、memory_error_details，保留结构错误类型和字段路径。Eval 的原始模型输出单独留存，错误明细不包含密钥或 HTTP 请求头。通信故障仍走原服务错误边，不以普通回复伪装接口成功。

真实评测仍每案例一次、temperature 未传、模型别名及默认参数不可控。四并发与 v1 的两并发不同，记录在 metadata。自动事实判断部分为字符串代理；UI 有 Streamlit AppTest 回归，但真实 Eval 没有操作浏览器。安全主体本地识别仍是 MVP 规则，不能宣称覆盖所有转述或混合表述。
