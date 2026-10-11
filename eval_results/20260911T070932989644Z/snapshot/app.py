"""MOMO 产品表现层；沿用原有 Agent 调用与记忆确认接口。"""
from datetime import datetime
from pathlib import Path
import hashlib
import json
import streamlit as st
from momo.graph import build_graph
from momo.memory import MemoryStore, edited_candidate, duplicate, sensitive_content, is_sensitive
from momo.models import initial_state
from momo.mock_llm import AliyunLLM, load_config, ModelAPIError
from ui_components import apply_style, brand, hero, greeting, memory_meta, AVATAR, user_marker

st.set_page_config(page_title='MOMO · 慢慢说，我听着',page_icon='🌿',layout='centered',initial_sidebar_state='collapsed')

@st.cache_resource
def startup_config():
    """每次服务启动读取一次本地配置；切换模型或更换密钥后需重启服务。"""
    return load_config()

store=MemoryStore(Path(__file__).parent/'data'/'momo.db')
for key,value in {'user_id':'local-single-tester','messages':[],'declined':False,'latched':False,
                  'support_open':False,'state':None,'pending':None,'action':None,'api_calls':[], 'error':None,
                  'connection':None,'connection_error':None,'connection_calls':[],'failed_input':None}.items():
    if key not in st.session_state:
        st.session_state[key]=value
st.session_state.user_id='local-single-tester'
for key,value in {'pending_items':[],'chat_open':False,'edit_key':None,'delete_request':None,'ui_page':'首页','candidate_edit':None,'action_started':False}.items():
    if key not in st.session_state: st.session_state[key]=value
for key,value in {'memory_plans':[], 'memory_revision':store.revision(st.session_state.user_id),
                  'context_start':0,'clarification_count':0,'clarification_topic':'','action_submission':None}.items():
    if key not in st.session_state: st.session_state[key]=value
revision=store.revision(st.session_state.user_id)
if revision!=st.session_state.memory_revision:
    # 界面保留原消息；普通模型上下文从修订后重新开始，Safety 仍读取原历史。
    st.session_state.context_start=len(st.session_state.messages)
    st.session_state.memory_revision=revision
    st.session_state.memory_plans=[]
    st.session_state.pending_items=[]

config=None
config_error=None
try:
    config=startup_config()
except ModelAPIError as exc:
    config_error=str(exc)

GROUPS=[('Identity','关于你'),('Episodic','最近的事'),('Relationship','共同经历'),('Preference','相处偏好')]

def open_chat():
    """进入当前会话，不新建身份或清除历史。"""
    st.session_state.chat_open=True
    st.session_state.ui_page='聊天'
    st.rerun()

