"""Scalar diagnostics only; no source bodies, answers, or model reasoning."""
from contextvars import ContextVar
import json
import math
import time

CURRENT = ContextVar('notice_progress', default=None)
TIMINGS = {'elapsed_seconds', 'headers_seconds', 'first_answer_seconds', 'provider_seconds', 'validation_seconds'}
TOKENS = {'input_tokens', 'output_tokens', 'cached_input_tokens', 'reasoning_tokens'}


def public_metrics(value,*,nested=False):
    if not isinstance(value, dict):
        return {}
    result = {}
    if value.get('transport') in {'sse', 'json'}:
        result['transport'] = value['transport']
    for key in TIMINGS | TOKENS:
        number = value.get(key)
        if type(number) in {int, float} and math.isfinite(number) and 0 <= number <= 100000000:
            if key in TIMINGS:
                result[key] = round(number, 3)
            elif type(number) is int:
                result[key] = number
    if not nested and isinstance(value.get('calls'),list):
        from .model_catalog import TEXT_MODELS
        calls=[]
        for call in value['calls'][:2]:
            if not isinstance(call,dict) or call.get('model') not in TEXT_MODELS or call.get('purpose') not in {'extraction','semantic_review'}:
                continue
            if call.get('status') not in {'succeeded','failed','skipped'}:continue
            calls.append({**public_metrics(call,nested=True),'purpose':call['purpose'],'model':call['model'],
                'status':call['status'],'requested':call.get('requested') is True})
        result['calls']=calls
        result['call_count']=sum(c['requested'] for c in calls)
        result['usage_complete']=all(c.get('input_tokens') is not None and c.get('output_tokens') is not None for c in calls if c['requested'])
    return result


class Trace:
    def __init__(self, on_phase=None):
        self.started = time.monotonic()
        self.metrics = {}
        self.on_phase = on_phase
        self.stage = 'extracting'
        self.requested = False

    def elapsed(self):
        return time.monotonic() - self.started

    def phase(self, name):
        if name not in {'extracting', 'receiving', 'verifying','reviewing'} or name == self.stage:
            return
        self.stage = name
        if self.on_phase:
            self.on_phase(name)

    def answer(self):
        if 'first_answer_seconds' not in self.metrics:
            self.metrics['first_answer_seconds'] = self.elapsed()
            self.phase('receiving')

    def usage(self, usage):
        if not isinstance(usage, dict):
            return
        for target, key in [('input_tokens', 'prompt_tokens'), ('output_tokens', 'completion_tokens')]:
            if type(usage.get(key)) is int and usage[key] >= 0:
                self.metrics[target] = usage[key]
        for target, group, key in [('cached_input_tokens', 'prompt_tokens_details', 'cached_tokens'),
                                   ('reasoning_tokens', 'completion_tokens_details', 'reasoning_tokens')]:
            detail = usage.get(group)
            if isinstance(detail, dict) and type(detail.get(key)) is int and detail[key] >= 0:
                self.metrics[target] = detail[key]

    def snapshot(self):
        return public_metrics({**self.metrics, 'elapsed_seconds': self.elapsed()})

    def call(self,purpose,model,trace,status):
        calls=self.metrics.setdefault('calls',[])
        calls.append({**public_metrics(trace.snapshot(),nested=True),'purpose':purpose,'model':model,
            'status':status,'requested':trace.requested})
        requested=[c for c in calls if c['requested']]
        for key in TOKENS|{'provider_seconds','validation_seconds'}:
            known=[c[key] for c in requested if key in c]
            if known:self.metrics[key]=sum(known)
            else:self.metrics.pop(key,None)


def save(conn, key, trace):
    # A deleted notice cascades its run; diagnostics must not resurrect it.
    conn.execute('''INSERT INTO execution_metrics(execution_id,metrics)
        SELECT id,? FROM executions WHERE id=?
        ON CONFLICT(execution_id) DO UPDATE SET metrics=excluded.metrics''',
        (json.dumps(trace.snapshot(), separators=(',', ':')), key))


def decode(value):
    try:
        return public_metrics(json.loads(value or '{}'))
    except (ValueError, TypeError):
        return {}
