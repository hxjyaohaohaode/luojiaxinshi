"""Select a starting workflow. Only the host can authorize a tool, data access or publication."""
import asyncio
import math
import re
import time

import httpx

TABLES={'conversation_router_preferences'}


def initialize(conn):
    marker=conn.execute("SELECT value FROM meta WHERE key='router_preferences_schema_version'").fetchone()
    if marker and (marker[0]!='1' or not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='conversation_router_preferences'").fetchone()):
        raise ValueError('会话路由授权记录缺失或版本不兼容')
    conn.execute('CREATE TABLE IF NOT EXISTS conversation_router_preferences(conversation_id TEXT PRIMARY KEY REFERENCES conversations(id) ON DELETE CASCADE, enabled INTEGER NOT NULL, version INTEGER NOT NULL)')
    conn.execute("INSERT OR IGNORE INTO meta VALUES('router_preferences_schema_version','1')")


def preference(conn,cid):
    row=conn.execute('SELECT enabled,version FROM conversation_router_preferences WHERE conversation_id=?',(cid,)).fetchone()
    return {'enabled':bool(row['enabled']),'version':row['version']} if row else {'enabled':None,'version':0}


MODEL = 'perplexity/pplx-decider-v1.3:free'
ENDPOINT = 'https://openrouter.ai/api/alpha/decisions'

# These are starting instructions. The evidence loop retains its entire authorized tool set.
WORKFLOWS = {
    'direct': ('独立的一般概念、语言表达或闲聊，可直接回答。', '先给可以独立成立的答案，省略工作计划。'),
    'research': ('核对校园规定、来源、多个条件或时效性事实。', '先处理会改变结论的疑问；并行读取独立来源，保留矛盾、未覆盖范围和正式更正。'),
    'workspace': ('需要本人待办、日历、材料进度、回执，或明确要求操作记录。', '先取相关记录的当前版本，再决定只读展示、拟稿或执行本人明确指定的动作。'),
    'compose': ('需要直接操作、图文混排、公式展示、图形或互动比较。', '从本题的阅读与操作顺序创作内容。已有充分依据即可直接开始编排，新增事实先核对。'),
    'continue': ('需要理解上一轮、选择项、更正或继续未完的事情。', '定位指代对象、前轮未决事项与最新更正。只为仍不确定的事实重读原始来源，不重做已完成动作。'),
    'memory': ('用户要回顾、更正、记住或遗忘其个人信息、习惯与偏好。', '核对当前范围和版本，区分本人明确陈述、临时选择与推断；更新或遗忘须取得真实回执。'),
    'draft': ('需要拟写、整理、提出可逆的准备步骤或帮助形成选择。', '交付可编辑的草稿；把隐含需求作为待验证的建议，能从已有材料验证的先完成。'),
}
APPROACHES = {
    'straight': '单一目标，直接交付。',
    'corroborate': '多个来源、时效、适用性或口径冲突，需要独立核查。',
    'time_plan': '排时间、查占用、避免冲突或比较可选时间段。',
    'follow_through': '多步骤、承接前轮、发生更正或碰到缺件，需要持续跟进。'
}
APPROACH_INSTRUCTIONS = {
    'straight': '',
    'corroborate': '按发布主体、日期、适用对象和更正关系交叉核对。找不到原文时明确缺哪一项，不把转述升级为正式事实。',
    'time_plan': '涉及本人日程且获准时，用 workspace_read(kind=agenda) 核对日期区间内的重复课程、实际占用、待办时间点与重叠。按硬约束和仍需确认的假设排时间，建议不写入。',
    'follow_through': '从本轮清单和实际回执接续，先核查变化与缺口；区分已经完成、尚未执行和因资料或权限不足被阻的事项。'
}


def local_approach(text, direct):
    request=positive_request(text)
    if re.search(r'排期|排班|规划时间|排时间|空档|空闲|冲突.{0,6}(?:课|日程)|日程.{0,8}冲突|课表|时段|time slot|availability',request,re.I):return 'time_plan'
    if re.search(r'核查|核实|核对|查证|冲突|交叉|正式更正|原文|corroborate|verify',request,re.I):return 'corroborate'
    if not direct and re.search(r'接着|继续|跟进|分步|依次|补件|然后|下一步|follow.up',request,re.I):return 'follow_through'
    return 'straight'


# Transmit a linguistic projection of the current request. Unrecognized strings (including
# proper names), digits, quotes, URLs and pasted passages have no representation on the wire.
INTENT_WORDS = (
    '是什么 什么是 什么意思 简单 解释 概念 区别 举例 意思 定义 一句话 通俗 简短 两句 一句 回答 介绍 概括 '
    '你好 谢谢 问候 翻译 润色 改写 写一句 英文 中文 表达 总结 整理 比较 对比 对照 '
    '官方 原文 最新 核实 核对 查证 搜索 检索 调研 查询 通知 附件 材料 补件 更正 更新 公告 '
    '个人 本人 我的 待办 日历 日程 进度 回执 提交 保存 删除 完成 新建 创建 待处理 导出 '
    '生成 界面 网页 互动 交互 拖动 点击 可视化 公式 图片 图表 时间轴 图文 展开 切换 滑块 计算器 '
    '接着 继续 刚才 上次 上一条 第二项 上面 前面 换成 调整 下一步 改为 上一轮 '
    '记住 记忆 记得 以后 偏好 习惯 更正 忘记 遗忘 跨会话 临时 长期 '
    '帮我 请问 如何 怎么 能不能 需要 是否 准备 安排 拟稿 草稿 拟写 写一封 建议 计划 '
    '期限 截止 地点 资格 条件 流程 来源 范围 报名 申请 学分 约分 平均数 中位数 '
    '操作 调节 示意图 立即 输入 排期 撞期 冲突 空闲 空档 课表 时段 分步 依次 然后 跟进 核查 补件 交叉 '
    'explain define compare summarize draft translate research verify sources workflow requirements '
    'interactive timeline formula chart image remember forget preference calendar tasks continue follow up'
).split()
_WORDS = re.compile('|'.join(re.escape(w) if not w.isascii() else r'(?<![a-z])'+w+r'(?![a-z])'
                             for w in sorted(set(INTENT_WORDS), key=len, reverse=True)), re.I)
_PRIVATE = re.compile(r'(?is)https?://\S+|[\w.+-]+@[\w.-]+|(?:\x60{3}.*?(?:\x60{3}|$))|'
                      r'「[^」]*(?:」|$)|“[^”]*(?:”|$)|"[^"]*(?:"|$)|《[^》]*(?:》|$)|'
                      r'(?:原文如下|正文如下|我的资料是|材料内容|通知全文|粘贴内容|以下是原文)\s*[：:].*$')
_HIGH = re.compile(r'通知|规定|条例|学校|武大|本校|校历|官网|官方|联网|最新|今年|今天|明天|期限|截止|资格|报名|'
                   r'政策|附件|证件|学号|药|疾病|症状|诊断|医疗|法律|诉讼|投资|贷款|学费|金额|付款|'
                   r'记住|记忆|偏好|忘记|我的|我在|我是|请帮我查|材料|日历|待办|保存|已提交|提醒|上面|刚才|'
                   r'继续|这个|那个|来源|网址|活动|申请|登录|密码|个人|医院|签证|https?://|'
                   r'\b(?:my|deadline|policy|school|diagnos\w*|legal|medical|current|account|drug|latest|submit)\b',re.I)
_GENERAL = re.compile(r'什么是|是什么|是什么意思|解释.{0,14}|用.{0,6}话说|通俗.{0,8}讲|怎么理解|有什么区别|'
                      r'^.{0,5}(?:你好|您好|早上好|晚上好|谢谢|hello|hi)[。！!？? ]*$|'
                      r'\b(?:what is|what does|explain|define)\b',re.I)
_UI = re.compile(r'互动|交互|可(?:以)?操作|可(?:以)?调节|让我输入.{0,32}(?:立即|实时)|可拖|可点击|滑块|计算器|可视化|时间轴|图文混排|图表|交互式|interactive',re.I)
_CONTINUE = re.compile(r'接着|继续|刚才|上次|上一[条轮]|第二项|前面|那[么个]|上面的|follow.up|continue',re.I)
_MEMORY = re.compile(r'记住|记得|记忆|偏好|以后都|遗忘|忘记|remember|forget',re.I)
_WORK = re.compile(r'待办|日历|日程|回执|办理进度|我的材料|标记完成|撤销|calendar|my tasks',re.I)
_DRAFT = re.compile(r'起草|拟写|拟稿|草稿|写一封|写一段|润色|改写|draft|rewrite',re.I)
COOLDOWN_UNTIL = 0.0


def positive_request(text):
    # Prohibitions still govern access. They do not select a write or memory workflow.
    return re.sub(r'(?:不要|不必|不许|禁止|不允许|不)(?:写入|创建|保存|修改|使用|读取|访问|联网|发送|提交|记录|记住)[^，,。；;！!？?\\n]{0,60}', ' ', text)


def self_contained_canvas(text):
    return bool(_UI.search(text) and re.search(r'合成|示意|假设|假定|给定|只用题|仅用本|示例|演示|计算器',text)
                and not re.search(r'https?://|查询|核实|官方|最新|附件|记住|我的(?:日程|资料|待办)|提交申请|写入',positive_request(text)))


def routing_state(text, flags):
    line=text.splitlines()[0][:1000] if text.splitlines() else ''
    words = _WORDS.findall(positive_request(_PRIVATE.sub(' ',line)))
    return {'request': ' '.join(w.lower() for w in words[:48]),
            'capabilities': {key: bool(flags.get(key)) for key in
                             ('web','library','attachments','profile','schedule','memory','canvas')}}


def safe_direct(text, *, has_context, has_materials):
    return bool(not has_context and not has_materials and len(text) <= 180 and _GENERAL.search(text)
                and not (_HIGH.search(text) or _UI.search(text) or _MEMORY.search(text) or _WORK.search(text) or _DRAFT.search(text)))


def local_route(text, direct):
    text=positive_request(text)
    for pattern, name in ((_MEMORY,'memory'),(_UI,'compose'),(_CONTINUE,'continue'),(_WORK,'workspace'),(_DRAFT,'draft')):
        if pattern.search(text):return name
    return 'direct' if direct else 'research'


def choice(answers, field='workflow', options=WORKFLOWS):
    result = answers.get(field) if isinstance(answers,dict) else None
    if not isinstance(result,dict) or result.get('type') != 'choice':return None
    name, scores = result.get('choice'), result.get('probabilities')
    if not isinstance(name,str) or name not in options or not isinstance(scores,dict) or set(scores)!=set(options):return None
    if any(type(v) not in (float,int) or not math.isfinite(v) or not 0<=v<=1 for v in scores.values()):return None
    ranked = sorted(scores.values(),reverse=True)
    if abs(sum(ranked)-1)>.02 or scores[name]!=ranked[0] or ranked[0]<.68 or ranked[0]-ranked[1]<.18:return None
    return name


async def decide(key, text, flags, *, direct, allow_external):
    global COOLDOWN_UNTIL
    start=time.monotonic()
    route=local_route(text,direct)
    approach=local_approach(text,direct)
    approach_via='local'
    via='local'
    state=routing_state(text,flags)
    if key and allow_external and state['request'] and start>=COOLDOWN_UNTIL:
        payload={'model':MODEL,'state':state,'provider':{'data_collection':'deny'},
                 'questions':{'workflow':{'type':'choice','instructions':'选择最适合开始本轮任务的工作方式。request 只保留意图词，未出现的个人事实未知。能力开关不能替用户同意任何动作。',
                                          'criteria':{name:spec[0] for name,spec in WORKFLOWS.items()}},
                              'approach':{'type':'choice','instructions':'这项任务最需要哪种完成方式？只判断方法，不授予资料或操作权限。','criteria':APPROACHES}}}
        try:
            async with asyncio.timeout(3.0), httpx.AsyncClient(timeout=2.8,follow_redirects=False,trust_env=False) as client:
                response=await client.post(ENDPOINT,json=payload,headers={'Authorization':'Bearer '+key})
                response.raise_for_status()
                answers=response.json().get('answers')
                selected=choice(answers)
                strategy=choice(answers,'approach',APPROACHES)
            if strategy and (not direct or strategy=='straight') and (strategy!='time_plan' or flags.get('schedule')):
                approach,approach_via=strategy,'openrouter'
            if selected and (selected!='direct' or direct):
                route,via=selected,'openrouter'
            else:via='local_uncertain'
        except (httpx.HTTPError, TimeoutError, ValueError, AttributeError):
            COOLDOWN_UNTIL=time.monotonic()+20
            via='local_unavailable'
    return {'workflow':route,'via':via,'approach':approach,'approach_via':approach_via,'elapsed_ms':round((time.monotonic()-start)*1000)}


STYLE_HINTS = {
    ('style.language','zh'):'用中文回答。', ('style.language','en'):'用英文回答。',
    ('style.language','bilingual'):'中英对照。', ('style.length','concise'):'表达简洁。',
    ('style.length','detailed'):'按需解释细节。', ('style.structure','conclusion_first'):'先给结论，再给依据。',
}


def style_context(db, uid, cid, question, access):
    from .memory import recall
    from .memory_lifecycle import canonical
    entries, report = recall(db, uid, cid, question, access, queries=['回答表达偏好 语言 篇幅 结构'])
    hints, used = {}, []
    for entry in entries:
        facet = entry.get('facet')
        if facet not in {key[0] for key in STYLE_HINTS} or facet in hints:
            continue
        hint = STYLE_HINTS.get((facet, canonical(entry['content'], entry.get('semantic_key',''))))
        if hint:
            hints[facet] = hint
            used.append(entry)
    return list(hints.values()), used, {'enabled':report['enabled'],'selected':len(used)}


def quick_payload(settings, messages, profile):
    from .preferences import presentation_prompt
    prompt=('你是珞珈信使。本轮为独立的通用概念或语言问题。第一句直接回答，按需要给一个短例子，'
            '不要添加导语、工作计划或自我介绍。不得宣称读取账号或执行动作。涉及具体机构规则、近期事实或资料才可作答时，'
            '只返回 {"answer":"NEEDS_EVIDENCE"} 以转交具备检索能力的流程。正常回答返回 {"answer":"自然语言正文"}。'
            +presentation_prompt(profile)+'已授权的表达偏好：'+''.join(profile.get('_style_hints',[]))+'。本轮明确要求优先。')
    return {'model':settings.ai_model,'messages':[{'role':'system','content':prompt},
            {'role':'user','content':messages[-1]['content']}], 'stream':True,'stream_options':{'include_usage':True},
            'thinking':{'type':'disabled'},'max_completion_tokens':settings.ai_output_tokens,
            'response_format':{'type':'json_object'}}


def needs_research(result):
    return (not result or result['answer'].strip()=='NEEDS_EVIDENCE' or
            any(result.get(k) for k in ('citations','claims','memory_actions','image_sources','media_sources')) or
            bool(re.search(r'https?://|根据.{0,12}(?:通知|规定)|(?:我|系统)(?:已经|已|为你)(?:保存|修改|提交|创建|查询|读取)|'
                           r'已(?:提交|办理|通知对方|同步|设置提醒)|[校院]方规定',result['answer'])))