def sensitive_stage(key, payload):
    """第一次确认绑定当前内容；编辑后的摘要变化会自动要求重新确认。"""
    token=hashlib.sha256(json.dumps(payload,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
    stage_key='sensitive_stage_'+key
    if stage_key in st.session_state and st.session_state[stage_key]!=token:
        st.session_state.pop(stage_key)
    return token, st.session_state.get(stage_key)==token

def begin_sensitive_confirmation(key, token):
    st.session_state['sensitive_stage_'+key]=token
    st.rerun()

def show_memory_plans():
    """展示整组影响范围；只有点击确认才调用 SQLite 事务。"""
    if st.session_state.latched: return
    for index,plan in enumerate(st.session_state.memory_plans):
        with st.container(border=True,key='card_memory_plan_'+str(index)):
            st.markdown('**确认这次记忆调整**')
            names={'CREATE':'新增','UPDATE':'修改','DELETE':'删除','BLOCK':'以后不再保存'}
            st.write('、'.join(names[x] for x in plan['operations']))
            if plan['targets']:
                st.caption('涉及的现有记忆')
                for row in plan['targets']: st.write(row['content'])
            revised=[]
            valid_content=True
            for n,c in enumerate(plan['candidates']):
                content=st.text_area('确认后的内容',c['content'],max_chars=300,key=f'plan_{index}_{n}')
                try: revised.append(edited_candidate(c,content) if content!=c['content'] else c)
                except ValueError:
                    valid_content=False
                    st.caption('内容不能为空，请填写后再确认。')
            if 'BLOCK' in plan['operations']:
                labels={'name':'称呼','job':'职业','city':'城市','education':'教育','relationship_status':'关系状态',
                    'advice_preference':'建议偏好','question_preference':'提问偏好','tone_preference':'语气偏好','interaction_preference':'互动偏好'}
                st.caption('未来不再保存：'+'、'.join(labels.get(x,x) for x in plan['slots']))
                if 'DELETE' not in plan['operations']: st.caption('本次只禁止未来写入，已有记忆保留。')
            sensitive=any(is_sensitive(c) for c in revised)
            token,second=sensitive_stage(f'plan_{index}',{**plan,'candidates':revised})
            consent=st.checkbox('我明确同意保存本次敏感信息',key=f'plan_consent_{token}') if sensitive and second else False
            if sensitive and second: st.caption('内容已确认，尚未保存。请再次确认敏感信息的保存。')
            left,right=st.columns(2)
            if left.button('确认保存敏感信息' if sensitive and second else '确认调整',key=f'apply_plan_{index}',disabled=not valid_content or (sensitive and second and not consent)):
                if sensitive and not second: begin_sensitive_confirmation(f'plan_{index}',token)
                status=store.apply_plan(st.session_state.user_id,{**plan,'candidates':revised},True,consent)
                if status=='已完成记忆操作':
                    st.toast(status)
                    st.rerun()
                st.warning(status)
            if right.button('这次不用',key=f'skip_plan_{index}'):
                st.session_state.pop(f'sensitive_stage_plan_{index}',None)
                st.session_state.memory_plans.pop(index)
                st.rerun()


def show_pending():
    """候选在聊天和记忆页共享；继续聊天不会覆盖，只有用户确认才写入长期记忆。"""
    if st.session_state.latched: return
    show_memory_plans()
    if not store.enabled(st.session_state.user_id): return
    valid=[c for c in st.session_state.pending_items if store.candidate_status(c,st.session_state.user_id)=='等待用户确认']
    st.session_state.pending_items=valid
    for c in valid:
        with st.container(border=True,key='card_pending_'+c['id']):
            st.markdown('**MOMO 想记住这件事**')
            st.write(c['content'])
            st.caption('由你决定。普通内容确认后保存，敏感内容还需再明确确认一次。')
            edited=c['content']
            if st.session_state.candidate_edit==c['id']:
                edited=st.text_area('调整这条内容',value=c['content'],max_chars=300,key='draft_'+c['id'])
            detected=is_sensitive({**c,'content':edited})
            with st.expander('保存范围与隐私'):
                marked=st.checkbox('这条内容涉及我的敏感信息',value=detected,disabled=detected,key='mark_'+c['id'])
            marked=marked or detected
            token,second=sensitive_stage(c['id'],{'content':edited,'sensitivity':marked,'id':c['id']})
            consent=st.checkbox('我明确同意保存这条敏感信息',key='consent_'+token) if marked and second else False
            if marked and second: st.caption('尚未保存，请再次确认敏感信息的保存。')
            left,middle,right=st.columns(3)
            if left.button('确认保存敏感信息' if marked and second else '记住',key='save_'+c['id'],disabled=marked and second and not consent):
                if marked and not second: begin_sensitive_confirmation(c['id'],token)
                try:
                    revised=edited_candidate(c,edited,marked) if edited!=c['content'] else {**c,'sensitivity':marked}
                    status=store.write(revised,st.session_state.user_id,{revised['id']},consent)
                    if status.startswith('已保存') or status=='已有相同或近似记忆':
                        st.session_state.pending_items=[x for x in valid if x['id']!=c['id']]
                        st.toast('已保存' if status.startswith('已保存') else status)
                        st.rerun()
                    st.warning(status)
                except (ValueError,TypeError): st.warning('请填写有效内容后再保存。')
            if middle.button('修改',key='revise_'+c['id']):
                st.session_state.candidate_edit=c['id']
                st.rerun()
            if right.button('这次不用',key='skip_'+c['id']):
                st.session_state.pop('sensitive_stage_'+c['id'],None)
                st.session_state.pending_items=[x for x in valid if x['id']!=c['id']]
                st.rerun()

def navigate(destination):
    """只切换展示页面，不重置对话、记忆或安全状态。"""
    st.session_state.ui_page=destination
    st.session_state.chat_open=destination=='聊天'

apply_style()
brand_column,mode_column=st.columns([5,1.5])
with brand_column: brand()
with mode_column: debug=st.toggle('开发者模式',value=False)
with st.container(key='momo_nav'):
    for column,destination in zip(st.columns(5),['首页','聊天','记忆','我们','设置']):
        column.button(destination,key='nav_'+destination,type='primary' if st.session_state.ui_page==destination else 'secondary',
                      use_container_width=True,on_click=navigate,args=(destination,))
page=st.session_state.ui_page
if debug:
    with st.expander('开发者调试面板',expanded=True):
        st.caption('本机单人测试 · 当前模型：'+(config.model if config else '未配置'))
        if config and st.button('测试连接（普通回复 + 分类 JSON）'):
            client=AliyunLLM(config)
            try: st.success(str(client.check_connection()))
            except ModelAPIError as exc: st.error(str(exc))
        state=st.session_state.state
        if state: st.json(state)
        st.write('待确认记忆')
        st.json(st.session_state.pending_items)
        st.write('最近模型调用')
        st.json(st.session_state.api_calls)

if st.session_state.support_open:
    st.title('安全支持')
    st.write('先照顾此刻的安全。可以让身边可信任的人陪你一起联系帮助。')
    st.selectbox('你所在的国家或地区',['请选择','中国大陆'],key='support_region')
    if st.session_state.support_region=='中国大陆':
        st.subheader('中国大陆 · 现实支持')
        with st.container(border=True,key='card_safety_urgent'):
            st.markdown('**立即危险或已经受伤：医疗急救 120**')
            st.write('需要紧急医疗救援时，请直接联系急救。')
            st.link_button('呼叫医疗急救 · 120','tel:120')
            st.markdown('**需要警方紧急帮助：110**')
            st.link_button('呼叫报警求助 · 110','tel:110')
        with st.container(border=True,key='card_safety_support'):
            st.markdown('**心理援助 · 12356**')
            st.write('可以寻求心理疏导和危机干预支持；具体服务时间以当地热线为准。紧急医疗救援请联系 120。')
            st.link_button('呼叫心理援助 · 12356','tel:12356')
        st.caption('点击后由设备打开拨号应用；电脑若无法拨号，请使用手机拨打上方号码。选择地区不会定位你或向机构发送信息。')
        with st.expander('号码来源'):
            st.markdown('[国家卫生健康委：12356 心理援助热线](https://www.nhc.gov.cn/yzygj/c100068/202412/49a1a65386cd4be582d4702fd0926ee8.shtml)')
            st.markdown('[通信管理局：110 与 120 用途](https://bjca.miit.gov.cn/zwgk/tzgg/art/2022/art_8d4eb93ee3424f30826c97ee400e8937.html)')
    else:
        st.info('请选择所在地以查看已核验的支持号码。目前覆盖中国大陆。')
    with st.expander('联系可信任的人，可以这样开口'):
        st.write('我现在状态不太好，希望你能陪我一会儿，帮我一起联系现实中的支持。')
    st.caption('这里没有真人实时监护，不会自动报警、拨号或代发消息。')
    if st.button('返回对话'):
        st.session_state.support_open=False
        st.session_state.chat_open=True
        st.session_state.ui_page='聊天'
        st.rerun()
    st.stop()

if page=='设置':
    st.title('设置')
    st.caption('舒服的相处方式，由你决定。')
    with st.container(border=True,key='card_settings_memory'):
        st.subheader('记忆与隐私')
        enabled=st.toggle('允许 MOMO 保存新的记忆',value=store.enabled(st.session_state.user_id))
        if enabled!=store.enabled(st.session_state.user_id):
            store.set_enabled(st.session_state.user_id,enabled)
            if not enabled: st.session_state.pending_items=[]
            st.rerun()
        st.caption('保存前会请你确认。关闭后，已有记忆仍可查看、修改和删除。')
        if st.button('查看我的记忆'):
            navigate('记忆')
            st.rerun()
        with st.expander('清除记忆'):
            confirm=st.checkbox('我确认清空全部演示记忆及不再记住规则')
            if st.button('清空演示记忆',disabled=not confirm):
                store.clear(st.session_state.user_id)
                st.session_state.pending_items=[]
                st.success('已清空本机测试身份的记忆与禁存规则。')
    with st.container(border=True,key='card_settings_companion'):
        st.subheader('陪伴设置')
        st.write('你可以直接告诉 MOMO，希望怎样被陪伴。')
        st.caption('主动问候与通知尚未启用。你不需要完成任务，也不用维持聊天频率。')
    with st.container(border=True,key='card_settings_safety'):
        st.subheader('安全与支持')
        st.write('需要的时候，也可以让现实中的人陪你一起。')
        if st.button('查看现实支持'):
            st.session_state.support_open=True
            st.rerun()
    with st.expander('关于 MOMO'):
        st.write('MOMO 是一个 AI 陪伴伙伴。可以倾听、陪伴和整理思绪，不能替代医生、心理专业人士或现实中的紧急帮助。')
        st.caption('对话会发送到已配置的阿里云模型；必要上下文可能包含你确认的记忆。当前为本机单人测试版本，没有登录系统。')
        if st.button('重置演示对话'):
            for key,value in {'messages':[],'declined':False,'latched':False,'support_open':False,'state':None,'pending_items':[],
                              'action':None,'api_calls':[],'error':None,'failed_input':None,'memory_plans':[],
                              'context_start':0,'clarification_count':0,'clarification_topic':'','action_submission':None}.items(): st.session_state[key]=value
            st.success('对话已重置；保留已确认记忆。这不表示现实风险已解除。')
    st.stop()

if page=='记忆':
    st.title('关于你的记忆')
    st.caption('这些是 MOMO 为了更好理解你而记住的事情。你随时可以修改或删除。')
    show_pending()
    rows=store.list(st.session_state.user_id)
    for kind,label in GROUPS:
        st.subheader(label)
        matching=[r for r in rows if r['kind']==kind]
        if not matching: st.caption('暂无已确认记忆')
        for row in matching:
            key=row['memory_key']
            with st.container(border=True,key='card_memory_'+key):
                st.write(row['content'])
                st.caption(memory_meta(row))
                with st.popover('••• 更多'):
                    if st.button('编辑',key='edit_'+key): st.session_state.edit_key=key
                    if st.button('删除',key='delete_'+key): st.session_state.delete_request=(key,False)
                    if st.button('不再记住类似内容',key='forget_'+key): st.session_state.delete_request=(key,True)
                if st.session_state.edit_key==key:
                    value=st.text_area('记忆内容',row['content'],max_chars=300,key='edittext_'+key)
                    detected=is_sensitive({**row,'content':value})
                    marked=st.checkbox('含敏感信息',value=detected,disabled=detected,key='editmark_'+key)
                    marked=marked or detected
                    token,second=sensitive_stage('edit_'+key,{'content':value,'sensitivity':marked,'row':row})
                    consent=st.checkbox('我明确同意保存修改后的敏感信息',key='editconsent_'+token) if marked and second else False
                    if st.button('确认保存敏感修改' if marked and second else '保存修改',key='update_'+key,disabled=marked and second and not consent):
                        if marked and not second: begin_sensitive_confirmation('edit_'+key,token)
                        try: status=store.update(st.session_state.user_id,key,value,consent,marked)
                        except ValueError: status='请填写有效的记忆内容。'
                        if status=='已更新':
                            st.session_state.edit_key=None
                            st.toast(status)
                            st.rerun()
                        st.warning(status)
                    if st.button('取消编辑',key='cancel_edit_'+key):
                        st.session_state.pop('sensitive_stage_edit_'+key,None)
                        st.session_state.edit_key=None
                        st.rerun()
                if st.session_state.delete_request and st.session_state.delete_request[0]==key:
                    block=st.session_state.delete_request[1]
                    st.info('删除并阻止该主题的常见类似表达再次保存。MVP 使用有限主题与文本匹配，不能识别所有改写。' if block else '仅删除这条记忆。以后再次提到时，仍可能询问是否保存。')
                    if st.button('确认不再记住' if block else '确认删除',key='confirm_'+key):
                        store.delete(st.session_state.user_id,key,block=block)
                        st.session_state.delete_request=None
                        st.rerun()
                    if st.button('取消',key='cancel_'+key):
                        st.session_state.delete_request=None
                        st.rerun()
    st.stop()

if page=='我们':
    st.title('我们')
    hero('我们还在慢慢认识彼此。','从一次倾听，到一点点了解。')
    st.markdown('<span class="momo-pill">当前阶段 · 初识</span>',unsafe_allow_html=True)
    st.caption('当前阶段保持不变，尚未启用自动关系成长。')
    st.subheader('我们的共同经历')
    shared=[r for r in store.list(st.session_state.user_id) if r['kind']=='Relationship']
    if not shared: st.caption('以后一起经历的事情，会慢慢留在这里。')
    for row in shared:
        with st.container(border=True,key='card_shared_'+row['memory_key']):
            st.write(row['content'])
            st.caption(memory_meta(row))
    st.stop()

if page=='首页':
    hero(greeting()+' 今天感觉怎么样？','想从哪里说起都可以。')
    if st.button('陪我聊聊',type='primary',use_container_width=True): open_chat()
    if st.session_state.messages and st.button('继续上次对话',use_container_width=True): open_chat()
    rows=store.list(st.session_state.user_id)
    with st.container(border=True,key='card_home_events'):
        st.subheader('最近的事')
        events=[r for r in rows if r['kind']=='Episodic'][:2]
        for event in events:
            st.write(event['content'])
            st.caption(memory_meta(event))
        if not events: st.caption('你可以慢慢告诉我。这里会留下你选择记住的事情。')
    if st.session_state.action:
        with st.container(border=True,key='card_home_action'):
            st.subheader('我们的小行动')
            st.write(st.session_state.action['title'])
            st.caption('按你的节奏来，不做也没关系。')
    shared=[r for r in rows if r['kind']=='Relationship'][:2]
    if shared:
        st.subheader('最近的共同经历')
        for row in shared:
            with st.container(border=True,key='card_home_shared_'+row['memory_key']):
                st.write(row['content'])
                st.caption(memory_meta(row))
    st.stop()

st.title('和 MOMO 聊聊')
st.caption('慢慢说，我听着。')
if config_error:
    st.error(config_error)
for message in st.session_state.messages:
    with st.chat_message(message['role'],avatar=AVATAR if message['role']=='assistant' else None):
        if message['role']=='user': user_marker()
        st.write(message['content'])
if st.session_state.error:
    if st.session_state.failed_input:
        st.caption('本轮未完成的输入：'+st.session_state.failed_input)
    st.error(st.session_state.error)
    st.caption('本轮未生成聊天回复，也未保存记忆。可在设置页测试连接后重新发送。')

state=st.session_state.state
if state and not state.get('service_error') and state['risk_level'] in ('High','Unknown'):
    with st.container(border=True,key='card_chat_safety'):
        st.subheader('安全监护 · 先照顾此刻的安全')
        st.write('可以联系身边可信任的人来陪你；如果有立即危险，请联系当地紧急服务。')
        st.caption('这里没有真人实时监护，不会自动报警或代发消息。')
        if st.button('选择地区，联系现实支持'):
            st.session_state.support_open=True
            st.rerun()

show_pending()

if st.session_state.action and not st.session_state.latched:
    with st.container(border=True,key='card_action'):
        st.markdown('**要不要试一个很小的动作？**')
        st.write(st.session_state.action['title'])
        st.caption('现在不做也可以，不影响我们相处。')
        left,right=st.columns(2)
        if left.button('试试看',use_container_width=True):
            st.session_state.action_started=True
        refused=right.button('今天算了',use_container_width=True)
        feedback='暂时不做' if refused else None
        if st.session_state.action_started:
            action=st.session_state.action
            if action.get('action_type','OFFLINE')=='IN_APP':
                options=action.get('options',[])
                answer=st.selectbox('请选择一项', ['请选择']+options,key='action_answer_choice') if action.get('input_mode','choice' if options else 'text')=='choice' else st.text_area(action['input_prompt'],key='action_answer_text',max_chars=1000)
                if st.button('提交给 MOMO',disabled=not answer.strip() or answer=='请选择'):
                    st.session_state.action_submission=answer
                    st.session_state.action=None
                    st.session_state.action_started=False
                    st.rerun()
                if st.button('不适合我'): feedback='不适合我'
            else:
                st.caption('试过之后，可以回来告诉我。')
                for column,label in zip(st.columns(2),['完成了','不适合我']):
                    if column.button(label): feedback=label
        if feedback:
            # 沿用既有反馈结果与业务状态；“试试看”仅展开反馈按钮，不当作已完成。
            st.session_state.declined=feedback!='完成了'
            st.session_state.messages.extend([{'role':'user','content':feedback},
                {'role':'assistant','content':'谢谢你告诉我。按你的节奏来就好。'}])
            st.session_state.action=None
            st.session_state.action_started=False
            st.rerun()

text=st.chat_input('今天想和 MOMO 说些什么？',max_chars=4000,disabled=config is None)
submitted_action=bool(st.session_state.action_submission)
if submitted_action:
    text=st.session_state.action_submission
    st.session_state.action_submission=None
if text and text.strip():
    # 先显示并保留用户消息；历史快照不包含当前输入，避免重复发送给模型。
    history=list(st.session_state.messages)
    st.session_state.messages.append({'role':'user','content':text})
    with st.chat_message('user'):
        user_marker()
        st.write(text)
    with st.chat_message('assistant',avatar=AVATAR):
        output=st.empty()
        output.caption('正在回应…')
        parts=[]
        def show_delta(chunk):
            """将模型正式正文逐段显示；不接收或展示内部思考。"""
            parts.append(chunk)
            output.markdown(''.join(parts)+' ▌')
        client=AliyunLLM(config,on_text=show_delta)
        state=build_graph(store,client).invoke(initial_state(st.session_state.user_id,text,
              history,st.session_state.declined,st.session_state.latched,
              st.session_state.clarification_count,st.session_state.clarification_topic,
              history[st.session_state.context_start:]))
        if state.get('service_error'):
            output.empty()
        else:
            output.markdown(state['final_response'])
    st.session_state.state=state
    st.session_state.api_calls=client.calls
    st.session_state.error=state.get('service_error')
    st.session_state.action=None
    st.session_state.action_started=False
    st.session_state.failed_input=None
    if not state.get('service_error'):
        st.session_state.messages.append({'role':'assistant','content':state['final_response']})
        st.session_state.clarification_count=state['clarification_count']
        st.session_state.clarification_topic=state['clarification_topic']
        if state.get('memory_plan') and not submitted_action:
            st.session_state.memory_plans=[state['memory_plan']]
        st.session_state.latched=state['safety_latched']
        st.session_state.declined=state['action_declined']
        if state['memory_status']=='等待用户确认' and not submitted_action:
            for candidate in state['memory_candidate']:
                if not any(duplicate(candidate,c) for c in st.session_state.pending_items):
                    st.session_state.pending_items.append(candidate)
        st.session_state.action=state['micro_action_candidate']
        if state['risk_level'] in ('High','Unknown'):
            st.session_state.support_open=True
    st.rerun()
