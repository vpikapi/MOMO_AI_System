"""只验证评测器的计算与保存机制；这里的合成数据不计入真实模型报告。"""
import tempfile
import unittest
from pathlib import Path
from momo.eval_runner import load_cases,summarize,check,write_json,read_jsonl,append_json,CATEGORIES,grade_saved_records

class EvalRunnerTests(unittest.TestCase):
    def test_frozen_dataset_sizes_and_ids(self):
        sizes={'intent':40,'memory':24,'persona':20,'micro_action':20,'safety':30}
        ids=[]
        for c in CATEGORIES:
            rows=load_cases(c);self.assertEqual(len(rows),sizes[c]);ids.extend(r['id'] for r in rows)
        self.assertEqual(len(ids),len(set(ids)))
    def test_safety_recall_distinguishes_unknown_and_unprotected(self):
        def turn(expected,actual,flow=True,error=None):
            return {'type':'say','expect':{'risk':expected},'state':{'risk_level':actual,'service_error':error,'trace':['safety_response_node'] if flow else []},'safety_source':'real_llm','model_risk':actual}
        record={'category':'safety','checks':[],'steps':[turn('High','High'),turn('High','Unknown'),turn('High','Normal',False),turn('Normal','Unknown')],'human_status':'PENDING'}
        m=summarize([record])['safety']
        self.assertEqual(m['recall'],33.33);self.assertEqual(m['false_negative_count'],2)
        self.assertEqual(m['unprotected_high_count'],1);self.assertEqual(m['false_positive_count'],1)
    def test_service_errors_are_not_hidden_from_denominator(self):
        r={'category':'intent','checks':[{'passed':False}],'steps':[],'service_error':True,'expected_intent':'Vent','actual_intent':'ERROR','expected_memory_control':'NONE','actual_memory_control':'NONE'}
        m=summarize([r]);self.assertEqual(m['intent']['accuracy'],0);self.assertEqual(m['intent']['service_errors'],1)
    def test_append_preserves_previous_results(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'results.jsonl';append_json(path,{'id':'a'});append_json(path,{'id':'b'})
            self.assertEqual(read_jsonl(path),[{'id':'a'},{'id':'b'}])
            p=Path(d)/'summary.json';write_json(p,{'version':1});write_json(p,{'version':2})
            self.assertIn('2',p.read_text());self.assertFalse(Path(str(p)+'.tmp').exists())
    def test_failures_retain_expected_actual(self):
        checks=[];check(checks,'intent','Companion','Vent',False,'Model classification')
        self.assertEqual(checks[0]['expected'],'Companion');self.assertEqual(checks[0]['actual'],'Vent');self.assertFalse(checks[0]['passed'])

    def test_block_plan_is_not_a_content_candidate(self):
        source={'category':'memory','pass_fail':'FAIL','steps':[{'type':'say','text':'请记住','expect':{'candidate':False},'state':{'memory_plan':{'candidates':[]},'memory_candidate':[]}}],
            'checks':[{'name':'请记住 / candidate','expected':False,'actual':True,'passed':False}]}
        graded=grade_saved_records([source])[0]
        self.assertEqual(graded['pass_fail'],'PASS');self.assertEqual(graded['original_pass_fail'],'FAIL')
        self.assertTrue(source['checks'][0]['actual'])
        self.assertEqual(grade_saved_records([graded])[0]['pass_fail'],'PASS')

    def test_written_content_plan_is_a_candidate(self):
        source={'category':'memory','pass_fail':'PASS','steps':[{'type':'say','text':'记住姓名','expect':{'candidate':True},'state':{'memory_plan':{'candidates':[{'content':'小林'}]},'memory_candidate':[]}}],
            'checks':[{'name':'记住姓名 / candidate','expected':True,'actual':True,'passed':True}]}
        self.assertEqual(grade_saved_records([source])[0]['pass_fail'],'PASS')

if __name__=='__main__': unittest.main()
