import json
from pydantic import ValidationError
from functools import partial
from langgraph.graph import StateGraph, START, END
from .models import AgentState, IntentResult, EmotionResult, SafetyResult, MemoryCandidate, MicroAction
from .mock_llm import PERSONA, STRATEGIES, AliyunLLM, ModelAPIError, explicit_text_request
from .memory import gate, is_sensitive

BANNED = ['只有我懂你', '不要离开我', '你只需要我']

def result(state, node, **updates):
    """为各节点统一构造局部状态更新，并记录执行轨迹。
    
    参数：
        state (AgentState)：读取已有 trace 的共享状态。
        node (str)：本次执行的节点名称。
        **updates：本节点要提交的字段及其新值。
    
    返回：
        dict：新轨迹与传入更新组成的字典；由调用方提交给 LangGraph。
    """
    return {'trace': state['trace']+[node], **updates}


def failed(state, node, exc):
    """统一记录脱敏故障，不编造分类或普通回复；返回局部状态供错误边终止本轮。"""
    message = str(exc) if isinstance(exc,ModelAPIError) else '本轮处理发生服务异常，请稍后重试。'
    return result(state,node,service_error=message,errors=state['errors']+[type(exc).__name__])

def route_result(state):
    """普通节点失败时终止，防止下游继续调用、产生伪回复或写入候选。"""
    return 'error' if state.get('service_error') else 'next'

def service_error_node(state):
    """服务故障单独结束本轮；界面显示错误，不作为聊天回复或安全监护信号。"""
    return result(state,'service_error_node',final_response='',draft_response='',micro_action_candidate=None,
                  memory_candidate=[],memory_status='服务异常，本轮不保存记忆')

def safety_node(state, *, llm):
    """作为首个节点判断安全风险，决定是否允许普通聊天。
    
    参数：
        state (AgentState)：本轮共享状态，包含当前输入及上游节点结果。
        llm (AliyunLLM 或测试替身)：提供 safety 分类接口。
    
    返回：
        dict：供 LangGraph 合并的局部更新，并非完整 AgentState。
        写入 risk_level、risk_reason、safety_latched；异常时写入 service_error，走独立服务错误分支。
    
    同时追加 trace 节点轨迹；不直接修改传入的 state 字典。
    """
    try:
        value = SafetyResult.model_validate(llm.safety(state['user_input'],state['short_term_context'],state['safety_latched']))
        return result(state,'safety_node',risk_level=value.risk_level, risk_reason=value.reason,
                      safety_subject=value.subject,safety_latched=value.risk_level=='High')
    except Exception as exc:
        return failed(state, 'safety_node', exc)

