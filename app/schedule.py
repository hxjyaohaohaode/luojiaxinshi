"""Owner-scoped personal arrangements. Notification deadlines remain separate."""
from .usage_limits import check_count, check_storage, limits_for
from datetime import date, datetime, time, timedelta, timezone
import json
import time as clock
from typing import Literal

from fastapi import Depends, HTTPException, Response, Path as ApiPath
from icalendar import Calendar, Event
from pydantic import Field, field_validator, model_validator

from .db import dumps, ident
from .models import Strict, Version

CST = timezone(timedelta(hours=8))


class Arrangement(Strict):
    title: str = Field(min_length=1, max_length=160)
    category: Literal['course', 'activity', 'personal'] = 'personal'
    start_date: str
    end_date: str
    start_time: str | None = None
    end_time: str | None = None
    repeat: Literal['none', 'weekly', 'biweekly'] = 'none'
    repeat_until: str | None = None
    location: str = Field(default='', max_length=300)
    notes: str = Field(default='', max_length=3000)

    @field_validator('start_date', 'end_date', 'repeat_until')
    @classmethod
    def dates(cls, value):
        if value is not None:
            parsed = date.fromisoformat(value)
            if len(value) != 10 or parsed.isoformat() != value or not 2000 <= parsed.year <= 2100:
                raise ValueError('日期须在 2000 至 2100 年之间，格式为 YYYY-MM-DD')
        return value

    @field_validator('start_time', 'end_time')
    @classmethod
    def times(cls, value):
        if value is not None and (len(value) != 5 or time.fromisoformat(value).strftime('%H:%M') != value):
            raise ValueError('时刻须为 HH:MM')
        return value

    @model_validator(mode='after')
    def coherent(self):
        span = (date.fromisoformat(self.end_date) - date.fromisoformat(self.start_date)).days
        if not 0 <= span <= 30:
            raise ValueError('结束日期不能早于开始日期，单次安排最多跨 31 天')
        if (self.start_time is None) != (self.end_time is None):
            raise ValueError('开始和结束时刻须一起填写，或一起留空作为全天安排')
        if self.start_time is not None and span == 0 and self.end_time <= self.start_time:
            raise ValueError('结束时刻须晚于开始时刻')
        if self.repeat == 'none' and self.repeat_until is not None:
            raise ValueError('不重复的安排不需要重复截止日期')
        if self.repeat != 'none':
            if span != 0 or not self.repeat_until:
                raise ValueError('重复安排须在同一天内，并指定最后重复日期')
            days = (date.fromisoformat(self.repeat_until) - date.fromisoformat(self.start_date)).days
            if not 0 <= days <= 366:
                raise ValueError('重复截止须在开始日期之后的一年内')
        return self


class CreateArrangement(Strict):
    data: Arrangement
    request_id: str = Field(min_length=16, max_length=80, pattern=r'^[a-zA-Z0-9_-]+$')


class UpdateArrangement(Version):
    data: Arrangement


class ExportArrangements(Strict):
    ids: list[str] = Field(min_length=1, max_length=1000)
    versions: dict[str, int]


def serialize(row):
    result = dict(row)
    result.pop('request_id', None)
    result.pop('user_id', None)
    result['data'] = json.loads(result['data'])
    return result


def own(conn, eid, uid, version=None):
    row = conn.execute('SELECT * FROM arrangements WHERE id=? AND user_id=?', (eid, uid)).fetchone()
    if row is None:
        raise HTTPException(404, '安排不存在或无权访问')
    if version is not None and version != row['version']:
        raise HTTPException(409, '这项安排已在其他页面修改，请刷新后重新核对')
    return row


def calendar_bytes(records):
    calendar = Calendar()
    calendar.add('prodid', '-//Campus Personal Arrangements//CN')
    calendar.add('version', '2.0')
    calendar.add('calscale', 'GREGORIAN')
    calendar.add('x-wr-calname', '我的校园安排')
    for item in records:
        data = item['data']
        event = Event()
        event.add('uid', item['id'] + '@campus-arrangement.local')
        event.add('sequence', item['version'])
        event.add('dtstamp', datetime.now(timezone.utc))
        event.add('last-modified', datetime.fromtimestamp(item['updated_at'], timezone.utc))
        event.add('summary', data['title'])
        event.add('location', data['location'])
        event.add('description', data['notes'] + '\n个人安排；导出后改期或取消，请同步修改外部日历。')
        event.add('status', 'CONFIRMED')
        start = date.fromisoformat(data['start_date'])
        end = date.fromisoformat(data['end_date']) + timedelta(days=1)
        if data['start_time']:
            start = datetime.combine(start, time.fromisoformat(data['start_time']), CST).astimezone(timezone.utc)
            end = datetime.combine(date.fromisoformat(data['end_date']), time.fromisoformat(data['end_time']), CST).astimezone(timezone.utc)
        event.add('dtstart', start)
        event.add('dtend', end)
        if data['repeat'] != 'none':
            until = date.fromisoformat(data['repeat_until'])
            if data['start_time']:
                until = datetime.combine(until, time(23, 59, 59), CST).astimezone(timezone.utc)
            event.add('rrule', {'freq': 'weekly', 'interval': 2 if data['repeat'] == 'biweekly' else 1, 'until': until})
        calendar.add_component(event)
    return calendar.to_ical()


