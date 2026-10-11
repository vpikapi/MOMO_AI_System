> 历史设计资料：当前服务已改为阿里云四模型接入，取消离线 Mock 和界面密钥输入，并独立处理服务错误。当前启动和配置请以项目根目录 README.md 与《接入阿里云调试说明.md》为准。

# Step 7 · LangGraph 骨架

`momo/graph.py` 每个节点均为独立函数；通过局部更新字典传递 State，依赖由 build_graph 注入。调用示例：

```python
from momo.graph import build_graph
from momo.memory import MemoryStore
from momo.models import initial_state
graph = build_graph(MemoryStore('data/momo.db'))
answer = graph.invoke(initial_state('demo-user', '我只想吐槽'))
print(answer['final_response'])
```

条件边提供显式 path_map：Normal → intent_node；High / Unknown → safety_response_node → END。使用真正的 StateGraph 编译与执行，并不是自制函数列表冒充 LangGraph。实现依据 [官方 Graph API](https://docs.langchain.com/oss/python/langgraph/graph-api)。

正常路径在 final_response_node 后仍同步经过候选与写入判断，再把完整结果交给 UI；目前没有流式展示、队列或后台写入。memory_write_node 只报告闸门结果；UI 用户确认后调用同一个 MemoryStore.write，不会暗中保存。

替换真实 LLM 时实现 MockLLM 的五个接口：safety、intent、emotion、response、candidates。分类返回结构化字典、生成返回文本；禁止让模型直接执行 SQL。配置超时、结构化输出验证、日志脱敏、成本限制与独立安全评测后再讨论部署。本交付没有网络模型调用，不需要 API Key。
