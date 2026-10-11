"""v2.1 故障注入和保存门槛测试；不混入真实模型成绩。"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from pydantic import ValidationError
from momo.models import initial_state, MemoryControlResult, MicroAction
from momo.memory import MemoryStore, fact_candidate, gate
from momo.graph import build_graph, action_gate_node
from momo.mock_llm import AliyunLLM, ModelAPIError
from test_system import TestLLM


class RegressionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.store=MemoryStore(Path(self.tmp.name)/'db')
    def tearDown(self): self.tmp.cleanup()

    def test_sensitive_slot_cannot_be_downgraded_by_model(self):
        for content in ['已婚','已经结婚了','单身']:
            c=fact_candidate('u',dict(kind='Identity',slot='relationship_status',content=content,importance=.9,confidence=.9,sensitivity=False))
            self.assertTrue(c['sensitivity'])
            self.assertIn('等待用户',self.store.write(c,'u',(),True))
            self.assertIn('敏感',self.store.write(c,'u',{c['id']},False))
            self.assertEqual(self.store.list('u'),[])

    def test_two_consents_required_at_write_boundary(self):
        c=fact_candidate('u',dict(kind='Identity',slot='relationship_status',content='已婚',importance=.9,confidence=.9,sensitivity=False))
        self.assertFalse(gate(c,'u',(),True)[0])
        self.assertFalse(gate(c,'u',{c['id']},False)[0])
        self.assertTrue(self.store.write(c,'u',{c['id']},True).startswith('已保存'))

    def test_unknown_sensitivity_fails_closed(self):
        c=fact_candidate('u',dict(kind='Identity',slot='name',content='小林',importance=.9,confidence=.9,sensitivity=False))
        for invalid in [None,'false',0]:
            self.assertFalse(gate({**c,'sensitivity':invalid},'u',{c['id']},True)[0])
        client=TestLLM()
        with patch.object(client,'_request',return_value=json.dumps({'intent':'MEMORY_CREATE','replacements':[{'kind':'Identity','content':'已婚'}]})):
            with self.assertRaises(json.JSONDecodeError): client.control(initial_state('u','已婚'),[],[])

    def test_automatic_candidate_defers_until_help_response(self):
        control=MemoryControlResult(intent='MEMORY_CREATE',operations=['CREATE'],slots=['other'],
            explicit_help=True,action_requested=True,replacements=[dict(kind='Episodic',slot='other',content='有重要面试',importance=.9,confidence=.9,sensitivity=False)]).model_dump()
        client=TestLLM()
        with patch.object(client,'control',return_value=control),patch.object(client,'intent',return_value={'intent':'Action','confidence':1}):
            state=build_graph(self.store,client).invoke(initial_state('u','明天面试很焦虑，不知道怎么办'))
        self.assertEqual(state['memory_control_intent'],'NONE')
        self.assertTrue(state['micro_action_candidate'])
        self.assertTrue(state['memory_candidate'])
        self.assertLess(state['trace'].index('response_node'),state['trace'].index('memory_candidate_node'))
        self.assertEqual(self.store.list('u'),[])

    def test_reflect_then_explicit_action(self):
        for text in ['只想理解原因','帮我想清楚','先分析一下','我不想做什么','不要给行动建议']:
            state=initial_state('u',text);state.update(risk_level='Normal',intent='Reflect',explicit_help=True,action_requested=True)
            self.assertFalse(action_gate_node(state)['micro_action_allowed'])
        state=initial_state('u','给我一个小行动');state.update(risk_level='Normal',intent='Action',explicit_help=True,action_requested=True)
        self.assertTrue(action_gate_node(state)['micro_action_allowed'])

    def play(self,action_values,text_error=False):
        client=TestLLM()
        control=MemoryControlResult(intent='NONE',explicit_help=True,action_requested=True).model_dump()
        with patch.object(client,'control',return_value=control),patch.object(client,'intent',return_value={'intent':'Play','confidence':1}),patch.object(client,'action',side_effect=action_values) as action,patch.object(client,'response',side_effect=ModelAPIError('测试文本失败') if text_error else None,return_value='我们轻松聊一会儿吧。'):
            state=build_graph(self.store,client).invoke(initial_state('u','陪我猜个谜'))
        return state,action.call_count

    def test_play_invalid_twice_uses_model_text(self):
        bad=dict(title='猜谜',action_type='IN_APP')
        s,n=self.play([bad,bad]);self.assertEqual(n,2)
        self.assertEqual(s['play_retry_count'],1);self.assertTrue(s['play_fallback'])
        self.assertEqual(s['fallback_source'],'model_text');self.assertTrue(s['final_response'])
        self.assertFalse(s['service_error']);self.assertIsNone(s['micro_action_candidate'])
        self.assertEqual(len(s['action_errors']),2)

    def test_play_text_failure_uses_approved_local_text(self):
        bad=dict(title='猜谜',action_type='IN_APP')
        s,n=self.play([bad,bad],True)
        self.assertEqual(n,2);self.assertEqual(s['fallback_source'],'local_text')
        self.assertTrue(s['final_response']);self.assertFalse(s['service_error'])
        self.assertEqual(s['action_errors'][-1]['stage'],'play_text_fallback')

    def test_play_retry_can_recover(self):
        s,n=self.play([dict(title='猜谜',action_type='IN_APP'),dict(title='猜谜',action_type='IN_APP',input_mode='text',input_prompt='写下答案')])
        self.assertEqual(n,2);self.assertFalse(s['play_fallback']);self.assertTrue(s['micro_action_candidate'])
        self.assertEqual(s['play_retry_count'],1)

    def test_mutually_exclusive_card_schema(self):
        for values in [dict(input_mode='text',options=['a']),dict(input_mode='choice',options=[]),dict(input_mode='choice',options=['a'],text_input=True)]:
            with self.assertRaises(ValidationError): MicroAction(title='试一试',action_type='IN_APP',input_prompt='选或填',**values)

    def test_capability_claim_is_checked_before_display(self):
        s=initial_state('u','帮我选择');s['micro_action_candidate']=dict(input_mode='choice',options=['a','b'])
        s['pending_memory_candidate']=[{'content':'喜好','sensitivity':False}]
        client=TestLLM();shown=[];client.on_text=shown.append
        with patch.object(client,'_request',return_value='我已经记录下了。你也可以自己输入其他答案。先慢慢来。'):
            text=AliyunLLM.response(client,s)
        self.assertNotIn('已经记录',text);self.assertNotIn('自己输入',text)
        self.assertEqual(shown,[text]);self.assertFalse(s['capability_truth']['memory_saved'])
        self.assertTrue(s['capability_truth']['guard_removed_claims'])

    def test_pending_plan_never_claims_already_saved(self):
        s=initial_state('u','记住这件事');s.update(memory_control_intent='MEMORY_CREATE',memory_plan={'candidates':[]})
        client=TestLLM()
        with patch.object(client,'_request') as request:
            text=AliyunLLM.response(client,s)
        request.assert_not_called();self.assertIn('尚未执行',text)


if __name__=='__main__': unittest.main()
