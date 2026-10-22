from .preferences import PERSONAL_KEYS,presentation_prompt
"""Existing compatible model transport, now with bounded SSE and JSON-string streaming."""
import base64
import codecs
import json
import re

import httpx
from pydantic import Field,ConfigDict,ValidationError

from .ai import AIError, ReplyValidationError, check_evidence
from .chat_ai import ChatAnswer, GroundingClaim, IMAGE_MIME, PROMPT, MAX_CITATIONS
from .genui import LIMITS
from .genui_prompt import system_prompt,expand_template,encode_authored_ui
from .genui import parse_message,CATALOG
from .models import Strict
from .genui_state import context_text
from .visual_evidence import IMAGE_POLICY


class IndexedClaim(GroundingClaim):
    evidence_refs: list[str] = Field(default_factory=list,max_length=24)


class IndexedAnswer(ChatAnswer):
    # Whitespace is meaningful in a streamed Markdown answer and must reconcile exactly.
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=False)
    answer: str = Field(min_length=1, max_length=80000)
    citation_refs: list[str] = Field(default_factory=list,max_length=MAX_CITATIONS)
    # A redundant empty position field carries no attribution. Accept only the
    # empty legacy value; real claim indices are always resolved per claim.
    citation_indices: list[int] = Field(default_factory=list,max_length=0,exclude=True)
    claims: list[IndexedClaim] = Field(default_factory=list,max_length=60)


class AuthoredNode(Strict):
    id: str = Field(min_length=1,max_length=64,pattern=r'^[A-Za-z][A-Za-z0-9_-]*$')
    type: str = Field(json_schema_extra={'enum':list(CATALOG['components'])})
    props: dict = Field(default_factory=dict)
    children: list['AuthoredNode | str'] = Field(default_factory=list,max_length=LIMITS['nodes'])
    on: dict = Field(default_factory=dict,json_schema_extra={'properties':{event:{'oneOf':list(CATALOG['actions'].values())} for event in ('click','change','submit')},'additionalProperties':False})


class AuthoredUI(Strict):
    state: dict = Field(default_factory=dict,max_length=LIMITS['stateKeys'])
    nodes: list[AuthoredNode] = Field(min_length=1,max_length=LIMITS['nodes'])


class UIAnswer(IndexedAnswer):
    answer: str = Field(min_length=0,max_length=80000)
    ui: AuthoredUI | None = None


class TemplateAnswer(IndexedAnswer):
    ui_template: dict | None = None


def capabilities(settings):
    return {'json': settings.ai_supports_json, 'tools': settings.ai_supports_tools, 'context_tokens': settings.ai_context_tokens}


def choose_tier(settings):
    caps = capabilities(settings)
    available = 3 if not caps['json'] or caps['context_tokens'] < 4096 else 2 if caps['context_tokens'] < 16000 else 1
    requested = int(settings.genui_tier) if settings.genui_tier != 'auto' else available
    return max(requested, available)


def presentation_tier(tier,choice='auto',*,no_ui=False):
    """The planner can simplify a view, never exceed deployment capabilities."""
    if no_ui or choice=='text':return 3
    return max(tier,2) if choice=='compact' else tier


def composition_thinking(profile,tier):
    context=profile.get('_grounding_context')
    return not bool(context) or context.get('route')=='focused_text' and tier==3


