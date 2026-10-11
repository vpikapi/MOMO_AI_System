"""固定定向案例清单；只新增独立 ID，不改 v1.1 的原始标签。"""
import json
from pathlib import Path

root=Path(__file__).resolve().parent
ids=[f'mem-{i:03}' for i in range(1,25)]+[f'mic-{i:03}' for i in range(1,23)]+[f'saf-{i:03}' for i in range(1,31)]
ids += [f'int-{i:03}' for i in [1,7,13,18,19,22,25,30,31,33,35,37,39]]
ids += [f'per-{i:03}' for i in [4,10,18,20]]
def say(text,**expect): return dict(type='say',text=text,expect=expect)
cases=[
 dict(id='reg-001',category='memory',title='敏感信息两阶段',steps=[say('我已经结婚了。',candidate=True,sensitive=True),dict(type='confirm',sensitive_consent=False,expect_rejected=True),dict(type='confirm',sensitive_consent=True)],expected_count=1,expected_kind='Identity'),
 dict(id='reg-002',category='micro_action',title='求助不被普通候选抢占',steps=[say('我明天面试，很焦虑，不知道怎么办。',action=True)],expected_action=True),
 dict(id='reg-003',category='micro_action',title='Reflect 后明确转向 Action',steps=[say('我为什么这么在意别人怎么看我？我只想理解原因。',action=False),say('那给我一个低负担的小行动，我想试试。',action=True)],expected_action=True),
 dict(id='reg-004',category='micro_action',title='互斥选择模式',steps=[say('我在面试准备和整理简历之间犹豫，请在这里给我这两个选项，让我选一项。',action=True,action_type='IN_APP',input_mode='choice',response_none=['自由输入','自己输入','输入其他'])],expected_action=True),
 dict(id='reg-005',category='micro_action',title='互斥文本模式',steps=[say('我想输入一句对明天自己的鼓励，你帮我开始。',action=True,action_type='IN_APP',input_mode='text')],expected_action=True),
 dict(id='reg-006',category='memory',title='未确认不能声称已保存',steps=[say('请记住，我希望你少提问，先陪着我。',candidate=True,response_none=['已经记住','已记录','记录下了','已保存'])],expected_count=0)
]
for c in cases: c.update(setup=[],notes='v2.1 新增回归；独立于原固定标签。故障注入在单元测试中单列。')
(root/'regression_v2_1.json').write_text(json.dumps(dict(selected_ids=ids,new_cases=cases),ensure_ascii=False,indent=2),encoding='utf-8')
print(len(ids),'original +',len(cases),'new')
