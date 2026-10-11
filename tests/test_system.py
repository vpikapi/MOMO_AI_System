import tempfile
import unittest
from pathlib import Path
from momo.graph import build_graph
from momo.memory import MemoryStore
from momo.models import initial_state
from momo.mock_llm import AliyunLLM, LLMConfig, ModelAPIError
from unittest.mock import patch
import hashlib
from datetime import datetime, timedelta, timezone

class TestLLM(AliyunLLM):
    """仅测试使用的传输替身；生产服务始终调用阿里云。"""
    def __init__(self):
        super().__init__(LLMConfig(api_key='test-not-real'))
    def _request(self, stage, instructions, data, schema=None):
        import json
        self.calls.append({'stage':stage})
        values={'memory_control':{'intent':'NONE','explicit_help':'小步骤' in data.get('current_input',''),'topic':'测试'},
                'micro_action':{'title':'写下你最担心的一件事','optional':True,'action_type':'IN_APP','input_prompt':'你最担心什么？','options':[]},
                'safety':{'risk_level':'Normal','reason':'测试普通输入'},
                'intent':{'intent':'Action' if '小步骤' in data.get('current_input','') else 'Companion','confidence':.9},
                'emotion':{'emotion':'Neutral','confidence':.9},
                'memory':{'candidates':[{'kind':'Preference','content':data.get('current_input','').split('：')[-1],
                    'importance':.9,'confidence':.9,'sensitivity':'家庭' in data.get('current_input','')}]}}
        return json.dumps(values[stage],ensure_ascii=False) if stage in values else '你好，很高兴见到你。'


