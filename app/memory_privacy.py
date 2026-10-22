"""Scrub recognized credentials at the memory-to-model boundary, not in storage."""
def redact(value):
    from .memory_learning import SECRET
    if isinstance(value,str):return SECRET.sub('[凭证已省略]',value)
    if isinstance(value,list):return [redact(item) for item in value]
    if isinstance(value,dict):return {key:redact(item) for key,item in value.items()}
    return value
