"""The CI aggregation must keep failed, skipped and partially available results."""
from pathlib import Path
import json
import xml.etree.ElementTree as ET
import pytest
import scripts.audit_full_suite as audit

from scripts.audit_full_suite import aggregate_partitions,combine_junit,run_shard


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


def partition_reports(tmp_path):
    files=['tests/test_alpha.py','tests/test_beta.py','tests/test_gamma.py']
    groups=[files[0::2],files[1::2]];manifests=[]
    for index,group in enumerate(groups,1):
        folder=tmp_path/str(index);folder.mkdir()
        manifest=folder/'manifest.json'
        manifest.write_text(json.dumps({'files':files,'count':len(files),'shards':groups,'selected_shards':[index]}))
        result={'shard':index,'exit_code':0,'files':len(group),'timed_out':False,
                'tests':len(group),'failures':0,'errors':0,'skipped':0}
        (folder/'summary.json').write_text(json.dumps({'scope':'partition','selected_shards':[index],
            'selected_complete':True,'complete':False,'shards':[result],'elapsed_seconds':1,
            'implementation_sha256':'frozen','implementation_unchanged':True}))
        suite=ET.Element('testsuite',tests=str(len(group)),failures='0',errors='0',skipped='0')
        for name in group:ET.SubElement(suite,'testcase',classname=name.removesuffix('.py').replace('/','.'),name='test_case')
        ET.ElementTree(suite).write(folder/f'shard-{index}.xml')
        manifests.append(manifest)
    return files,groups,manifests


def test_only_the_exact_complete_partition_union_can_claim_full_completion(tmp_path):
    files,groups,manifests=partition_reports(tmp_path)
    summary,reports=aggregate_partitions(manifests,files,groups,'frozen')
    assert summary['complete'] and summary['tests']==3 and summary['passed']==3
    assert summary['selected_shards']==[1,2] and not summary['aggregation_errors']
    output=tmp_path/'combined.xml';combine_junit(reports,output)
    assert len(list(ET.parse(output).getroot().iter('testcase')))==3


@pytest.mark.parametrize('fault',['missing','duplicate','different_code','inventory','fabricated_counts','wrong_case','missing_file_cases'])
def test_partition_aggregation_rejects_missing_duplicate_stale_or_fabricated_evidence(tmp_path,fault):
    files,groups,manifests=partition_reports(tmp_path)
    if fault=='missing':manifests=manifests[:1]
    elif fault=='duplicate':manifests=[manifests[0],manifests[0]]
    elif fault in {'different_code','fabricated_counts'}:
        path=manifests[1].parent/'summary.json';data=json.loads(path.read_text())
        if fault=='different_code':data['implementation_sha256']='other-code'
        else:data['shards'][0]['tests']+=1
        path.write_text(json.dumps(data))
    elif fault=='inventory':
        path=manifests[1];data=json.loads(path.read_text());data['files']=files[:-1];path.write_text(json.dumps(data))
    elif fault=='wrong_case':
        path=manifests[1].parent/'shard-2.xml';tree=ET.parse(path)
        next(tree.getroot().iter('testcase')).set('classname','tests.test_unassigned');tree.write(path)
    else:
        path=manifests[0].parent/'shard-1.xml';tree=ET.parse(path)
        tree.getroot().remove(list(tree.getroot())[0]);tree.write(path)
        path=manifests[0].parent/'summary.json';data=json.loads(path.read_text())
        data['shards'][0]['tests']-=1;path.write_text(json.dumps(data))
    summary,_=aggregate_partitions(manifests,files,groups,'frozen')
    assert not summary['complete'] and summary['aggregation_errors']


def test_a_real_failed_partition_is_kept_as_failure_in_the_full_union(tmp_path):
    files,groups,manifests=partition_reports(tmp_path)
    path=manifests[0].parent/'shard-1.xml';tree=ET.parse(path)
    ET.SubElement(next(tree.getroot().iter('testcase')),'failure',message='real rejection');tree.write(path)
    path=manifests[0].parent/'summary.json';data=json.loads(path.read_text())
    data['shards'][0].update(exit_code=1,failures=1);path.write_text(json.dumps(data))
    summary,reports=aggregate_partitions(manifests,files,groups,'frozen')
    assert summary['complete'] and summary['failures']==1 and summary['passed']==2
    assert any(result['exit_code']for result in summary['shards'])
    output=tmp_path/'combined.xml';combine_junit(reports,output)
    assert len(list(ET.parse(output).getroot().iter('failure')))==1


