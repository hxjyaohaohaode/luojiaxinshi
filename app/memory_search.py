"""Scope-filtered lexical, facet, temporal and provenance recall with feedback."""
import json
import re
import time
from collections import Counter

from .memory_store import tokens
from .memory_policy import scope_key
from .memory_lifecycle import facet,task_memory_ids

CONCEPTS = (
    ('回复','回答','表达','写作','措辞','输出','风格'),
    ('简短','简洁','精炼','精简','简明'),
    ('期限','截止','到期','提交时间'),
    ('经验','教训','失败','方法','技能','流程'),
    ('计划','安排','待办','打算','下一步'),
    ('语言','中文','英文','英语','汉语'),
    ('约束','限制','要求','必须','禁止'),
    ('称呼','名字','姓名','叫我'),
)
STOP = {'怎么','什么','如何','我的','我们','请问','一下','是否','可以','这个','那个','以及','关于','需要','现在','这些','给我','帮我','一个','哪些'}


def match_query(query):
    words=list(dict.fromkeys(tokens(query).split()))
    long=[word for word in words if len(word)>1 and word not in STOP]
    words=(long or [word for word in words if word not in STOP])[:64]
    return ' OR '.join('"'+word.replace('"','""')+'"' for word in words)


def requested_facets(question):
    result=set()
    name=facet(question)
    if name:result.add(name)
    for pattern,name in ((r'称呼|名字|姓名|我是谁','identity.name'),
                          (r'排版|排布|组织回答|格式|先说|结构','style.structure'),
                          (r'篇幅|长短|多长|字数','style.length'),
                          (r'地点|住哪|哪个校区|住的地方','identity.location'),
                          (r'专业|年级|就读','identity.study')):
        if re.search(pattern,question):result.add(name)
    if re.search(r'偏好|习惯|风格|帮助我|写作|怎么回答',question):
        result.update(('style.structure','style.length','style.language'))
    return result


PROMPT_FIELDS = ('id','scope','project_id','topic','kind','content','version','updated_at',
    'origin','locked','labels','recall_score','recall_reasons','tier','facet','admission','last_confirmed_at','scope_name','node_id')


