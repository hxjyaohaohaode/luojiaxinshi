"""Deterministic presentation adapters; no fact repair or tool execution.

Models can answer in Markdown despite a typed tool request. Preserve that
answer and its explicit evidence IDs instead of buying another generation to
change its envelope. Every candidate still enters the original compiler and
independent reviewer. Ambiguous/broken structured output stays an error.
"""
import json
import math
import re

from .db import dumps


def _json(text):
    def unique(pairs):
        value={}
        for key,item in pairs:
            if key in value:raise ValueError('重复字段')
            value[key]=item
        return value
    def finite(raw):
        value=float(raw)
        if not math.isfinite(value):raise ValueError('非有限数值')
        return value
    def constant(_):raise ValueError('非标准JSON常量')
    return json.loads(text,object_pairs_hook=unique,parse_float=finite,parse_constant=constant)


def answer_content(raw, sources, entries):
    if not isinstance(raw, str) or not raw.strip('\ufeff \t\r\n'):
        raise ValueError('模型未返回可用正文或最终答复工具')
    if len(raw) > 262144:
        raise ValueError('答复封装超过长度上限')
    text = raw.strip('\ufeff \t\r\n')
    format_name = None
    # A complete, solitary JSON fence is an envelope, never an instruction to
    # execute code. Never discard prose surrounding a structured document.
    fence = re.fullmatch(r'```(?:json)?[ \t]*\r?\n([\s\S]*?)\r?\n```[ \t]*', text, re.I)
    if fence and fence[1].lstrip().startswith(('{', '[', '"')):
        text, format_name = fence[1], 'json_fence'
    leading_reference = re.match(r'\[(?:E[1-9][0-9]*|[1-9][0-9]*)\]|\[[^\]\n]+\]\(', text)
    structured = text.startswith(('{', '"')) or text.startswith('[') and not leading_reference
    if structured:
        try:
            value = _json(text)
            # Bounded support for a JSON object serialized as a JSON string.
            if isinstance(value, str) and value.lstrip().startswith('{'):
                value = _json(value)
                format_name = 'serialized_json'
        except (ValueError, TypeError, RecursionError):
            raise ValueError('答复结构不完整：请将已有正文完整提交到 submit_answer.answer，不重做分析或操作') from None
        if not isinstance(value, dict):
            raise ValueError('答复结构须为对象，不能是数组、字符串或其他 JSON 值')
        return dumps(value), format_name
    if text in ('true', 'false', 'null') or re.fullmatch(r'-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?', text):
        raise ValueError('模型只返回了一个 JSON 值，没有可核对的答复正文')
    if re.search(r'^```json\b', text, re.I | re.M) or re.match(r'(?:answer|claims|memory_actions|ui)\s*[:=]', text):
        raise ValueError('答复结构混杂或不完整：请只提交一个完整的最终答复对象，保留全部正文')
    refs = set(re.findall(r'\[(E[1-9][0-9]*)\]', text))
    selected = [e for e in entries if e['ref'] in refs]
    index = {s['id']: s for s in sources}
    # Identity metadata follows only references the model actually wrote. Do
    # not attach every image, fabricate quotes, claims or memory operations.
    images = list(dict.fromkeys(e['source_id'] for e in selected
        if index.get(e['source_id'], {}).get('visual_evidence')))
    media = list(dict.fromkeys(e['source_id'] for e in selected
        if index.get(e['source_id'], {}).get('media_evidence')))
    return dumps({'answer': text, 'claims': [], 'image_sources': images,
                  'media_sources': media, 'memory_actions': []}), 'markdown'


class AnswerPreview:
    """Preview actual prose from JSON, JSON fences or native Markdown.

    JSON fields and private reasoning never become prose. Prefix classification
    tolerates token-sized chunks, so an opening backtick or quote cannot leak
    the next structured fields while waiting for its format to become clear.
    """
    def __init__(self):
        from .genui_ai import AnswerDecoder
        self.raw = ''
        self.mode = None
        self.decoder = AnswerDecoder(fields=('answer', 'lead'))
        self.output = ''

    def push(self, delta):
        text = self._push(delta)
        self.output += text
        return text

    def _push(self, delta):
        if self.mode == 'json':
            return self.decoder.push(delta)
        if self.mode == 'markdown':
            return delta
        if self.mode == 'blocked':
            return ''
        self.raw += delta
        text = self.raw.lstrip('\ufeff \t\r\n')
        if not text:
            return ''
        if text.startswith(('`', '~')):
            if '\n' not in text:
                return ''
            header, rest = text.split('\n', 1)
            if re.fullmatch(r'```(?:json)?[ \t\r]*', header, re.I):
                if not rest.strip():
                    return ''
                if rest.lstrip().startswith('{'):
                    self.mode = 'json'
                    return self.decoder.push(rest)
                if header.strip().lower() == '```json':
                    self.mode = 'blocked'
                    return ''
        if text.startswith('{'):
            self.mode = 'json'
            return self.decoder.push(text)
        if text.startswith('['):
            if ']' not in text and len(text)<512:
                return ''
            if not re.match(r'\[(?:E[1-9][0-9]*|[1-9][0-9]*)\]|\[[^\]\n]+\]\(', text):
                self.mode = 'blocked'
                return ''
        if text.startswith('"'):
            self.mode = 'blocked'
            return ''
        self.mode = 'markdown'
        return self.raw.lstrip('\ufeff')


class JSONEnvelopeStream:
    """Expose one JSON object incrementally, tolerating only an outer fence.

    No braces in Markdown are searched for or executed. The caller retains the
    original full response and must validate the envelope at end of stream.
    """
    def __init__(self):
        self.prefix = ''
        self.mode = None
        self.depth = 0
        self.string = False
        self.escape = False
        self.done = False

    def push(self, delta):
        if self.done or self.mode == 'other':
            return ''
        if self.mode is None:
            self.prefix += delta
            text = self.prefix.lstrip('\ufeff \t\r\n')
            if not text:
                return ''
            if text.startswith('`'):
                if '\n' not in text:
                    return ''
                header, text = text.split('\n', 1)
                if not re.fullmatch(r'```(?:json)?[ \t\r]*', header, re.I):
                    self.mode = 'other'
                    return ''
                text = text.lstrip()
                if not text:
                    return ''
            if not text.startswith('{'):
                self.mode = 'other'
                return ''
            self.mode = 'json'
            delta = text
            self.prefix = ''
        output = []
        for char in delta:
            output.append(char)
            if self.string:
                if self.escape:self.escape=False
                elif char=='\\':self.escape=True
                elif char=='"':self.string=False
            elif char=='"':self.string=True
            elif char in '{[':self.depth+=1
            elif char in '}]':
                self.depth-=1
                if self.depth==0:
                    self.done=True
                    break
        return ''.join(output)
