# MOMO Agent 行为修复 · 2026-09-10

## 修改范围

app.py；momo/graph.py、models.py、memory.py、mock_llm.py；prompts/memory.md、新增 memory_control.md 与 micro_action.md；tests/test_system.py、test_demo.py、新增 test_agent_behavior.py；README、相关 JSON Schema 与本说明。

LangGraph 与 SQLite 保留。唯一真实模型适配仍为 mock_llm.py。Safety 节点、固定安全回应、风险路由判断、local_safety、安全模型接口，以及原 HTTP/流式传输和配置读取函数经过 AST 比较，未改动。仅 Safety 正常出口接入新的控制节点。

## 记忆行为

Safety → Memory Control → 普通意图/情绪 → 记忆检索 → Action Gate → 可选行动生成 → 上下文 → 流式回复 → 普通候选检查。Memory Control 优先于普通 Intent，阻止行动与普通候选重复提取。

CREATE / UPDATE / DELETE / BLOCK 均先展示确认；QUERY 自然语言总结已确认信息。明确范围不能确定时询问，模型不能直接写 SQLite。多槽位操作展示完整旧记录与替换清单，确认后事务提交；每个明确槽位只允许一个当前事实，other 不自动合并。更新不保留历史版本，增加更新时间；旧组合记录不启动批量自动迁移，按实际操作提出拆分并请用户确认。

DELETE 只删指定事实；BLOCK 保留旧记忆，只拦截未来槽位写入；组合操作同时删除并禁存。页面不再记住类似内容保留组合含义。禁止规则不通过普通 Preference 记忆代替。

确认计划带目标快照与修订号；过期计划不能覆盖后来的编辑。价值、置信度、敏感性与到期检查继续有效。秘密与危机内容保存限制保留。

身份检索始终包含有效 Identity 与 Preference，避免“我是谁”没有词重叠而漏召回。回复遵循最新明确纠正 > 最新确认记忆 > 较早用户消息 > 模型推测。记忆修订后保留界面消息，但普通模型上下文整体从修订后开始；Safety 仍读原有上下文。查询不使用旧聊天补全身份。

## 行动行为

门槛先于正文生成，同一门槛约束回复和动作卡。记忆控制、隐私设置、明确拒绝、普通倾诉和 Safety 不生成行动。Overwhelmed 仅在 Safety=Normal 且本轮明确求助时允许低负担动作；不因情绪标签默认触发。

同一求助话题最多一次必要澄清，足够明确的面试焦虑直接提供一个动作。IN_APP 提供输入或选项，提交作为用户消息进入原 Agent，不自动写长期记忆；OFFLINE 继续使用完成了 / 不适合我。动作不重复作为固定结尾附加，不影响冻结的关系阶段。

## 新增字段

- AgentState：memory_control_intent、memory_operation、memory_slot、memory_plan、micro_action_allowed、micro_action_block_reason、action_type、active_memory_used_for_context、explicit_help、action_willing、refuses_action、clarification_count、clarification_topic、needs_clarification、ordinary_history。
- MemoryCandidate：slot。
- MemoryControlResult：intent、operations、slots、target_keys、replacements、clarification、explicit_help、action_willing、refuses_action、topic、needs_clarification。
- MicroAction：action_type、input_prompt、options。
- SQLite memories：slot、updated_at；新增 memory_revision、memory_slots_blocked 与明确槽位唯一索引。原数据库会兼容补列，旧记录保留。
- 页面会话：确认计划、修订号、上下文分界、澄清状态和应用内提交状态。

上述工程状态仅在开发者模式展示。

## 验证

最终 55 项自动化测试全部通过，覆盖原有边界和十项验收情形，并补充原子确认、旧组合保留未改字段、过期确认、禁存后不再提出计划、用户隔离、敏感确认、应用内提交与上下文分界。执行命令：python -m unittest discover -s tests。

真实 Kimi 测试使用独立虚构用户与临时 SQLite：身份创建、姓名职业一起更新、身份查询、职业删除、禁存、倾诉及面试求助。后续复测旧组合记录只改职业、IN_APP 与 OFFLINE；同时改善回复中泄露字段名的问题。结果见 eval/agent_behavior_live.json 与 agent_behavior_live_followup.json。前一报告保留了文案约束调整前的原始输出，后一报告记录后续复测。本轮未重复付费验证其余三个模型。

## MVP 限制

槽位识别、旧组合拆分、话题连续性依赖模型，复杂改写仍可能需要澄清；有限保护规则不能替代全面语义系统。为避免遗忘后从旧聊天重新引用事实，采用整个普通上下文分界，会暂时减少与旧话题的连贯性。尚未实现逐句事实遮蔽、历史版本库、向量数据库、登录、多用户系统或自动关系成长。

每轮增加一次控制识别，允许行动时另有一次动作生成，因此真实模型响应等待时间可能增加。正式回复继续流式输出。

关闭新增记忆不妨碍确认编辑或删除已有记录，包括保留旧组合中的未删除事实；全新 CREATE 仍被禁止。

## 启动和回退

在项目目录 conda activate momo 后运行：
python -m streamlit run app.py --server.address 127.0.0.1 --server.port 8505 --browser.gatherUsageStats false

当前服务：http://127.0.0.1:8505 。代码更新后需重启旧终端服务才能载入新模块。

源码备份：上级目录 MOMO_Agent修复前备份.zip；本机 SQLite 备份：上级目录 MOMO_Agent修复前本机数据.sqlite。新版交付包不包含本机数据库、密钥或这份数据备份。
