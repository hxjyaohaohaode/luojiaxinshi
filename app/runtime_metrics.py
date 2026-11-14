"""Bounded process-local SQLite lock timings; no paths or user data in output."""
from collections import OrderedDict,deque
import math
from threading import Lock

_guard=Lock()
_databases=OrderedDict()
MAX_DATABASES=8
MAX_SAMPLES=4096


def record(path,kind,milliseconds,failed=False):
    key=str(path.resolve())
    with _guard:
        bucket=_databases.setdefault(key,{'wait':deque(maxlen=MAX_SAMPLES),'hold':deque(maxlen=MAX_SAMPLES),'wait_count':0,'hold_count':0,'failed_acquisitions':0})
        _databases.move_to_end(key)
        bucket[kind].append(max(0.0,float(milliseconds)));bucket[kind+'_count']+=1
        if failed:bucket['failed_acquisitions']+=1
        while len(_databases)>MAX_DATABASES:_databases.popitem(last=False)


def summary(path):
    with _guard:
        bucket=_databases.get(str(path.resolve()))
        if not bucket:return {'observed':False,'sample_limit':MAX_SAMPLES,'scope':'本进程尚无写事务计时'}
        result={'observed':True,'sample_limit':MAX_SAMPLES,'failed_acquisitions':bucket['failed_acquisitions'],
                'scope':'本进程最近最多4096次写入总等待（公平准入排队、连接准备、SQLite BEGIN IMMEDIATE等待），以及成功BEGIN至提交或回滚的事务持有时间；重启清零，非生产吞吐承诺'}
        for kind in ('wait','hold'):
            values=sorted(bucket[kind]);n=len(values)
            result[kind]={'total_observations':bucket[kind+'_count'],'samples':n,
                          'p50_ms':round(values[max(0,math.ceil(n*.5)-1)],3) if n else None,
                          'p95_ms':round(values[max(0,math.ceil(n*.95)-1)],3) if n else None,
                          'max_ms':round(values[-1],3) if n else None}
        return result
