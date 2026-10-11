"""界面回归测试：替换外部传输，不提供生产离线模式。"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import streamlit as st
from streamlit.testing.v1 import AppTest
from momo.memory import MemoryStore
from momo.mock_llm import LLMConfig, ModelAPIError
from test_system import TestLLM

class DemoTests(unittest.TestCase):
    def setUp(self):
        """隔离数据库和配置，保证测试不会使用真实密钥或联网。"""
        st.cache_resource.clear()
        self.tmp=tempfile.TemporaryDirectory()
        self.store=MemoryStore(Path(self.tmp.name)/'ui.db')
        self.patches=[patch('momo.memory.MemoryStore',return_value=self.store),
            patch('momo.mock_llm.load_config',return_value=LLMConfig(api_key='test-not-real')),
            patch('momo.mock_llm.AliyunLLM._request',TestLLM._request)]
        for p in self.patches: p.start()
        self.app=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'app.py'),default_timeout=15).run()
        next(b for b in self.app.button if b.label=='陪我聊聊').click().run()

    def tearDown(self):
        for p in reversed(self.patches): p.stop()
        st.cache_resource.clear()
        self.tmp.cleanup()

    def test_navigation_and_configuration(self):
        """普通页面不展示密钥配置，开发者模式可主动测试连接。"""
        app=self.app
        self.assertEqual(len(app.radio),0)
        self.assertTrue(all(any(b.key=='nav_'+n for b in app.button) for n in ['首页','聊天','记忆','我们','设置']))
        for name in ['记忆','我们','设置','首页']:
            next(b for b in app.button if b.key=='nav_'+name).click().run()
            self.assertEqual(len(app.exception),0)
            self.assertEqual(len(app.selectbox),0)
            self.assertEqual(len(app.text_input),0)
        next(b for b in app.button if b.key=='nav_设置').click().run()
        next(t for t in app.toggle if t.label=='开发者模式').set_value(True).run()
        next(b for b in app.button if b.label.startswith('测试连接')).click().run()
        self.assertTrue(app.success)

    def test_sensitive_candidate_requires_second_screen_and_edit_reconfirmation(self):
        app=self.app
        app.chat_input[0].set_value('家庭情况：我已经结婚了').run()
        c=app.session_state['pending_items'][0]
        self.assertFalse(any(x.label=='我明确同意保存这条敏感信息' for x in app.checkbox))
        next(b for b in app.button if b.key=='save_'+c['id']).click().run()
        self.assertEqual(self.store.list('local-single-tester'),[])
        self.assertTrue(next(b for b in app.button if b.key=='save_'+c['id']).disabled)
        next(b for b in app.button if b.key=='revise_'+c['id']).click().run()
        next(t for t in app.text_area if t.key=='draft_'+c['id']).set_value('家庭情况：已婚').run()
        self.assertFalse(any(x.label=='我明确同意保存这条敏感信息' for x in app.checkbox))
        next(b for b in app.button if b.key=='save_'+c['id']).click().run()
        next(x for x in app.checkbox if x.label=='我明确同意保存这条敏感信息').check().run()
        self.assertEqual(self.store.list('local-single-tester'),[])
        next(b for b in app.button if b.key=='save_'+c['id']).click().run()
        self.assertEqual(len(self.store.list('local-single-tester')),1)
        self.assertEqual(len(app.exception),0)

    def test_error_does_not_show_safety_or_fake_reply(self):
        """服务故障不会生成助手回复或安全监护面板。"""
        with patch('momo.mock_llm.AliyunLLM._request',side_effect=ModelAPIError('接口超时')):
            self.app.chat_input[0].set_value('你好').run()
        self.assertEqual(len(self.app.exception),0)
        self.assertEqual(self.app.session_state['messages'],[{'role':'user','content':'你好'}])
        self.assertTrue(self.app.error)
        self.assertFalse(any('安全监护' in s.value for s in self.app.subheader))

    def test_sensitive_plan_two_confirmations(self):
        from momo.models import MemoryControlResult
        value=MemoryControlResult(intent='MEMORY_CREATE',operations=['CREATE'],slots=['relationship_status'],replacements=[dict(kind='Identity',slot='relationship_status',content='已婚',sensitivity=False)]).model_dump()
        plan=self.store.prepare_plan('local-single-tester',value)
        app=self.app;app.session_state['memory_plans']=[plan];app.run()
        next(b for b in app.button if b.key=='apply_plan_0').click().run()
        self.assertEqual(self.store.list('local-single-tester'),[])
        next(c for c in app.checkbox if c.label=='我明确同意保存本次敏感信息').check().run()
        self.assertEqual(self.store.list('local-single-tester'),[])
        next(b for b in app.button if b.key=='apply_plan_0').click().run()
        self.assertEqual(len(self.store.list('local-single-tester')),1)
        self.assertFalse(app.exception)

    def test_edit_to_sensitive_requires_two_confirmations(self):
        from momo.memory import fact_candidate
        c=fact_candidate('local-single-tester',dict(kind='Identity',slot='other',content='喜欢读书',sensitivity=False,importance=.9,confidence=.9))
        self.store.write(c,'local-single-tester',{c['id']})
        app=self.app
        next(b for b in app.button if b.key=='nav_记忆').click().run()
        next(b for b in app.button if b.key=='edit_'+c['memory_key']).click().run()
        next(t for t in app.text_area if t.key=='edittext_'+c['memory_key']).set_value('已经结婚了').run()
        next(b for b in app.button if b.key=='update_'+c['memory_key']).click().run()
        self.assertEqual(self.store.list('local-single-tester')[0]['content'],'喜欢读书')
        next(x for x in app.checkbox if x.label=='我明确同意保存修改后的敏感信息').check().run()
        next(b for b in app.button if b.key=='update_'+c['memory_key']).click().run()
        self.assertEqual(self.store.list('local-single-tester')[0]['content'],'已经结婚了')
        self.assertFalse(app.exception)

    def test_action_input_modes_are_exclusive_in_ui(self):
        app=self.app
        for mode,options in [('choice',['面试','简历']),('text',[])]:
            app.session_state['action']={'title':'试一试','action_type':'IN_APP','input_mode':mode,'options':options,'input_prompt':'请填写','optional':True}
            app.session_state['action_started']=True;app.run()
            self.assertEqual(any(x.key=='action_answer_choice' for x in app.selectbox),mode=='choice')
            self.assertEqual(any(x.key=='action_answer_text' for x in app.text_area),mode=='text')
            self.assertFalse(app.exception)

    def test_user_message_exists_before_model_request(self):
        """开始第一项模型请求前，用户消息已经保存且渲染。"""
        seen=[]
        def inspect_request(client,stage,instructions,data,schema=None):
            seen.append(dict(st.session_state.messages[-1]))
            return TestLLM._request(client,stage,instructions,data,schema)
        with patch('momo.mock_llm.AliyunLLM._request',inspect_request):
            self.app.chat_input[0].set_value('你好').run()
        self.assertTrue(seen)
        self.assertTrue(all(x=={'role':'user','content':'你好'} for x in seen))
        self.assertEqual(len(self.app.session_state['messages']),2)

    def test_pending_survives_next_turn_and_edit_save(self):
        app=self.app
        app.chat_input[0].set_value('我喜欢简短回复').run()
        candidate=app.session_state['pending_items'][0]
        app.chat_input[0].set_value('今天工作还算顺利').run()
        self.assertTrue(any(c['id']==candidate['id'] for c in app.session_state['pending_items']))
        next(b for b in app.button if b.key=='nav_记忆').click().run()
        next(b for b in app.button if b.key=='revise_'+candidate['id']).click().run()
        next(t for t in app.text_area if t.key=='draft_'+candidate['id']).set_value('我喜欢详细回复').run()
        next(b for b in app.button if b.key=='save_'+candidate['id']).click().run()
        self.assertEqual(self.store.list('local-single-tester')[0]['content'],'我喜欢详细回复')
        self.assertEqual(len(app.exception),0)
        fresh=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'app.py')).run()
        self.assertEqual(fresh.session_state['user_id'],'local-single-tester')
        next(b for b in fresh.button if b.key=='nav_记忆').click().run()
        self.assertTrue(any(m.value=='我喜欢详细回复' for m in fresh.markdown))

    def test_action_accept_is_not_completion_and_refusal_unchanged(self):
        app=self.app
        app.chat_input[0].set_value('给我一个小步骤').run()
        self.assertIsNotNone(app.session_state['action'])
        next(b for b in app.button if b.label=='试试看').click().run()
        self.assertIsNotNone(app.session_state['action'])
        self.assertFalse(app.session_state['declined'])
        next(b for b in app.button if b.label=='今天算了').click().run()
        self.assertTrue(app.session_state['declined'])
        self.assertIsNone(app.session_state['action'])
        self.assertEqual(app.session_state['messages'][-2]['content'],'暂时不做')

    def test_debug_and_schema_hidden_by_default(self):
        app=self.app
        self.assertEqual(len(app.json),0)
        next(b for b in app.button if b.key=='nav_记忆').click().run()
        labels=' '.join(x.value for x in app.subheader)
        self.assertNotIn('Identity',labels)
        self.assertNotIn('Preference',labels)
        next(t for t in app.toggle if t.label=='开发者模式').set_value(True).run()
        self.assertGreater(len(app.json),0)

    def test_memory_reset_and_farewell(self):
        """确认记忆、告别安全分支、重置对话和清空记忆互不混淆。"""
        app=self.app
        app.chat_input[0].set_value('记住：我喜欢简短回复').run()
        next(b for b in app.button if b.label=='记住').click().run()
        user=app.session_state['user_id']
        self.assertEqual(len(self.store.list(user)),1)
        app.chat_input[0].set_value('最后再看一眼这个世界，谢谢你的陪伴').run()
        self.assertTrue(any('安全支持' == s.value for s in app.title))
        app.selectbox[0].select('中国大陆').run()
        self.assertEqual(len(app.get('link_button')),3)
        next(b for b in app.button if b.label=='返回对话').click().run()
        self.assertEqual(app.session_state['api_calls'],[])
        next(b for b in app.button if b.key=='nav_设置').click().run()
        next(b for b in app.button if b.label=='重置演示对话').click().run()
        self.assertEqual(app.session_state['messages'],[])
        self.assertEqual(len(self.store.list(user)),1)
        next(c for c in app.checkbox if '清空全部' in c.label).set_value(True).run()
        next(b for b in app.button if b.label=='清空演示记忆').click().run()
        self.assertEqual(self.store.list(user),[])
        self.assertEqual(len(app.exception),0)




    def test_in_app_submission_is_a_message_not_automatic_memory(self):
        app=self.app
        app.chat_input[0].set_value('给我一个小步骤').run()
        next(b for b in app.button if b.label=='试试看').click().run()
        next(t for t in app.text_area if t.key=='action_answer_text').set_value('最担心面试时忘词').run()
        next(b for b in app.button if b.label=='提交给 MOMO').click().run()
        self.assertFalse(app.exception)
        self.assertTrue(any(m['role']=='user' and m['content']=='最担心面试时忘词' for m in app.session_state['messages']))
        self.assertEqual(self.store.list('local-single-tester'),[])

    def test_memory_control_confirm_and_history_boundary(self):
        from momo.models import MemoryControlResult
        app=self.app
        value=MemoryControlResult(intent='MEMORY_CREATE',operations=['CREATE'],slots=['name','job'],replacements=[
            dict(kind='Identity',slot='name',content='我叫小豆'),dict(kind='Identity',slot='job',content='我是英语老师')]).model_dump()
        with patch('momo.mock_llm.AliyunLLM.control',return_value=value):
            app.chat_input[0].set_value('我叫小豆，是英语老师').run()
        self.assertFalse(app.exception);self.assertEqual(self.store.list('local-single-tester'),[])
        next(b for b in app.button if b.label=='确认调整').click().run()
        self.assertFalse(app.exception);self.assertEqual(len(self.store.list('local-single-tester')),2)
        self.assertEqual(app.session_state['context_start'],len(app.session_state['messages']))
        self.assertEqual(app.session_state['memory_plans'],[])

if __name__=='__main__': unittest.main()
