# MOMO · 产品逻辑对齐版

## 2026-10-12：按需加载密钥

打开页面不读取模型配置，也不会因缺少本地密钥而禁用聊天输入。发送消息或点击开发者模式中的“测试连接”时，才加载并校验配置。

开发者模式的“本次会话 API Key”使用密码输入框，输入后按回车生效。非空时优先于本地 Key；清空后回退 `config.local.toml`。仅保存在当前 Streamlit 会话，不写文件、不进入 Agent 状态或调用记录，也不跨会话缓存；隐藏开发者模式后仍有效，刷新或重连不保证保留。

本地文件存在时保留其中的模型和接口参数；云端没有本地文件而填写了会话 Key 时，使用仓库 `config.example.toml` 的模型和接口参数，并替换 Key。当前示例模型为 `kimi-k3`，如需其他已适配模型，修改示例中的 model 后推送。配置无效时明确报错，不偷偷换用另一把密钥。此更新不接入 Streamlit Secrets。

输入的 Key 会传到应用服务器用于模型调用；请仅在自己信任的部署中填写。不同会话的密钥隔离不等于记忆隔离，当前固定测试身份保持不变。以下较早说明中的“仅从文件配置”以本节为准。

2026-09-10。本版依据《MOMO_产品原型_最新版.zip》调整 Memory 与 Streamlit 页面，保留 LangGraph、SQLite、四模型阿里云适配和既有 Safety 分支。

## 启动

在 Anaconda Prompt 中：

```powershell
conda activate momo
cd C:\Users\pikapi\Desktop\AI-Companion\05_Figma\outputs\MOMO_AI_System
python -m pip install -r requirements.txt
python -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501 --browser.gatherUsageStats false
```

看到服务地址后访问 http://127.0.0.1:8501 。首次 Email 提示直接回车即可。Ctrl+C 停止；改代码或模型配置后建议重新启动。若没有环境，先 `conda create -n momo python=3.12 -y`。不要再使用旧项目的 `.venv`。

当前电脑的 `config.local.toml` 已有配置。其他电脑解压后复制 `config.example.toml` 为 `config.local.toml` 再填写密钥。默认 `kimi-k3`，另外可填 `qwen3.8-flash`、`glm-5.2`、`deepseek-v4-flash-0731`，修改后重启。不要覆盖本机已有密钥文件；交付 ZIP 排除该文件。唯一模型实现仍为 `momo/mock_llm.py`，没有离线模式。

## 页面结构

- **主页**：自然问候、明显的聊天入口、已确认的最近事件和当前小行动；不填充虚构经历。
- **Chat**：从主页直接进入。用户消息即时显示，正式回复逐段输出；必要时展示可拒绝行动和待确认记忆。
- **记忆**：About You / Recent Events / Shared Experiences / How You Want MOMO to Treat You 四组；展示正文、类型、已知来源和保存日期。
- **我们**：阶段冻结为“初识”，只展示已确认的共同经历，明确未启用自动成长。
- **设置**：新记忆开关、隐私边界、现实支持、测试数据管理。模型连接检查及内部状态在默认关闭的开发者侧栏中。

## Memory 行为

Safety 放行后，先识别 Memory Control，再进入普通对话。明确身份与相处偏好可提出 CREATE / UPDATE 计划；同一输入可涉及多个事实槽位。查询只总结已确认记忆。所有新增、修改、删除和禁存操作都先展示影响范围，经用户点击确认后执行；敏感内容另需同意。

Identity 槽位为 name / job / city / education / relationship_status / other；Preference 为 advice_preference / question_preference / tone_preference / interaction_preference / other。other 不按类别自动合并。旧组合记忆保留原数据，由模型提出拆分后的完整替换清单，用户确认后事务更新；没有历史版本库。

- 删除：移除指定事实；组合记录中其他事实在确认清单中保留。
- 禁存：只阻止相应槽位未来写入，已有记录保留。
- 删除并禁存：同时执行以上两项。页面“不再记住类似内容”沿用这个组合含义。
- 指代不明确：先问清范围，不猜目标。
- 确认计划绑定目标快照和修订号，数据已变化的旧计划不能覆盖新编辑。
- 每个明确槽位最多保留一个当前值；普通文本候选继续使用保守文本去重，不使用向量数据库。

身份事实优先级为最新用户明确纠正、最新已确认记忆、较早用户消息、助手推断。确认修改或删除后，界面保留聊天记录，但普通模型上下文从本次修订后重新开始，避免引用旧事实。Safety 仍使用原有历史。这个 MVP 采用整体上下文分界，尚未实现逐句事实定向遮蔽。

其他事件与共同经历仍通过普通候选提取，确认前不写数据库。事件日期和有效期规则延续原实现。关闭新记忆后不会保存新事实；查询、删除和禁存入口仍可使用。控制计划与候选仅保留在当前浏览器会话中，刷新可能丢失。

## Micro Action

行动门槛位于正文生成前，记忆控制、明确拒绝、隐私设置和 Safety 均不生成行动。普通倾诉、陪伴默认不触发。用户明确求助、请求方案、愿意尝试或明确 Action 意图时，才可能提供一个相关的小动作；Overwhelmed 必须同时满足 Safety=Normal 且用户明确求助。

同一求助话题最多一次必要澄清，信息充分直接给行动。话题连续性仍由模型判断。IN_APP 在卡片中提供输入框或选项，提交后作为用户消息进入现有 Agent；OFFLINE 保留完成了 / 不适合我反馈。拒绝不影响关系阶段。应用内输入不会自动保存长期记忆。

## 身份和数据范围

固定测试身份为 `local-single-tester`，浏览器刷新和重启服务后访问同一本机记忆。没有登录系统，同一服务的不同浏览器也会使用同一身份，故只适合本机单人测试。旧版随机身份的数据没有被删除或擅自迁移，本版不会自动认领这些旧记录。

