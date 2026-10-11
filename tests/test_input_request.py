"""明确填写识别、控件能力和既有保护的局部回归，不联网。"""
import json
import unittest
from unittest.mock import patch
from momo.models import initial_state
from momo.graph import action_gate_node
from momo.mock_llm import explicit_text_request, input_capability_mismatch, AliyunLLM
from test_system import TestLLM
import test_demo

class InputRequestTests(unittest.TestCase):
    def test_six_explicit_requests_override_only_clarification(self):
        for text in ['我想在这里写一句','让我填一句','给我一个输入框','我想输入一个答案','让我在这里填一下','帮我留个地方写','帮我用一句话写下最担心的事，就在这里输入。']:
            with self.subTest(text=text):
                self.assertTrue(explicit_text_request(text))
                s=initial_state('u',text);s.update(risk_level='Normal',intent='Action',context_sufficient=False,needs_clarification=True)
                out=action_gate_node(s)
                self.assertTrue(out['micro_action_allowed']);self.assertTrue(out['context_sufficient'])
                self.assertFalse(out['needs_clarification']);self.assertEqual(out['clarification_count'],0)
                self.assertEqual(out['requested_input_mode'],'text');self.assertEqual(out['action_type'],'IN_APP')

    def test_ambiguous_negated_quoted_and_offline_not_forced(self):
        for text in ['这个怎么弄？','这里怎么办？','我该填什么？','这个要怎么处理？','不要给我一个输入框','我想在纸上写一句','朋友说“让我输入一个答案”','想在这里选一个，请给我选项']:
            with self.subTest(text=text): self.assertFalse(explicit_text_request(text))

    def test_existing_guards_win(self):
        for values in [dict(risk_level='High'),dict(memory_control_intent='MEMORY_CREATE'),dict(intent='Reflect'),dict(refuses_action=True),dict(memory_suppressed=True)]:
            s=initial_state('u','给我一个输入框');s.update(risk_level='Normal',intent='Action',**{k:v for k,v in values.items() if k not in ['risk_level','intent']})
            s.update(values)
            self.assertFalse(action_gate_node(s)['micro_action_allowed'])

    def test_ambiguous_keeps_one_clarification(self):
        s=initial_state('u','这里怎么办？');s.update(risk_level='Normal',intent='Action',context_sufficient=False,needs_clarification=True)
        first=action_gate_node(s);self.assertFalse(first['micro_action_allowed'])
        s.update(first);second=action_gate_node(s);self.assertTrue(second['micro_action_allowed'])
        self.assertEqual(second['clarification_count'],1);self.assertIsNone(second['requested_input_mode'])

    def test_text_mode_cannot_be_changed_back_to_choice(self):
        s=initial_state('u','让我输入一句');s['requested_input_mode']='text'
        client=TestLLM()
        raw=json.dumps(dict(title='写一句',action_type='IN_APP',input_mode='choice',options=['A','B'],input_prompt='写下内容'))
        with patch.object(client,'_request',return_value=raw): action=client.action(s)
        self.assertEqual(action['input_mode'],'text');self.assertEqual(action['options'],[])

    def test_no_control_cannot_claim_input(self):
        for text in ['你可以在这里输入。','直接写下来就好。','可以在这里填一句。','在下面输入。','也可以自由输入。']:
            self.assertTrue(input_capability_mismatch(text,False))
            self.assertFalse(input_capability_mismatch(text,True))
        self.assertFalse(input_capability_mismatch('在纸上写下一句话。',False))

    def test_stream_never_exposes_nonexistent_input(self):
        client=TestLLM();seen=[];client.on_text=seen.append
        def stream(*args,**kwargs):
            chunks=['我在听。你可以在这','里输入。慢慢来。']
            for c in chunks: client.on_text(c)
            return ''.join(chunks)
        with patch.object(client,'_request',side_effect=stream):
            text=AliyunLLM.response(client,initial_state('u','这里怎么办？'))
        self.assertEqual(''.join(seen),text)
        self.assertNotIn('输入',text);self.assertEqual(text,'我在听。慢慢来。')

class InputCardUITests(unittest.TestCase):
    setUp=test_demo.DemoTests.setUp
    tearDown=test_demo.DemoTests.tearDown
    def test_text_card_is_rendered_without_try_button(self):
        app=self.app
        app.chat_input[0].set_value('给我一个输入框').run()
        self.assertFalse(app.session_state['action_started'])
        self.assertEqual(app.session_state['action']['input_mode'],'text')
        self.assertTrue(any(x.key=='action_answer_text' for x in app.text_area))
        self.assertFalse(any(x.key=='action_answer_choice' for x in app.selectbox))
        self.assertFalse(app.exception)

if __name__=='__main__': unittest.main()
