import hashlib
import re
import unicodedata
from difflib import SequenceMatcher
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path
from .models import MemoryCandidate

# 记忆表按用户与内容键去重；禁止重存表只保留用户作用域内的内容键。
DDL = '''
CREATE TABLE IF NOT EXISTS memories (
 user_id TEXT NOT NULL, memory_key TEXT NOT NULL, candidate_id TEXT NOT NULL,
 kind TEXT NOT NULL, content TEXT NOT NULL, importance REAL NOT NULL,
 confidence REAL NOT NULL, sensitivity INTEGER NOT NULL,
 expires_at TEXT NOT NULL, created_at TEXT NOT NULL,
 PRIMARY KEY(user_id, memory_key)
);
CREATE TABLE IF NOT EXISTS blocked_memory (
 user_id TEXT NOT NULL, memory_key TEXT NOT NULL,
 PRIMARY KEY(user_id, memory_key)
);
CREATE TABLE IF NOT EXISTS memory_topics (user_id TEXT NOT NULL, topic TEXT NOT NULL, PRIMARY KEY(user_id,topic));
CREATE TABLE IF NOT EXISTS memory_revision (user_id TEXT PRIMARY KEY, revision INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS memory_slots_blocked (user_id TEXT NOT NULL, slot TEXT NOT NULL, PRIMARY KEY(user_id,slot));
CREATE TABLE IF NOT EXISTS memory_settings (user_id TEXT PRIMARY KEY, enabled INTEGER NOT NULL);
'''

def utcnow():
    """为记忆有效期判断和数据库时间字段提供统一 UTC 时钟。
    
    参数：
        无。
    
    返回：
        datetime：带 UTC 时区的当前时间。
    """
    return datetime.now(timezone.utc)

def gate(candidate, user_id, confirmed_ids=(), sensitive_consent=False):
    """在初次候选检查和用户确认写入时复用同一组保存门槛。
    
    参数：
        candidate (dict 或 MemoryCandidate)：待检查的记忆内容与元数据。
        user_id (str)：当前操作所属用户，必须与候选归属一致。
        confirmed_ids (字符串容器)：用户明确同意保存的候选 ID。
        sensitive_consent (bool)：是否额外同意保存敏感候选。
    
    返回：
        tuple[bool, str]：是否允许保存及首个未通过原因；不写数据库。
    
    会验证内容绑定、禁存词、价值、置信度、时效和同意；无效模型或日期可抛出验证异常。
    """
    c = MemoryCandidate.model_validate(candidate)
    if c.user_id != user_id:
        return False, '用户不匹配'
    key = hashlib.sha256(c.content.encode()).hexdigest()
    if c.memory_key != key or c.id != hashlib.sha256((user_id+':'+key).encode()).hexdigest():
        return False, '候选完整性检查失败'
    if any(x in c.content for x in ['密码', '身份证', '银行卡', '自杀', '不想活', '最后再看一眼', '诊断']):
        return False, '不保存秘密、诊断或危机原文'
    if c.importance < .6 or c.confidence < .8:
        return False, '价值或确定性不足'
    expiry = datetime.fromisoformat(c.expires_at)
    if expiry.tzinfo is None or expiry <= utcnow():
        return False, '已过期或时间格式无时区'
    if c.id not in confirmed_ids:
        return False, '等待用户确认'
    if (c.sensitivity or sensitive_content(c.content)) and not sensitive_consent:
        return False, '等待单独的敏感信息确认'
    return True, '允许保存'

def sensitive_content(content):
    """敏感性最低保护规则；补充模型标记与用户勾选，避免编辑后漏掉明显敏感信息。"""
    return any(word in content for word in ['家庭','健康','病史','住址','收入','婚姻','伴侣','创伤','药物'])


def normalize(content):
    """规范常见同义表述及标点；仅用于 MVP 去重，不进行向量语义推断。"""
    text=unicodedata.normalize('NFKC',content).lower()
    for a,b in [('任教','教师'),('老师','教师'),('教书','教师'),('连续追问','连续提问'),('一直问我','连续提问'),('简洁','简短')]:
        text=text.replace(a,b)
    for phrase in ['我的职业是','我是一名','我是一位','用户是一名','用户是','你是一名','我是','我希望','希望momo']:
        text=text.replace(phrase,'')
    return re.sub(r'[\W_]+','',text)


