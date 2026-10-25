from importlib.metadata import distribution
from pathlib import Path
from packaging.requirements import Requirement

roots=['fastapi','uvicorn','python-multipart','pypdf','defusedxml','httpx','python-dotenv','icalendar',
       'Pillow','cryptography','opentelemetry-api','av','pywebpush']
seen={}
pending=list(roots)
while pending:
    package=distribution(pending.pop())
    name=package.metadata['Name']
    if name in seen:
        continue
    seen[name]=package.version
    for raw in package.requires or []:
        requirement=Requirement(raw)
        if requirement.marker is None or requirement.marker.evaluate():
            pending.append(requirement.name)
root=Path(__file__).resolve().parent.parent
# colorama is conditionally required on Windows, but installing it on Linux is harmless.
seen['colorama']=distribution('colorama').version
(root/'requirements.lock').write_text('\n'.join(k+'=='+v for k,v in sorted(seen.items()))+'\n',encoding='utf-8')
print(f'Locked {len(seen)} runtime packages')