def ranked(conn,uid,items,question,queries=None,limit=12,byte_budget=8000,prompt_only=False):
    scenario=(question+' '+' '.join(queries or [])).casefold()
    historic=bool(re.search(r'以前|上次|过去|曾经|当时|历史|回顾|经历|经验|教训',question))
    personal_progress=bool(re.search(r'我的待办|我的任务|我还有|进度|还没完成|办理记录|已经完成',question))
    task_backed=task_memory_ids(conn,uid)
    def usable_episode(item):
        if item['id'] not in task_backed or historic or personal_progress:return True
        title=re.search(r'^办理记录：(.+?)。当前状态',item['content'])
        return bool(title and len(title[1])>=4 and title[1] in scenario)
    by_id={item['id']:item for item in items if usable_episode(item) and (not item.get('applies_to') or any(cue.casefold() in scenario for cue in item['applies_to']))}
    scores={key:0.0 for key in by_id}
    reasons={key:set() for key in by_id}
    eligible_ids=json.dumps(list(by_id))
    searches=list(dict.fromkeys([question,*(queries or [])]))[:5]
    expansion=' '.join(word for group in CONCEPTS if any(term in question for term in group) for word in group)
    if expansion:searches.append(expansion)
    arms=[]
    for index,query in enumerate(searches):
        match=match_query(query)
        if not match:continue
        hits=conn.execute('''SELECT memory_id,bm25(memory_fts) score FROM memory_fts
            WHERE memory_fts MATCH ? AND user_id=? AND memory_id IN (SELECT value FROM json_each(?))
            ORDER BY score,memory_id LIMIT 240''',(match,uid,eligible_ids)).fetchall()
        arms.append(([hit['memory_id'] for hit in hits],1.5 if index==0 else 1.0,'原句匹配' if index==0 else '相关表达'))
    wanted=requested_facets(question+' '+' '.join(queries or []))
    facet_hits=[key for key,item in by_id.items() if item.get('facet') in wanted]
    facet_hits.sort(key=lambda key:(-by_id[key].get('last_confirmed_at',by_id[key]['updated_at']),key))
    if facet_hits:arms.append((facet_hits,1.4,'信息槽位'))
    # Presentation preferences apply to the reply; arbitrary personal facts and
    # pinned hobbies do not become universal instructions.
    style=[]
    for key,item in by_id.items():
        cues=item.get('applies_to',[])
        if cues and not any(cue in question for cue in cues):continue
        if item.get('facet','').startswith('style.') or (re.search(r'帮助我|偏好|习惯|约束',question) and item['kind'] in ('preference','constraint')):
            style.append(key)
    style.sort(key=lambda key:(-by_id[key].get('locked',False),-by_id[key]['updated_at'],key))
    if style:arms.append((style[:3],.65,'适用于当前回答的表达偏好'))
    branch_hits=[key for key,item in by_id.items() if item.get('_tree_selected')]
    if branch_hits:arms.append((branch_hits[:80],.8,'相关记忆目录'))
    # Rank-space boosts avoid a flat constant that can swamp direct matches.
    for keys,boost,reason in arms:
        for rank,key in enumerate(keys,1):
            scores[key]+=1/(30+rank/boost)
            reasons[key].add(reason)
    seeds=sorted((key for key in scores if scores[key]),key=lambda key:-scores[key])[:8]
    if seeds:
        marks=','.join('?' for _ in seeds)
        for edge in conn.execute(f'''SELECT l.* FROM memory_links l JOIN personal_memories m ON m.id=l.child_id
                WHERE m.user_id=? AND (l.child_id IN ({marks}) OR l.parent_id IN ({marks})) LIMIT 80''',(uid,*seeds,*seeds)):
            for key in (edge['child_id'],edge['parent_id']):
                if key in by_id and (scores[key] or by_id[key]['kind']=='summary'):
                    scores[key]+=.003
                    reasons[key].add('来源关联')
    now=int(time.time())
    for key,item in by_id.items():
        if not scores[key]:continue
        age=max(0,now-item.get('last_confirmed_at',item['updated_at']))/86400
        half_life=30 if item.get('tier')=='episodic' else 180
        scores[key]*=.7+.3/(1+age/half_life)
        scores[key]*=max(.3,min(1.3,1+.08*item.get('positive',0)-.14*item.get('negative',0)))
        if item.get('tier')=='episodic':
            scores[key]*=1.15 if historic else .5
            reasons[key].add('回顾经历' if historic else '历史记录降权')
        if item['pinned']:
            scores[key]*=1.12
            reasons[key].add('相关内容中本人置顶')
        if item['scope']=='project':scores[key]*=1.08
        if item.get('origin')=='organizer':scores[key]*=.5
    ordered=sorted((key for key in scores if scores[key]),key=lambda key:(-scores[key],-by_id[key]['updated_at'],key))[:512]
    reranked=len(ordered)
    signatures={key:(scope_key(by_id[key]),(by_id[key]['facet'],by_id[key]['canonical_value']) if by_id[key].get('facet') and by_id[key].get('canonical_value')
        else re.sub(r'\s+','',by_id[key]['content']).casefold()) for key in ordered}
    prepared={key:{**by_id[key],'recall_score':round(scores[key],6),'recall_reasons':sorted(reasons[key])} for key in ordered}
    costs={key:len(json.dumps({k:item[k] for k in PROMPT_FIELDS if k in item} if prompt_only else item,
        ensure_ascii=False,separators=(',',':')).encode('utf-8'))+1 for key,item in prepared.items()}
    selected,used,seen,picked_words=[],2,set(),[]
    facets=Counter(); styles=0; word_cache={}
    while ordered and len(selected)<limit:
        # Eliminate impossible candidates before tokenization/MMR, rather than
        # repeatedly scoring thousands of duplicates or already-full facets.
        ordered=[key for key in ordered if signatures[key] not in seen
            and used+costs[key]<=byte_budget
            and (not by_id[key].get('facet') or facets[(scope_key(by_id[key]),by_id[key]['facet'])]<2)
            and not (by_id[key].get('facet','').startswith('style.') and styles>=2 and by_id[key]['facet'] not in wanted)]
        if not ordered:break
        window=ordered[:32]
        def diversity(key):
            if key not in word_cache:word_cache[key]=set(tokens(by_id[key]['content']).split())
            words=word_cache[key]
            similarity=max((len(words&other)/max(1,len(words|other)) for other in picked_words),default=0)
            return scores[key]*(1-.45*similarity)
        key=max(window,key=diversity);ordered.remove(key)
        item=by_id[key]
        name=item.get('facet','')
        signature=signatures[key]
        if signature in seen:continue
        if name.startswith('style.') and styles>=2 and name not in wanted:continue
        if name and facets[(scope_key(item),name)]>=2:continue
        result=prepared[key]
        cost=costs[key]
        if used+cost>byte_budget:continue
        selected.append(result);used+=cost;seen.add(signature);picked_words.append(word_cache[key])
        if name:facets[(scope_key(item),name)]+=1
        if name.startswith('style.'):styles+=1
    return selected,{'algorithm':'zh-bm25-facet-temporal-feedback-rrf-mmr-v3','dense_embeddings':False,
        'query_count':len(searches),'matched':sum(bool(value) for value in scores.values()),
        'context_bytes':used,'requested_facets':sorted(wanted),'intent':'retrospective' if historic else 'current',
        'rerank_candidates':reranked,
        'strategies':['lexical','facet','provenance','temporal','feedback'],'exposure_is_not_confirmation':True}
