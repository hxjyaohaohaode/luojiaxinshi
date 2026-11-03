"""View the isolated real-model fixture; no real users or messaging channels."""
from dataclasses import replace
from pathlib import Path
import argparse
import sys

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from app.config import Settings
from app.main import create_app
import uvicorn


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir',type=Path,required=True)
    args=parser.parse_args();directory=args.data_dir.resolve()
    if not directory.is_relative_to((ROOT/'artifacts').resolve()) or directory==(ROOT/'artifacts').resolve():
        parser.error('Only an isolated data directory under artifacts is allowed')
    if not (directory/'campus.sqlite3').is_file():parser.error('Prepare the isolated fixture first')
    settings=replace(Settings.from_env(),data_dir=directory,origin='http://localhost:18785',production=False,
        agent_enabled=False,aliyun_access_key_id='',aliyun_access_key_secret='',smtp_username='',smtp_authorization_code='',
        mail_sender='')
    app=create_app(settings)
    print('Isolated engineering account; actual model enabled; external SMS/email disabled.',flush=True)
    uvicorn.run(app,host='127.0.0.1',port=18785,access_log=False)


if __name__=='__main__':main()