已确认记忆和开关在 SQLite 中持久保存；聊天历史、未确认候选、微行动反馈仍是当前会话状态。删除长期记忆不会删除聊天记录，当前会话历史仍可能含有原始表述；需要排除历史影响时，可在设置重置演示对话。

## Safety 与 MVP 边界

现有 High / Unknown 分支、明确危机兜底与安全锁定保留；跳过普通链、微行动与记忆提取。安全支持页提供已核验的中国大陆拨号链接，用户点击后交给设备，不自动呼叫。返回聊天不解除风险锁定；演示重置不是现实风险解除。

本版未开发登录、多用户身份隔离入口、向量数据库、复杂语义去重、自动关系成长、主动推送、医疗诊断或自动联系机构。

## 验证与五条手动路径

```powershell
python -m unittest discover -s tests
```

自动化测试不联网。真实模型 Memory 测试见 `eval/memory_product_live.json`。早期对话/流式报告为先前版本证据，不替代本版验收。

1. 表达“我不喜欢连续被提问，希望先安慰我” → 待确认 → 修改后保存 → 记忆页 Preference；继续聊天后未确认候选仍在。
2. 表达姓名、职业或明日重要事件 → 检查类型与绝对日期 → 保存 → 刷新页面 → 同一固定身份能看到记录。
3. 编辑一条记忆 → 新正文召回；删除后再次提及可申请保存；选择不再记住后常见类似表达不再生成候选。
4. 敏感家庭信息需额外同意；关闭新记忆开关后继续聊天不产生候选，但旧记忆可编辑、删除。
5. 危机告别 → 现实支持页 → 不生成行动或成长记忆；在设置重置演示对话后再测试普通聊天。我们页阶段始终冻结。

达到条件：适用于本机单人、有人组织的真实 LLM MVP 体验测试；不是公开多人服务或安全效果认证。模型误判、日期误解与规则匹配局限需要在测试中记录。


## 2026-09-10 UI / UX 升级

新版入口为首页、聊天、记忆、我们、设置。开发者模式移到右上角且默认关闭；记忆操作位于卡片的更多菜单。此轮仅升级表现层，后端与配置保持不变。详细改动、启动方式和限制见 `UI升级说明.md`，页面截图见 `UI_新版截图/`。


## Agent 修复验收

详细字段、限制及测试记录见 `Agent行为修复说明.md`。真实 Kimi 测试使用隔离的虚构用户和临时 SQLite；报告在 `eval/agent_behavior_live.json` 与 `eval/agent_behavior_live_followup.json`。调试模式展示记忆控制、操作、槽位、行动门槛、行动类型和实际召回记忆，普通界面不显示这些字段。


## 真实 LLM Eval v1

固定数据共 134 个场景；评测与业务实现分离，使用当前真实模型和隔离的临时 SQLite。

```powershell
python -m momo.eval_runner --all
python -m momo.eval_runner --category intent
python -m momo.eval_runner --category memory
python -m momo.eval_runner --category safety
python -m momo.eval_runner --validate
```

详细方法、指标分母、恢复运行和人工评分说明见 `eval/EVAL_V1_METHOD.md`。运行结果逐次保存在 `eval_results/时间戳/`，包含原始模型输出、逐步状态、失败样本、人工评分表和版本快照。Persona 与行动质量未人工评分时显示待评分，不冒充已完成的质量分数。现有 `momo.eval` 是历史联调入口，v1 请使用新的 `momo.eval_runner`。

首次完整运行：`eval_results/20260910T115123410210Z/结果解读与优先级.md`。初始计分与计分器纠错记录均保留；没有依据结果自动修改业务或提示词。

## Eval v2 修复与验证

经产品确认后，记忆结构解析失败与候选质量拒绝不再用内部错误提示替代普通陪伴；失败轮不执行记忆操作、不从其他提取路径生成候选。Response 接收禁存和待确认状态；共同经历与现实事件分类标准统一。Action Gate 统一记录请求、上下文充分性和动作类型；安全分支区分风险主体及首次/后续回应，保持锁定和现实支持入口。

运行 `python -m momo.eval_runner --all --dataset-version v1_1 --workers 4`，再以新运行目录执行 `python -m momo.eval_compare eval_results/运行目录名`。方法、标签变更、评分口径及限制见 `eval/EVAL_V2_METHOD.md`。v1 保持冻结，v2 人工评分不复用旧分数。仍使用原启动命令，重启服务加载新代码。

## 小范围回归 v2.1

敏感记忆先确认内容，再单独同意敏感保存；修改内容后需要重新确认。普通事件候选不抢占当前求助，Reflect 默认不触发行动。IN_APP 只显示选项或文本框之一。Play 结构失败最多重试一次，再尝试文本回复；该文本请求也失败才使用已授权的本地陪伴文字，调试中保留来源与错误。

含行动卡片或已知待确认事实的正文先完成能力校验再展示；其他普通回复继续流式。模型、供应商、LangGraph、SQLite 和安全锁定均保持。

```powershell
python -m unittest discover -s tests -q
python -m momo.eval_runner --all --dataset-version v1_1 --regression-v2-1 --workers 4
```

本轮结果：`eval_results/20260911T070932989644Z/验收结论.md`。定向运行 99 个场景，不代表完整基准或真人质量评分。存在新回归 mic-014，详见报告；后续未经确认不继续改规则。新评分表为该目录的 `human_scores_v2_1_pending.csv`，没有复制旧分数。

使用已安装依赖的环境启动：`python -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501 --browser.gatherUsageStats false`。在项目目录运行，已有服务需重启加载本轮修改。
