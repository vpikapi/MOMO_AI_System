"""密钥延迟加载与会话隔离回归，不使用真实密钥或网络。"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from streamlit.testing.v1 import AppTest
from momo.memory import MemoryStore
from momo.mock_llm import load_config, ModelAPIError, LLMConfig

class SessionKeyTests(unittest.TestCase):
    def test_override_and_local_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'config.toml'
            self.assertEqual(load_config(path, ' session-test ').api_key.get_secret_value(),'session-test')
            with self.assertRaises(ModelAPIError): load_config(path)
            path.write_text('model="qwen3.8-flash"\napi_key="local-test"',encoding='utf-8')
            self.assertEqual(load_config(path,'session-test').api_key.get_secret_value(),'session-test')
            self.assertEqual(load_config(path,'  ').api_key.get_secret_value(),'local-test')
            self.assertEqual(load_config(path,'session-test').model,'qwen3.8-flash')
            self.assertNotIn('session-test',path.read_text())

    def test_lazy_ui_and_key_lifecycle(self):
        with tempfile.TemporaryDirectory() as tmp, patch('momo.memory.MemoryStore',return_value=MemoryStore(Path(tmp)/'test.db')), patch('momo.mock_llm.load_config') as loader, patch('momo.mock_llm.AliyunLLM') as client:
            loader.return_value=LLMConfig(api_key='test-only')
            client.return_value.check_connection.return_value='ok'
            app=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'app.py'),default_timeout=20).run()
            next(b for b in app.button if b.key=='nav_聊天').click().run()
            loader.assert_not_called()
            self.assertFalse(app.error)
            self.assertFalse(app.chat_input[0].disabled)
            app.toggle[0].set_value(True).run()
            app.text_input[0].set_value('session-test').run()
            loader.assert_not_called()
            next(b for b in app.button if b.label.startswith('测试连接')).click().run()
            loader.assert_called_with(api_key_override='session-test')
            app.toggle[0].set_value(False).run()
            self.assertEqual(app.session_state['session_api_key'],'session-test')
            other=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'app.py'),default_timeout=20).run()
            self.assertNotIn('session_api_key',other.session_state)
            app.toggle[0].set_value(True).run()
            app.text_input[0].set_value('').run()
            next(b for b in app.button if b.label.startswith('测试连接')).click().run()
            loader.assert_called_with()
            loader.side_effect=ModelAPIError('missing config')
            app.chat_input[0].set_value('你好').run()
            self.assertTrue(app.error)
            self.assertFalse(app.exception)

if __name__=='__main__': unittest.main()