def memory_control_node(state, *, llm, memory_store):
    """Safety 放行后检测记忆操作；只准备确认计划，不执行模型提出的写入。"""
    try:
        blocked=memory_store.blocked_slots(state['user_id'])
        value=llm.control(state,memory_store.list(state['user_id']),blocked)
        explicit=value.get('memory_control_explicit',False) or any(w in state['user_input'] for w in ['请记住','帮我记住','忘掉','不要记住','以后别记','修改记忆','删除记忆','处理我的记忆'])
        help_now=value['explicit_help'] or value.get('action_requested',False)
        plan=None
        rejection=''
        clarification=value['clarification']
        if value['intent'] not in ('NONE','MEMORY_QUERY') and not clarification:
            try: plan=memory_store.prepare_plan(state['user_id'],value)
            except ValueError as exc:
                rejection=str(exc)
                if rejection=='本次信息不适合保存，请核对内容。':
                    # 候选质量不足不等于用户需要修正说话方式，不让内部提示替代陪伴。
                    clarification=''
                else:
                    clarification=rejection if rejection in ('新记忆保存已关闭，本次不会保存。','你已禁止保存这类内容，本次不会生成保存计划。') else '请确认要处理哪条记忆以及修改后的内容，我暂时没有更改。'
        topic=value['topic']
        count=state['clarification_count'] if topic==state['clarification_topic'] else 0
        # 普通自动候选不抢占当前帮助；显式控制及修改/删除等操作仍优先。
        deferred=plan['candidates'] if plan and value['intent']=='MEMORY_CREATE' and help_now and not explicit else []
        if value['intent']=='MEMORY_CREATE' and help_now and not explicit:
            value={**value,'intent':'NONE','operations':[],'slots':[]}
            plan=None
            clarification=''
        return result(state,'memory_control_node',memory_control_intent=value['intent'],
            primary_task_priority='memory_control' if value['intent']!='NONE' else 'user_task',deferred_memory_candidates=deferred,
            memory_operation=value['operations'],memory_slot=value['slots'],memory_plan=plan,
            blocked_slots=blocked,memory_save_allowed=bool(plan and plan['candidates']),
            pending_memory_candidate=plan['candidates'] if plan else [],memory_suppressed=bool(rejection),
            memory_rejection_reason=rejection,
            action_requested=value.get('action_requested',False),action_type=value.get('action_type'),
            context_sufficient=value.get('context_sufficient',True) and not value['needs_clarification'],
            explicit_help=value['explicit_help'],action_willing=value['action_willing'],refuses_action=value['refuses_action'],
            clarification_topic=topic,clarification_count=count,
            needs_clarification=bool(value['needs_clarification'] and count<1),
            draft_response=clarification)
    except (ValidationError, json.JSONDecodeError) as exc:
        # 仅隔离结构解析失败；保留错误路径/类型，原始模型正文由 Eval RecordedClient 保存。
        details=exc.errors(include_input=False,include_url=False) if isinstance(exc,ValidationError) else [{'type':'json_invalid','msg':exc.msg,'line':exc.lineno,'column':exc.colno}]
        return result(state,'memory_control_node',memory_plan=None,memory_operation=[],memory_candidate=[],
            memory_suppressed=True,memory_save_allowed=False,memory_rejection_reason='结构解析失败，本轮不执行记忆操作',
            memory_error_details=details,errors=state['errors']+[type(exc).__name__],draft_response='')
    except Exception as exc: return failed(state,'memory_control_node',exc)


def intent_node(state, *, llm):
    """在安全检查允许普通流程后识别用户希望怎样被回应。
    
    参数：
        state (AgentState)：本轮共享状态，包含当前输入及上游节点结果。
        llm (AliyunLLM 或测试替身)：提供 intent 分类接口。
    
    返回：
        dict：供 LangGraph 合并的局部更新，并非完整 AgentState。
        写入 intent、intent_confidence；低置信时使用倾听意图 Vent；异常时终止本轮。
    
    同时追加 trace 节点轨迹；不直接修改传入的 state 字典。
    """
    try:
        if state['memory_control_intent']!='NONE':
            return result(state,'intent_node',intent='Companion',intent_confidence=1.)
        value = IntentResult.model_validate(llm.intent(state['user_input']))
        intent = value.intent if value.confidence >= .6 else 'Vent'
        return result(state,'intent_node',intent=intent,intent_confidence=value.confidence)
    except Exception as exc:
        return failed(state, 'intent_node', exc)

def emotion_node(state, *, llm):
    """在意图识别后理解非医学情绪线索，为回应和行动门槛提供依据。
    
    参数：
        state (AgentState)：本轮共享状态，包含当前输入及上游节点结果。
        llm (AliyunLLM 或测试替身)：提供 emotion 分类接口。
    
    返回：
        dict：供 LangGraph 合并的局部更新，并非完整 AgentState。
        写入 emotion、emotion_confidence；不会覆盖上游安全等级。
    
    同时追加 trace 节点轨迹；不直接修改传入的 state 字典。
    """
    try:
        value = EmotionResult.model_validate(llm.emotion(state['user_input']))
        # A downstream classifier cannot promote or clear the safety decision.
        emotion = value.emotion if value.emotion != 'High_Risk' else 'Overwhelmed'
        if value.confidence < .6:
            emotion = 'Neutral'
        return result(state,'emotion_node',emotion=emotion,emotion_confidence=value.confidence)
    except Exception as exc:
        return failed(state, 'emotion_node', exc)

