"""Per-reply execution telemetry and a bounded no-progress guard.

No prompt bodies, API keys, model reasoning or memory contents enter telemetry.
"""
from contextvars import ContextVar
import hashlib
import json
import time

VERSION='harness-v2'
GENERATION_LIMIT=5
PROTOCOL_RETRIES=3
SEMANTIC_RETRIES=1
CURRENT=ContextVar('reply_harness',default=None)


class Trace:
    def __init__(self):
        self.started=time.monotonic()
        self.stage='planning'
        self.calls=[]
        self.phases=[]
        self.repairs=set()
        self.stop_reason=None

    def phase(self,name):
        now=time.monotonic()
        if self.phases:self.phases[-1]['elapsed_seconds']=round(now-self.phases[-1]['_start'],3)
        self.stage=name
        self.phases.append({'stage':name,'_start':now,'elapsed_seconds':0})

    def progress(self,issues,draft):
        signature=hashlib.sha256(json.dumps([sorted(issues),draft],ensure_ascii=False).encode()).hexdigest()
        repeated=signature in self.repairs
        self.repairs.add(signature)
        if repeated:self.stop_reason='no_progress'
        return not repeated

    def snapshot(self):
        phases=[{k:v for k,v in p.items() if k!='_start'} for p in self.phases]
        if phases:phases[-1]['elapsed_seconds']=round(time.monotonic()-self.phases[-1]['_start'],3)
        calls=[{k:v for k,v in call.items() if k!='_start'} for call in self.calls]
        return {'version':VERSION,'elapsed_seconds':round(time.monotonic()-self.started,3),'calls':calls,
            'call_count':len(self.calls),'phases':phases,'cached_input_tokens':sum(c.get('cached_input_tokens',0) for c in self.calls),
            'stop_reason':self.stop_reason,'loop_limits':{'generations':GENERATION_LIMIT,'protocol_repairs':PROTOCOL_RETRIES,'semantic_repairs':SEMANTIC_RETRIES}}


def start_call(payload):
    trace=CURRENT.get()
    if trace is None:return None
    entry={'stage':trace.stage,'model':payload.get('model'),'thinking':payload.get('thinking',{}).get('type'),
        'output_limit':payload.get('max_completion_tokens'),'status':'running','_start':time.monotonic()}
    trace.calls.append(entry)
    return entry


def finish_call(entry,usage=None,error=None):
    if entry is None:return
    usage=usage or {}
    entry.update(status='failed' if error else 'complete',elapsed_seconds=round(time.monotonic()-entry.pop('_start'),3),
        input_tokens=int(usage.get('prompt_tokens',usage.get('input_tokens',0)) or 0),
        output_tokens=int(usage.get('completion_tokens',usage.get('output_tokens',0)) or 0),
        cached_input_tokens=int((usage.get('prompt_tokens_details') or {}).get('cached_tokens') or 0),
        reasoning_tokens=int((usage.get('completion_tokens_details') or {}).get('reasoning_tokens') or 0))
    if error:entry['error_type']=type(error).__name__
    if isinstance(usage.get('provider_model'), str):entry['provider_model']=usage['provider_model'][:128]
