"""Native answer authoring inside the tool loop, using the chat's validator.

Evidence IDs are append-only for a turn. A later search must never renumber a
span already read by the model. UI schemas are discovered only when needed.
"""
import json
import re
from copy import deepcopy

from ..ai import check_evidence
from ..genui import CATALOG, LIMITS, ROOT, parse_message
from ..genui_ai import UIAnswer, evidence_index, resolve_citations
from ..genui_prompt import encode_authored_ui


CONTRACT = '''
你负责本轮完整答复：必要时调用工具，读取结果后决定继续查证还是直接回答，不走固定步骤。
偏好说明、纠错、问候等日常交流应自然简短回应，不强行要求提供学校通知，也不套“结论/依据/说明”段落。内部协议修复和记忆字段校验不写进正文；除非实际失败需要用户处理，不添加无关免责声明或重复用户原话。
证据足够或已清楚说明缺项后，单独调用 submit_answer 提交最终内容（不能只是计划或声称将继续工作）。用户说“纯文字”“一句话”限制的是 answer 的呈现，不取消内部工具协议。参数形状：
{"answer":"Markdown 正文","claims":[{"kind":"fact|inference|advice|unknown|interface","text":"关键结论","evidence_refs":["E1"]}],"image_sources":[],"memory_actions":[]}
answer 先给本题结论、最重要的条件或下一步；正文中的材料事实就近引用工具 evidence_index 中的 [E编号]。不要手写显示编号、citations 或 citation_indices。没有依据的结论保留未知。执行回执只证明那次操作；读取和子任务概述不能证明学校手续已经完成。
每条 claim 聚焦一个可核对的事实，evidence_refs 只放支持这条事实的原文；不能把相邻的另一个材料顺手挂到同一 claim。图像/音视频中的直接观察属于 fact，尚未直接观察到的推断才是 inference。
submit_answer 不能与其他工具放在同一批。也兼容无工具调用的最终 JSON 内容。服务器将检查引文、交互协议、当前权限，并独立复核后发布；有问题会阻止发布。简单问答不需要检索或界面，不因流程而额外搜索。
需要分层阅读、选择、筛选、试算等交互时，先调用 ui_capabilities 取得所需组件的准确协议，再用随之开放的 submit_interface 提交 lead/state/nodes/claims。lead 只用一句必要导语，nodes 承担主要信息和操作，不套整页模板；同一事实只表达一次，支持细节按需展开。
memory_control.may_propose=true 时，主动判断本轮是否有新事实、偏好、项目目标或纠错；有维护需要才读取 memory_capabilities，再随最终答复提交 memory_actions，不必等用户说“记住”。没有新信息不为凑流程调用。纯文字答复同样可以维护记忆。临时要求不能变成长期偏好，目标 ID、版本和范围不能猜，关闭或限制记忆时不提交操作。已有记忆不能当作当前官方规定。
长期偏好与本次答复要求分别处理；每条 source_quote 只摘取支持这一条的最小完整原句，不把同一消息里的临时指令混入长期记录。维护操作在答复核验后才执行，本次提交前没有保存回执，正文不能声称“已保存/已记下”；用实际内容说明本轮如何响应，保存状态由宿主真实回执展示。
本轮提供的原图直接随调用发送；看到像素后可使用图片观察 ref 作答，同时登记 image_sources。不为读图额外转交生成器；未附原图或无法辨认时保留缺口，不猜内容。
建议的理由也须有依据：材料中的功能清单不等于评分标准，未给全规则时不得声称“只有这些要求”或“唯一缺口”；自己拟定的顺序、优先级和验收方式明确作为个人建议。
缺失年份或关键前提时先标明未知，继续做不依赖这些前提的准备，不主动假设年份计算倒计时。不要为解释简单材料扩展无关情景或反复复述全部原文。
attachment_inventory 是整批材料目录，不等于全部内容已理解。失败、旧 Office 无文字、没有附原件的媒体需按文件名明确缺口，不能静默漏读。音视频随调用发送，观察结论引用对应 ref 并登记 media_sources；不把媒体信息或文件名当成内容。多份资料要比较和汇总当前问题所需内容，不只复述第一份。
'''


