"""Create a source delivery archive from an explicit allowlist; never include user data."""
import hashlib
from pathlib import Path
import zipfile

ROOT=Path(__file__).resolve().parent.parent
FILES=['README.md','OPERATIONS.md','TESTING.md','ASSETS.md','REDESIGN.md','INTEGRATIONS.md','requirements.lock','requirements-dev.txt',
       '.env.example','.dockerignore','.gitignore','Dockerfile','compose.yaml','Caddyfile',
       'manage.py','start.ps1','stop.ps1','启动工作台.cmd','停止工作台.cmd','重启工作台.cmd','pytest.ini',
       'scripts/local-runtime.ps1','scripts/check_dependencies.py','scripts/lock_dependencies.py',
       'scripts/build_release.py','scripts/verify_local_runtime.py']
for directory,extensions in [('app',{'.py'}),('static',{'.js','.css','.svg','.html','.png'}),('tests',{'.py','.mjs'})]:
    FILES.extend(str(p.relative_to(ROOT)).replace('\\','/') for p in (ROOT/directory).rglob('*')
                 if p.is_file() and p.suffix in extensions and '__pycache__' not in p.parts)
destination=ROOT/'releases'/'campus-notice-1.1.0.zip'
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
