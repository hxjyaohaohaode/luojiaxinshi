"""Existing compatible model transport, now with bounded SSE and JSON-string streaming."""
import base64
import codecs
import json

import httpx
from pydantic import Field,ConfigDict

from .ai import AIError, check_evidence
from .chat_ai import ChatAnswer, IMAGE_MIME, PROMPT
from .genui import LIMITS


class UIAnswer(ChatAnswer):
    # Whitespace is meaningful in a streamed Markdown answer and must reconcile exactly.
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=False)
    answer: str = Field(min_length=1, max_length=80000)


def capabilities(settings):
    return {'json': settings.ai_supports_json, 'tools': settings.ai_supports_tools, 'context_tokens': settings.ai_context_tokens}


def choose_tier(settings):
    caps = capabilities(settings)
    available = 3 if not caps['json'] or caps['context_tokens'] < 4096 else 2 if caps['context_tokens'] < 16000 else 1
    requested = int(settings.genui_tier) if settings.genui_tier != 'auto' else available
    return max(requested, available)


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


def payload(settings, sources, messages, profile, tier):
    context = {'personal_conditions': {k: v for k, v in profile.items() if k in {'campus_role','school','level','grade','college','major','semester','goals'}},
               'materials': [{'id': s['id'], 'name': s['name'], 'status': s['status'], 'warning': s['warning'], 'sections': s['sections']} for s in sources]}
    materials = [{'type': 'text', 'text': json.dumps(context, ensure_ascii=False)}]
    for source in sources:
        if source['kind'] in IMAGE_MIME and source['content'] and source['status'] != 'failed':
            materials += [{'type':'text','text':'以下图片 source_id='+source['id']+'，名称='+source['name']},
                          {'type':'image_url','image_url':{'url':'data:'+IMAGE_MIME[source['kind']]+';base64,'+base64.b64encode(source['content']).decode()}}]
    # The original persona and evidence rules are preserved; Phase 5 supplies the separate UI module.
    prompt = PROMPT + json.dumps(UIAnswer.model_json_schema(), ensure_ascii=False)
    if not settings.ai_supports_json:
        prompt = PROMPT.rsplit('输出中文 JSON', 1)[0] + '输出中文 Markdown 文字，不输出 HTML 或 genui。原文引用尚未程序校验，请提醒本人核对。'
    request = {'model':settings.ai_model,'messages':[{'role':'system','content':prompt},{'role':'user','content':materials}]+[{'role':m['role'],'content':m['content']} for m in messages],
               'stream':True,'stream_options':{'include_usage':True},'enable_thinking':False,'max_tokens':6000}
    if settings.ai_supports_json:
        request['response_format'] = {'type':'json_object'}
    return request


async def stream_reply(settings, sources, messages, profile, tier):
    if not settings.ai_api_key:
        raise AIError('问题和材料已保存。AI 尚未配置，填写 API 后可点击重试。')
    request = payload(settings, sources, messages, profile, tier)
    answer = AnswerDecoder()
    raw, buffer, size, finish, usage = '', '', 0, None, {}
    decoder = codecs.getincrementaldecoder('utf-8')()
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(settings.ai_timeout,connect=10), follow_redirects=False, trust_env=False) as client:
            async with client.stream('POST',settings.ai_base_url+'/chat/completions',headers={'Authorization':'Bearer '+settings.ai_api_key},json=request) as response:
                if response.status_code != 200:
                    errors={401:'模型凭证无效或地域不匹配',403:'模型没有访问权限',404:'模型或接口不存在',429:'模型额度不足或调用受限'}
                    raise AIError(errors.get(response.status_code,'模型服务暂时不可用')+'；原消息已保留，可稍后重试。')
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > 2 * LIMITS['messageBytes']:
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
                        if len(raw.encode('utf-8')) > min(300000,settings.genui_limits.get('messageBytes',LIMITS['messageBytes'])):
                            raise AIError('回复过长，已停止读取；请缩小问题后重试。')
                        text=answer.push(delta) if settings.ai_supports_json else delta
                        if text:
                            yield {'type':'delta','text':text}
        if buffer.strip() or decoder.decode(b'',final=True):
            raise AIError('模型数据流未完整结束，已保留收到的内容。')
        if finish!='stop':
            raise AIError('模型回复未完整结束，已保留收到的内容；请重试或缩小问题。')
        if settings.ai_supports_json:
            result=UIAnswer.model_validate_json(raw)
            check_evidence(result.citations,sources)
            available={s['id'] for s in sources if s['kind'] in IMAGE_MIME and s['status']!='failed'}
            if any(sid not in available for sid in result.image_sources) or result.answer!=answer.output or not result.answer.strip():
                raise ValueError('invalid_evidence_or_stream')
            result=result.model_dump()
        else:
            result={'answer':raw,'citations':[],'image_sources':[]}
        yield {'type':'complete','result':result,'usage':{'input_tokens':usage.get('prompt_tokens'),'output_tokens':usage.get('completion_tokens')}}
    except (httpx.TimeoutException,httpx.NetworkError):
        raise AIError('连接模型超时或中断。已保留收到的内容，本次可能已计费；请自行选择重试。') from None
    except (ValueError,KeyError,IndexError,TypeError,httpx.HTTPError,UnicodeError):
        raise AIError('回复或引用未通过最终检查。已收到的内容仅供参考，请对照原文核对后重试。') from None