CAPABILITY_RULES = '''
使用 submit_interface 提交互动答复，参数为 {lead:一句必要导语,state:{},nodes:[节点],claims:[]}，主要回答写在 nodes，不再把 ui 序列化为字符串。按问题自由组织内容，不选整页模板。先突出结论或期限，再给有用交互，依据按需展开。Section 默认 plain；不套卡片，不写装饰标题、重复说明和空统计。lead 不重复 nodes 中的期限、结论、清单或原文。控件只用短功能标签。
控件自带 label，不再配同义 Heading。标签不加“可勾选”“按需展开”等操作说明。相同限制、用途、免责声明最多出现一次；没有提交行为或误解风险时，不额外插入未提交声明。时区用于内部判断，仅在跨时区确实影响结论时展示。不要复述用户的生成指令，把这些指令当成活动原文。
ui 是 JSON 对象 {state:{},nodes:[节点]}。节点只有 id/type/props/children/on；id 唯一且英文安全，children 与 props 同级，可直接嵌套子节点。不要写传输 op 或 HTML/JS/CSS。建议不超过40节点和4层；Markdown 正文使用 props.text。common_properties 适用于全部组件，其余属性按 components 的准确字段，禁止猜字段。
props 支持字面量或单键 {$bind:状态路径}/{$expr:纯表达式}/{$ref:数据路径}。输入的 bind 和 state 动作 key 必须在 state 中初始化。服务器材料用 $ref:materials（id/name/status），不能冒充服务器数据或把未知填为0。事实引用[E编号]，本地勾选不代表已提交或已完成手续。
on 映射 click/change/submit，动作按 actions schema。host 用 name（不是 action），open_calendar/open_sources/upload_material 参数为 {}；review_material 参数为 {source_id:当前材料id}。open_url 只能指向本轮证据登记的网址。ask_model 只能由用户显式点击或提交触发，values 携带当前选择；不会自动办理。只有宿主的保存互动进度按钮才持久保存，不用 state.saved 冒充保存。
表达式只允许目录中的纯函数、路径、数组、运算和条件表达式；不支持 JavaScript、对象字面量、箭头函数、方法调用或 concat/append。where(rows,"字段",值)、search(rows,关键词)、orderBy(rows,"字段",降序)、take(rows,数量)、pluck(rows,"字段") 操作记录；contains(数组或字符串,值) 判包含。数值计算须说明假设与单位。
Collection 用 items/keyField/children；子树用 $bind:item.字段、$expr:item.字段 和 itemIndex。逐项编辑须 Collection.bind 指向 state 原始数组，输入 bind:item.note，字段提前初始化，按稳定 keyField 保留归属。来源事实保持只读，批注和草稿另设字段。不可用静态初值冒充用户确认。Checklist.bind 指向已勾选id数组；Tabs/Choice 只有确需切换视角时使用，选择应改变可见内容。
Grid/Row 用目录定义控制列数、ratios、minWidth，窄屏由宿主纵排。每个输入或按钮必须有实际作用；补充原文用 Accordion。不创建重复“查看依据”入口。Image/Video 只能用当前 resources 中的 src，有 alt/label；没有素材就用文字。Plot 只在需要可信数值试算时用，不编造事实。
'''


def extend_index(entries, sources):
    keys = {(e['source_id'], e['locator'], e['quote']) for e in entries}
    for entry in evidence_index(sources):
        key = entry['source_id'], entry['locator'], entry['quote']
        if key not in keys and len(entries) < 120:
            entries.append({**entry, 'ref': 'E' + str(len(entries) + 1)})
            keys.add(key)


