"""Budget prompts in UTF-8 bytes; never split an assistant/tool-result group."""
import json
from copy import deepcopy

from .types import AgentError


def size(value):
    return len(json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode('utf-8'))


def excerpt(text, byte_limit):
    """Keep both ends verbatim, marking the gap instead of inventing a summary."""
    raw = text.encode('utf-8')
    if len(raw) <= byte_limit:
        return text
    marker = '\n[中间原文已省略；此为节选，不能推断缺失内容]\n'
    keep = max(0, byte_limit - len(marker.encode('utf-8')))
    head = keep // 2
    return raw[:head].decode('utf-8', errors='ignore') + marker + (raw[-(keep-head):].decode('utf-8', errors='ignore') if keep>head else '')


def history_groups(history):
    groups = []
    for message in history:
        if message['role'] == 'user' or not groups:
            groups.append([])
        groups[-1].append(message)
    return groups


def initial_context(value, budget):
    """Keep usable JSON and complete evidence entries, with explicit omissions.

    A byte prefix of the whole context can hide the trailing scope/permission
    fields or cut a citation in half. Large bodies remain retrievable by ID.
    """
    result = {key: value[key] for key in ('now', 'timezone', 'memory_control', 'web_restricted') if key in value}
    result['deferred'] = {}
    for key in ('personal_conditions', 'session_memory', 'working_memory', 'memory_catalog'):
        data = value.get(key)
        if data:
            candidate = {**result, key: data}
            if size(data) <= max(600, budget // 3) and size(candidate) <= budget - 512:
                result = candidate
            else:
                result['deferred'][key] = '按需用 memory_capabilities(section=context) 读取完整当前记录'
    for key in ('attachment_inventory', 'sources', 'user_sources', 'evidence_index'):
        result[key] = []
        omitted = 0
        for entry in value.get(key, []):
            candidate = {**result, key: result[key] + [entry]}
            if size(candidate) <= budget - 512:
                result = candidate
            else:
                omitted += 1
        if omitted:
            result['deferred'][key] = {'omitted': omitted, 'next': '原文仍在本轮；用 read_source 按已知 ID 读取，或 campus_search 查找'}
    if size(result) > budget:
        raise AgentError('初始权限与上下文超过本轮预算，请缩小任务范围')
    return result


def compact(system, history, current, tools, budget, *, protected_tools=()):
    fixed = [{'role': 'system', 'content': system}]
    current = deepcopy(current)
    # Compact older completed exchanges in-place in the prompt copy, keeping
    # call IDs paired and the latest exchange intact. The durable transcript is
    # untouched. Exact excerpts are explicitly incomplete, never invented facts.
    last_call = max((i for i, message in enumerate(current) if message.get('tool_calls')), default=0)
    protected_ids = {call['id'] for message in current for call in message.get('tool_calls', [])
                     if call['function']['name'] in protected_tools}
    compacted_tools = 0
    for index, message in enumerate(current):
        if size(fixed + current) + size(tools) + 512 <= budget:
            break
        if (index < last_call and message.get('role') == 'tool' and message.get('tool_call_id') not in protected_ids
                and len(message.get('content', '').encode('utf-8')) > 700):
            raw = message['content'].encode('utf-8')
            message['content'] = json.dumps({'context_compacted': True, 'original_bytes': len(raw),
                'excerpt': excerpt(message['content'], 600), 'warning': '较早工具结果仅保留首尾原文，需要时重新读取；不能重放已执行的副作用。'}, ensure_ascii=False)
            compacted_tools += 1
    # The current user input, every call and its matching result are indivisible.
    required = size(fixed + current) + size(tools) + 512
    if required > budget:
        raise AgentError('本轮工具与材料超过上下文预算；原始记录已保留，请拆分任务')
    selected, compacted_history = [], 0
    for group in reversed(history_groups(history)):
        if size(fixed + group + selected + current) + size(tools) + 768 <= budget:
            selected = group + selected
            continue
        # Keep a contiguous recent suffix. Never skip an oversized recent
        # answer and then silently substitute an older conversation turn.
        if not selected and not any(m.get('tool_calls') or m['role']=='tool' for m in group):
            available = budget - required - 320 - sum(size({**m, 'content': ''}) for m in group)
            if available >= 400 * len(group):
                per_message = available // len(group)
                candidate = [{**m, 'content': excerpt(m.get('content', ''), per_message)} for m in group]
                if size(fixed + candidate + current) + size(tools) + 768 <= budget:
                    selected = candidate
                    compacted_history = sum(a.get('content') != b.get('content') for a,b in zip(group,candidate))
        break
    omitted = len(history) - len(selected)
    if omitted:
        note = {'role': 'system', 'content': f'较早的 {omitted} 条历史未进入本轮。不要推断被省略的内容。'}
        if size(fixed + [note] + selected + current) + size(tools) + 512 <= budget:
            fixed.append(note)
    packed = fixed + selected + current
    return packed, {'omitted_messages': omitted, 'compacted_tool_results': compacted_tools,
                    'compacted_history_messages': compacted_history,
                    'packed_bytes': size(packed) + size(tools), 'budget_bytes': budget}
