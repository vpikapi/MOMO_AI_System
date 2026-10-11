"""验证真实适配器的请求协议与失败边界；HTTP 替身只用于单元测试。"""
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from momo.mock_llm import AliyunLLM,LLMConfig,ModelAPIError,SUPPORTED_MODELS,load_config

def reply(content,finish='stop'):
    """构造兼容接口返回体，供传输测试读取。"""
    return io.BytesIO(json.dumps({'choices':[{'finish_reason':finish,'message':{'content':content}}]}).encode())

class AliyunTests(unittest.TestCase):
    def client(self,model='kimi-k3'):
        return AliyunLLM(LLMConfig(model=model,api_key='test-not-real'))

    def test_four_model_parameters(self):
        for model in SUPPORTED_MODELS:
            with self.subTest(model=model),patch('momo.mock_llm.urlopen',return_value=reply('{"risk_level":"Normal","reason":"问候"}')) as send:
                c=self.client(model)
                self.assertEqual(c.safety('你好',[])['risk_level'],'Normal')
                req=send.call_args.args[0]
                body=json.loads(req.data)
                self.assertEqual(req.full_url,'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions')
                self.assertEqual(body['model'],model)
                self.assertEqual(body['enable_thinking'],model=='kimi-k3')
                self.assertEqual(body['response_format'],{'type':'json_object'})
                self.assertGreater(body['max_completion_tokens'],8192)
                self.assertNotIn('test-not-real',repr(c.config))

    def test_invalid_or_incomplete_response_fails(self):
        for content,finish in [('bad','stop'),('{"risk_level":"normal","reason":"x"}','stop'),('', 'stop'),('{}','length')]:
            with self.subTest(content=content),patch('momo.mock_llm.urlopen',return_value=reply(content,finish)):
                with self.assertRaises(ModelAPIError): self.client().safety('你好',[])

    def test_connection_requires_both_results(self):
        with patch('momo.mock_llm.urlopen',side_effect=[reply('你好'),reply('{"risk_level":"High","reason":"wrong"}')]):
            with self.assertRaises(ModelAPIError): self.client().check_connection()

    def test_http_error_is_sanitized(self):
        c=self.client()
        with patch('momo.mock_llm.urlopen',side_effect=HTTPError('hidden',401,'test-not-real',{},None)):
            with self.assertRaises(ModelAPIError) as error: c.safety('你好',[])
        self.assertNotIn('test-not-real',str(error.exception))
        self.assertEqual(c.calls[-1]['http_status'],401)

    def test_local_high_risk_never_calls_transport(self):
        with patch('momo.mock_llm.urlopen') as send:
            self.assertEqual(self.client().safety('最后再看一眼这个世界',[])['risk_level'],'High')
            send.assert_not_called()

    def test_stream_uses_content_only_and_requires_completion(self):
        pieces=[]
        client=AliyunLLM(LLMConfig(api_key='test-not-real'),on_text=pieces.append)
        events=[{'choices':[{'delta':{'reasoning_content':'不可显示的思考'}}]},
                {'choices':[{'delta':{'content':'你好，我在这里听你说。可以慢慢来。'}}]},
                {'choices':[{'delta':{'content':'我们按你的节奏聊。'},'finish_reason':'stop'}]}]
        wire=''.join('data: '+json.dumps(e)+'\n\n' for e in events)+'data: [DONE]\n\n'
        with patch('momo.mock_llm.urlopen',return_value=io.BytesIO(wire.encode())) as send:
            result=client._request('response','test',{})
        self.assertEqual(''.join(pieces),result)
        self.assertGreater(len(pieces),1)
        self.assertNotIn('思考',result)
        self.assertTrue(json.loads(send.call_args.args[0].data)['stream'])
        with patch('momo.mock_llm.urlopen',return_value=io.BytesIO(('data: '+json.dumps(events[1])+'\n').encode())):
            with self.assertRaises(ModelAPIError): client._request('response','test',{})

    def test_config_missing_and_invalid(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'config.toml'
            with self.assertRaises(ModelAPIError): load_config(p)
            p.write_text('api_key="test-not-real"\nmodel="not-supported"',encoding='utf-8')
            with self.assertRaises(ModelAPIError): load_config(p)

if __name__=='__main__': unittest.main()