def capabilities(components, include_memory=False):
    names = [] if include_memory and not components else list(dict.fromkeys(['Stack', 'Section'] + (components or ['Heading', 'Markdown', 'KeyValue', 'List', 'Accordion', 'Button', 'Checklist'])))
    if any(name not in CATALOG['components'] for name in names):
        raise ValueError('未知组件；可选：' + ', '.join(CATALOG['components']))
    shared = {key: CATALOG['components']['Section']['properties'][key] for key in ('status','fallback','error','visible')}
    schemas = {name: {**{key: value for key, value in CATALOG['components'][name].items() if key not in ('tier','a11y','properties')},
                      'properties': {key: value for key, value in CATALOG['components'][name]['properties'].items() if key not in shared}}
               for name in names}
    result = {'node_shape': {'id': 'uniqueId', 'type': '组件名', 'props': {}, 'children': [], 'on': {}},
              'structure': 'children 与 props 是同级字段；不要把 children 放在 props 内。',
              'rules': CAPABILITY_RULES if names else '',
              'common_properties': shared, 'components': schemas,
              'actions': CATALOG['actions'], 'available_components': list(CATALOG['components'])}
    # Expressions are an interpreter, never arbitrary JavaScript.
    text = (ROOT / 'docs/genui/CAPABILITIES.txt').read_text(encoding='utf-8')
    result['expressions'] = '\n'.join(line for line in text.splitlines() if line.startswith(('表达式', '状态', '数据', '$', '函数', '纯函数')))
    if include_memory:
        from ..memory_learning import MemoryAction, AGENT_POLICY
        result.update(memory_actions_schema=MemoryAction.model_json_schema(), memory_policy=AGENT_POLICY)
    return result


def page_capabilities(result, budget):
    """Never cut a schema mid-field: return complete schemas and deferred names."""
    def size(value):return len(json.dumps(value,ensure_ascii=False,separators=(',',':')).encode())
    if size(result) <= budget:return result
    remaining = list(result['components'])
    page = {**result, 'components': {}, 'deferred_components': remaining,
            'next': '本页只包含 components 中列出的完整协议；需要其他组件时再次调用 ui_capabilities 并仅传 deferred_components 中所需名称。'}
    for name, schema in result['components'].items():
        candidate = {**page, 'components': {**page['components'], name: schema},
                     'deferred_components': [n for n in page['deferred_components'] if n != name]}
        if size(candidate) <= budget:page = candidate
    if not page['components'] or size(page) > budget:
        raise ValueError('本轮上下文余量不足以完整返回组件或记忆协议；不要猜字段，缩小请求范围或使用 research_complete 转交原生成器')
    return page


def normalize_ui(value):
    """One unambiguous structural spelling, not content repair or a template.

    Some tool providers put container children in props despite the schema.
    Move that exact field only for a known container with no competing field;
    all values still pass the original graph/action/evidence checks below.
    """
    value, changes = deepcopy(value), []
    if not isinstance(value, dict) or not isinstance(value.get('nodes'), list):
        return value, changes
    def visit(node, depth):
        if depth >= LIMITS['depth']:
            raise ValueError('界面嵌套超过限制')
        if not isinstance(node, dict):
            return
        props = node.get('props', {})
        kind = node.get('type')
        if isinstance(props, dict) and 'children' in props and isinstance(kind, str) and CATALOG['components'].get(kind, {}).get('children'):
            if 'children' in node:
                raise ValueError('children 同时出现在节点和 props 中；请消除歧义，不能自动合并')
            node['children'] = props.pop('children')
            changes.append({'node': node.get('id'), 'field': 'props.children', 'normalized_to': 'children'})
        if isinstance(node.get('children'), list):
            for child in node['children']:
                visit(child, depth + 1)
    for node in value['nodes']:
        visit(node, 0)
    # A Checklist already renders its label. An adjacent, identical Heading
    # has no additional content; remove only that exact, unreferenced duplicate.
    referenced = set()
    def references(nodes):
        for node in nodes:
            if not isinstance(node, dict):
                continue
            children = node.get('children', [])
            if isinstance(children, list):
                referenced.update(child for child in children if isinstance(child, str))
                references(child for child in children if isinstance(child, dict))
    references(value['nodes'])
    def deduplicate(nodes):
        kept = []
        for index, node in enumerate(nodes):
            after = nodes[index+1] if index+1 < len(nodes) else None
            if isinstance(node, dict):
                props = node.get('props', {})
                if (node.get('type') == 'Heading' and isinstance(props, dict) and set(props) <= {'text', 'level'}
                    and isinstance(props.get('text'), str) and not node.get('children') and not node.get('on')
                    and isinstance(node.get('id'), str) and node['id'] not in referenced and isinstance(after, dict) and after.get('type') == 'Checklist'
                    and isinstance(after.get('props'), dict) and after['props'].get('visible', True) is True
                    and props['text'] == after['props'].get('label')):
                    changes.append({'node': node.get('id'), 'field': 'duplicate_heading', 'normalized_to': 'Checklist.label'})
                    continue
                if isinstance(node.get('children'), list):
                    node['children'] = deduplicate(node['children'])
            kept.append(node)
        return kept
    value['nodes'] = deduplicate(value['nodes'])
    return value, changes


