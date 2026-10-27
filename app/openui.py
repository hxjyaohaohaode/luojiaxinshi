"""OpenIntelligentUI-style authored documents, kept outside the host DOM.

The server validates the envelope and retains a readable, inspectable artifact.
Only the browser's opaque-origin sandbox ever executes authored JavaScript.
"""
from copy import deepcopy
from html.parser import HTMLParser
import json
import math
from typing import Literal

from pydantic import ConfigDict, Field
from .models import Strict


class SandboxUI(Strict):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=False)
    renderer: Literal['open_generative_ui']
    title: str = Field(min_length=1, max_length=100)
    initialHeight: int = Field(default=240, ge=80, le=1600)
    placeholderMessages: list[str] = Field(default_factory=list, max_length=4)
    css: str = Field(default='', max_length=24000)
    html: list[str] = Field(min_length=1, max_length=100)
    jsFunctions: str = Field(default='', max_length=32000)
    jsExpressions: list[str] = Field(default_factory=list, max_length=40)


class Document(HTMLParser):
    """Extract accessible text and native control contracts, never execute HTML."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.text, self.controls, self.links, self.ids = [], {}, [], set()
        self.hidden = 0
        self.current = None
        self.option = None
        self.labels = {}
        self.label = None

    def handle_starttag(self, tag, attrs):
        p = dict(attrs)
        if tag in ('script','style','iframe','frame','object','embed','base','link','meta','foreignobject') or any(k.lower().startswith('on') for k in p):raise ValueError('openui_separate_script_channel')
        if tag=='input' and p.get('type','').lower() in ('file','password'):raise ValueError('openui_unsupported_control')
        if tag in ('script', 'style'):self.hidden += 1
        if p.get('id'):
            if p['id'] in self.ids:raise ValueError('openui_duplicate_id')
            self.ids.add(p['id'])
        if tag == 'a' and p.get('href'):self.links.append(p['href'])
        if tag == 'label' and p.get('for'):self.label = p['for']
        if tag in ('input', 'select', 'textarea') and p.get('type','').lower() not in ('submit', 'button', 'reset'):
            key = p.get('id') or p.get('name')
            if not key or len(key)>100 or key in self.controls or key in ('__proto__','prototype','constructor'):raise ValueError('openui_control_id')
            kind = p.get('type', 'text').lower() if tag == 'input' else tag
            value = 'checked' in p if kind in ('checkbox', 'radio') else p.get('value', '')
            self.controls[key] = {'type':kind, 'label':p.get('aria-label') or p.get('name') or key, 'value':value, 'options':[]}
            if tag in ('select', 'textarea'):self.current = key
        if tag == 'option' and self.current:
            self.option = {'value':p.get('value'), 'text':'', 'selected':'selected' in p}

    def handle_data(self, value):
        if self.hidden:return
        if value.strip():self.text.append(value.strip())
        if self.label:self.labels[self.label] = self.labels.get(self.label, '') + value
        if self.current and self.controls[self.current]['type'] == 'textarea':self.controls[self.current]['value'] += value
        if self.option is not None:self.option['text'] += value

    def handle_endtag(self, tag):
        if tag in ('script', 'style'):self.hidden = max(0, self.hidden-1)
        if tag == 'label':self.label = None
        if tag == 'option' and self.current and self.option is not None:
            item = self.controls[self.current]
            value = self.option['value'] if self.option['value'] is not None else self.option['text']
            item['options'].append(value)
            if self.option['selected'] or len(item['options']) == 1:item['value'] = value
            self.option = None
        if tag in ('select', 'textarea'):self.current = None


def inspect_document(value):
    doc = Document()
    doc.feed(''.join(value['html']))
    doc.close()
    for key, item in doc.controls.items():item['label'] = doc.labels.get(key, item['label']).strip()[:160]
    if len(doc.controls)>40:raise ValueError('openui_control_limit')
    return doc


def validate_ui(value):
    ui = SandboxUI.model_validate(value).model_dump()
    if len(json.dumps(ui, ensure_ascii=False).encode())>131072:raise ValueError('openui_size_limit')
    if not ''.join(ui['html']).strip():raise ValueError('openui_empty_html')
    if any(len(s)>160 for s in ui['placeholderMessages']):raise ValueError('openui_placeholder_limit')
    if any(len(s)>16000 for s in ui['jsExpressions']):raise ValueError('openui_expression_limit')
    doc = inspect_document(ui)
    return ui, doc


def encode_ui(value):
    ui, _ = validate_ui(value)
    # A single JSON line safely contains Markdown fences inside generated code.
    return '\n```openui\n'+json.dumps(ui, ensure_ascii=False, separators=(',', ':'))+'\n```'


class OpenUIBlock:
    def __init__(self, limits=None, data=None):
        self.lines, self.errors, self.closed, self.ended = [], [], False, True
        self.size = 0

    def error(self, code, *_):
        if not any(e['code'] == code for e in self.errors):self.errors.append({'code':code})

    def line(self, line):
        self.size += len(line.encode('utf-8'))
        if self.size>131072:self.error('openui_size_limit')
        else:self.lines.append(line)

    def spec(self):
        errors = self.errors[:]
        ui, controls, text = None, {}, ''
        try:
            ui, doc = validate_ui(json.loads('\n'.join(self.lines)))
            controls, text = doc.controls, '\n'.join(doc.text)
        except (ValueError, TypeError, KeyError, RecursionError):
            if self.closed:errors.append({'code':'openui_invalid_document'})
        return {'v':1, 'roots':[], 'nodes':{}, 'state':{'controls':{key:item['value'] for key,item in controls.items()}},
                'data':{}, 'complete':self.closed and ui is not None and not errors, 'errors':errors,
                'sandbox':ui, 'controls':controls, 'text':text}


def validate_controls(spec, state):
    if not isinstance(state, dict) or set(state)!={'controls'} or not isinstance(state['controls'], dict):raise ValueError('openui_state')
    if set(state['controls'])-set(spec['controls']):raise ValueError('openui_unknown_control')
    for key, value in state['controls'].items():
        control = spec['controls'][key]
        if control['type'] in ('checkbox', 'radio'):
            if not isinstance(value, bool):raise ValueError('openui_control_type')
        elif not isinstance(value, str) or len(value)>4000:raise ValueError('openui_control_type')
        elif control['type']=='select' and value not in control['options']:raise ValueError('openui_control_option')
    if len(json.dumps(state, ensure_ascii=False).encode())>16000:raise ValueError('openui_state_limit')
    return deepcopy(state)


class UIStreamDecoder:
    """Linear incremental JSON lexer: expose CSS/HTML strings before JSON closes.

    Paths, escapes and array boundaries are tracked, so quoted fake field names,
    incomplete unicode and nested objects cannot escape into another channel.
    Preview contents are always inert. Full model validation is still mandatory.
    """
    def __init__(self, prefix=('ui',)):
        self.prefix = prefix
        self.stack, self.token, self.string, self.escape = [], '', False, ''
        self.is_key, self.path, self.literal = False, (), ''
        self.high_surrogate = None
        self.content = {'renderer':'', 'css':'', 'html':[], 'jsFunctions':'', 'jsExpressions':[], 'generating':True, 'cssComplete':False, 'htmlComplete':False}
        self.changed = False
        self.emitted = None
        self.completed_expressions=0
        self.published_expressions=0
        self.published_functions=False

    def packet(self, delta):
        current=self.push(delta)
        if not current or not current.get('css') and not current.get('html'):return None
        previous=self.emitted or {'css':'','html':[]}
        patch={'reset':self.emitted is None,'css':current['css'][len(previous['css']):],
               'html':[{'index':i,'text':text[len(previous['html'][i]) if i<len(previous['html']) else 0:]}
                       for i,text in enumerate(current['html']) if i>=len(previous['html']) or text!=previous['html'][i]]}
        if current.get('jsFunctionsComplete') and not self.published_functions:
            patch['jsFunctions']=current['jsFunctions'];self.published_functions=True
        if self.completed_expressions>self.published_expressions:
            patch['jsExpressions']=[{'index':i,'text':current['jsExpressions'][i]} for i in range(self.published_expressions,self.completed_expressions)]
            self.published_expressions=self.completed_expressions
        for key in ('title','initialHeight','cssComplete','htmlComplete','jsFunctionsComplete','jsExpressionsComplete','localReady'):
            if key in current and current[key]!=previous.get(key):patch[key]=current[key]
        self.emitted=deepcopy(current)
        return patch

    def value_path(self):
        if not self.stack:return ()
        frame = self.stack[-1]
        return frame['path'] + ((frame['key'],) if frame['kind']=='{' else (frame['index'],))

    def consumed(self):
        if self.stack:
            frame = self.stack[-1]
            frame['expect'] = 'comma'
            if frame['kind']=='[':frame['index'] += 1

    def append(self, value):
        relative = self.path[len(self.prefix):] if self.path[:len(self.prefix)] == self.prefix else ()
        if relative in (('css',), ('title',), ('renderer',), ('jsFunctions',)):
            key = relative[0]
            self.content[key] = self.content.get(key, '') + value
            if relative[0] in ('css','title'):self.changed = True
        elif len(relative)==2 and relative[0] in ('html','jsExpressions') and isinstance(relative[1], int) and relative[1]<100:
            key=relative[0]
            while len(self.content[key])<=relative[1]:self.content[key].append('')
            self.content[key][relative[1]] += value
            if key=='html':self.changed = True

    def push(self, delta):
        self.changed = False
        for char in delta:
            if self.string:
                if self.escape:
                    self.escape += char
                    if self.escape.startswith('\\u'):
                        if len(self.escape)<6:continue
                    elif len(self.escape)<2:continue
                    value = json.loads('"'+self.escape+'"')
                    # A literal backslash-u in CSS is not a JSON surrogate.
                    # Track actual decoded code units separately from text.
                    if self.high_surrogate is not None:
                        if len(value)!=1 or not 0xDC00<=ord(value)<=0xDFFF:raise ValueError('invalid_surrogate')
                        value=chr(0x10000+((self.high_surrogate-0xD800)<<10)+(ord(value)-0xDC00))
                        self.high_surrogate=None
                    elif len(value)==1 and 0xD800<=ord(value)<=0xDBFF:
                        self.high_surrogate=ord(value);self.escape='';continue
                    elif any(0xD800<=ord(c)<=0xDFFF for c in value):raise ValueError('invalid_surrogate')
                    self.token += value
                    if not self.is_key:self.append(value)
                    self.escape = ''
                elif char=='\\':self.escape = '\\'
                elif char=='"':
                    if self.high_surrogate is not None:raise ValueError('invalid_surrogate')
                    self.string=False
                    if self.is_key:self.stack[-1]['key']=self.token;self.stack[-1]['expect']='colon'
                    else:
                        if self.path==self.prefix+('css',):self.content['cssComplete']=True;self.changed=True
                        if self.path==self.prefix+('jsFunctions',):self.content['jsFunctionsComplete']=True;self.changed=True
                        if self.path[:len(self.prefix)+1]==self.prefix+('jsExpressions',):self.completed_expressions=self.path[-1]+1;self.changed=True
                        self.consumed()
                else:
                    if self.high_surrogate is not None:raise ValueError('invalid_surrogate')
                    self.token += char
                    if not self.is_key:self.append(char)
                continue
            if char.isspace():continue
            if self.literal and char not in ',]}':self.literal+=char;continue
            if self.literal:
                if self.path==self.prefix+('initialHeight',):
                    try:
                        height=json.loads(self.literal)
                        if isinstance(height,(int,float)) and math.isfinite(height):self.content['initialHeight']=max(80,min(1600,int(height)));self.changed=True
                    except ValueError:pass
                self.literal='';self.consumed()
            if char=='"':
                self.string=True;self.token='';self.is_key=bool(self.stack and self.stack[-1]['kind']=='{' and self.stack[-1]['expect']=='key');self.path=self.value_path()
            elif char in '{[':
                path=self.value_path();self.stack.append({'kind':char,'path':path,'key':None,'index':0,'expect':'key' if char=='{' else 'value'})
            elif char in '}]':
                if self.stack:
                    frame=self.stack.pop()
                    if frame['path']==self.prefix+('html',):self.content['htmlComplete']=True;self.changed=True
                    if frame['path']==self.prefix+('jsExpressions',):self.content['jsExpressionsComplete']=True;self.changed=True
                    if frame['kind']=='{' and frame['path']==self.prefix and self.content.get('htmlComplete'):
                        try:
                            validate_ui({key:self.content[key] for key in SandboxUI.model_fields if key in self.content})
                            self.content['localReady']=True;self.changed=True
                        except (ValueError,TypeError):pass
                self.consumed()
            elif char==':':
                if self.stack:self.stack[-1]['expect']='value'
            elif char==',':
                if self.stack:self.stack[-1]['expect']='key' if self.stack[-1]['kind']=='{' else 'value'
            else:self.path=self.value_path();self.literal=char
        return deepcopy(self.content) if self.changed else None