def memory_retrieval_node(state, *, store):
    """在组装上下文前检索当前用户的有效记忆，维持对话连续性。
    
    参数：
        state (AgentState)：本轮共享状态，包含当前输入及上游节点结果。
        store (MemoryStore)：执行带用户作用域的记忆检索。
    
    返回：
        dict：供 LangGraph 合并的局部更新，并非完整 AgentState。
        写入 retrieved_memory；检索失败时终止本轮并记录错误类型。
    
    同时追加 trace 节点轨迹；不直接修改传入的 state 字典。
    """
    try:
        rows = store.retrieve(state['user_id'],state['user_input'])
        return result(state,'memory_retrieval_node',retrieved_memory=rows,active_memory_used_for_context=rows)
    except Exception as exc:
        return failed(state, 'memory_retrieval_node', exc)

def context_node(state):
    """在生成回复前组合稳定人格、意图策略和上下文资料。
    
    参数：
        state (AgentState)：本轮共享状态，包含当前输入及上游节点结果。
    
    返回：
        dict：供 LangGraph 合并的局部更新，并非完整 AgentState。
        写入 persona_context；序列化失败时终止本轮。
    
    同时追加 trace 节点轨迹；不直接修改传入的 state 字典。
    """
    data = {'emotion':state['emotion'],'relationship_stage':state['relationship_stage'],
            'untrusted_memory':state['retrieved_memory'],'untrusted_history':[] if state['memory_control_intent']=='MEMORY_QUERY' else state['ordinary_history']}
    try:
        return result(state,'context_node',persona_context=PERSONA+'\n'+STRATEGIES[state['intent']]+'\n'+json.dumps(data,ensure_ascii=False))
    except Exception as exc:
        return failed(state, 'context_node', exc)

def response_node(state, *, llm):
    """在上下文组装后产生普通聊天初稿，后续仍需行动判断和输出检查。
    
    参数：
        state (AgentState)：本轮共享状态，包含当前输入及上游节点结果。
        llm (AliyunLLM 或测试替身)：提供 response 生成接口。
    
    返回：
        dict：供 LangGraph 合并的局部更新，并非完整 AgentState。
        写入 draft_response；一般生成异常终止本轮。仅 Play 卡片降级后的文本请求失败，
        使用获准的本地陪伴文字，并标记 fallback_source，不冒充模型生成。
    
    同时追加 trace 节点轨迹；不直接修改传入的 state 字典。
    """
    try:
        text = state['draft_response'] if state['memory_control_intent']!='NONE' and state['draft_response'] else llm.response(state)
        if not isinstance(text,str) or not text.strip():
            raise ValueError('Empty response')
        return result(state,'response_node',draft_response=text,capability_truth=state.get('capability_truth',{}))
    except Exception as exc:
        if state.get('play_fallback') and state['risk_level']=='Normal':
            return result(state,'response_node',draft_response='我们先轻松聊一会儿也好，不急着猜。你可以随时停下来，我按你的节奏来。',
                fallback_source='local_text',errors=state['errors']+[type(exc).__name__],
                action_errors=state['action_errors']+[{'stage':'play_text_fallback','type':type(exc).__name__}])
        return failed(state, 'response_node', exc)