def topic_for(kind, content):
    """给有限常见主题生成本地规则键；未知主题只按规范文本阻止重存。"""
    groups={'Identity': [('职业',['教师','工程师','职业','工作是']),('称呼',['名字','我叫','叫我'])],
            'Preference':[('提问方式',['提问','追问','一直问']),('回复长度',['简短','简洁','长篇','回复长度'])]}
    for label,words in groups.get(kind,[]):
        if any(w in normalize(content) for w in words):
            return kind+':'+label
    return kind+':'+normalize(content)


def duplicate(a, b):
    """同类记忆做保守文本去重；肯定与否定差异保留给用户判断。"""
    if a['kind']!=b['kind']: return False
    x,y=normalize(a['content']),normalize(b['content'])
    if any(w in x for w in ['不','没','讨厌'])!=any(w in y for w in ['不','没','讨厌']): return False
    return x==y or SequenceMatcher(None,x,y).ratio()>=.9


def edited_candidate(candidate, content, sensitivity=False):
    """用户修改后重新绑定内容 ID，保留来源与有效期，并重新走保存门槛。"""
    c=MemoryCandidate.model_validate(candidate).model_dump()
    c['content']=content.strip()
    c['memory_key']=hashlib.sha256(c['content'].encode()).hexdigest()
    c['id']=hashlib.sha256((c['user_id']+':'+c['memory_key']).encode()).hexdigest()
    c['sensitivity']=bool(c['sensitivity'] or sensitivity or sensitive_content(content))
    c['source']='由你编辑确认'
    return MemoryCandidate.model_validate(c).model_dump()