def test_partition_cli_runs_only_its_declared_files_without_claiming_full_completion(tmp_path,monkeypatch):
    root=tmp_path/'project';(root/'tests').mkdir(parents=True)
    for name in ('alpha','beta','gamma'):(root/'tests'/f'test_{name}.py').write_text('# synthetic inventory')
    monkeypatch.setattr(audit,'ROOT',root);monkeypatch.setattr(audit,'fingerprint',lambda:'frozen')
    seen=[]
    def run(index,group,out,timeout):
        seen.append((index,group));suite=ET.Element('testsuite',tests='1',failures='0',errors='0',skipped='0')
        ET.SubElement(suite,'testcase',classname='tests.test_beta',name='selected')
        ET.ElementTree(suite).write(out/'shard-2.xml')
        return {'shard':index+1,'files':len(group),'tests':1,'failures':0,'errors':0,'skipped':0,'exit_code':0,'timed_out':False}
    monkeypatch.setattr(audit,'run_shard',run)
    monkeypatch.setattr(audit.sys,'argv',['audit','--workers','2','--only-shard','2','--output','out'])
    assert audit.main()==0 and seen==[(1,['tests/test_beta.py'])]
    summary=json.loads((root/'out/summary.json').read_text())
    assert summary['selected_complete'] and not summary['complete'] and summary['scope']=='partition'


def test_merge_cli_replaces_an_old_full_report_when_a_partition_is_missing(tmp_path,monkeypatch):
    root=tmp_path/'project';(root/'tests').mkdir(parents=True)
    for name in ('alpha','beta','gamma'):(root/'tests'/f'test_{name}.py').write_text('# synthetic inventory')
    inputs=root/'inputs';inputs.mkdir();files,groups,manifests=partition_reports(inputs)
    monkeypatch.setattr(audit,'ROOT',root);monkeypatch.setattr(audit,'fingerprint',lambda:'frozen')
    combined=root/'combined.xml'
    monkeypatch.setattr(audit.sys,'argv',['audit','--workers','2','--merge-partitions',str(inputs),'--output','out','--junitxml',str(combined)])
    assert audit.main()==0
    assert len(list(ET.parse(combined).getroot().iter('testcase')))==3
    # Even a forged zero process exit cannot turn a real JUnit failure green.
    path=manifests[0].parent/'shard-1.xml';tree=ET.parse(path)
    ET.SubElement(next(tree.getroot().iter('testcase')),'failure',message='must remain a failure');tree.write(path)
    path=manifests[0].parent/'summary.json';data=json.loads(path.read_text())
    data['shards'][0].update(failures=1,exit_code=0);path.write_text(json.dumps(data))
    assert audit.main()==1 and len(list(ET.parse(combined).getroot().iter('failure')))==1
    (manifests[1].parent/'summary.json').unlink()
    assert audit.main()==1
    assert not json.loads((root/'out/summary.json').read_text())['complete']
    assert len(list(ET.parse(combined).getroot().iter('testcase')))==2


def test_ambient_pytest_filter_cannot_omit_cases_from_an_assigned_file(tmp_path,monkeypatch):
    # Match the real coordinator: assigned files belong to its own project.
    # A foreign absolute path makes pytest traverse shared temporary ancestors.
    monkeypatch.setattr(audit,'ROOT',tmp_path)
    file=tmp_path/'test_filter_guard.py'
    file.write_text('def test_keep():\n    assert True\n\ndef test_must_also_run():\n    assert False\n',encoding='utf8')
    monkeypatch.setenv('PYTEST_ADDOPTS','-k test_keep')
    result=run_shard(0,[str(file)],tmp_path,30)
    assert result['exit_code']==1 and result['tests']==2 and result['failures']==1


@pytest.mark.parametrize('report,counts', [
    ({'checks':[{'ok':True},{'ok':False}],'errors':[]}, [2,1,0,0]),
    ({'passed':False,'checks':['completed first step'],'errors':[],'error':'real assertion'}, [1,1,0,0]),
    ({'passed':False,'checks':[{'passed':False}],'errors':[]}, [1,1,0,0]),
    ({'passed':False,'checks':['completed first step'],'errors':['uncaught page error']}, [1,0,1,0]),
    ({'passed':True,'checks':['one','two'],'errors':[]}, [2,0,0,0]),
])
def test_browser_summary_preserves_heterogeneous_failure_evidence_once(report,counts):
    from scripts.write_ci_summary import browser_counts
    assert browser_counts(report)==counts


def test_browser_summary_lists_new_suite_once_and_never_reports_missing_evidence_as_zero_passes(tmp_path,monkeypatch):
    import scripts.write_ci_summary as summary
    import sys
    path=tmp_path/'artifacts/sprint-ui-browser/report.json';path.parent.mkdir(parents=True)
    path.write_text(json.dumps({'checks':[{'ok':True},{'ok':False}],'errors':[]}),encoding='utf8')
    monkeypatch.setattr(summary,'ROOT',tmp_path)
    monkeypatch.setattr(sys,'argv',['summary','--kind','browser'])
    monkeypatch.delenv('GITHUB_STEP_SUMMARY',raising=False)
    summary.main()
    rendered=(tmp_path/'artifacts/ci/summary.md').read_text(encoding='utf8')
    assert rendered.count('| Sprint workflows and loading performance |')==1
    assert '| Sprint workflows and loading performance | 2 | 1 | 0 | 0 |' in rendered
    assert '| Browser stability | report unavailable | - | - | - |' in rendered