def action_gate_node(state):
    """生成正文前统一决定是否允许行动；显式拒绝及记忆控制优先。"""
    control=state['memory_control_intent']!='NONE'
    refusal=state['refuses_action'] or any(x in state['user_input'] for x in ['不想做任何事','不要建议','不想行动','暂时不做','不适合我','不要给行动建议','我不想做什么'])
    reflect_only=state['intent']=='Reflect' or any(x in state['user_input'] for x in ['只想理解','帮我想清楚','先分析一下'])
    text_request=(explicit_text_request(state['user_input']) and state['risk_level']=='Normal'
                  and not control and not refusal and not reflect_only and not state.get('memory_suppressed'))
    if text_request:
        # 只纠正明确填写的上下文信息，仍经过下方原有全部保护门槛。
        state={**state,'action_requested':True,'explicit_help':True,'action_type':'IN_APP',
               'context_sufficient':True,'needs_clarification':False}
    requested=state.get('action_requested',False) or state['intent']=='Action'
    # 已有求助信号用于兼容调用方，但理解原因不等于请求执行动作。
    requested=requested or (state['explicit_help'] and not reflect_only)
    declined=refusal or (state['action_declined'] and not (state['explicit_help'] or state['action_willing']))
    reason=''
    if state['risk_level']!='Normal': reason='安全分支'
    elif control: reason='记忆控制'
    elif state.get('memory_suppressed') and not (state.get('primary_task_priority')=='user_task' and state['explicit_help']): reason='记忆处理未可靠完成'
    elif declined: reason='用户拒绝建议或行动'
    elif reflect_only: reason='当前只需理解与反思'
    elif state['emotion']=='Overwhelmed' and not state['explicit_help']: reason='情绪压倒且未明确求助'
    elif not requested: reason='未请求行动'
    elif (state['needs_clarification'] or not state.get('context_sufficient',True)) and state['clarification_count']<1: reason='等待一次必要澄清'
    count=state['clarification_count']+(1 if reason=='等待一次必要澄清' else 0)
    return result(state,'action_gate_node',micro_action_allowed=not reason,micro_action_block_reason=reason,
                  requested_input_mode='text' if text_request and not reason else None,
                  action_type=state['action_type'],context_sufficient=state['context_sufficient'],explicit_help=state['explicit_help'],
                  action_requested=bool(requested),
                  action_declined=declined,clarification_count=count,
                  needs_clarification=reason=='等待一次必要澄清')


def micro_action_node(state, *, llm):
    """门槛放行后才生成一个结构化动作；不再使用通用固定结尾。"""
    if not state['micro_action_allowed']:
        return result(state,'micro_action_node',micro_action_candidate=None,action_type=None)
    errors=[]
    for attempt in range(2 if state['intent']=='Play' else 1):
        try:
            action=MicroAction.model_validate(llm.action(state)).model_dump()
            return result(state,'micro_action_node',micro_action_candidate=action,action_type=action['action_type'],
                          play_retry_count=attempt,action_errors=errors)
        except Exception as exc:
            detail={'stage':'micro_action','attempt':attempt+1,'type':type(exc).__name__}
            if isinstance(exc,ValidationError): detail['details']=exc.errors(include_input=False,include_url=False,include_context=False)
            errors.append(detail)
            if state['intent']!='Play': return failed(state,'micro_action_node',exc)
            if not isinstance(exc,(ValueError,ValidationError,json.JSONDecodeError)):
                break  # 只重试结构失败，不自动重试通信故障。
    return result(state,'micro_action_node',micro_action_candidate=None,action_type=None,micro_action_allowed=False,
        micro_action_block_reason='Play 卡片不可用，改为文本',play_retry_count=len(errors)-1,
        play_fallback=True,fallback_source='model_text',action_errors=errors,
        errors=state['errors']+[e['type'] for e in errors])