# SQLite 记忆服务：由界面、命令行或测试创建，供检索节点及用户确认、删除操作调用。
class MemoryStore:
    def __init__(self, path):
        """在启动记忆服务时准备数据库路径并确保所需表存在。
        
        参数：
            self (MemoryStore)：当前记忆服务实例。
            path (str 或 Path)：本地 SQLite 文件路径。
        
        返回：
            None。
        
        写入 self.path，并可能创建父目录、数据库文件及表。
        """
        self.path = str(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript(DDL)
            # 兼容现有数据库，旧记录来源留空，绝不猜测历史来源。
            columns={r[1] for r in db.execute('PRAGMA table_info(memories)')}
            if 'source' not in columns:
                db.execute("ALTER TABLE memories ADD COLUMN source TEXT NOT NULL DEFAULT ''")
            if 'slot' not in columns:
                db.execute("ALTER TABLE memories ADD COLUMN slot TEXT NOT NULL DEFAULT 'other'")
            if 'updated_at' not in columns:
                db.execute("ALTER TABLE memories ADD COLUMN updated_at TEXT NOT NULL DEFAULT ''")
            db.execute("CREATE UNIQUE INDEX IF NOT EXISTS unique_active_slot ON memories(user_id,kind,slot) WHERE slot!='other'")

    @contextmanager
    def connect(self):
        """为各次记忆操作提供独立事务和可靠关闭的连接。
        
        参数：
            self (MemoryStore)：提供数据库路径的服务实例。
        
        返回：
            上下文管理器：进入时产出 sqlite3.Connection，查询行以 sqlite3.Row 表示。
        
        正常退出提交，异常退出回滚，最终关闭连接。
        """
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def write(self, candidate, user_id, confirmed_ids=(), sensitive_consent=False):
        """在用户确认后复核保存门槛，将获准候选写入当前用户的记忆。
        
        参数：
            self (MemoryStore)：数据库服务。
            candidate (dict 或 MemoryCandidate)：待检查的记忆内容与元数据。
            user_id (str)：当前操作所属用户，必须与候选归属一致。
            confirmed_ids (字符串容器)：用户明确同意保存的候选 ID。
            sensitive_consent (bool)：是否额外同意保存敏感候选。
        
        返回：
            str：拒绝原因或保存状态，用于界面反馈。
        
        检查禁止重存记录；相同用户与内容键的重复确认不会重复插入。
        """
        allowed, reason = gate(candidate, user_id, confirmed_ids, sensitive_consent)
        if not allowed:
            return reason
        c = MemoryCandidate.model_validate(candidate)
        status=self.candidate_status(candidate,user_id)
        if status!='等待用户确认': return status
        with self.connect() as db:
            if self.slot_blocked(db,user_id,MemoryCandidate.model_validate(candidate).slot): return '已被用户禁止保存类似主题'
            if db.execute('SELECT 1 FROM blocked_memory WHERE user_id=? AND memory_key=?', (user_id,c.memory_key)).fetchone():
                return '已被用户禁止再次保存'
            db.execute('INSERT INTO memories (user_id,memory_key,candidate_id,kind,content,importance,confidence,sensitivity,expires_at,created_at,source) VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(user_id,memory_key) DO NOTHING',
                       (user_id,c.memory_key,c.id,c.kind,c.content,c.importance,c.confidence,int(c.sensitivity),datetime.fromisoformat(c.expires_at).astimezone(timezone.utc).isoformat(),utcnow().isoformat(),c.source))
            db.execute('UPDATE memories SET slot=? WHERE user_id=? AND memory_key=?',(c.slot,user_id,c.memory_key))
        return '已保存（重复确认不重复写入）'

    def list(self, user_id):
        """为检索和记忆管理界面列出当前用户仍有效的记忆。
        
        参数：
            self (MemoryStore)：数据库服务。
            user_id (str)：本次可访问的用户作用域。
        
        返回：
            list[dict]：按创建时间倒序排列的记忆记录。
        
        读取前会物理删除该用户已过期记录，不清理其他用户数据。
        """
        with self.connect() as db:
            db.execute('DELETE FROM memories WHERE user_id=? AND expires_at<=?', (user_id,utcnow().isoformat()))
            rows = db.execute('SELECT * FROM memories WHERE user_id=? ORDER BY created_at DESC', (user_id,)).fetchall()
        return [dict(row) for row in rows]

    def retrieve(self, user_id, query, limit=3):
        """在普通聊天链中用词匹配选取相关记忆，不执行向量检索。
        
        参数：
            self (MemoryStore)：数据库服务。
            user_id (str)：限定可召回的用户记录。
            query (str)：本轮输入，用于中文二元词匹配。
            limit (int)：最多返回条数，默认 3。
        
        返回：
            list[dict]：按匹配分数排序的记忆；偏好记录获得基础分。
        
        调用 list 时会清理当前用户的过期记录。
        """
        # Transparent lexical retrieval: Chinese bigrams, not embeddings.
        tokens = {query[i:i+2] for i in range(max(0,len(query)-1))}
        ranked = []
        for row in self.list(user_id):
            score = sum(t in row['content'] for t in tokens) + (1 if row['kind'] in ('Identity','Preference') else 0)
            if score:
                ranked.append((score,row))
        stable=[r for r in self.list(user_id) if r['kind'] in ('Identity','Preference')]
        extra=[r for _,r in sorted(ranked,key=lambda x:x[0],reverse=True) if r['kind'] not in ('Identity','Preference')][:limit]
        return stable+extra

    def delete(self, user_id, key, block=False):
        """响应用户删除操作，并可阻止完全相同内容再次保存。
        
        参数：
            self (MemoryStore)：数据库服务。
            user_id (str)：要操作的用户作用域。
            key (str)：待删除内容的 memory_key。
            block (bool)：是否同时保留禁止重存的内容键，默认关闭。
        
        返回：
            None。
        
        删除对应数据库行；block 为真时写入该用户的禁止重存表。
        """
        with self.connect() as db:
            row=db.execute('SELECT kind,content,slot FROM memories WHERE user_id=? AND memory_key=?',(user_id,key)).fetchone()
            if block and row:
                if row['slot']!='other': db.execute('INSERT OR IGNORE INTO memory_slots_blocked VALUES (?,?)',(user_id,row['slot']))
                db.execute('INSERT OR IGNORE INTO memory_topics VALUES (?,?)',(user_id,topic_for(row['kind'],row['content'])))
            db.execute('DELETE FROM memories WHERE user_id=? AND memory_key=?', (user_id,key))
            if block:
                db.execute('INSERT OR IGNORE INTO blocked_memory VALUES (?,?)', (user_id,key))
            self.bump_revision(db,user_id)

    def clear(self, user_id):
        """响应界面的清空操作，移除该用户全部记忆及禁止重存记录。
        
        参数：
            self (MemoryStore)：数据库服务。
            user_id (str)：要清空的数据所属用户。
        
        返回：
            None；不修改其他用户记录，也不负责清空页面会话。
        """
        with self.connect() as db:
            db.execute('DELETE FROM memories WHERE user_id=?', (user_id,))
            db.execute('DELETE FROM blocked_memory WHERE user_id=?', (user_id,))
            db.execute('DELETE FROM memory_topics WHERE user_id=?', (user_id,))
            db.execute('DELETE FROM memory_slots_blocked WHERE user_id=?',(user_id,))
            self.bump_revision(db,user_id)

    def enabled(self,user_id):
        """读取本机测试用户的记忆开关；默认允许生成候选。"""
        with self.connect() as db:
            row=db.execute('SELECT enabled FROM memory_settings WHERE user_id=?',(user_id,)).fetchone()
        return bool(row[0]) if row else True

    def set_enabled(self,user_id,enabled):
        """只修改新记忆开关，不删除已有长期记忆。"""
        with self.connect() as db:
            db.execute('INSERT INTO memory_settings VALUES (?,?) ON CONFLICT(user_id) DO UPDATE SET enabled=excluded.enabled',(user_id,int(enabled)))

    def candidate_status(self,candidate,user_id,exclude_key=None):
        """候选展示和最终保存复核开关、门槛、禁存主题与重复；不写长期记忆。"""
        if not self.enabled(user_id): return '新记忆保存已关闭'
        _,reason=gate(candidate,user_id)
        if reason!='等待用户确认': return reason
        with self.connect() as db:
            if self.slot_blocked(db,user_id,MemoryCandidate.model_validate(candidate).slot): return '已被用户禁止保存类似主题'
            if db.execute('SELECT 1 FROM blocked_memory WHERE user_id=? AND memory_key=?',(user_id,candidate['memory_key'])).fetchone():
                return '已被用户禁止再次保存'
            if db.execute('SELECT 1 FROM memory_topics WHERE user_id=? AND topic=?',(user_id,topic_for(candidate['kind'],candidate['content']))).fetchone():
                return '已被用户禁止保存类似主题'
        c=MemoryCandidate.model_validate(candidate).model_dump()
        if any(r['memory_key']!=exclude_key and c['slot']!='other' and r['slot']==c['slot'] and r['kind']==c['kind'] and not duplicate(c,r) for r in self.list(user_id)):
            return '已有同槽位记忆，请确认更新'
        if any(r['memory_key']!=exclude_key and duplicate(candidate,r) for r in self.list(user_id)):
            return '已有相同或近似记忆'
        return '等待用户确认'

    def update(self,user_id,key,content,sensitive_consent=False,marked_sensitive=False):
        """编辑已保存记录；验证后事务替换，保留创建时间。失败不删除原记录。"""
        row=next((r for r in self.list(user_id) if r['memory_key']==key),None)
        if not row: return '记忆不存在或已过期'
        c=edited_candidate({**row,'id':row['candidate_id']},content,marked_sensitive)
        allowed,reason=gate(c,user_id,{c['id']},sensitive_consent)
        if not allowed: return reason
        # 关闭新增不妨碍编辑已有记忆；主题禁存仍须遵守。
        with self.connect() as db:
            blocked=db.execute('SELECT 1 FROM memory_topics WHERE user_id=? AND topic=?',(user_id,topic_for(c['kind'],c['content']))).fetchone()
            exact=db.execute('SELECT 1 FROM blocked_memory WHERE user_id=? AND memory_key=?',(user_id,c['memory_key'])).fetchone()
            if blocked or exact or self.slot_blocked(db,user_id,c['slot']): return '已被用户禁止再次保存'
            if any(r['memory_key']!=key and duplicate(c,r) for r in self.list(user_id)): return '已有相同或近似记忆'
            db.execute('UPDATE memories SET memory_key=?,candidate_id=?,content=?,sensitivity=?,source=? WHERE user_id=? AND memory_key=?',
                (c['memory_key'],c['id'],c['content'],int(c['sensitivity']),c['source'],user_id,key))
            db.execute('UPDATE memories SET updated_at=? WHERE user_id=? AND memory_key=?',(utcnow().isoformat(),user_id,c['memory_key']))
            self.bump_revision(db,user_id)
        return '已更新'


    @staticmethod
    def bump_revision(db,user_id):
        """事务内推进记忆修订号，让界面隔离修改前的普通聊天上下文。"""
        db.execute('INSERT INTO memory_revision VALUES (?,1) ON CONFLICT(user_id) DO UPDATE SET revision=revision+1',(user_id,))

    def revision(self,user_id):
        with self.connect() as db:
            row=db.execute('SELECT revision FROM memory_revision WHERE user_id=?',(user_id,)).fetchone()
        return row[0] if row else 0

    @staticmethod
    def slot_blocked(db,user_id,slot):
        return slot!='other' and db.execute('SELECT 1 FROM memory_slots_blocked WHERE user_id=? AND slot=?',(user_id,slot)).fetchone() is not None

    def blocked_slots(self,user_id):
        with self.connect() as db:
            return [r[0] for r in db.execute('SELECT slot FROM memory_slots_blocked WHERE user_id=?',(user_id,))]

    def prepare_plan(self,user_id,control):
        """绑定操作目标快照和完整替换清单；此处只创建待确认计划。"""
        rows={r['memory_key']:r for r in self.list(user_id)}
        targets=control['target_keys']
        if any(k not in rows for k in targets): raise ValueError('目标已失效')
        facts=control['replacements']
        for f in facts:
            if f['slot'] not in SLOTS.get(f['kind'],{'other'}): raise ValueError('无效槽位')
            if f['kind']=='Identity' and f['slot']=='other' and any(w in f['content'] for w in ['老师','教师','工程师','我叫','名字','职业']):
                raise ValueError('已知身份事实需要明确槽位，不能以组合文本覆盖')
        slots=[f['slot'] for f in facts if f['slot']!='other']
        if len(set(slots))!=len(slots): raise ValueError('同一槽位存在多个替换值')
        operations=control['operations']
        if not operations or any(x not in ('CREATE','UPDATE','DELETE','BLOCK') for x in operations): raise ValueError('无效操作')
        if 'UPDATE' in operations and not targets: raise ValueError('更新目标不明确')
        if any(x in operations for x in ('CREATE','UPDATE')) and not facts: raise ValueError('没有新事实')
        if 'BLOCK' in operations and (not control['slots'] or any(x=='other' or x not in ALL_SLOTS for x in control['slots'])): raise ValueError('禁存范围不明确')
        if operations==['BLOCK'] and facts: raise ValueError('禁存不能新增事实')
        if operations==['CREATE'] and targets: raise ValueError('新增不能覆盖旧记录')
        candidates=[fact_candidate(user_id,f) for f in facts]
        if candidates:
            if any(gate(c,user_id)[1]!='等待用户确认' for c in candidates): raise ValueError('本次信息不适合保存，请核对内容。')
            if not self.enabled(user_id) and (not targets or 'CREATE' in operations): raise ValueError('新记忆保存已关闭，本次不会保存。')
            with self.connect() as db:
                if any(self.slot_blocked(db,user_id,c['slot']) or db.execute('SELECT 1 FROM memory_topics WHERE user_id=? AND topic=?',(user_id,topic_for(c['kind'],c['content']))).fetchone() or db.execute('SELECT 1 FROM blocked_memory WHERE user_id=? AND memory_key=?',(user_id,c['memory_key'])).fetchone() for c in candidates):
                    raise ValueError('你已禁止保存这类内容，本次不会生成保存计划。')
        return {'operations':operations,'slots':control['slots'],'targets':[rows[k] for k in targets],
                'candidates':candidates,'revision':self.revision(user_id)}

    def apply_plan(self,user_id,plan,confirmed=False,sensitive_consent=False):
        """用户确认后原子执行整组变更；过期计划不能覆盖更新后的数据。"""
        if not confirmed: return '等待用户确认'
        operations=plan['operations']; candidates=plan['candidates']
        if len({c['memory_key'] for c in candidates})!=len(candidates): return '调整内容存在重复，请修改后确认'
        if candidates and not self.enabled(user_id) and (not plan['targets'] or 'CREATE' in operations): return '新记忆保存已关闭'
        for c in candidates:
            allowed,reason=gate(c,user_id,{c['id']},sensitive_consent)
            if not allowed: return reason
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT revision FROM memory_revision WHERE user_id=?',(user_id,)).fetchone()
            if (row[0] if row else 0)!=plan['revision']: return '记忆已变化，请重新发起操作'
            for old in plan['targets']:
                row=db.execute('SELECT * FROM memories WHERE user_id=? AND memory_key=?',(user_id,old['memory_key'])).fetchone()
                if not row or dict(row)!=old: return '记忆已变化，请重新发起操作'
            targets={r['memory_key'] for r in plan['targets']}
            for c in candidates:
                if self.slot_blocked(db,user_id,c['slot']): return '已被用户禁止保存类似主题'
                if db.execute('SELECT 1 FROM blocked_memory WHERE user_id=? AND memory_key=?',(user_id,c['memory_key'])).fetchone(): return '已被用户禁止再次保存'
                if db.execute('SELECT 1 FROM memory_topics WHERE user_id=? AND topic=?',(user_id,topic_for(c['kind'],c['content']))).fetchone(): return '已被用户禁止保存类似主题'
                active=db.execute('SELECT * FROM memories WHERE user_id=?',(user_id,)).fetchall()
                if any(r['memory_key'] not in targets and (duplicate(c,dict(r)) or (c['slot']!='other' and r['slot']==c['slot'] and r['kind']==c['kind'])) for r in active): return '已有同槽位记忆，请重新确认更新范围'
            if any(op in operations for op in ('UPDATE','DELETE')):
                for key in targets: db.execute('DELETE FROM memories WHERE user_id=? AND memory_key=?',(user_id,key))
            if 'BLOCK' in operations:
                for slot in plan['slots']: db.execute('INSERT OR IGNORE INTO memory_slots_blocked VALUES (?,?)',(user_id,slot))
            created=min((r['created_at'] for r in plan['targets']),default=utcnow().isoformat())
            for c in candidates:
                db.execute('INSERT INTO memories (user_id,memory_key,candidate_id,kind,content,importance,confidence,sensitivity,expires_at,created_at,source,slot,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    (user_id,c['memory_key'],c['id'],c['kind'],c['content'],c['importance'],c['confidence'],int(c['sensitivity']),c['expires_at'],created,c['source'],c['slot'],utcnow().isoformat()))
            self.bump_revision(db,user_id)
        return '已完成记忆操作'


SLOTS={'Identity':{'name','job','city','education','relationship_status','other'},
       'Preference':{'advice_preference','question_preference','tone_preference','interaction_preference','other'},
       'Episodic':{'other'},'Relationship':{'other'}}
ALL_SLOTS=set().union(*SLOTS.values())

def fact_candidate(user_id,fact):
    """为已验证的单一事实绑定本地 ID、来源和期限，模型不能指定用户身份。"""
    key=hashlib.sha256(fact['content'].encode()).hexdigest()
    days={'Identity':180,'Preference':90,'Relationship':90,'Episodic':14}[fact['kind']]
    return MemoryCandidate(**fact,id=hashlib.sha256((user_id+':'+key).encode()).hexdigest(),user_id=user_id,memory_key=key,
        expires_at=(utcnow()+timedelta(days=days)).isoformat(),source='来自对话 · 用户确认').model_dump()
