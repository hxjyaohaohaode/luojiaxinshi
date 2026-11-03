"""The CI aggregation must keep failed, skipped and partially available results."""
from pathlib import Path
import xml.etree.ElementTree as ET

from scripts.audit_full_suite import combine_junit,run_shard


def test_combined_junit_keeps_every_case_and_its_real_outcome(tmp_path):
    first=tmp_path/'one.xml';second=tmp_path/'two.xml'
    first.write_text('<testsuites><testsuite tests="2" failures="1"><testcase name="ok"/><testcase name="bad"><failure message="rejected"/></testcase></testsuite></testsuites>')
    second.write_text('<testsuite tests="1" skipped="1"><testcase name="platform"><skipped/></testcase></testsuite>')
    output=tmp_path/'combined.xml'
    combine_junit([first,second],output)
    cases=list(ET.parse(output).getroot().iter('testcase'))
    assert [case.get('name')for case in cases]==['ok','bad','platform']
    assert cases[1].find('failure')is not None and cases[2].find('skipped')is not None


def test_missing_shard_is_not_fabricated_as_a_passing_test(tmp_path):
    output=tmp_path/'combined.xml';combine_junit([tmp_path/'missing.xml'],output)
    assert not list(ET.parse(output).getroot().iter('testcase'))


def test_timed_out_owned_shard_cannot_reuse_an_old_passing_report(tmp_path):
    slow=tmp_path/'test_owned_deadline.py'
    slow.write_text('import time\ndef test_delayed():\n    time.sleep(30)\n',encoding='utf8')
    old=tmp_path/'shard-1.xml'
    old.write_text('<testsuite tests="1"><testcase name="old-pass"/></testsuite>',encoding='utf8')
    value=run_shard(0,[str(slow)],tmp_path,1)
    assert value['timed_out'] and value['exit_code']==124
    assert not old.exists() or 'old-pass'not in old.read_text(encoding='utf8')
    assert 'exceeded its deadline' in (tmp_path/'shard-1.log').read_text(encoding='utf8')
