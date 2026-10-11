"""Agent 行为回归：隔离数据库，控制模型返回，验证程序门槛与确认事务。"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from momo.memory import MemoryStore, fact_candidate
from momo.models import initial_state, MemoryControlResult
from momo.graph import build_graph
from test_system import TestLLM

class AgentBehaviorTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.store=MemoryStore(Path(self.tmp.name)/'db')
    def tearDown(self): self.tmp.cleanup()
    def fact(self,slot,content):
        return fact_candidate('u',dict(kind='Identity',slot=slot,content=content,importance=.9,confidence=.9))
    def save(self,slot,content):
        c=self.fact(slot,content);self.store.write(c,'u',{c['id']});return c
    def control(self,**values): return MemoryControlResult(**{'intent':'NONE',**values}).model_dump()
    def run_turn(self,text,control=None,emotion='Neutral',intent='Companion',**kwargs):
        llm=TestLLM()
        with patch.object(llm,'control',return_value=control or self.control()),patch.object(llm,'emotion',return_value={'emotion':emotion,'confidence':1}),patch.object(llm,'intent',return_value={'intent':intent,'confidence':1}):
            return build_graph(self.store,llm).invoke(initial_state('u',text,**kwargs))
    def test_name_job_update_atomic_and_confirmed(self):
        n=self.save('name','我叫小林');j=self.save('job','我是物理老师')
        c=self.control(intent='MEMORY_UPDATE',operations=['UPDATE'],slots=['name','job'],target_keys=[n['memory_key'],j['memory_key']],replacements=[dict(kind='Identity',slot='name',content='我叫小豆'),dict(kind='Identity',slot='job',content='我是英语老师')])
        state=self.run_turn('不是，我叫小豆，是英语老师',c)
        self.assertEqual(len(self.store.list('u')),2)
        self.assertEqual(self.store.apply_plan('u',state['memory_plan']),'等待用户确认')
        self.assertEqual(self.store.apply_plan('u',state['memory_plan'],True),'已完成记忆操作')
        self.assertEqual({r['content'] for r in self.store.list('u')},{'我叫小豆','我是英语老师'})
        self.assertFalse(state['micro_action_allowed'])
    def test_query_retrieves_identity_without_lexical_overlap(self):
        c=self.save('job','我是物理老师');self.store.update('u',c['memory_key'],'我是英语老师')
        state=self.run_turn('我是谁',self.control(intent='MEMORY_QUERY'),history=[{'role':'user','content':'我是物理老师'}],ordinary_history=[])
        self.assertEqual(state['active_memory_used_for_context'][0]['content'],'我是英语老师')
        self.assertNotIn('物理',state['persona_context'])
    def test_delete_and_block_are_distinct(self):
        j=self.save('job','我是物理老师')
        block=self.store.prepare_plan('u',self.control(intent='MEMORY_BLOCK',operations=['BLOCK'],slots=['job']))
        self.assertEqual(self.store.apply_plan('u',block,True),'已完成记忆操作')
        self.assertEqual(len(self.store.list('u')),1)
        delete=self.store.prepare_plan('u',self.control(intent='MEMORY_DELETE',operations=['DELETE'],slots=['job'],target_keys=[j['memory_key']]))
        self.assertEqual(self.store.apply_plan('u',delete,True),'已完成记忆操作')
        self.assertEqual(self.store.list('u'),[])
        c=self.fact('job','我是英语老师');self.assertIn('禁止',self.store.write(c,'u',{c['id']}))
    def test_delete_all_work_keeps_unrelated_name(self):
        old=self.save('other','小林，物理老师')
        plan=self.store.prepare_plan('u',self.control(intent='MEMORY_DELETE',operations=['DELETE'],slots=['job'],target_keys=[old['memory_key']],replacements=[dict(kind='Identity',slot='name',content='我叫小林')]))
        self.store.apply_plan('u',plan,True)
        self.assertEqual([r['slot'] for r in self.store.list('u')],['name'])
    def test_stale_plan_cannot_overwrite_edit(self):
        old=self.save('job','物理老师')
        plan=self.store.prepare_plan('u',self.control(intent='MEMORY_DELETE',operations=['DELETE'],slots=['job'],target_keys=[old['memory_key']]))
        self.store.update('u',old['memory_key'],'英语老师')
        self.assertIn('变化',self.store.apply_plan('u',plan,True));self.assertEqual(len(self.store.list('u')),1)
    def test_vent_and_refusal_no_action(self):
        for text,c in [('我今天很累，就想吐槽',self.control()),('我不想做任何事',self.control(explicit_help=True,refuses_action=True))]:
            state=self.run_turn(text,c);self.assertIsNone(state['micro_action_candidate'])
    def test_overwhelmed_requires_explicit_help(self):
        self.assertFalse(self.run_turn('很累',self.control(),emotion='Overwhelmed',intent='Action')['micro_action_allowed'])
        state=self.run_turn('明天面试焦虑不知道怎么办',self.control(explicit_help=True,topic='面试'),emotion='Overwhelmed')
        self.assertTrue(state['micro_action_allowed']);self.assertEqual(state['action_type'],'IN_APP')
    def test_only_one_clarification(self):
        c=self.control(explicit_help=True,topic='面试',needs_clarification=True)
        first=self.run_turn('帮我准备',c)
        self.assertEqual(first['clarification_count'],1);self.assertFalse(first['micro_action_allowed'])
        second=self.run_turn('英语岗位',c,clarification_count=1,clarification_topic='面试')
        self.assertTrue(second['micro_action_allowed']);self.assertEqual(second['clarification_count'],1)
    def test_offline_schema(self):
        llm=TestLLM()
        with patch.object(llm,'control',return_value=self.control(explicit_help=True)),patch.object(llm,'action',return_value=dict(title='去喝一口水',action_type='OFFLINE')):
            state=build_graph(self.store,llm).invoke(initial_state('u','给个小步骤'))
        self.assertEqual(state['action_type'],'OFFLINE')
    def test_all_memory_control_intents_block_action(self):
        for intent in ['MEMORY_CREATE','MEMORY_UPDATE','MEMORY_DELETE','MEMORY_BLOCK','MEMORY_QUERY']:
            c=self.control(intent=intent,clarification='请确认范围',explicit_help=True)
            state=self.run_turn('处理我的记忆',c,intent='Action')
            self.assertFalse(state['micro_action_allowed']);self.assertEqual(state['micro_action_block_reason'],'记忆控制')
    def test_safety_never_calls_new_control(self):
        llm=TestLLM()
        with patch.object(llm,'control',side_effect=AssertionError('不可调用')):
            state=build_graph(self.store,llm).invoke(initial_state('u','最后再看一眼这个世界，谢谢你的陪伴'))
        self.assertEqual(state['risk_level'],'High');self.assertEqual(state['trace'],['safety_node','safety_response_node'])
    def test_sensitive_transaction_requires_consent(self):
        plan=self.store.prepare_plan('u',self.control(intent='MEMORY_CREATE',operations=['CREATE'],slots=['relationship_status'],replacements=[dict(kind='Identity',slot='relationship_status',content='婚姻状况已婚',sensitivity=True)]))
        self.assertIn('敏感',self.store.apply_plan('u',plan,True));self.assertEqual(self.store.list('u'),[])
    def test_action_response_receives_gate_and_no_stale_history(self):
        from momo.mock_llm import AliyunLLM
        state=self.run_turn('我是谁',self.control(intent='MEMORY_QUERY'),history=[{'role':'user','content':'旧职业物理老师'}])
        llm=TestLLM(); captured={}
        def request(stage,instructions,data,schema=None): captured.update(data=data,instructions=instructions);return '暂无已确认记忆'
        with patch.object(llm,'_request',side_effect=request): AliyunLLM.response(llm,state)
        self.assertNotIn('旧职业',json.dumps(captured,ensure_ascii=False))

    def test_delete_plus_block_and_no_new_plan(self):
        j=self.save('job','我是老师')
        c=self.control(intent='MEMORY_DELETE',operations=['DELETE','BLOCK'],slots=['job'],target_keys=[j['memory_key']])
        self.store.apply_plan('u',self.store.prepare_plan('u',c),True)
        self.assertEqual(self.store.list('u'),[])
        new=self.control(intent='MEMORY_CREATE',operations=['CREATE'],slots=['job'],replacements=[dict(kind='Identity',slot='job',content='我是英语老师')])
        state=self.run_turn('我是英语老师',new)
        self.assertIsNone(state['memory_plan']);self.assertIn('禁止',state['final_response'])

    def test_invalid_slot_and_cross_user_target_rejected(self):
        old=self.save('job','教师')
        c=self.control(intent='MEMORY_DELETE',operations=['DELETE'],slots=['job'],target_keys=[old['memory_key']])
        with self.assertRaises(ValueError): self.store.prepare_plan('different-user',c)

    def test_disabled_new_memory_allows_partial_delete(self):
        old=self.save('other','小林，物理老师')
        self.store.set_enabled('u',False)
        value=self.control(intent='MEMORY_DELETE',operations=['DELETE'],slots=['job'],target_keys=[old['memory_key']],replacements=[dict(kind='Identity',slot='name',content='小林')])
        plan=self.store.prepare_plan('u',value)
        self.assertEqual(self.store.apply_plan('u',plan,True),'已完成记忆操作')
        self.assertEqual([r['slot'] for r in self.store.list('u')],['name'])

if __name__=='__main__': unittest.main()
