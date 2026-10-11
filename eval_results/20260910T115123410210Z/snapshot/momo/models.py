from typing import Literal, TypedDict
from pydantic import BaseModel, Field, ConfigDict, field_validator

Intent = Literal['Vent', 'Companion', 'Reflect', 'Action', 'Play']
Emotion = Literal['Neutral', 'Stressed', 'Overwhelmed', 'High_Risk']
Risk = Literal['Normal', 'High', 'Unknown']

# 意图分类结果：由 intent_node 验证模型输出后生成，节点读取它来更新意图及置信度。
class IntentResult(BaseModel):
    # 当前回应意图：Vent / Companion / Reflect / Action / Play，用于选择策略和行动门槛。
    intent: Intent
    # 当前分类结果置信分值；用于阈值判断，不代表经校准的真实概率。
    confidence: float = Field(ge=0, le=1)

# 非医学情绪分类结果：由 emotion_node 验证生成，供情绪状态更新使用，不决定安全路由。
class EmotionResult(BaseModel):
    # 非医学情绪标签 Neutral / Stressed / Overwhelmed / High_Risk，用于回应和调试展示。
    emotion: Emotion
    # 当前分类结果置信分值；用于阈值判断，不代表经校准的真实概率。
    confidence: float = Field(ge=0, le=1)

# 安全分类结果：由 safety_node 验证生成，其风险等级写入共享状态并由条件路由读取。
class SafetyResult(BaseModel):
    # 独立安全等级 Normal / High / Unknown，决定普通链或安全回应链。
    risk_level: Risk
    # 安全分类器返回的简短说明，由节点转入风险依据字段。
    reason: str

# 单个可拒绝行动的数据结构：由 micro_action_node 生成，最终回复节点和界面读取。
class MicroAction(BaseModel):
    # 向用户展示的单个小步骤文案，由最终回复节点合并。
    title: str
    # 固定为 True，表示行动可拒绝，不构成必须完成的任务。
    optional: Literal[True] = True
    action_type: Literal['IN_APP', 'OFFLINE'] = 'OFFLINE'
    input_prompt: str = ''
    options: list[str] = Field(default_factory=list, max_length=5)

# 待确认记忆结构：由阿里云模型提取并经节点验证，保存闸门和数据库写入接口读取。
class MemoryCandidate(BaseModel):
    # 冻结候选模型的字段赋值，减少确认前内容被意外改写的机会。
    model_config = ConfigDict(frozen=True)
    # 绑定用户与内容哈希的候选 ID，用于核对本次用户确认。
    id: str
    # 当前用户的数据隔离键；记忆读写必须限定到这一用户。
    user_id: str
    # 内容哈希键，用于同一用户内去重、删除和禁止相同内容重存。
    memory_key: str
    # 记忆类别 Identity / Episodic / Relationship / Preference，标识事实的业务用途。
    kind: Literal['Identity', 'Episodic', 'Relationship', 'Preference']
    # 待保存的用户事实文本，长度限制为 1–300 字，不是完整聊天记录。
    content: str = Field(min_length=1, max_length=300)
    # 记忆保留价值分值，写入闸门用它排除价值不足的候选。
    importance: float = Field(ge=0, le=1)
    # 当前记忆事实确定性分值；用于阈值判断，不代表经校准的真实概率。
    confidence: float = Field(ge=0, le=1)
    # 是否需要额外的敏感信息保存同意；普通确认不能替代该同意。
    sensitivity: bool = False
    # 带时区的 ISO 日期时间，用于拒绝过期候选并清理到期记录。
    expires_at: str
    # 来源说明由程序填写；历史记录为空时界面显示未记录。
    source: str = ""
    # 单一事实槽位；other 不据此覆盖其他记录。
    slot: str = 'other' 

