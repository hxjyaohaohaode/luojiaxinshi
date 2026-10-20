"""Chinese-aware BM25, query expansion and provenance-neighbour rank fusion."""
import json
import re
import time

from .memory_store import tokens

# These are transparent lexical expansions, not a pretend embedding model.
CONCEPTS = (
    ('回复', '回答', '表达', '写作', '措辞', '输出', '风格'),
    ('简短', '简洁', '精炼', '精简', '简明'),
    ('期限', '截止', '到期', '提交时间'),
    ('经验', '教训', '失败', '方法', '技能', '流程'),
    ('计划', '安排', '待办', '打算', '下一步'),
    ('语言', '中文', '英文', '英语', '汉语'),
    ('约束', '限制', '要求', '必须', '禁止'),
)


def match_query(query):
    words = list(dict.fromkeys(tokens(query).split()))
    # Unigrams keep one-character Chinese names searchable but are too broad
    # when longer words are available.
    long = [word for word in words if len(word) > 1]
    words = (long or words)[:64]
    return ' OR '.join('"' + word.replace('"', '""') + '"' for word in words)


def ranked(conn, uid, items, question, queries=None, limit=12, byte_budget=8000):
    by_id = {item['id']: item for item in items}
    eligible_ids = json.dumps(list(by_id))
    scores = {key: 0.0 for key in by_id}
    reasons = {key: set() for key in by_id}
    searches = list(dict.fromkeys([question, *(queries or [])]))[:5]
    expansion = ' '.join(word for group in CONCEPTS if any(term in question for term in group) for word in group)
    if expansion:
        searches.append(expansion)
    for index, query in enumerate(searches):
        match = match_query(query)
        if not match:
            continue
        hits = conn.execute('''SELECT memory_id,bm25(memory_fts) score FROM memory_fts
            WHERE memory_fts MATCH ? AND user_id=?
            AND memory_id IN (SELECT value FROM json_each(?))
            ORDER BY score,memory_id LIMIT 240''', (match, uid, eligible_ids)).fetchall()
        weight = 1.0 if index == 0 else .65
        for rank, hit in enumerate(hits, 1):
            key = hit['memory_id']
            if key in by_id:
                scores[key] += weight / (30 + rank)
                reasons[key].add('关键词' if index == 0 else '相关表达')
    seeds = sorted((key for key in scores if scores[key]), key=lambda key: -scores[key])[:8]
    if seeds:
        marks = ','.join('?' for _ in seeds)
        for edge in conn.execute(f'''SELECT l.* FROM memory_links l JOIN personal_memories m
                ON m.id=l.child_id WHERE m.user_id=? AND
                (l.child_id IN ({marks}) OR l.parent_id IN ({marks})) LIMIT 80''', (uid, *seeds, *seeds)):
            for key in (edge['child_id'], edge['parent_id']):
                if key in by_id:
                    scores[key] += .006
                    reasons[key].add('来源关联')
    now = int(time.time())
    for key, item in by_id.items():
        if item['pinned']:
            scores[key] += .08
            reasons[key].add('本人置顶')
        elif item['kind'] in ('preference', 'constraint'):
            scores[key] += .009
            reasons[key].add('偏好与约束')
        if scores[key]:
            age = max(0, now-item['updated_at']) / 86400
            scores[key] += .002 / (1 + age / 30)
    ordered = sorted((key for key in scores if scores[key]),
                     key=lambda key: (-scores[key], -by_id[key]['updated_at'], key))
    selected, used, seen, picked_words = [], 2, set(), []
    word_cache = {}
    while ordered and len(selected) < limit:
        # MMR-style redundancy penalty is bounded to candidates already selected.
        window = ordered[:32]
        def diversity(key):
            if key not in word_cache:
                word_cache[key] = set(tokens(by_id[key]['content']).split())
            words = word_cache[key]
            similarity = max((len(words & other)/max(1, len(words | other)) for other in picked_words), default=0)
            return scores[key] * (1 - .4*similarity)
        key = max(window, key=diversity)
        ordered.remove(key)
        item = by_id[key]
        signature = re.sub(r'\s+', '', item['content']).casefold()
        selected_item = {**item, 'recall_score': round(scores[key], 6), 'recall_reasons': sorted(reasons[key])}
        # Include metadata in the budget. This is conservative for recall(),
        # which removes management-only fields before constructing the prompt.
        cost = len(json.dumps(selected_item,ensure_ascii=False,separators=(',',':')).encode('utf-8')) + 1
        if signature in seen or used + cost > byte_budget:
            continue
        selected.append(selected_item)
        used += cost
        seen.add(signature)
        picked_words.append(word_cache[key])
    return selected, {'algorithm': 'zh-bm25-rrf-provenance-mmr-v1', 'dense_embeddings': False,
                      'query_count': len(searches), 'matched': sum(bool(value) for value in scores.values()),
                      'context_bytes': used}
