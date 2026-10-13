"""Bounded declarative UI validation. No model code is ever evaluated here."""
from copy import deepcopy
import json
import math
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent.parent
CATALOG = json.loads((ROOT / 'schema/genui/catalog.json').read_text(encoding='utf-8'))
LIMITS = CATALOG['limits']
FORBIDDEN = set(CATALOG['forbiddenKeys'])


def fail(code):
    raise ValueError(code)


def safe_key(key):
    return isinstance(key, str) and bool(re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,63}', key)) and key not in FORBIDDEN


def path_parts(path):
    if not isinstance(path, str) or len(path) > 200:
        fail('invalid_path')
    parts = path.split('.')
    if len(parts) > 8 or any(p in FORBIDDEN or not re.fullmatch(r'(?:[A-Za-z][\w-]{0,63}|\d{1,4})', p, re.ASCII) for p in parts):
        fail('invalid_path')
    return parts


def safe_value(value, limits=None):
    limits = limits or LIMITS
    steps = 0

    def walk(item, depth=0):
        nonlocal steps
        steps += 1
        if steps > 20000 or depth > limits['depth']:
            fail('value_too_deep')
        if item is None or isinstance(item, bool):
            return item
        if isinstance(item, (int, float)):
            if not math.isfinite(item):
                fail('non_finite_number')
            return item
        if isinstance(item, str):
            if len(item.encode('utf-8', errors='replace')) > limits['stringBytes']:
                fail('string_limit')
            return item
        if isinstance(item, list):
            if len(item) > limits['dataItems']:
                fail('array_limit')
            return [walk(v, depth + 1) for v in item]
        if not isinstance(item, dict):
            fail('invalid_value')
        if any(not isinstance(k, str) or k in FORBIDDEN or len(k) > 100 for k in item):
            fail('forbidden_key')
        return {k: walk(v, depth + 1) for k, v in item.items()}

    return walk(value)


def matches(value, schema=None, dynamic=True):
    schema = schema or {}
    if dynamic and isinstance(value, dict) and len(value) == 1 and next(iter(value)) in {'$bind', '$expr', '$ref'}:
        key = next(iter(value))
        if not isinstance(value[key], str):
            return False
        try:
            if key == '$expr':
                if len(value[key]) > LIMITS['expressionChars']:
                    return False
            else:
                path_parts(value[key])
            return True
        except ValueError:
            return False
    kind = 'null' if value is None else 'boolean' if isinstance(value, bool) else 'number' if isinstance(value, (int, float)) else 'array' if isinstance(value, list) else 'object' if isinstance(value, dict) else 'string'
    types = schema.get('type', [])
    if isinstance(types, str):
        types = [types]
    if types and kind not in types and not ('integer' in types and kind == 'number' and math.isfinite(value) and int(value) == value):
        return False
    if 'const' in schema and (type(schema['const']) is not type(value) or value != schema['const']):
        return False
    if 'enum' in schema and value not in schema['enum']:
        return False
    if kind == 'string' and len(value) > schema.get('maxLength', LIMITS['stringBytes']):
        return False
    if kind == 'number' and (not math.isfinite(value) or value < schema.get('minimum', -math.inf) or value > schema.get('maximum', math.inf) or value <= schema.get('exclusiveMinimum', -math.inf)):
        return False
    if kind == 'array' and (len(value) > schema.get('maxItems', LIMITS['dataItems']) or ('items' in schema and not all(matches(v, schema['items'], dynamic) for v in value))):
        return False
    if kind == 'object':
        if any(k not in value for k in schema.get('required', [])):
            return False
        if 'properties' in schema:
            for key, item in value.items():
                if key not in schema['properties']:
                    if schema.get('additionalProperties') is False:
                        return False
                elif not matches(item, schema['properties'][key], dynamic):
                    return False
    return True


