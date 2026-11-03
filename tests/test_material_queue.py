"""An ordinary three-file upload waits for the two bounded parser workers."""
from concurrent.futures import ThreadPoolExecutor
import json
import threading
import time
from types import SimpleNamespace

from app import material_files


def test_third_upload_waits_without_expanding_parser_concurrency(monkeypatch):
    slots=threading.BoundedSemaphore(2)
    monkeypatch.setattr(material_files,'PARSER_SLOTS',slots)
    ready=threading.Event();release=threading.Event();lock=threading.Lock()
    active=0;peak=0

    def parse(*args,input,**kwargs):
        nonlocal active,peak
        with lock:
            active+=1;peak=max(peak,active)
            if active==2:ready.set()
        try:
            assert release.wait(8)
            return SimpleNamespace(returncode=0,stdout=json.dumps({'sections':[{'text':input.decode(),'locator':'正文'}],'status':'ok','warning':''}).encode())
        finally:
            with lock:active-=1

    monkeypatch.setattr(material_files,'subprocess',SimpleNamespace(run=parse))
    with ThreadPoolExecutor(max_workers=3) as pool:
        first=[pool.submit(material_files.library_file,f'{i}.txt',str(i).encode())for i in range(2)]
        assert ready.wait(3)
        queued=pool.submit(material_files.library_file,'2.txt',b'2')
        try:
            # Longer than the former admission window. No parser process or
            # source is started for the queued third upload before a slot opens.
            time.sleep(2.2)
            assert not queued.done()
        finally:release.set()
        results=[future.result(timeout=5)for future in [*first,queued]]
    assert peak==2
    assert [value['full_sections'][0]['text']for value in results]==['0','1','2']
    assert [value['content']for value in results]==[b'0',b'1',b'2']