class AnswerDecoder:
    """Incrementally decode only the top-level answer JSON string, including escapes."""
    def __init__(self):
        self.raw = ''
        self.index = 0
        self.depth = 0
        self.in_string = False
        self.string_start = 0
        self.escape = False
        self.answer_start = None
        self.output = ''
        self.done = False

    def push(self, text):
        self.raw += text
        before = len(self.output)
        while self.index < len(self.raw):
            char = self.raw[self.index]
            if self.answer_start is not None and not self.done:
                if char == '"':
                    self.done = True
                    self.index += 1
                    continue
                if char == '\\':
                    if self.index + 1 >= len(self.raw):
                        break
                    end = self.index + (6 if self.raw[self.index + 1] == 'u' else 2)
                    if end > len(self.raw):
                        break
                    encoded = self.raw[self.index:end]
                    value = json.loads('"' + encoded + '"')
                    if len(value) == 1 and 0xD800 <= ord(value) <= 0xDBFF:
                        if end + 6 > len(self.raw):
                            break
                        pair = self.raw[end:end + 6]
                        if not pair.startswith('\\u'):
                            raise ValueError('invalid_surrogate')
                        value = json.loads('"' + encoded + pair + '"')
                        end += 6
                    if any(0xD800 <= ord(c) <= 0xDFFF for c in value):
                        raise ValueError('invalid_surrogate')
                    self.output += value
                    self.index = end
                    continue
                if ord(char) < 32:
                    raise ValueError('unescaped_control')
                self.output += char
                self.index += 1
                continue
            if self.done:
                self.index = len(self.raw)
                break
            if self.in_string:
                if self.escape:
                    self.escape = False
                elif char == '\\':
                    self.escape = True
                elif char == '"':
                    self.in_string = False
                    if self.depth == 1 and json.loads(self.raw[self.string_start:self.index + 1]) == 'answer':
                        end = self.index + 1
                        while end < len(self.raw) and self.raw[end].isspace():
                            end += 1
                        if end == len(self.raw):
                            self.in_string = True
                            break
                        if self.raw[end] == ':':
                            end += 1
                            while end < len(self.raw) and self.raw[end].isspace():
                                end += 1
                            if end == len(self.raw):
                                self.in_string = True
                                break
                            if self.raw[end] != '"':
                                raise ValueError('answer_not_string')
                            self.answer_start = end + 1
                            self.index = end + 1
                            continue
            elif char == '"':
                self.in_string = True
                self.string_start = self.index
            elif char in '{[':
                self.depth += 1
            elif char in '}]':
                self.depth -= 1
            self.index += 1
        return self.output[before:]


def evidence_index(sources):
    """Bounded, relevance-ranked and source-balanced references to exact spans.

    A real institutional page had 479 short navigation paragraphs before its
    policy body. Taking the first 120 silently excluded every relevant rule and
    the next document. Rank original spans, deduplicate web navigation, and
    reserve a share for each source before applying the cap. No quote is rewritten.
    """
    groups=[]
    for source in sources:
        spans=[];seen=set()
        for section_index, section in enumerate(source.get('sections',[])):
            text=section.get('text','')
            web=source.get('evidence_kind') in ('web_page','web_summary')
            if web and text in seen:continue
            seen.add(text)
            for offset in range(0,len(text),1400):
                quote=text[offset:offset+1400]
                if not quote.strip():continue
                score=float(section.get('_retrieval_score') or 0)
                if web:
                    substantial=len(quote)>=40 or bool(re.search(r'\d|[。；：:]',quote))
                    score+=4 if substantial else -8
                spans.append((score,section_index,offset,{'source_id':source['id'],'locator':section['locator'],'quote':quote}))
        spans.sort(key=lambda item:(-item[0],item[1],item[2]))
        if spans:groups.append([item[3] for item in spans])
    entries=[];position=0
    while len(entries)<MAX_CITATIONS:
        advanced=False
        for spans in groups:
            if position<len(spans):
                entries.append({'ref':'E'+str(len(entries)+1),**spans[position]});advanced=True
                if len(entries)>=MAX_CITATIONS:break
        if not advanced:break
        position+=1
    return entries