def final_response_node(state):
    """在微行动判断后合并回复，并执行现有禁句与长度检查。
    
    参数：
        state (AgentState)：本轮共享状态，包含当前输入及上游节点结果。
    
    返回：
        dict：供 LangGraph 合并的局部更新，并非完整 AgentState。
        写入 final_response、micro_action_candidate；不合格时终止本轮并清空行动。
    
    同时追加 trace 节点轨迹；不直接修改传入的 state 字典。
    """
    text = state['draft_response']
    action = state['micro_action_candidate']
    # 行动已在正文生成前确定，卡片单独呈现，不重复追加固定结尾。
    if any(x in text for x in BANNED) or len(text)>500:
        if state.get('play_fallback') and state['risk_level']=='Normal':
            return result(state,'final_response_node',final_response='我们先轻松聊一会儿吧，不急着猜。想停下来也可以。',
                          micro_action_candidate=None,fallback_source='local_text',errors=state['errors']+['PlayOutputConstraint'])
        return failed(state, 'final_response_node', ModelAPIError('回复未通过输出约束，本轮已暂停，请重试。'))
    return result(state,'final_response_node',final_response=text,micro_action_candidate=action)

def memory_candidate_node(state, *, llm, memory_store=None):
    """在最终回复形成后，从当前用户输入提取最多一个待确认记忆候选。
    
    参数：
        state (AgentState)：本轮共享状态，包含当前输入及上游节点结果。
        llm (AliyunLLM 或测试替身)：提供 candidates 提取接口。
    
    返回：
        dict：供 LangGraph 合并的局部更新，并非完整 AgentState。
        写入 memory_candidate；拒记时为空列表；提取失败时保留聊天且不生成候选，不直接保存。
    
    同时追加 trace 节点轨迹；不直接修改传入的 state 字典。
    """
    try:
        if state['memory_control_intent']!='NONE' or state.get('memory_suppressed'):
            return result(state,'memory_candidate_node',memory_candidate=[])
        if memory_store is not None and not memory_store.enabled(state['user_id']):
            return result(state,'memory_candidate_node',memory_candidate=[])
        values = state.get('deferred_memory_candidates') or llm.candidates(state['user_input'],state['user_id'])
        candidates = [MemoryCandidate.model_validate({**x,'sensitivity':is_sensitive(x)}).model_dump() for x in values[:1]]
        if any(x in state['user_input'] for x in ['不要记住','别记住','不保存']):
            candidates = []
        if memory_store is not None:
            candidates=[c for c in candidates if memory_store.candidate_status(c,state['user_id'])=='等待用户确认']
        return result(state,'memory_candidate_node',memory_candidate=candidates)
    except Exception as exc:
        return result(state,'memory_candidate_node',memory_candidate=[],memory_status='记忆整理暂不可用，本轮未生成候选',errors=state['errors']+[type(exc).__name__])

def memory_write_node(state):
    """作为普通链末尾节点检查记忆保存资格，向界面报告是否等待确认。
    
    参数：
        state (AgentState)：本轮共享状态，包含当前输入及上游节点结果。
    
    返回：
        dict：供 LangGraph 合并的局部更新，并非完整 AgentState。
        写入 memory_status；本节点不写数据库，实际确认由界面调用 MemoryStore.write。
    
    同时追加 trace 节点轨迹；不直接修改传入的 state 字典。
    """
    # Never persist without explicit UI consent. Confirmation reuses gate in store.write.
    if state['memory_status'].startswith('记忆整理暂不可用'):
        return result(state,'memory_write_node',memory_status=state['memory_status'])
    status = '未提取待保存内容'
    if state['memory_candidate']:
        try:
            _, status = gate(state['memory_candidate'][0],state['user_id'])
        except Exception:
            status = '候选无效，不保存'
    return result(state,'memory_write_node',memory_status=status)

