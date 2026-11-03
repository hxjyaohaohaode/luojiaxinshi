import io
from pathlib import Path
import subprocess
import zipfile

import pytest

from app import legacy_office
from app.documents import file_source
from scripts.install_legacy_parser import unpack

XHTML=b'''<html xmlns="http://www.w3.org/1999/xhtml"><body><p>Deadline 2027-11-06 17:00</p><table><tr><th>Name</th><th>Required</th></tr><tr><td>Form</td><td>Yes</td></tr></table><p>Contact office.</p><img src="embedded-image"/></body></html>'''


def test_legacy_table_rows_and_missing_image_remain_distinct_evidence():
    result=legacy_office.sections_from_xhtml(XHTML,10000)
    assert result['sections']==[
        {'locator':'第 1 段','text':'Deadline 2027-11-06 17:00'},
        {'locator':'第 1 表第 1 行','text':'Name | Required','table':True},
        {'locator':'第 1 表第 2 行','text':'Form | Yes','table':True},
        {'locator':'第 2 段','text':'Contact office.'}]
    assert result['status']=='review' and '图片' in result['warning'] and '行列' in result['warning']
    with pytest.raises(ValueError,match='未截断'):legacy_office.sections_from_xhtml(XHTML,5)


def test_legacy_invalid_bytes_do_not_launch_a_parser(monkeypatch):
    monkeypatch.setattr(legacy_office,'tools',lambda:pytest.fail('Do not launch a parser for invalid bytes'))
    with pytest.raises(ValueError,match='类型与内容不符'):legacy_office.extract(b'not an office file','doc')


def test_parser_receives_bytes_not_urls_or_application_secrets(monkeypatch,tmp_path):
    monkeypatch.setattr(legacy_office,'tools',lambda:('java',tmp_path/'tika.jar'))
    monkeypatch.setenv('AI_API_KEY','synthetic-private-value')
    monkeypatch.setenv('JAVA_TOOL_OPTIONS','-javaagent:untrusted')
    seen=[]
    def run(command,**kwargs):
        seen.append((command,kwargs))
        assert kwargs['input']==bytes.fromhex('D0CF11E0A1B11AE1')
        assert 'AI_API_KEY' not in kwargs['env'] and 'JAVA_TOOL_OPTIONS' not in kwargs['env']
        assert command[-1]=='-' and '--maxEmbeddedCount=0' in command
        assert '-XX:ActiveProcessorCount=2' in command and '-Xmx192m' in command
        assert kwargs['timeout']<legacy_office.WORKER_TIMEOUT_SECONDS<legacy_office.QUEUE_TIMEOUT_SECONDS
        kwargs['stdout'].write(XHTML)
        return subprocess.CompletedProcess(command,0)
    monkeypatch.setattr(legacy_office.subprocess,'run',run)
    assert legacy_office.extract(bytes.fromhex('D0CF11E0A1B11AE1'),'doc')['status']=='review'
    assert len(seen)==1


def test_parser_timeout_is_actionable_and_preserves_unknown(monkeypatch,tmp_path):
    monkeypatch.setattr(legacy_office,'tools',lambda:('java',tmp_path/'tika.jar'))
    def timeout(*args,**kwargs):raise subprocess.TimeoutExpired(args[0],15)
    monkeypatch.setattr(legacy_office.subprocess,'run',timeout)
    with pytest.raises(ValueError,match='解析超时'):legacy_office.extract(bytes.fromhex('D0CF11E0A1B11AE1'),'xls')


def test_installer_rejects_archive_path_escape_before_extracting_any_file(tmp_path):
    archive=tmp_path/'bad.zip'
    with zipfile.ZipFile(archive,'w')as package:
        package.writestr('safe.txt','safe');package.writestr('../outside.txt','unsafe')
    destination=tmp_path/'vendor'
    with pytest.raises(ValueError,match='Unsafe'):unpack(archive,destination)
    assert not (tmp_path/'outside.txt').exists() and not list(destination.iterdir())


def test_real_pinned_parser_reads_a_synthetic_rtf_doc_through_notice_worker():
    try:legacy_office.tools()
    except ValueError:pytest.skip('Optional pinned Tika/JRE not installed in this environment')
    result=file_source('application.doc',b'{\\rtf1\\ansi Synthetic application. \\par Deadline: 2027-11-06 17:00.}')
    assert result['status']=='ok',result['warning']
    assert [s['text']for s in result['sections']]==['Synthetic application.','Deadline: 2027-11-06 17:00.']