def resolve_citations(result, entries):
    refs=result.pop('citation_refs',[])
    index={item['ref']:item for item in entries}
    marker=re.compile(r'\[(E[1-9][0-9]*)\]')
    def selected(value):
        if isinstance(value,str):return marker.findall(value)
        if isinstance(value,dict):return [ref for item in value.values() for ref in selected(item)]
        if isinstance(value,list):return [ref for item in value for ref in selected(item)]
        return []
    claim_refs=[claim.pop('evidence_refs',[]) for claim in result.get('claims',[])]
    marked=selected(result.get('answer',''))+selected(result.get('ui'))
    marked += [ref for claim in result.get('claims',[]) for ref in selected(claim.get('text',''))]
    stable=bool(marked or any(claim_refs))
    if stable:
        # Model-authored text and claims use stable original-span IDs. Numbering
        # is a presentation detail; a revision must not change their attribution.
        if refs or any(claim.get('citation_indices') for claim in result.get('claims',[])):
            raise ValueError('mixed_citation_protocols')
        from .response_contract import prose_without_code
        manual = re.findall(r'(?<!\\)\[([0-9]+)\](?!\()', prose_without_code(result.get('answer','')))
        if manual:
            raise ValueError('mixed_citation_markers:'+','.join(manual[:8]))
        refs=list(dict.fromkeys(marked+[ref for group in claim_refs for ref in group]+refs))
        if len(refs)>MAX_CITATIONS:raise ValueError('citation_ref_limit')
    if not refs:return result
    missing=[str(ref)[:24] for ref in refs if ref not in index]
    if missing:
        raise ValueError('invalid_citation_refs:'+','.join(missing[:8]))
    resolved=[{key:index[ref][key] for key in ('source_id','locator','quote')} for ref in refs]
    # Reusing an existing valid span preserves every numbered citation position.
    # It is redundant, but does not justify discarding an otherwise correct UI.
    # Redundant manual citations are accepted only when they agree exactly.
    if result.get('citations') and result['citations']!=resolved:
        raise ValueError('conflicting_citation_sets')
    result['citations']=resolved
    if stable:
        numbers={ref:i+1 for i,ref in enumerate(refs)}
        def numbered(value):
            if isinstance(value,str):return marker.sub(lambda m:'['+str(numbers[m[1]])+']',value)
            if isinstance(value,dict):return {key:numbered(item) for key,item in value.items()}
            if isinstance(value,list):return [numbered(item) for item in value]
            return value
        result['answer']=numbered(result['answer'])
        if result.get('ui') is not None:result['ui']=numbered(result['ui'])
        for claim,group in zip(result.get('claims',[]),claim_refs):
            claim['text']=numbered(claim['text'])
            claim['citation_indices']=[numbers[ref] for ref in dict.fromkeys(group)]
    return result


def validation_failure(reason,raw):
    # Only the provider's answer-channel JSON, never reasoning_content. The draft
    # stays in the current authorized repair request, not the UI/error message.
    draft=raw if raw and len(raw.encode('utf-8'))<=131072 else None
    return ReplyValidationError(reason,draft=draft)


