> 历史设计资料：当前服务已改为阿里云四模型接入，取消离线 Mock 和界面密钥输入，并独立处理服务错误。当前启动和配置请以项目根目录 README.md 与《接入阿里云调试说明.md》为准。

# Step 2 · Agent State

代码：`momo/models.py`。LangGraph 使用 TypedDict 传递状态，分类器和记忆候选使用 Pydantic 做运行时校验。每轮重新初始化推导字段；仅显式传入短期上下文、拒绝状态与安全锁存，防止上一轮状态串入下一轮。

|字段|类型 / 用途|写入者|读取者|
|---|---|---|---|
|user_id|str，数据隔离键|入口|记忆读写|
|user_input|str，1–4000 字当前输入|入口|安全、分类、生成、候选|
|intent / intent_confidence|五类字符串 / 0–1|intent_node|上下文、回应、微行动|
|emotion / emotion_confidence|四类字符串 / 0–1|emotion_node；安全分支|回应、微行动、调试|
|risk_level / risk_reason|Normal/High/Unknown 与原因|safety_node|路由、安全回应|
|short_term_context|list[dict]，最近 8 条消息|入口|安全、上下文|
|retrieved_memory|list[dict]，最多 3 条有效记忆|memory_retrieval_node|上下文、调试|
|persona_context|str，稳定人格与本轮策略|context_node|response_node|
|relationship_stage|str，默认初识且不自动升级|入口|上下文|
|micro_action_candidate|dict 或 None，最多一个|micro_action_node|final_response_node、UI|
|draft_response / final_response|str，初稿与经检查回复|response / final_response_node|最终检查 / UI|
|memory_candidate|list[dict]，最多一个待确认候选|memory_candidate_node|写入闸门、UI|
|memory_status|str，不宣称未发生的保存|memory_write_node|UI|
|action_declined|bool，拒绝后保持，明确请求行动才解除|入口、micro_action_node|微行动|
|safety_latched|bool，本会话风险尚未解除|入口、安全节点|下一轮安全检查|
|trace / errors|list[str]，节点名 / 错误类型，不记录原文|各节点|开发侧栏、测试|

Pydantic JSON Schema 由 `python -m momo.export` 导出到 schemas。Mock 的 confidence 是测试常量，不是校准概率。接入真实模型时应独立做标定。

这里没有把 TypedDict 当作运行时验证器；模型输出必须经过对应 Pydantic 模型。持久化采用参数化 SQL 和用户作用域，不能只依靠类型注解保证隔离。