TOKEN = re.compile(r'''(?:(\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?|([A-Za-z_][A-Za-z0-9_.]*)|("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')|(===|!==|<=|>=|==|!=|&&|\|\||[+\-*/%<>()!?:,]))''')
PRECEDENCE = {'||': 1, '&&': 2, '==': 3, '!=': 3, '===': 3, '!==': 3, '<': 4, '<=': 4, '>': 4, '>=': 4, '+': 5, '-': 5, '*': 6, '/': 6, '%': 6}


def validate_expression(source, limits=None):
    """The same restricted grammar as the client; never Python eval or compilation."""
    limits = limits or LIMITS
    if not isinstance(source, str) or len(source) > limits['expressionChars']:
        fail('expression_limit')
    tokens, pos = [], 0
    while pos < len(source):
        if source[pos].isspace():
            pos += 1
            continue
        match = TOKEN.match(source, pos)
        if not match:
            fail('invalid_expression_token')
        pos = match.end()
        if match[1]:
            tokens.append(('literal', match[0]))
        elif match[2]:
            path_parts(match[2])
            tokens.append(('name', match[2]))
        elif match[3]:
            if match[3].startswith('"'):
                json.loads(match[3])
            tokens.append(('literal', match[3]))
        else:
            tokens.append((match[4], match[4]))
    index, steps = 0, 0

    def peek():
        return tokens[index][0] if index < len(tokens) else None

    def take(kind):
        nonlocal index
        if peek() != kind:
            fail('invalid_expression')
        index += 1

    def parse(minimum=0, depth=0):
        nonlocal index, steps
        steps += 1
        if depth > limits['expressionDepth'] or steps > limits['expressionSteps']:
            fail('expression_steps')
        if index >= len(tokens):
            fail('invalid_expression')
        kind, value = tokens[index]
        index += 1
        if kind == 'name' and peek() == '(':
            if value not in CATALOG['functions']:
                fail('forbidden_function')
            index += 1
            if peek() != ')':
                while True:
                    parse(0, depth + 1)
                    if peek() != ',':
                        break
                    index += 1
            take(')')
        elif kind in {'literal', 'name'}:
            pass
        elif kind in {'!', '+', '-'}:
            parse(7, depth + 1)
        elif kind == '(':
            parse(0, depth + 1)
            take(')')
        else:
            fail('invalid_expression')
        while peek() in PRECEDENCE and PRECEDENCE[peek()] >= minimum:
            precedence = PRECEDENCE[peek()]
            index += 1
            parse(precedence + 1, depth + 1)
        if minimum == 0 and peek() == '?':
            index += 1
            parse(0, depth + 1)
            take(':')
            parse(0, depth + 1)

    parse()
    if index != len(tokens):
        fail('invalid_expression')


def validate_action(action):
    action = safe_value(action)
    if not isinstance(action, dict) or action.get('kind') not in CATALOG['actions'] or not matches(action, CATALOG['actions'][action['kind']]):
        fail('invalid_action')
    if action['kind'] == 'state':
        path_parts(action['key'])
    if action['kind'] == 'host' and (action.get('name') not in CATALOG['hostActions'] or not matches(action.get('params', {}), CATALOG['hostActions'][action['name']])):
        fail('invalid_host_params')
    return action


