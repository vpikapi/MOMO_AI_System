"""纯展示工具：样式、角色占位与日期文字；不修改业务状态或数据库。"""
from pathlib import Path
from html import escape
from datetime import datetime, timezone, timedelta
import base64
import streamlit as st

UI=Path(__file__).parent/'ui'
AVATAR=str(UI/'momo-avatar.svg')

def avatar_url():
    """返回自带 SVG 数据地址，避免页面加载外部图像。"""
    return 'data:image/svg+xml;base64,'+base64.b64encode(Path(AVATAR).read_bytes()).decode()

def apply_style():
    st.markdown('<style>'+ (UI/'styles.css').read_text(encoding='utf-8')+'</style>',unsafe_allow_html=True)

def brand():
    st.markdown('<div class="momo-brand"><img src="'+avatar_url()+'" alt="MOMO"/>MOMO <span>慢慢说，我听着。</span></div>',unsafe_allow_html=True)

def hero(title, subtitle):
    """仅呈现传入文案；动态内容转义，角色是占位图，不表示实时情绪。"""
    st.markdown('<div class="momo-hero"><div class="eyebrow">A little space for you</div><img src="'+avatar_url()+'" alt="MOMO 小宠物"/><h1>'+escape(title)+'</h1><p>'+escape(subtitle)+'</p></div>',unsafe_allow_html=True)

def memory_meta(row):
    """把已有来源与日期转成用户可读文案；不推断不存在的来源。"""
    source=row.get('source','')
    label='来自我们的聊天' if source.startswith('来自对话') else ('由你修改确认' if source=='由你编辑确认' else '来源未记录')
    try:
        day=datetime.fromisoformat(row['created_at']).astimezone(timezone(timedelta(hours=8)))
        return f'{label} · {day.month}月{day.day}日'
    except (ValueError,KeyError): return label

def greeting():
    hour=datetime.now(timezone(timedelta(hours=8))).hour
    return '早上好。' if 5<=hour<12 else '下午好。' if 12<=hour<18 else '晚上好。'

def user_marker():
    st.markdown('<span class="chat-user-marker"></span>',unsafe_allow_html=True)
