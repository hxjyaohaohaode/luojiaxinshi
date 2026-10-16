"""Keep the user's current response requirements through drafting and repairs.

These are publication checks, never automatic truncation or evidence exemptions.
"""
import re

from .retrieval_scope import user_request


COUNTS = {'一':1, '二':2, '两':2, '三':3, '四':4, '五':5,
          '六':6, '七':7, '八':8, '九':9, '十':10}


def response_contract(messages):
    result = {}
    for message in reversed(messages):
        if message.get('role') != 'user':
            continue
        text = user_request(message)
        if not text:
            continue
        result.setdefault('latest_user_request', text[-6000:])
        if 'max_sentences' not in result:
            matches = list(re.finditer(r'(?<!第)([一二两三四五六七八九十]|[1-9][0-9]?)\s*(?:句话|句)(?:以内|内|回答|说明|概括|就好|即可)', text))
            english = list(re.finditer(r'(?:at most|no more than)\s+([1-9][0-9]?)\s+sentences?', text, re.I))
            candidates = matches + english
            if candidates:
                value = max(candidates, key=lambda m:m.start())[1]
                result['max_sentences'] = COUNTS[value] if value in COUNTS else int(value)
        if 'no_ui' not in result:
            if re.search(r'(?:不|不要|无需)(?:重新)?(?:生成|重建)(?:互动)?(?:界面|工作区|UI)|只(?:要|用)(?:纯)?文字', text, re.I):
                result['no_ui'] = True
            elif re.search(r'(?:生成|做|制作|提供|给出).{0,25}(?:界面|工作区|面板|交互组件|图表)', text):
                result['no_ui'] = False
    return result


def prose_without_code(text):
    # Code and escaped brackets are literal content, not citation or sentence syntax.
    text = re.sub(r'(?ms)^\s*(`{3,}|~{3,})[^\n]*\n.*?^\s*\1\s*$', '', text)
    return re.sub(r'(`+)[^\n]*?\1', '', text)


def embedded_quotation_text(text):
    """Ignore internal stops only when a balanced quotation continues a sentence.

    A quote followed by a comma/semicolon is an embedded clause. Standalone
    quoted sentences and unfinished quotes keep all their sentence endings.
    """
    pairs = {'“':'”', '「':'」', '『':'』', '"':'"'}
    continuation = re.compile(r'\s*[,，;；:：、]')
    stack, spans = [], []
    for index, char in enumerate(text):
        if stack and char == stack[-1][1]:
            start, _ = stack.pop()
            if continuation.match(text, index+1):
                spans.append((start, index+1))
        elif char in pairs:
            stack.append((index, pairs[char]))
    merged = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    parts, previous = [], 0
    for start, end in merged:
        parts.extend((text[previous:start], re.sub(r'[。！？!?.]', ' ', text[start:end])))
        previous = end
    return ''.join(parts)+text[previous:]


def sentence_count(text):
    text = prose_without_code(text)
    text = re.sub(r'https?://[^\s)<>]+|(?<!\\)\[(?:E)?[0-9]+\]', '', text)
    text = embedded_quotation_text(text)
    count = 0
    # An unpunctuated list/paragraph is still a response unit, not a loophole.
    for block in re.split(r'\n\s*\n|\n(?=\s*(?:[-*+]\s|\d+[.)、]\s|#{1,6}\s))', text):
        block = re.sub(r'^\s*(?:#{1,6}\s|[-*+]\s|\d+[.)、]\s)', '', block).strip()
        if not block:
            continue
        endings = list(re.finditer(r'[。！？!?]+|(?<!\d)\.(?!\d)(?=\s|$)', block))
        count += len(endings)
        tail = block[endings[-1].end():] if endings else block
        if tail.strip(' \n\t\r”’\"\'」』】)]*_:：;；,，'):
            count += 1
    return count


def check_response_contract(parts, contract):
    if contract.get('no_ui') and any(part['kind'] == 'ui' for part in parts):
        raise ValueError('本轮明确要求不重建界面；请只返回正文，保持已有工作区可继续使用。')
    limit = contract.get('max_sentences')
    if limit:
        count = sentence_count('\n\n'.join(part['text'] for part in parts if part['kind']=='text'))
        if count > limit:
            raise ValueError(f'本轮最多{limit}句话，草稿有{count}个句子或独立段落。请在该上限内重写完整回答，保留必要条件、准确引用和未知边界，不添加未问的条款，不靠截断草稿修复。逐字引句可作为句内引用，用闭引号后的逗号或分号接续主句；闭引号后直接开始新陈述仍算下一句，不要删改用户要求逐字保留的引句。')