def validate_node(node, limits=None):
    limits = limits or LIMITS
    node = safe_value(node, limits)
    if not isinstance(node, dict) or not safe_key(node.get('id')) or not isinstance(node.get('type'), str):
        fail('invalid_node_id')
    if set(node) - {'op', 'id', 'type', 'props', 'children', 'on'}:
        fail('invalid_node_field')
    definition = CATALOG['components'].get(node['type'])
    if not definition:
        fallback = node.get('props', {}).get('fallback') if isinstance(node.get('props'), dict) else None
        return {'id': node['id'], 'type': 'Unknown', 'props': {'text': fallback if isinstance(fallback, str) else '这部分展示方式暂不支持，请以文字说明为准。'}, 'children': [], 'error': 'unknown_component'}
    if 'props' in node and not isinstance(node['props'], dict):
        fail('invalid_props')
    props = {**deepcopy(definition['defaults']), **node.get('props', {})}
    if not matches(props, {'type': 'object', 'properties': definition['properties'], 'required': definition['required'], 'additionalProperties': False}):
        fail('invalid_props')
    if 'bind' in props:
        path_parts(props['bind'])

    def expressions(value):
        if isinstance(value, dict):
            if '$expr' in value:
                validate_expression(value['$expr'], limits)
            for item in value.values():
                expressions(item)
        elif isinstance(value, list):
            for item in value:
                expressions(item)
    expressions(props)
    children = node.get('children', [])
    if not isinstance(children, list) or len(children) > limits['nodes'] or any(not safe_key(c) for c in children) or (not definition['children'] and children):
        fail('invalid_children')
    on = node.get('on', {})
    if not isinstance(on, dict) or set(on) - {'click', 'change', 'submit'}:
        fail('invalid_event')
    for action in on.values():
        validate_action(action)
    return {'id': node['id'], 'type': node['type'], 'props': props, 'children': children[:], 'on': on}


class Block:
    def __init__(self, limits=None, data=None):
        self.limits = limits or LIMITS
        self.nodes, self.state = {}, {}
        self.data = safe_value(data or {}, self.limits)
        self.errors = []
        self.begun = self.ended = self.closed = False
        self.size = self.count = 0

    def error(self, code, node_id=None):
        item = {'code': code, **({'id': node_id} if node_id else {})}
        if len(self.errors) < 50 and item not in self.errors:
            self.errors.append(item)

    def apply(self, source, trusted=False):
        if self.ended:
            self.error('after_end')
            return
        self.count += 1
        if self.count > self.limits['operations']:
            self.error('operation_limit')
            return
        try:
            op = safe_value(source, self.limits)
            if not isinstance(op, dict):
                fail('invalid_operation')
            kind = op.get('op')
            allowed = {'begin': {'op', 'v'}, 'state': {'op', 'set'}, 'data': {'op', 'id', 'value'}, 'node': {'op', 'id', 'type', 'props', 'children', 'on'}, 'patch': {'op', 'id', 'props', 'children', 'on'}, 'end': {'op'}}.get(kind)
            if allowed is None or set(op) - allowed:
                fail('invalid_operation')
            if kind == 'begin':
                if self.begun or type(op.get('v')) is not int or op['v'] != 1:
                    fail('unsupported_version')
                self.begun = True
                return
            if not self.begun:
                fail('missing_begin')
            if kind == 'state':
                values = op.get('set')
                if not isinstance(values, dict):
                    fail('invalid_state')
                if any(not safe_key(k) for k in values):
                    fail('invalid_state_key')
                if len(set(self.state) | set(values)) > self.limits['stateKeys']:
                    fail('state_limit')
                self.state.update(values)
            elif kind == 'data':
                if not trusted:
                    fail('untrusted_data')
                if not safe_key(op.get('id')):
                    fail('invalid_data_id')
                self.data[op['id']] = op.get('value')
            elif kind in {'node', 'patch'}:
                if kind == 'patch':
                    old = self.nodes.get(op.get('id'))
                    if not old:
                        fail('patch_missing_node')
                    op = {**old, **op, 'props': {**old['props'], **op.get('props', {})}}
                    op.pop('error', None)
                if op.get('id') not in self.nodes and len(self.nodes) >= self.limits['nodes']:
                    fail('node_limit')
                node = validate_node(op, self.limits)
                self.nodes[node['id']] = node
                if node.get('error'):
                    self.error(node['error'], node['id'])
            elif kind == 'end':
                self.ended = True
        except (ValueError, TypeError, KeyError, OverflowError, RecursionError) as error:
            node_id = source.get('id') if isinstance(source, dict) and safe_key(source.get('id')) else None
            code = str(error) if isinstance(error, ValueError) else 'invalid_operation'
            self.error(code, node_id)
            if isinstance(source, dict) and source.get('op') == 'node' and node_id and (node_id in self.nodes or len(self.nodes) < self.limits['nodes']):
                self.nodes[node_id] = {'id': node_id, 'type': 'Unknown', 'props': {'text': '此部分界面未能通过校验，请以回答中的文字说明为准。'}, 'children': [], 'error': code}

    def line(self, line):
        self.size += len(line.encode('utf-8', errors='replace')) + 1
        if self.size > self.limits['blockBytes']:
            self.error('block_limit')
            return
        try:
            self.apply(json.loads(line, parse_constant=lambda _: fail('non_finite_number')))
        except (ValueError, RecursionError):
            self.error('malformed_line')

    def spec(self):
        nodes = deepcopy(self.nodes)
        referenced = {c for node in nodes.values() for c in node.get('children', [])}
        roots = [i for i in nodes if i not in referenced]
        visited, errors, edges = set(), self.errors[:], 0

        def issue(code, node_id):
            item = {'code': code, 'id': node_id}
            if len(errors) < 50 and item not in errors:
                errors.append(item)

        def walk(node_id, path=()):
            nonlocal edges
            if node_id in visited:
                return
            visited.add(node_id)
            children = []
            for child in nodes[node_id].get('children', []):
                edges += 1
                if edges > self.limits['nodes']:
                    issue('reference_limit', node_id)
                elif child in path or child == node_id:
                    issue('cycle', node_id)
                elif len(path) + 1 >= self.limits['depth']:
                    issue('depth_limit', child)
                elif child in visited:
                    issue('shared_child', child)
                else:
                    children.append(child)
                    if child in nodes:
                        walk(child, (*path, node_id))
                    elif self.ended:
                        issue('missing_child', child)
            nodes[node_id]['children'] = children

        for node_id in roots[:]:
            walk(node_id)
        for node_id in nodes:
            if node_id not in visited:
                roots.append(node_id)
                walk(node_id)
        return {'v': 1, 'roots': roots, 'nodes': nodes, 'state': deepcopy(self.state), 'data': deepcopy(self.data), 'complete': self.ended and self.closed, 'errors': errors}