# 系统边界测试集：由 unittest 创建并运行，验证图路由、输出约束与记忆隔离。
class SystemTests(unittest.TestCase):
    def test_failure_stops_later_nodes(self):
        """生成失败后不继续提取记忆或返回此前的行动。"""
        client=TestLLM()
        with patch.object(client,'response',side_effect=ModelAPIError('接口超时')),patch.object(client,'candidates') as extract:
            state=self.run_turn('记住：我喜欢简短回复',client)
            extract.assert_not_called()
        self.assertEqual(state['trace'][-1],'service_error_node')
        self.assertEqual(state['final_response'],'')
        self.assertEqual(self.store.list('a'),[])

    def test_greeting_has_valid_reason_and_real_adapter_flow(self):
        """普通问候通过适配器分类，原因写入状态，完整经过生成链。"""
        client=TestLLM()
        state=self.run_turn('你好',client)
        self.assertEqual(state['risk_level'],'Normal')
        self.assertEqual(state['risk_reason'],'测试普通输入')
        self.assertEqual([c['stage'] for c in client.calls],['safety','memory_control','intent','emotion','response','memory'])
        self.assertTrue(state['final_response'])

    def test_graph_uses_project_memory_store(self):
        """验证实际图调用能召回已确认记忆，而不是被框架 store 参数注入覆盖。"""
        c=self.candidate()
        self.store.write(c,'a',{c['id']})
        state=self.run_turn('你好')
        self.assertFalse(state['errors'])
        self.assertEqual(state['retrieved_memory'][0]['content'],c['content'])

    def setUp(self):
        """为每个系统测试创建独立临时目录与记忆库，避免测试间数据污染。
        
        参数：
            self (当前测试类实例)：提供测试断言和测试资源。
        
        返回：
            None；断言失败时由 unittest 报告测试失败。
        """
        self.tmp=tempfile.TemporaryDirectory()
        self.store=MemoryStore(Path(self.tmp.name)/'test.db')
    def tearDown(self):
        """在每个系统测试结束后清理临时数据库目录。
        
        参数：
            self (当前测试类实例)：提供测试断言和测试资源。
        
        返回：
            None；断言失败时由 unittest 报告测试失败。
        """
        self.tmp.cleanup()
    def run_turn(self,text,llm=None,**kwargs):
        """为测试执行一轮注入指定依赖的工作流。
        
        参数：
            self (当前测试类实例)：提供测试断言和测试资源。
            text (str)：测试输入。
            llm (适配器或 None)：用于正常或故障模拟。
            **kwargs：传给 initial_state 的历史、拒绝或安全锁存参数。
        
        返回：
            dict：执行完一轮后的完整工作流状态。
        """
        return build_graph(self.store,llm if llm is not None else TestLLM()).invoke(initial_state('a',text,**kwargs))
    def candidate(self,text='记住：我喜欢简短回复'):
        """为记忆边界测试构造属于用户 a 的固定候选。
        
        参数：
            self (当前测试类实例)：提供测试断言和测试资源。
            text (str)：带显式记忆前缀的测试内容。
        
        返回：
            dict：Mock 生成的首个待保存候选。
        """
        return TestLLM().candidates(text,'a')[0]
    def test_high_risk_never_reads_memory(self):
        """验证高风险仅经过安全节点与安全回应，不调用记忆检索。
        
        参数：
            self (当前测试类实例)：提供测试断言和测试资源。
        
        返回：
            None；断言失败时由 unittest 报告测试失败。
        """
        def fail(*args,**kwargs):
            """作为记忆读取替身，一旦被调用就让测试失败。
            
            参数：
                *args、**kwargs：兼容记忆检索调用的任意参数，替身不读取。
            
            返回：
                不正常返回，始终抛出 AssertionError。
            """
            raise AssertionError('Memory was accessed')
        self.store.retrieve=fail
        state=self.run_turn('最后再看一眼这个世界，谢谢你的陪伴')
        self.assertEqual(state['trace'],['safety_node','safety_response_node'])
        self.assertFalse(state['errors'])
        self.assertFalse(state['memory_candidate'])
    def test_safety_exception_fails_closed(self):
        """验证检测异常走服务错误分支，不误报用户风险。
        
        参数：
            self (当前测试类实例)：提供测试断言和测试资源。
        
        返回：
            None；断言失败时由 unittest 报告测试失败。
        """
        # 故障分类器替身：本测试创建并注入图，用于检查安全检测异常的降级路径。
        class Broken(TestLLM):
            # 故障注入接口：self 为替身实例，*args 接收安全检查参数；始终抛出超时异常，无返回值。
            def safety(self,*args): raise TimeoutError()
        state=self.run_turn('你好',Broken())
        self.assertEqual(state['risk_level'],'Unknown')
        self.assertEqual(state['trace'],['safety_node','service_error_node'])
        self.assertEqual(state['final_response'],'')
        self.assertTrue(state['service_error'])
    def test_invalid_intent_falls_back(self):
        """验证非法意图被拒绝并终止本轮。
        
        参数：
            self (当前测试类实例)：提供测试断言和测试资源。
        
        返回：
            None；断言失败时由 unittest 报告测试失败。
        """
        # 非法意图替身：本测试创建并注入图，用于检查分类结果验证失败后的回退。
        class Invalid(TestLLM):
            # 非法分类接口：self 为替身，text 为测试输入字符串；返回刻意不满足模型约束的字典。
            def intent(self,text): return {'intent':'Therapy','confidence':2}
        state=self.run_turn('你好',Invalid())
        self.assertEqual(state['intent'],'Vent')
        self.assertEqual(state['intent_confidence'],0)
        self.assertTrue(state['service_error'])
        self.assertEqual(state['final_response'],'')
    def test_bad_generation_removed(self):
        """验证不合格回复终止本轮且行动候选被清空。
        
        参数：
            self (当前测试类实例)：提供测试断言和测试资源。
        
        返回：
            None；断言失败时由 unittest 报告测试失败。
        """
        # 违规回复替身：本测试创建并注入图，用于检查最终回复的禁句过滤。
        class Bad(TestLLM):
            # 违规生成接口：self 为替身，state 为本轮状态；返回含禁句的字符串供最终检查。
            def response(self,state): return '只有我懂你'
        state=self.run_turn('给我一个小步骤',Bad())
        self.assertNotIn('只有我懂你',state['final_response'])
        self.assertIsNone(state['micro_action_candidate'])
    def test_latched_safety(self):
        """验证已有安全锁存时，游戏请求仍留在安全分支。
        
        参数：
            self (当前测试类实例)：提供测试断言和测试资源。
        
        返回：
            None；断言失败时由 unittest 报告测试失败。
        """
        state=self.run_turn('我们玩吧',latched=True)
        self.assertEqual(state['risk_level'],'High')
    def test_refusal_and_explicit_reopen(self):
        """验证拒绝建议优先，之后明确请求行动可以重新开启行动门槛。
        
        参数：
            self (当前测试类实例)：提供测试断言和测试资源。
        
        返回：
            None；断言失败时由 unittest 报告测试失败。
        """
        state=self.run_turn('不要建议，给我一个小步骤')
        self.assertIsNone(state['micro_action_candidate'])
        self.assertTrue(state['action_declined'])
        self.assertIsNotNone(self.run_turn('给我一个小步骤',declined=True)['micro_action_candidate'])
    def test_confirmed_idempotent_and_isolated(self):
        """验证未确认不保存、重复确认不重复写入且用户数据隔离。
        
        参数：
            self (当前测试类实例)：提供测试断言和测试资源。
        
        返回：
            None；断言失败时由 unittest 报告测试失败。
        """
        c=self.candidate()
        self.store.write(c,'a')
        self.assertEqual(self.store.list('a'),[])
        for _ in range(2): self.store.write(c,'a',{c['id']})
        self.assertEqual(len(self.store.list('a')),1)
        self.assertEqual(self.store.list('b'),[])
        self.assertEqual(self.store.write(c,'b',{c['id']}),'用户不匹配')
    def test_delete_blocks_rewrite(self):
        """验证删除并禁止重存后，相同内容不能再次写入。
        
        参数：
            self (当前测试类实例)：提供测试断言和测试资源。
        
        返回：
            None；断言失败时由 unittest 报告测试失败。
        """
        c=self.candidate()
        self.store.write(c,'a',{c['id']})
        self.store.delete('a',c['memory_key'],block=True)
        self.assertIn('禁止',self.store.write(c,'a',{c['id']}))
        self.assertEqual(self.store.list('a'),[])
    def test_sensitive_requires_separate_consent(self):
        """验证敏感候选必须获得独立于普通确认的额外同意。
        
        参数：
            self (当前测试类实例)：提供测试断言和测试资源。
        
        返回：
            None；断言失败时由 unittest 报告测试失败。
        """
        c=self.candidate('记住：家庭沟通情况')
        self.assertIn('敏感',self.store.write(c,'a',{c['id']}))
        self.store.write(c,'a',{c['id']},True)
        self.assertEqual(len(self.store.list('a')),1)
    def test_optout_no_candidate(self):
        """验证拒记表达不会产生待保存候选。
        
        参数：
            self (当前测试类实例)：提供测试断言和测试资源。
        
        返回：
            None；断言失败时由 unittest 报告测试失败。
        """
        self.assertEqual(self.run_turn('不要记住：我喜欢简短回复')['memory_candidate'],[])
    def test_input_boundary(self):
        """验证空白和超长输入在工作流入口被拒绝。
        
        参数：
            self (当前测试类实例)：提供测试断言和测试资源。
        
        返回：
            None；断言失败时由 unittest 报告测试失败。
        """
        with self.assertRaises(ValueError): initial_state('a',' ')
        with self.assertRaises(ValueError): initial_state('a','x'*4001)
    def test_candidate_tamper(self):
        """验证候选内容与绑定 ID 不一致时拒绝保存。
        
        参数：
            self (当前测试类实例)：提供测试断言和测试资源。
        
        返回：
            None；断言失败时由 unittest 报告测试失败。
        """
        c=self.candidate()
        c['content']='被更换的内容'
        self.assertIn('完整性',self.store.write(c,'a',{c['id']}))

if __name__=='__main__': unittest.main()
