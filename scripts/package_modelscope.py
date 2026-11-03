"""Create a code-only upload bundle. Never includes local accounts, .env, or credentials."""
import hashlib
import json
from pathlib import Path
import shutil
import tarfile

ROOT=Path(__file__).resolve().parent.parent
OUTPUT=ROOT/'artifacts'/'modelscope-deploy'
DIRECTORIES=('app','static','schema','skills','docs/genui','docs/licenses')
FILES=('manage.py','requirements.lock','scripts/install_legacy_parser.py')

def allowed(path):
    relative=path.relative_to(ROOT)
    return path.is_file() and not path.is_symlink() and '__pycache__' not in relative.parts \
        and not any(part.startswith('.') for part in relative.parts) \
        and path.suffix.lower() not in {'.pyc','.pyo','.key','.pem','.sqlite','.sqlite3','.db','.log'}

def main():
    OUTPUT.mkdir(parents=True,exist_ok=True)
    paths=[ROOT/name for name in FILES]
    paths.extend(path for name in DIRECTORIES for path in (ROOT/name).rglob('*') if allowed(path))
    archive=OUTPUT/'application.tar.gz'
    with tarfile.open(archive,'w:gz') as bundle:
        for path in sorted(paths):
            info=bundle.gettarinfo(str(path),arcname=path.relative_to(ROOT).as_posix())
            info.uid=info.gid=0;info.uname=info.gname='';info.mode=0o644
            with path.open('rb') as stream:bundle.addfile(info,stream)
    for name in ('Dockerfile','studio_entrypoint.py','.dockerignore'):
        shutil.copyfile(ROOT/'deploy'/'modelscope'/name,OUTPUT/name)
    (OUTPUT/'README.md').write_text('''---
license: other
---
# 珞珈信使试点

项目代码私有托管；未另行授予开源许可。第三方组件保留原有许可证。
这是尚未通过正式试点验收的实验性部署包，不是可直接开放的生产服务。
默认创空间 OSSFS 挂载不满足当前 SQLite WAL 存储条件，入口会在写入数据前停止。
只有平台提供经确认的本地持久化卷后才可继续验证重启、恢复和独立 HTTPS 地址。
在完成这些验证前，不要上传真实账号数据或密钥。容器端口为 7860。
''',encoding='utf-8')
    result={'file_count':len(paths),'archive_bytes':archive.stat().st_size,
            'sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),
            'upload_files':['Dockerfile','application.tar.gz','studio_entrypoint.py','README.md','.dockerignore'],
            'excluded':['.env','data','backups','artifacts','local credentials','local user accounts']}
    (OUTPUT/'manifest.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__':main()