def payload(settings, sources, messages, profile, tier):
    from .chat_media import resource_index
    if not profile.get('_grounding_context'):
        from .context_engine import pack_history
        messages,_,_=pack_history(messages)
    context = {'personal_conditions': {k: v for k, v in profile.items() if k in PERSONAL_KEYS},
               'memory_control':profile.get('_memory_control',{}),'working_memory':profile.get('_working_memory',''),
               'session_memory':profile.get('_session_memory',{}),
               'memory_registry':[{k:item[k] for k in ('id','version','kind','locked','scope') if k in item} for item in profile.get('_memory_entries',[])],
               'materials': [{k:v for k,v in s.items() if k not in ('content','sha256')} for s in sources], 'resources':resource_index(sources)}
    if not profile.get('_grounding_context'):
        context['memories']=profile.get('_memory_entries',[])
    if profile.get('_grounding_context'):
        context['grounding_context']=profile['_grounding_context']
        context['evidence_index']=evidence_index(sources)
        context['evidence_index_scope']={'selected_spans':len(context['evidence_index']),'maximum_spans':MAX_CITATIONS,
            'method':'相关性排序、去除网页重复段落、按来源轮流保留；有上限，未登记片段不能据此引用。'}
        # The index holds the exact evidence text; do not duplicate paragraphs in the prompt.
        for source in context['materials']:source.pop('sections',None)
    materials = [{'type': 'text', 'text': json.dumps(context, ensure_ascii=False)}]
    for source in sources:
        if source['kind'] in IMAGE_MIME and source['content'] and source['status'] != 'failed':
            materials += [{'type':'text','text':'以下图片 source_id='+source['id']+'，名称='+source['name']},
                          {'type':'image_url','image_url':{'url':'data:'+IMAGE_MIME[source['kind']]+';base64,'+base64.b64encode(source['content']).decode()}}]
    response_model=UIAnswer if tier==1 else TemplateAnswer if tier==2 else IndexedAnswer
    output_schema=response_model.model_json_schema()
    if context.get('evidence_index'):
        output_schema['properties']['citation_refs']['items']['enum']=[item['ref'] for item in context['evidence_index']]
        output_schema['$defs']['IndexedClaim']['properties']['evidence_refs']['items']['enum']=[item['ref'] for item in context['evidence_index']]
    prompt = system_prompt(tier,output_schema,settings.ai_supports_json,indexed_evidence=bool(profile.get('_grounding_context')))+presentation_prompt(profile)
    from .memory_learning import AGENT_POLICY
    prompt+='\n'+AGENT_POLICY
    if profile.get('_grounding_context'):
        from .grounding import POLICY
        prompt+='\n'+POLICY
        prompt+='\n'+IMAGE_POLICY
        prompt+='\n引用协议：evidence_index 是服务器登记的原文片段。正文和 ui 文本就近使用稳定标记 [E3]、[E8]（必须是本轮存在的 ref），不要手写 [1] 等显示序号。claims.evidence_refs 选择支撑该结论的 ref；不要输出 citations、citation_refs 或 citation_indices 字段，这些由服务器统一生成。服务器恢复准确来源、位置与逐字原句；同一 ref 反复使用仍指向同一原文，改稿不得靠猜测换 ref。只选真正支持结论的片段。引用可打开原文面板，正文无需重复罗列网址；若另列 Markdown 链接，须在同段引用该网页自身的 ref，用户提供链接的提问不能代替网页证据。'
    # Prepared evidence already has a retrieval plan and coverage audit. Keep
    # formatting quick; the independent factual/UI review still gates publication.
    model=settings.ai_composition_model if profile.get('_grounding_context') and tier==1 else settings.ai_model
    composition_only=bool(profile.get('_grounding_context'))
    focused=profile.get('_grounding_context',{}).get('route')=='focused_text'
    if composition_only:
        request_role='\n本调用是展示编排阶段。依据 Pro 提供的 coverage_check、evidence_index 与原文组织正文和控件，不重新检索或补造事实。直接输出有效 JSON；事实、未知和建议仍须清楚区分。稿件随后由 Pro 独立核验，未通过不会发布。'
        prompt+=('\n本轮把证据覆盖检查与文字组织合并：逐项识别当前问题、所给证据、个人条件、冲突和缺项，依据完整原文组织回答；不得补造未知。只完成当前用户要求，保持必要条件与准确引用。仍会由另一独立调用核验全部回答后发布。' if focused else request_role)
    thinking = composition_thinking(profile,tier)
    request = {'model':model,'messages':[{'role':'system','content':prompt},{'role':'user','content':materials}]+[{'role':m['role'],'content':context_text(m)} for m in messages],
               'stream':True,'stream_options':{'include_usage':True},'thinking':{'type':'enabled' if thinking else 'disabled'},'max_completion_tokens':settings.ai_output_tokens}
    if not thinking:request['temperature']=0.2
    if settings.ai_supports_json:
        request['response_format'] = {'type':'json_object'}
    return request


async def stream_reply(settings, sources, messages, profile, tier):
    from .harness import start_call,finish_call
    call=start_call({'model':settings.ai_composition_model if profile.get('_grounding_context') and tier==1 else settings.ai_model,
        'thinking':{'type':'enabled' if composition_thinking(profile,tier) else 'disabled'},'max_completion_tokens':settings.ai_output_tokens})
    usage={}
    try:
        async for event in _stream_reply(settings,sources,messages,profile,tier):
            if event['type']=='complete':usage=event.get('provider_usage',event.get('usage',{}))
            yield event
    except BaseException as exc:
        finish_call(call,usage,exc)
        raise
    else:finish_call(call,usage)


