"""固定错误注入验证机制，不作为真实 LLM 评测成绩。"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from momo.models import initial_state, MemoryControlResult
from momo.memory import MemoryStore
from momo.graph import build_graph, safety_response_node, action_gate_node
from momo.mock_llm import local_safety, AliyunLLM
from test_system import TestLLM

class EvalV2FixTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.store=MemoryStore(Path(self.tmp.name)/'db')
    def tearDown(self):
        self.tmp.cleanup()

    def test_invalid_control_keeps_response_but_blocks_all_memory(self):
        client=TestLLM()
        with patch.object(client,'control',side_effect=lambda *a: MemoryControlResult.model_validate_json('{"intent":"MEMORY_CREATE","operations":["、CREATE"]}')),patch.object(client,'candidates') as extract:
            state=build_graph(self.store,client).invoke(initial_state('u','请记住，我已婚'))
        self.assertTrue(state['final_response'])
        self.assertIsNone(state['service_error'])
        self.assertIn('ValidationError',state['errors'])
        self.assertTrue(state['memory_error_details'])
        self.assertTrue(state['memory_suppressed'])
        self.assertFalse(state['micro_action_allowed'])
        extract.assert_not_called()
        self.assertEqual(self.store.list('u'),[])

    def test_low_confidence_is_not_chat_error(self):
        client=TestLLM()
        control=MemoryControlResult(intent='MEMORY_CREATE',operations=['CREATE'],slots=['question_preference'],
            replacements=[dict(kind='Preference',slot='question_preference',content='不喜欢被连续提问',confidence=.75)]).model_dump()
        with patch.object(client,'control',return_value=control),patch.object(client,'response',return_value='抱歉让你不舒服了，我少问一些。') as respond,patch.object(client,'candidates') as extract:
            state=build_graph(self.store,client).invoke(initial_state('u','刚才问太多了'))
        respond.assert_called_once();extract.assert_not_called()
        self.assertIn('抱歉',state['final_response'])
        self.assertFalse(state['pending_memory_candidate'])
        self.assertFalse(state['memory_save_allowed'])
        self.assertIsNone(state['memory_plan'])

    def test_block_state_reaches_response(self):
        s=initial_state('u','我是老师')
        s.update(blocked_slots=['job'],memory_operation=['BLOCK'],memory_save_allowed=False)
        client=TestLLM()
        with patch.object(client,'_request',return_value='不会保存这类信息') as request:
            AliyunLLM.response(client,s)
        data=request.call_args.args[2]
        self.assertEqual(data['blocked_slots'],['job'])
        self.assertFalse(data['memory_save_allowed'])

    def test_third_person_does_not_latch_self(self):
        for text in ['别人说“最后再看一眼这个世界”，我不知道怎么理解。','我朋友说他不想活了。','别人说“我要自杀”。']:
            result=local_safety(text)
            self.assertEqual(result['risk_level'],'Unknown')
            self.assertEqual(result['subject'],'THIRD_PERSON')

    def test_quote_does_not_hide_own_risk(self):
        self.assertEqual(local_safety('朋友说“不想活了”，但我现在准备结束自己的生命。')['risk_level'],'High')
        self.assertEqual(local_safety('最后再看一眼这个世界，谢谢你的陪伴')['risk_level'],'High')

    def test_followup_keeps_protection_without_duplicate(self):
        first=initial_state('u','危机');first.update(risk_level='High',safety_subject='FIRST_PERSON')
        follow=initial_state('u','你今天怎么样',latched=True)
        follow.update(risk_level='High',risk_reason='本会话安全关注尚未解除',safety_subject='FIRST_PERSON')
        a=safety_response_node(first);b=safety_response_node(follow)
        self.assertNotEqual(a['final_response'],b['final_response'])
        self.assertIn('紧急服务',b['final_response'])
        self.assertIsNone(b['micro_action_candidate'])
        self.assertTrue(follow['safety_latched'])

    def test_gate_preserves_refusal_and_single_clarification(self):
        s=initial_state('u','让我选一个');s.update(risk_level='Normal',action_requested=True,context_sufficient=False)
        first=action_gate_node(s);self.assertFalse(first['micro_action_allowed'])
        s.update(first);second=action_gate_node(s);self.assertTrue(second['micro_action_allowed'])
        s.update(refuses_action=True);self.assertFalse(action_gate_node(s)['micro_action_allowed'])

if __name__=='__main__': unittest.main()
