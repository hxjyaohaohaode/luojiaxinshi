"""Read-only deployment prerequisites. Never prints credentials or sends messages."""
import argparse
import json
from pathlib import Path
import sys
from urllib.parse import urlsplit
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from app.config import Settings
from app.cloud_messages import CloudMessages

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--production',action='store_true')
    parser.add_argument('--local-env',action='store_true',help='Read this project .env explicitly; never prints its values')
    args=parser.parse_args()
    if args.local_env:
        from dotenv import load_dotenv
        load_dotenv(ROOT/'.env',override=True)
    settings=Settings.from_env();sender=CloudMessages(settings);origin=urlsplit(settings.origin)
    checks={'sms_configuration':sender.available('sms'),'email_configuration':sender.available('email'),
        'operator_contact':bool(settings.operator_contact),
        'pwa_files':all((ROOT/'static'/name).is_file() for name in ('manifest.webmanifest','notification-worker.js','pwa.js','assets/app-icon.svg')),
        'registration_policy_configured':settings.registration_mode in {'public','invite'},
        'public_https':origin.scheme=='https' and origin.hostname not in {'localhost','127.0.0.1','::1'},
        'production_mode':settings.production}
    required=checks if args.production else {key:checks[key] for key in ('sms_configuration','email_configuration','pwa_files')}
    print(json.dumps({'ready_for_configuration_review':all(required.values()),'checks':checks,
        'registration_mode':settings.registration_mode,
        'external_acceptance':'not_assessed',
        'remaining_evidence':['真实邮箱验证码与收件箱验证','公网 HTTPS 与持久化数据验证','真实设备锁屏提醒验证','累计不少于 5 天的现场实践或场景验证书面记录','发榜或验证单位出具的验收结论'],
        'note':'配置存在不代表外部通道送达或真实试点已验收。'},ensure_ascii=False,indent=2))
    return 0 if all(required.values()) else 2

if __name__=='__main__':raise SystemExit(main())