def parse_message(raw, limits=None, data=None):
    limits = {**LIMITS, **(limits or {})}
    if not isinstance(raw, str):
        fail('invalid_message')
    if len(raw.encode('utf-8')) > limits['messageBytes']:
        fail('message_limit')
    parts, block, fence = [], None, None

    def text(value):
        if parts and parts[-1]['kind'] == 'text':
            parts[-1]['text'] += value
        else:
            parts.append({'kind': 'text', 'text': value})
    lines = raw.split('\n')
    for index, physical_line in enumerate(lines):
        newline = index < len(lines) - 1
        if not newline and not physical_line:
            continue
        line = physical_line.removesuffix('\r') if newline else physical_line
        if block:
            if re.fullmatch(r'\s*```\s*', line):
                block.closed = True
                if not block.ended:
                    block.error('missing_end')
                block = None
            elif line.strip():
                block.line(line)
        elif not fence and re.fullmatch(r'\s*```genui\s*', line):
            if sum(p['kind'] == 'ui' for p in parts) >= limits['blocks']:
                fence = 'overflow'
                text('交互区块数量已达上限，以下为原始说明。\n')
            else:
                block = Block(limits, data)
                parts.append({'kind': 'ui', 'block': block})
        else:
            if re.match(r'\s*```', line):
                if fence and re.fullmatch(r'\s*```\s*', line):
                    fence = None
                elif not fence:
                    fence = 'code'
            text(line + ('\n' if newline else ''))
    if block:
        block.error('incomplete')
    return [{'kind': 'ui', 'spec': p['block'].spec()} if p['kind'] == 'ui' else p for p in parts]