def compile_answer(raw, sources, entries, *, allow_ui=True, normalization_log=None):
    """Same strict citation/graph boundary as the existing streaming writer."""
    value = json.loads(raw)
    changes = []
    if isinstance(value, dict) and value.get('ui') is not None:
        value['ui'], changes = normalize_ui(value['ui'])
    parsed = UIAnswer.model_validate(value)
    # Reuse the existing lifecycle decision for each quoted sentence. A
    # durable sentence cannot confer lifetime on a following one-off command.
    # Return feedback; never silently rewrite the user's meaning or action.
    from ..memory_lifecycle import admit
    for action in parsed.memory_actions:
        if action.operation != 'remember' or action.lifetime != 'long_term':
            continue
        sentences = [s.strip() for s in re.split(r'[。！？；\n]+', action.source_quote) if s.strip()]
        transient = [s for s in sentences if admit(s, action.kind) != 'long_term'
                     and re.match(r'^(?:请|这次|本次|本轮|暂时|今天|仅|只)', s)]
        if transient:
            raise ValueError('长期记忆混入临时要求：' + '；'.join(transient)[:220] +
                '。把这些句子移出长期 content/source_quote，必要时另用 lifetime=turn/session；同步修正正文中的长期承诺。')
    if not parsed.answer.strip():
        raise ValueError('answer 须先给简短结论，不能为空')
    if parsed.ui and not allow_ui:
        raise ValueError('本轮要求纯文字，请移除 ui')
    result = resolve_citations(parsed.model_dump(), entries)
    check_evidence(result['citations'], sources)
    ui = result.pop('ui', None)
    if any(p['kind'] == 'ui' for p in parse_message(result['answer'])):
        raise ValueError('answer 只能写 Markdown，界面须放在 ui 字段')
    if ui:
        result['answer'] += encode_authored_ui(ui)
    if len(result['answer']) > 80000:
        raise ValueError('回答超过长度上限')
    # Parse every graph before it becomes even a candidate for publication.
    from ..grounding import check_result
    check_result(result, sources)
    if normalization_log is not None:
        normalization_log.extend(changes)
    return result


def rebase_draft(raw, entries, sources):
    """Rebase stable refs only when handing a rejected candidate to the writer."""
    current = {(e['source_id'], e['locator'], e['quote']): e['ref'] for e in evidence_index(sources)}
    mapping = {e['ref']: current.get((e['source_id'], e['locator'], e['quote']), e['ref']) for e in entries}
    import re
    def visit(value):
        if isinstance(value, str):
            return re.sub(r'\[(E[1-9][0-9]*)\]', lambda m: '[' + mapping.get(m[1], m[1]) + ']', value)
        if isinstance(value, list): return [visit(v) for v in value]
        if isinstance(value, dict): return {k: [mapping.get(ref, ref) for ref in v] if k=='evidence_refs' and isinstance(v,list) else visit(v) for k, v in value.items()}
        return value
    return json.dumps(visit(json.loads(raw)), ensure_ascii=False)
