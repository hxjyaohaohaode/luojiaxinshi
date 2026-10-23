import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent/'scripts'))
from export_verification_evidence import browser_cases, junit_cases
import run_browser_checks
import sqlite3


def test_browser_suite_limit_reset_is_confined_to_the_owned_synthetic_database(tmp_path,monkeypatch):
    monkeypatch.setattr(run_browser_checks,'ROOT',tmp_path)
    monkeypatch.setattr(run_browser_checks,'OUT',tmp_path/'artifacts/ci-browser')
    data=tmp_path/'artifacts/ci-browser/fixture-test';data.mkdir(parents=True)
    with sqlite3.connect(data/'campus.sqlite3') as connection:
        connection.execute('CREATE TABLE limits (key TEXT)')
        connection.execute("INSERT INTO limits VALUES ('synthetic-login')")
    with pytest.raises(ValueError,match='owned synthetic'):
        run_browser_checks.reset_fixture_limits(tmp_path/'data')
    run_browser_checks.reset_fixture_limits(data)
    with sqlite3.connect(data/'campus.sqlite3') as connection:
        assert connection.execute('SELECT COUNT(*) FROM limits').fetchone()[0]==0


def test_public_browser_snapshot_rejects_private_or_failed_runs(tmp_path):
    path=tmp_path/'report.json'
    value={'fixture':'real account', 'checks':[{'engine':'chromium','name':'case','ok':True}], 'errors':[]}
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError,match='synthetic'):browser_cases(path)
    value['fixture']='synthetic fixture';value['checks'][0]['ok']=False;path.write_text(json.dumps(value))
    with pytest.raises(ValueError,match='passing'):browser_cases(path)


def test_public_results_strip_captured_output_properties_and_extra_fields(tmp_path):
    browser=tmp_path/'browser.json'
    browser.write_text(json.dumps({'fixture':'synthetic fixture','checks':[{'engine':'chromium','name':'case','ok':True,'private':'secret-not-for-export'}],'errors':[],'cookies':'secret-not-for-export'}))
    assert 'secret-not-for-export' not in json.dumps(browser_cases(browser))
    junit=tmp_path/'junit.xml'
    junit.write_text('<testsuites><testsuite hostname="private-host"><properties><property name="token" value="secret-not-for-export"/></properties><testcase classname="test_module" name="case" time="0.01"><system-out>secret-not-for-export</system-out></testcase></testsuite></testsuites>')
    report=junit_cases(junit)
    assert report['tests']==1 and report['cases'][0]['passed'] is True
    assert 'secret-not-for-export' not in json.dumps(report) and 'private-host' not in json.dumps(report)
    junit.write_text('<testsuite><testcase name="case"><failure>fixture failure</failure></testcase></testsuite>')
    with pytest.raises(ValueError,match='failed'):junit_cases(junit)