def safety_response_node(state):
    """在 High 或 Unknown 分支提供固定安全支持回应，随后结束本轮。
    
    参数：
        state (AgentState)：本轮共享状态，包含当前输入及上游节点结果。
    
    返回：
        dict：供 LangGraph 合并的局部更新，并非完整 AgentState。
        写入 final_response、emotion、emotion_confidence、memory_status；清空记忆及行动候选。
    
    同时追加 trace 节点轨迹；不直接修改传入的 state 字典。
    """
    if state.get('safety_subject') in ('THIRD_PERSON','QUOTE'):
        text = '这句话是在转述他人，还是引用作品里的内容？如果那个人可能正处于危险中，请联系能到场的可信任的人；若有立即危险，请联系当地紧急服务。'
    elif state.get('safety_followup') and state.get('risk_reason')=='本会话安全关注尚未解除':
        text = '我在听。先确认一下：你此刻安全吗，身边有可信任的人能陪着你吗？如果有立即危险，请联系当地紧急服务。'
    elif state['risk_level']=='High':
        text = '谢谢你告诉我。我很在意你此刻的安全。你现在已经伤害自己，或正准备这样做吗？请尽快联系身边可信任的人来陪你；如果已经采取行动或有立即危险，请马上联系当地紧急服务。'
    else:
        text = '我想先确认你的安全：你现在有伤害自己的想法或打算吗？如果你有立即危险，请联系当地紧急服务或身边可信任的人。'
    return result(state,'safety_response_node',final_response=text,emotion='High_Risk' if state['risk_level']=='High' else 'Neutral',
                  emotion_confidence=0.,memory_status='安全分支不读写记忆',micro_action_candidate=None,memory_candidate=[],retrieved_memory=[])

def route_safety(state):
    """在安全节点后选择普通链或直接安全回应链。
    
    参数：
        state (AgentState)：读取 risk_level，不依赖 emotion。
    
    返回：
        str：Normal 返回 normal，其他等级返回 safety，对应条件边映射。
    """
    if state.get('service_error'):
        return 'error'
    return 'normal' if state['risk_level']=='Normal' else 'safety'

def build_graph(store, llm=None):
    """注入记忆和模型依赖，按既定顺序编译 MOMO 工作流。
    
    参数：
        store (MemoryStore)：普通链使用的 SQLite 记忆服务。
        llm (AliyunLLM、测试替身或 None)：为空时读取本地阿里云配置。
    
    返回：
        CompiledStateGraph：可调用 invoke 的图；此函数只组图，不处理一轮对话。
    """
    llm = llm if llm is not None else AliyunLLM()
    builder = StateGraph(AgentState)
    def retrieve_for_graph(state):
        """绑定项目记忆服务；避免 LangGraph 将保留参数 store 注入为框架自己的存储对象。"""
        return memory_retrieval_node(state, store=store)
    nodes = {'safety_node':partial(safety_node,llm=llm),'intent_node':partial(intent_node,llm=llm),
             'memory_control_node':partial(memory_control_node,llm=llm,memory_store=store),'action_gate_node':action_gate_node,
             'emotion_node':partial(emotion_node,llm=llm),'memory_retrieval_node':retrieve_for_graph,
             'context_node':context_node,'response_node':partial(response_node,llm=llm),'micro_action_node':partial(micro_action_node,llm=llm),
             'final_response_node':final_response_node,'memory_candidate_node':partial(memory_candidate_node,llm=llm,memory_store=store),
             'memory_write_node':memory_write_node,'safety_response_node':safety_response_node,'service_error_node':service_error_node}
    for name, function in nodes.items():
        builder.add_node(name,function)
    builder.add_edge(START,'safety_node')
    # 安全等级不是 Normal 时跳过普通链，直接进入安全回应节点并结束。
    builder.add_conditional_edges('safety_node',route_safety,{'normal':'memory_control_node','safety':'safety_response_node','error':'service_error_node'})
    chain = ['memory_control_node','intent_node','emotion_node','memory_retrieval_node','action_gate_node','micro_action_node','context_node','response_node','final_response_node','memory_candidate_node','memory_write_node']
    for left,right in zip(chain,chain[1:]):
        builder.add_conditional_edges(left, route_result, {'next':right,'error':'service_error_node'})
    builder.add_edge(chain[-1],END)
    builder.add_edge('safety_response_node',END)
    builder.add_edge('service_error_node',END)
    return builder.compile()
