import html
import json
import re
from pathlib import Path
from .models import IntentResult,EmotionResult,SafetyResult,MemoryCandidate,MicroAction
from .memory import DDL

ROOT=Path(__file__).resolve().parents[1]

def main():
    """在交付阶段导出数据结构、设计文档和可编辑流程图。
    
    参数：
        无；读取项目模型、DDL 和 docs 中的九步文档。
    
    返回：
        None。
    
    创建 schemas 目录，并写入或覆盖 JSON Schema、SQL、合并 Markdown、Mermaid 和 SVG 文件。
    """
    (ROOT/'schemas').mkdir(exist_ok=True)
    for model in [IntentResult,EmotionResult,SafetyResult,MemoryCandidate,MicroAction]:
        (ROOT/'schemas'/f'{model.__name__}.json').write_text(json.dumps(model.model_json_schema(),ensure_ascii=False,indent=2),encoding='utf-8')
    (ROOT/'schemas/memory.sql').write_text(DDL,encoding='utf-8')
    docs=sorted((ROOT/'docs').glob('0[1-9]_*.md'))
    combined='# MOMO AI 系统设计文档\n\n版本：0.1 · 本地 Mock 教学实现\n\n建议依次阅读九个步骤；运行入口和文件导航见 README。\n\n'
    combined+='\n\n---\n\n'.join(p.read_text(encoding='utf-8') for p in docs)
    (ROOT/'MOMO_AI_系统设计文档.md').write_text(combined,encoding='utf-8')
    flow=re.search(r'```mermaid\n(.*?)```',docs[0].read_text(encoding='utf-8'),re.S).group(1)
    (ROOT/'MOMO_AI_Workflow.mmd').write_text(flow,encoding='utf-8')
    svg=['<svg xmlns="http://www.w3.org/2000/svg" width="1120" height="1510" viewBox="0 0 1120 1510">',
         '<defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0 0L8 4L0 8" fill="#7b908b"/></marker></defs>',
         '<rect width="1120" height="1510" fill="#f5f8f4"/>',
         '<style>text{font-family:"Microsoft YaHei",sans-serif;fill:#26473e}.small{font-size:15px;fill:#667b73}.label{font-size:20px;font-weight:600}.en{font-size:13px;fill:#667b73}</style>',
         '<text x="64" y="68" font-size="34" font-weight="700">MOMO · AI 系统流程</text>',
         '<text x="64" y="104" class="small">先倾听，再连接现实生活　/　Python + LangGraph + SQLite + Streamlit</text>']
    nodes=[('用户输入','User Input'),('安全检查','Safety Check'),('识别当前意图','Intent Detection'),('理解情绪线索','Emotion Understanding'),('检索有效记忆','Memory Retrieval · Top 3'),('组装人格与上下文','Persona + Context'),('生成倾听回应','Response Generation'),('判断是否提供微行动','Micro Action · Zero or One'),('检查并形成最终回复','Final Response'),('提取记忆候选','Memory Candidate · Current Input Only'),('判断是否可保存','Memory Gate · Await Consent'),('本轮结束','End')]
    for i,(cn,en) in enumerate(nodes):
        y=145+i*105
        color='#dceee3' if i==1 else '#ffffff'
        svg.append(f'<rect x="64" y="{y}" width="500" height="76" rx="18" fill="{color}" stroke="#ceddd2"/>')
        svg.append(f'<text x="88" y="{y+31}" class="label">{i+1:02d}　{cn}</text><text x="135" y="{y+56}" class="en">{en}</text>')
        if i<11:
            svg.append(f'<path d="M314 {y+76}V{y+100}" fill="none" stroke="#7b908b" stroke-width="2" marker-end="url(#arrow)"/>')
    svg.extend([
        '<path d="M564 288H660" stroke="#7b908b" stroke-width="2" marker-end="url(#arrow)"/><text x="579" y="238" class="small">High / Unknown</text>',
        '<rect x="674" y="250" width="384" height="236" rx="20" fill="#fff0e8" stroke="#e6c9b4"/>',
        '<text x="700" y="288" class="label">安全支持分支</text>',
        '<text x="700" y="325" class="small">High：告别 / 明确危机 → 直接展示</text>',
        '<text x="700" y="356" class="small">Unknown：含糊表达 / 故障 → 确认安全</text>',
        '<text x="700" y="397" class="small">简短稳定回应，鼓励现实支持</text>',
        '<text x="700" y="428" class="small">跳过普通生成、记忆与微行动</text>',
        '<text x="700" y="459" class="small">不诊断，不宣称真人监护</text>',
        '<path d="M1058 368H1080V1338H569" fill="none" stroke="#7b908b" stroke-width="2" marker-end="url(#arrow)"/>',
        '<text x="340" y="344" class="small">Normal</text>',
        '<rect x="674" y="610" width="384" height="190" rx="20" fill="#edf1fa"/>',
        '<text x="700" y="649" class="label">微行动的四道门槛</text>',
        '<text x="700" y="686" class="small">明确 Action 意图 · Normal 风险</text>',
        '<text x="700" y="717" class="small">没有被情绪压倒 · 尊重拒绝</text>',
        '<text x="700" y="758" class="small">最多一个；可拒绝；无关系奖励</text>',
        '<rect x="674" y="944" width="384" height="266" rx="20" fill="#e8f0e7"/>',
        '<text x="700" y="983" class="label">用户确认后才写入 SQLite</text>',
        '<text x="700" y="1021" class="small">归属与完整性 → 价值与确定性</text>',
        '<text x="700" y="1052" class="small">排除禁存内容 → 敏感性 → 时效</text>',
        '<text x="700" y="1083" class="small">明确确认 → 敏感内容单独确认</text>',
        '<text x="700" y="1114" class="small">禁止重存检查 → 幂等写入</text>',
        '<text x="700" y="1163" class="small">未确认候选仅留会话；用户可删除</text>',
        '<path d="M564 1233H640V1130H670" fill="none" stroke="#7b908b" stroke-width="2" stroke-dasharray="5 5" marker-end="url(#arrow)"/>',
        '<text x="64" y="1430" class="small">本地 Mock 教学实现：验证流程与边界，不代表真实模型准确率或危机识别能力。</text>',
        '<text x="64" y="1463" class="small">虚线为用户确认后的独立写入操作；对话本轮不会等待确认，也不提前保存。</text></svg>'])
    (ROOT/'MOMO_AI_Workflow.svg').write_text(''.join(svg),encoding='utf-8')

if __name__=='__main__': main()
