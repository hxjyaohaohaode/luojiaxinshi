"""Explicit synthetic rule samples for tests arranging an enabled subscription.

The context ends before the behavior under test. It never bypasses validation
in product code or mocks the subscription/apply endpoints themselves.
"""
from contextlib import contextmanager
from unittest.mock import patch
from urllib.parse import urlsplit

from app import source_sync
from app.documents import text_source


@contextmanager
def successful_rule_trial():
    async def index(config):
        value=urlsplit(config['url'])
        host=(config.get('allowed_article_origins') or [value.scheme+'://'+value.netloc])[0]
        return source_sync.IndexEntries([{'url':host+'/info/fixture-rule-sample.htm',
            'title':'合成来源规则样本','published_at':None}])
    async def read(url):
        source=text_source('合成规则试读正文，测试准备阶段不接收通知。')
        source['origin']={'url':url,'title':'合成来源规则样本','attachments':[],'warnings':[]}
        return source,'合成来源规则样本'
    with patch.object(source_sync,'fetch_index',index),patch.object(source_sync,'read_link',read):
        yield