async def _stream_reply(settings, sources, messages, profile, tier):
    if not settings.ai_api_key:
        raise AIError('问题和材料已保存。AI 尚未配置，填写 API 后可点击重试。')
    request = payload(settings, sources, messages, profile, tier)
    buffered_answer=bool(profile.get('_grounding_context'))
    appended_flags={}
    answer = AnswerDecoder()
    raw, buffer, size, finish, usage = '', '', 0, None, {}
    raw_bytes=0
    decoder = codecs.getincrementaldecoder('utf-8')()
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(settings.ai_timeout,connect=10), follow_redirects=False, trust_env=False) as client:
            async with client.stream('POST',settings.ai_base_url+'/chat/completions',headers={'Authorization':'Bearer '+settings.ai_api_key},json=request) as response:
                if response.status_code != 200:
                    errors={401:'模型凭证无效或地域不匹配',403:'模型没有访问权限',404:'模型或接口不存在',429:'模型额度不足或调用受限'}
                    raise AIError(errors.get(response.status_code,'模型服务暂时不可用')+'；原消息已保留，可稍后重试。')
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    # SSE framing and reasoning tokens are not the answer body.
                    if size > 16 * LIMITS['messageBytes']:
                        raise AIError('回复超过大小限制，已保留接收到的内容。')
                    buffer += decoder.decode(chunk)
                    if len(buffer) > 262144:
                        raise AIError('流式数据行过长，已停止读取。')
                    while '\n' in buffer:
                        line, buffer = buffer.split('\n',1)
                        if not line.startswith('data:'):
                            continue
                        content=line[5:].strip()
                        if content=='[DONE]':
                            continue
                        packet=json.loads(content)
                        if packet.get('usage'):
                            usage=packet['usage']
                        choices=packet.get('choices',[])
                        if not choices:
                            continue
                        choice=choices[0]
                        if choice.get('finish_reason'):
                            finish=choice['finish_reason']
                        delta=choice.get('delta',{}).get('content') or ''
                        if not isinstance(delta,str):
                            raise ValueError('invalid_delta')
                        raw += delta
                        raw_bytes+=len(delta.encode('utf-8'))
                        if raw_bytes > settings.genui_limits.get('messageBytes',LIMITS['messageBytes']):
                            raise AIError('回复过长，已停止读取；请缩小问题后重试。')
                        text=answer.push(delta) if settings.ai_supports_json else delta
                        if text:
                            # The actual provider stream is visible immediately. A preview
                            # cannot mount controls or acquire validated citation status.
                            yield {'type':'preview' if buffered_answer else 'delta','text':text}
        if buffer.strip() or decoder.decode(b'',final=True):
            raise AIError('模型数据流未完整结束，已保留收到的内容。')
        if finish!='stop':
            if finish in ('length','repetition_truncation'):
                raise validation_failure('模型输出达到长度上限' if finish=='length' else '模型输出出现重复',raw)
            raise AIError('模型回复未完整结束，未采纳本次草稿；请重试或缩小问题。')
        if settings.ai_supports_json:
            result=(UIAnswer if tier==1 else TemplateAnswer if tier==2 else IndexedAnswer).model_validate_json(raw)
            available={s['id'] for s in sources if s['kind'] in IMAGE_MIME and s['status']!='failed'}
            if any(sid not in available for sid in result.image_sources) or result.answer!=answer.output or not result.answer.strip() and not getattr(result,'ui',None):
                raise ValueError('invalid_evidence_or_stream')
            result=resolve_citations(result.model_dump(),evidence_index(sources) if profile.get('_grounding_context') else [])
            check_evidence(result['citations'],sources)
            if tier==1:
                authored=result.pop('ui',None)
                if authored:
                    if any(p['kind']=='ui' for p in parse_message(result['answer'])):raise ValueError('authored_ui_duplicate_channels')
                    appended=encode_authored_ui(authored)
                    if len(result['answer']+appended)>80000:raise ValueError('authored_ui_answer_limit')
                    result['answer']+=appended
                    appended_flags['authored_ui']=True
                    if not buffered_answer:yield {'type':'delta','text':appended,'authored_ui':True}
            if tier==2:
                if any(p['kind']=='ui' for p in parse_message(result['answer'])):
                    raise ValueError('template_mode_raw_ui')
                appended=expand_template(result.pop('ui_template',None))
                if appended:
                    result['answer']+=appended
                    appended_flags['expanded_template']=True
                    if not buffered_answer:yield {'type':'delta','text':appended,'expanded_template':True}
        else:
            result={'answer':raw,'citations':[],'image_sources':[]}
        if buffered_answer:yield {'type':'delta','text':result['answer'],**appended_flags}
        # A correction must see the original authoring shape (ui + citation_refs),
        # not the compiled JSONL string produced for the renderer. It is private
        # to this in-memory repair loop and never returned by the chat endpoint.
        repair_draft=raw if settings.ai_supports_json and len(raw.encode('utf-8'))<=131072 else None
        yield {'type':'complete','result':result,'repair_draft':repair_draft,'provider_usage':usage,'usage':{'input_tokens':usage.get('prompt_tokens'),'output_tokens':usage.get('completion_tokens')}}
    except (httpx.TimeoutException,httpx.NetworkError):
        raise AIError('连接模型超时或中断。已保留收到的内容，本次可能已计费；请自行选择重试。') from None
    except ValidationError as exc:
        # Send bounded field names/types to the correction pass, never raw input or secrets.
        fields=['.'.join(str(v) for v in error['loc'])+':'+error['type']+(('；允许值='+str(error['ctx']['expected'])) if error.get('ctx',{}).get('expected') else '') for error in exc.errors(include_input=False)[:8]]
        raise validation_failure('回复字段未通过格式检查：'+'；'.join(fields)+'。请严格按 JSON Schema 修正这些字段。',raw) from None
    except (ValueError,KeyError,IndexError,TypeError,UnicodeError) as exc:
        indexed=bool(profile.get('_grounding_context'))
        detail=str(exc)
        reason=(detail if detail.startswith('authored_ui_') else '引用包含未登记的 ref：'+detail.partition(':')[2] if detail.startswith('invalid_citation_refs:') else
                '稳定引用标记与手填编号混用；正文和UI使用 [E编号]，claims 仅填写 evidence_refs，citation_indices 留空' if detail=='mixed_citation_protocols' else
                '正文混入手写引用序号 ['+detail.partition(':')[2]+']；本轮只用 evidence_index 中的 [E编号] 标记，不能沿用审查意见或旧回复的显示序号' if detail.startswith('mixed_citation_markers:') else
                f'引用片段超过{MAX_CITATIONS}项服务器证据上限，请复用支持同一规则的原文，不删除用户要求' if detail=='citation_ref_limit' else
                'citations 与 citation_refs 指向的片段冲突' if detail=='conflicting_citation_sets' else
                '引用位置或原句不匹配' if '原文依据校验失败' in detail else
                '流式正文与完整 JSON 不一致' if detail=='invalid_evidence_or_stream' else 'JSON 结构或转义格式不正确')
        protocol='正文/UI 使用当前 evidence_index 的 [E编号] 标记；claims.evidence_refs 选择对应 ref；不要输出 citations、citation_refs 或 citation_indices，服务器统一生成这些字段。' if indexed else '请逐字使用当前证据中的 source_id、locator、quote。'
        raise validation_failure(reason+'。'+protocol+'严格遵守输出 Schema。',raw) from None
    except httpx.HTTPError:
        raise AIError('模型传输未完整结束，请重试。') from None
