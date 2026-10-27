"""Durable, explicitly unverified stream checkpoints; never publication evidence."""
from copy import deepcopy
import json
import time

from .ai import AIError
from .db import dumps


class PreviewCheckpoint:
    def __init__(self, limit):
        self.limit = limit
        self.text, self.ui, self.revision, self.sequence = '', None, 0, 0

    def reset(self, clear_ui=False):
        self.text = ''
        if clear_ui: self.ui = None
        self.revision += 1

    def apply(self, kind, event):
        if kind == 'preview':
            if event.get('reset'): self.reset(event.get('clear_ui',False))
            self.text += event['text']
        elif kind == 'ui_preview':
            patch = event['content']
            if self.ui is None or patch.get('reset'):
                self.ui = {'renderer':'open_generative_ui', 'css':'', 'html':[],
                           'jsFunctions':'', 'jsExpressions':[], 'generating':True}
            ui = self.ui
            ui['css'] += patch.get('css', '')
            for item in patch.get('html', []):
                index = item['index']
                if not isinstance(index, int) or not 0 <= index < 100: raise AIError('界面预览片段无效。')
                while len(ui['html']) <= index: ui['html'].append('')
                ui['html'][index] += item['text']
            if 'jsFunctions' in patch: ui['jsFunctions'] = patch['jsFunctions']
            for item in patch.get('jsExpressions', []):
                index = item['index']
                if not isinstance(index, int) or not 0 <= index < 40: raise AIError('界面初始化片段无效。')
                while len(ui['jsExpressions']) <= index: ui['jsExpressions'].append('')
                ui['jsExpressions'][index] = item['text']
            for key in ('title','initialHeight','cssComplete','htmlComplete','jsFunctionsComplete',
                        'jsExpressionsComplete','localReady'):
                if key in patch: ui[key] = deepcopy(patch[key])
        if len(self.text.encode()) > self.limit or len(dumps(self.ui).encode()) > 150000:
            raise AIError('回复预览已达大小上限，已保留先前收到的部分。')
        self.sequence += 1

    def save(self, conn, mid):
        conn.execute('''INSERT INTO reply_previews VALUES(?,?,?,?,?,?)
            ON CONFLICT(message_id) DO UPDATE SET text=excluded.text,ui=excluded.ui,
            revision=excluded.revision,sequence=excluded.sequence,updated_at=excluded.updated_at''',
            (mid, self.text, dumps(self.ui), self.revision, self.sequence, time.time()))


def load(conn, item):
    if item.get('status') == 'complete': return item
    row = conn.execute('SELECT * FROM reply_previews WHERE message_id=?', (item['id'],)).fetchone()
    if row:
        ui = json.loads(row['ui'])
        # A failed/cancelled draft is readable but its authored code stays inert.
        if ui and item['status'] != 'processing': ui['localReady'] = False
        item['preview'] = {'text':row['text'], 'ui':ui, 'revision':row['revision'],
                           'sequence':row['sequence'], 'updated_at':row['updated_at']}
    return item
