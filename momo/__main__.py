# 命令行演示入口：读取命令行文本，执行一轮工作流并打印完整状态。
import json
import sys
from .graph import build_graph
from .memory import MemoryStore
from .models import initial_state

if __name__ == '__main__':
    graph = build_graph(MemoryStore('data/momo.db'))
    state = graph.invoke(initial_state('cli-demo', ' '.join(sys.argv[1:]) or '明天面试好紧张，给我一个小步骤'))
    print(json.dumps(state,ensure_ascii=False,indent=2))