# 工作流共享状态：入口创建，各节点提交局部更新；后续节点、界面及评测读取。
class AgentState(TypedDict):
    # 当前用户的数据隔离键；记忆读写必须限定到这一用户。
    user_id: str
    memory_control_intent: str
    memory_operation: list[str]
    memory_slot: list[str]
    memory_plan: dict | None
    micro_action_allowed: bool
    micro_action_block_reason: str
    action_type: str | None
    active_memory_used_for_context: list[dict]
    explicit_help: bool
    action_willing: bool
    refuses_action: bool
    clarification_count: int
    clarification_topic: str
    needs_clarification: bool
    ordinary_history: list[dict]
    # 本轮输入经入口去除首尾空白后的文本，供安全检查、分类及候选提取读取。
    user_input: str
    # 当前回应意图：Vent / Companion / Reflect / Action / Play，用于选择策略和行动门槛。
    intent: str
    # 意图分类的置信分值，低置信时使用倾听回退策略；模型分值未经校准。
    intent_confidence: float
    # 非医学情绪标签 Neutral / Stressed / Overwhelmed / High_Risk，用于回应和调试展示。
    emotion: str
    # 情绪标签的置信分值；安全分支未调用情绪分类时设置为 0。
    emotion_confidence: float
    # 独立安全等级 Normal / High / Unknown，决定普通链或安全回应链。
    risk_level: str
    # 安全等级的简短依据，供调试侧栏解释分支选择。
    risk_reason: str
    # 最近最多 8 条会话消息，供上下文组装及安全适配接口使用。
    short_term_context: list[dict]
    # 本轮召回的当前用户有效记忆列表，供上下文组装及侧栏展示。
    retrieved_memory: list[dict]
    # 人格核心、意图策略和不可信上下文的组合文本，为生成接口预留。
    persona_context: str
    # 当前关系阶段，初版固定为初识，不以行动完成或依赖程度升级。
    relationship_stage: str
    # 本轮可选的单个行动字典；不满足门槛时为 None，供回复合并及反馈界面读取。
    micro_action_candidate: dict | None
    # 经输出检查或安全分支形成的最终用户可见回复。
    final_response: str
    # 普通生成节点的初稿，尚未合并行动或经过最终输出检查。
    draft_response: str
    # 当前输入提取的待确认候选列表，最多一个；不等同于已保存记忆。
    memory_candidate: list[dict]
    # 候选保存门槛的结果说明，由写入判断节点产生，界面据此决定是否提示确认。
    memory_status: str
    # 会话内的行动拒绝标记；供微行动门槛读取，可被明确的 Action 意图解除。
    action_declined: bool
    # 保留当前会话高风险关注的标记，后续安全检查据此维持安全分支。
    safety_latched: bool
    # 按执行顺序累计的节点名称，供开发侧栏及路由测试核查。
    trace: list[str]
    # 已捕获异常的类型名列表，用于调试，不记录异常原文。
    errors: list[str]
    # 独立服务故障，不与模型判定的 Unknown 或 High 风险混用。
    service_error: str | None

def initial_state(user_id: str, text: str, history=None, declined=False, latched=False, clarification_count=0, clarification_topic='', ordinary_history=None) -> AgentState:
    """在调用工作流前创建本轮共享状态，避免沿用上一轮推导结果。
    
    参数：
        user_id (str)：当前用户的数据隔离标识。
        text (str)：本轮输入，去除首尾空白后用于节点处理。
        history (可迭代消息集合或 None)：短期上下文，只保留最后 8 条。
        declined (bool)：此前是否拒绝微行动。
        latched (bool)：是否保留本会话的高风险关注。
    
    返回：
        AgentState：包含默认分类、空候选及传入会话状态的新字典。
    
    输入为空、超过长度限制或缺少用户标识时抛出 ValueError；不修改传入历史。
    """
    if not user_id or not text.strip() or len(text) > 4000:
        raise ValueError('请输入 1–4000 字的消息，并提供用户标识。')
    return dict(memory_control_intent='NONE',memory_operation=[],memory_slot=[],memory_plan=None,
                micro_action_allowed=False,micro_action_block_reason='尚未判断',action_type=None,
                active_memory_used_for_context=[],explicit_help=False,action_willing=False,refuses_action=False,
                clarification_count=clarification_count,clarification_topic=clarification_topic,
                needs_clarification=False,ordinary_history=list(history if ordinary_history is None else ordinary_history or [])[-8:] if history or ordinary_history else [],user_id=user_id, user_input=text.strip(), intent='Vent', intent_confidence=0.,
                emotion='Neutral', emotion_confidence=0., risk_level='Unknown', risk_reason='',
                short_term_context=list(history or [])[-8:], retrieved_memory=[], persona_context='',
                relationship_stage='初识', micro_action_candidate=None, final_response='', draft_response='',
                memory_candidate=[], memory_status='未保存', action_declined=declined,
                safety_latched=latched, trace=[], errors=[], service_error=None)


MemorySlot = Literal['name','job','city','education','relationship_status','advice_preference','question_preference','tone_preference','interaction_preference','other']

class MemoryFact(BaseModel):
    """模型提出的单一事实；只有确认后才转为长期记忆。"""
    kind: Literal['Identity','Preference','Episodic','Relationship']
    slot: MemorySlot
    content: str = Field(min_length=1,max_length=300)
    importance: float = Field(default=.9,ge=0,le=1)
    confidence: float = Field(default=.9,ge=0,le=1)
    sensitivity: bool = False

class MemoryControlResult(BaseModel):
    """安全放行后生成的控制计划；目标键由程序校验，模型不执行写入。"""
    intent: Literal['MEMORY_CREATE','MEMORY_UPDATE','MEMORY_DELETE','MEMORY_BLOCK','MEMORY_QUERY','NONE']
    operations: list[Literal['CREATE','UPDATE','DELETE','BLOCK']] = Field(default_factory=list)
    slots: list[MemorySlot] = Field(default_factory=list)

    @field_validator('slots',mode='before')
    @classmethod
    def normalize_slots(cls,values):
        """兼容模型添加类别前缀的写法，随后仍由固定枚举验证。"""
        return [v.split(':')[-1] if isinstance(v,str) else v for v in values]
    target_keys: list[str] = Field(default_factory=list)
    replacements: list[MemoryFact] = Field(default_factory=list,max_length=8)
    clarification: str = ''
    explicit_help: bool = False
    action_willing: bool = False
    refuses_action: bool = False
    topic: str = ''
    needs_clarification: bool = False
