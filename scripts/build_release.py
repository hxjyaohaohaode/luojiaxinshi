"""Create a source delivery archive from an explicit allowlist; never include user data."""
import hashlib
from pathlib import Path
import zipfile
import sys

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from app.version import VERSION
FILES=['README.md','CONTRIBUTING.md','OPERATIONS.md','TESTING.md','ASSETS.md','REDESIGN.md','INTEGRATIONS.md','MIMO_INTEGRATION.md','requirements.lock','requirements-dev.txt',
       '.env.example','.dockerignore','.gitignore','.gitattributes','Dockerfile','compose.yaml','Caddyfile',
       'manage.py','start.ps1','stop.ps1','启动工作台.cmd','停止工作台.cmd','重启工作台.cmd','pytest.ini',
       'package.json','package-lock.json','THIRD_PARTY_NOTICES.md']
for directory,extensions in [('app',{'.py'}),('static',{'.js','.css','.svg','.html','.png','.webm','.json'}),('tests',{'.py','.mjs'}),
                             ('scripts',{'.py','.mjs','.ps1'}),('docs',{'.md','.txt','.json'}),
                             ('schema',{'.json'}),('fixtures',{'.json','.md'}),
                             ('项目资料',{'.md','.txt','.json','.csv','.docx','.pdf','.png','.html'})]:
    FILES.extend(str(p.relative_to(ROOT)).replace('\\','/') for p in (ROOT/directory).rglob('*')
                 if p.is_file() and p.suffix in extensions and '__pycache__' not in p.parts)
destination=ROOT/'releases'/f'campus-notice-{VERSION}.zip'
destination.parent.mkdir(exist_ok=True)
with zipfile.ZipFile(destination,'w',zipfile.ZIP_DEFLATED) as archive:
    for filename in sorted(FILES):
        if not (ROOT/filename).is_file(): raise FileNotFoundError(filename)
        archive.write(ROOT/filename,'campus-notice/'+filename)
with zipfile.ZipFile(destination) as archive:
    assert archive.testzip() is None
    assert not any('/data/' in name or '/artifacts/' in name or name.endswith('/.env') for name in archive.namelist())
checksum=hashlib.sha256(destination.read_bytes()).hexdigest()
destination.with_suffix('.zip.sha256').write_text(checksum+'  '+destination.name+'\n',encoding='ascii')
print(f'{destination.name}: {len(FILES)} files, {destination.stat().st_size} bytes, SHA256 {checksum}')
