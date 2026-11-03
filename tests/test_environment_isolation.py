"""Isolated checks must not import project env files or their credentials."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.parametrize('automatic',[False,True])
def test_automatic_environment_loading_can_be_disabled_without_breaking_local_launch(automatic):
    script='''
import json
from unittest.mock import patch
calls=[]
def values(path):calls.append('read');return {'MIMO_API_KEY':'xiaomi-file-fixture-only'}
def load(path):calls.append('load');return True
with patch('dotenv.dotenv_values',values),patch('dotenv.load_dotenv',load):
    from app.config import Settings
    key=Settings.from_env().ai_api_key
print(json.dumps({'calls':calls,'parent_preserved':key=='xiaomi-parent-fixture-only','file_applied':key=='xiaomi-file-fixture-only'}))
'''
    env=dict(os.environ,CAMPUS_AUTO_LOAD_ENV='1'if automatic else'0',APP_ENV='local',MIMO_API_KEY='xiaomi-parent-fixture-only')
    result=subprocess.run([sys.executable,'-c',script],cwd=Path(__file__).resolve().parent.parent,
                          env=env,capture_output=True,text=True,timeout=20)
    assert result.returncode==0,result.stderr
    assert json.loads(result.stdout)=={'calls':['read','load']if automatic else[],
                   'parent_preserved':not automatic,'file_applied':automatic}
