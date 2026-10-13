"""Local operator commands. Public registration never grants administrator access."""
import argparse
from datetime import datetime
import getpass
import json
import os
from pathlib import Path
import secrets
import sqlite3
import sys
import time

from app.config import ROOT, Settings
from app.backups import restore_database
from app.db import Database
from app.security import hash_password, new_invite


def main():
    parser=argparse.ArgumentParser(description='校园通知工作台运行与维护')
    parser.add_argument('command', choices=['serve','init','invite','backup','restore','reset-password','check','runtime'])
    parser.add_argument('--admin',action='store_true')
    parser.add_argument('--file',type=Path)
    parser.add_argument('--username')
    args=parser.parse_args()
    cfg=Settings.from_env()
    if args.command=='runtime':
        print(json.dumps({'data_dir':str(cfg.data_dir),'origin':cfg.origin,'production':cfg.production,
                          'host':os.getenv('APP_HOST','127.0.0.1'),'port':int(os.getenv('APP_PORT','8765'))}))
        return
    if args.command=='restore':
        if not args.file or not args.file.is_file():
            parser.error('请用 --file 指定有效备份')
        destination=cfg.data_dir/'campus.sqlite3'
        if destination.exists():
            parser.error('为防覆盖，恢复要求 DATA_DIR 指向一个新的空目录；请先停止服务')
        try:
            restore_database(args.file,destination)
        except (ValueError,sqlite3.Error,OSError) as exc:
            parser.error('恢复未完成，已有数据未覆盖：'+str(exc))
        print('恢复完成。会话和邀请已清除，请使用已有账号重新登录。')
        return
    db=Database(cfg.data_dir/'campus.sqlite3')
    if args.command=='init':
        with db.connect() as conn:
            count=conn.execute("SELECT COUNT(*) FROM users WHERE role='admin'").fetchone()[0]
        if count:
            setup=cfg.data_dir/'admin-setup.url.txt'
            if setup.exists():
                setup.unlink()
            print('已有账号，初始化不会覆盖数据。')
            return
        setup=cfg.data_dir/'admin-setup.url.txt'
        with db.connect(write=True) as conn:
            # Initialization is an explicit local action; revoke previous unused bootstrap invitations.
            conn.execute("DELETE FROM invites WHERE role='admin' AND used_at IS NULL")
        url=cfg.origin+'/#invite='+new_invite(db,'admin')
        setup.write_text(url+'\n',encoding='utf-8')
        try:
            setup.chmod(0o600)
        except OSError:
            pass
        print('请打开以下一次性管理员邀请链接，自行设置用户名和密码：\n'+url)
        print('链接也保存在 data/admin-setup.url.txt，仅向管理员提供。')
    elif args.command=='invite':
        print(cfg.origin+'/#invite='+new_invite(db,'admin' if args.admin else 'user'))
    elif args.command=='backup':
        folder=ROOT/'backups'
        filename=args.file or folder/('campus-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+secrets.token_hex(2)+'.sqlite3')
        db.backup(filename.resolve())
        print('备份完成并通过完整性检查：'+str(filename.resolve()))
        retention=max(1,int(os.getenv('BACKUP_RETENTION_DAYS','7')))
        # Only managed files in the verified backup directory are pruned.
        folder=folder.resolve()
        if folder.is_dir():
            for item in folder.glob('campus-*.sqlite3'):
                if item.resolve().parent==folder and item.stat().st_mtime<time.time()-retention*86400:
                    item.unlink()
    elif args.command=='reset-password':
        if not args.username:
            parser.error('请指定 --username')
        password=getpass.getpass('新密码（至少 12 字符）：')
        if len(password)<12 or len(password)>128:
            parser.error('密码长度须为 12—128 字符')
        if password!=getpass.getpass('再输入一次：'):
            parser.error('两次密码不一致')
        with db.connect(write=True) as conn:
            row=conn.execute('SELECT id FROM users WHERE username=?',(args.username.lower(),)).fetchone()
            if not row:
                parser.error('用户名不存在')
            conn.execute('UPDATE users SET password=? WHERE id=?',(hash_password(password),row['id']))
            conn.execute('DELETE FROM sessions WHERE user_id=?',(row['id'],))
        print('密码已更新，所有旧会话已注销。')
    elif args.command=='check':
        with db.connect() as conn:
            print(json.dumps({'database':conn.execute('PRAGMA integrity_check').fetchone()[0],
                  'schema':conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0],
                  'users':conn.execute('SELECT COUNT(*) FROM users').fetchone()[0],
                  'ai_configured':bool(cfg.ai_api_key),'ai_model':cfg.ai_model,'origin':cfg.origin},ensure_ascii=False))
    else:
        import uvicorn
        host=os.getenv('APP_HOST','127.0.0.1')
        if not cfg.production and host not in {'127.0.0.1','localhost','::1'}:
            parser.error('本地模式仅允许监听回环地址；外部访问请配置生产 HTTPS')
        runtime=cfg.data_dir/'campus-runtime.json'
        runtime.write_text(json.dumps({'pid':os.getpid(),'root':str(ROOT),'origin':cfg.origin}),encoding='utf-8')
        try:
            uvicorn.run('app.main:create_app',factory=True,host=host,port=int(os.getenv('APP_PORT','8765')),
                        workers=1,access_log=False,proxy_headers=cfg.production,
                        forwarded_allow_ips=os.getenv('FORWARDED_ALLOW_IPS','127.0.0.1'),limit_concurrency=60)
        finally:
            if runtime.exists() and json.loads(runtime.read_text(encoding='utf-8')).get('pid')==os.getpid():
                runtime.unlink()


if __name__=='__main__':
    main()
