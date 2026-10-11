"""Memory 产品边界：确认、编辑、去重、禁存与普通对话连续性。"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from momo.memory import MemoryStore, edited_candidate
from momo.graph import build_graph
from momo.models import initial_state
from momo.mock_llm import ModelAPIError
from test_system import TestLLM

class MemoryProductTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.store=MemoryStore(Path(self.tmp.name)/'memory.db')
    def tearDown(self): self.tmp.cleanup()
    def candidate(self,text='我喜欢简短回复'):
        return TestLLM().candidates(text,'tester')[0]
    def save(self,c): return self.store.write(c,'tester',{c['id']},True)

    def test_natural_input_waits_for_confirmation(self):
        state=build_graph(self.store,TestLLM()).invoke(initial_state('tester','我不喜欢连续提问'))
        self.assertEqual(state['memory_status'],'等待用户确认')
        self.assertEqual(self.store.list('tester'),[])
        self.assertEqual(len(state['memory_candidate']),1)

    def test_edit_preserves_source_and_retrieves_new_content(self):
        c=self.candidate();self.save(c)
        self.assertEqual(self.store.update('tester',c['memory_key'],'我喜欢详细回复'),'已更新')
        rows=self.store.retrieve('tester','回复')
        self.assertEqual([r['content'] for r in rows],['我喜欢详细回复'])
        self.assertEqual(rows[0]['source'],'由你编辑确认')
        self.assertEqual(self.store.list('another'),[])

    def test_delete_and_forget_have_different_meanings(self):
        c=self.candidate('我不喜欢连续提问');self.save(c)
        self.store.delete('tester',c['memory_key'])
        self.assertTrue(self.save(c).startswith('已保存'))
        self.store.delete('tester',c['memory_key'],block=True)
        related=self.candidate('不要一直问我')
        self.assertIn('禁止',self.save(related))
        other=self.candidate('我喜欢简短回复')
        self.assertTrue(self.save(other).startswith('已保存'))

    def test_duplicate_and_toggle(self):
        c=self.candidate();self.save(c)
        revised=edited_candidate(c,'我喜欢简洁回复。')
        self.assertEqual(self.save(revised),'已有相同或近似记忆')
        self.assertEqual(len(self.store.list('tester')),1)
        self.store.set_enabled('tester',False)
        llm=TestLLM()
        with patch.object(llm,'candidates') as extract:
            state=build_graph(self.store,llm).invoke(initial_state('tester','我喜欢咖啡'))
            extract.assert_not_called()
        self.assertTrue(state['final_response'])
        self.assertEqual(self.store.update('tester',c['memory_key'],'我喜欢详细回复'),'已更新')
        self.assertFalse(MemoryStore(Path(self.tmp.name)/'memory.db').enabled('tester'))

    def test_sensitive_edit_requires_new_consent(self):
        c=self.candidate();self.save(c)
        self.assertIn('敏感',self.store.update('tester',c['memory_key'],'家庭沟通让我感到压力'))
        self.assertEqual(self.store.list('tester')[0]['content'],c['content'])
        self.assertEqual(self.store.update('tester',c['memory_key'],'家庭沟通让我感到压力',True),'已更新')

    def test_optional_memory_failure_keeps_chat(self):
        llm=TestLLM()
        with patch.object(llm,'candidates',side_effect=ModelAPIError('测试记忆服务故障')):
            state=build_graph(self.store,llm).invoke(initial_state('tester','你好'))
        self.assertTrue(state['final_response'])
        self.assertIsNone(state['service_error'])
        self.assertEqual(state['memory_candidate'],[])
        self.assertIn('暂不可用',state['memory_status'])

    def test_old_schema_migration_preserves_records(self):
        import sqlite3
        legacy=Path(self.tmp.name)/'legacy.db'
        with sqlite3.connect(legacy) as db:
            db.execute('CREATE TABLE memories (user_id TEXT NOT NULL,memory_key TEXT NOT NULL,candidate_id TEXT NOT NULL,kind TEXT NOT NULL,content TEXT NOT NULL,importance REAL NOT NULL,confidence REAL NOT NULL,sensitivity INTEGER NOT NULL,expires_at TEXT NOT NULL,created_at TEXT NOT NULL,PRIMARY KEY(user_id,memory_key))')
            c=self.candidate()
            db.execute('INSERT INTO memories VALUES (?,?,?,?,?,?,?,?,?,?)',('tester',c['memory_key'],c['id'],c['kind'],c['content'],.9,.9,0,c['expires_at'],'2026-09-01T00:00:00+00:00'))
        db.close()
        rows=MemoryStore(legacy).list('tester')
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['source'],'')
        self.assertEqual(rows[0]['content'],c['content'])

    def test_high_risk_skips_candidate(self):
        llm=TestLLM()
        with patch.object(llm,'candidates') as extract:
            state=build_graph(self.store,llm).invoke(initial_state('tester','最后再看一眼这个世界'))
            extract.assert_not_called()
        self.assertEqual(state['trace'],['safety_node','safety_response_node'])
        self.assertEqual(self.store.list('tester'),[])

if __name__=='__main__': unittest.main()