def create_arrangement(conn,uid,payload):
    prior = conn.execute('SELECT * FROM arrangements WHERE user_id=? AND request_id=?', (uid, payload.request_id)).fetchone()
    if prior:
        if json.loads(prior['data']) != payload.data.model_dump():
            raise HTTPException(409, '这项安排已经保存，但内容与当前草稿不同。请先在日历中打开已保存安排核对，再继续修改；当前草稿已保留。')
        return serialize(prior)
    if conn.execute('SELECT 1 FROM arrangement_receipts WHERE user_id=? AND request_id=?', (uid,payload.request_id)).fetchone():
        raise HTTPException(409, '这项安排曾经保存，随后已删除。请先核对保存状态；需要另建时使用新的草稿。')
    check_count(conn,uid,'arrangements','arrangements','个人安排')
    eid, now = ident(), int(clock.time())
    conn.execute('INSERT INTO arrangements(id,user_id,request_id,data,created_at,updated_at) VALUES(?,?,?,?,?,?)', (eid, uid, payload.request_id, dumps(payload.data.model_dump()), now, now))
    return serialize(own(conn, eid, uid))


def update_arrangement(conn,uid,eid,payload):
    own(conn, eid, uid, payload.version)
    conn.execute('UPDATE arrangements SET data=?,version=version+1,updated_at=? WHERE id=?', (dumps(payload.data.model_dump()), int(clock.time()), eid))
    return serialize(own(conn, eid, uid))


def delete_arrangement(conn,uid,eid,payload):
    own(conn, eid, uid, payload.version)
    conn.execute('DELETE FROM arrangements WHERE id=?', (eid,))
    conn.execute('DELETE FROM edit_caches WHERE user_id=? AND cache_key LIKE ?', (uid, 'arrangement:'+eid+':%'))
    return {'ok': True}


def install_schedule(app, db, user):
    @app.get('/api/arrangements')
    def listing(current=Depends(user)):
        with db.connect() as conn:
            return [serialize(r) for r in conn.execute('SELECT * FROM arrangements WHERE user_id=? ORDER BY created_at,id', (current['id'],))]

    @app.get('/api/arrangements/requests/{request_id}')
    def request_status(request_id: str = ApiPath(min_length=16, max_length=80, pattern=r'^[a-zA-Z0-9_-]+$'), current=Depends(user)):
        with db.connect() as conn:
            receipt=conn.execute('SELECT arrangement_id FROM arrangement_receipts WHERE user_id=? AND request_id=?', (current['id'],request_id)).fetchone()
            if not receipt:
                return {'state':'missing','arrangement':None}
            record=conn.execute('SELECT * FROM arrangements WHERE id=? AND user_id=?', (receipt['arrangement_id'],current['id'])).fetchone()
            return {'state':'saved' if record else 'deleted','arrangement':serialize(record) if record else None}

    @app.post('/api/arrangements')
    def create(payload: CreateArrangement, current=Depends(user)):
        with db.connect(write=True) as conn:
            return create_arrangement(conn,current['id'],payload)

    @app.put('/api/arrangements/{eid}')
    def update(eid: str, payload: UpdateArrangement, current=Depends(user)):
        with db.connect(write=True) as conn:
            return update_arrangement(conn,current['id'],eid,payload)

    @app.delete('/api/arrangements/{eid}')
    def delete(eid: str, payload: Version, current=Depends(user)):
        with db.connect(write=True) as conn:
            return delete_arrangement(conn,current['id'],eid,payload)

    @app.post('/api/arrangements/export')
    def export(payload: ExportArrangements, current=Depends(user)):
        with db.connect() as conn:
            records = []
            for eid in dict.fromkeys(payload.ids):
                if eid not in payload.versions:
                    raise HTTPException(422, '请刷新安排后再导出')
                records.append(serialize(own(conn, eid, current['id'], payload.versions[eid])))
            content = calendar_bytes(records)
        return Response(content, media_type='text/calendar', headers={'Content-Disposition': 'attachment; filename="campus-arrangements.ics"'})
