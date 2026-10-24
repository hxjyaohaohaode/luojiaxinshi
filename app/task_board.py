"""Atomic personal board moves; existing completion gates remain authoritative."""
import time
from typing import Literal

from fastapi import Depends, HTTPException
from pydantic import Field

from .db import audit, dumps
from .models import Strict, TaskData, TaskUpdate


class BoardMove(Strict):
    task_version: int = Field(ge=1)
    workflow_version: int = Field(ge=0)
    lane: Literal['action', 'followup', 'closed']
    before_id: str | None = Field(default=None,min_length=1,max_length=40)
    after_id: str | None = Field(default=None,min_length=1,max_length=40)
    automatic: bool = False
    allow_missing_anchor: bool = Field(default=False,strict=True)


def lane_for(task, automatic=False):
    if task['status'] != 'pending' or task.get('action_excluded'):
        return 'closed'
    data=task['workflow']['data']
    if not automatic and data.get('board_lane'):
        return data['board_lane']
    return 'followup' if task.get('followup_due') or data['stage'] in {'submitted','supplement','blocked','waiting'} else 'action'


def ordered(tasks):
    # Python's stable sort preserves the default deadline order for untouched cards.
    return sorted(tasks,key=lambda task:(task['workflow']['data'].get('board_order') is None,
                                         task['workflow']['data'].get('board_order') or 0))


def install(app,db,user,list_tasks,update_task_record):
    @app.post('/api/tasks/{tid}/move')
    def move(tid:str,payload:BoardMove,current=Depends(user)):
        with db.connect(write=True) as conn:
            tasks=list_tasks(conn,current['id'])
            by_id={task['id']:task for task in tasks}
            task=by_id.get(tid)
            if task is None:
                raise HTTPException(404,'这项待办不存在')
            if task['version']!=payload.task_version or task['workflow']['version']!=payload.workflow_version:
                raise HTTPException(409,'这项待办刚有更新，已恢复最新位置，请重试')
            if payload.before_id and payload.after_id:
                raise HTTPException(422,'一次移动只能选择一个相邻位置')
            source_lane=lane_for(task)
            source=ordered([t for t in tasks if lane_for(t)==source_lane])
            index=next(i for i,t in enumerate(source) if t['id']==tid)
            undo={'lane':source_lane,'automatic':task['workflow']['data'].get('board_lane') is None,'allow_missing_anchor':True,
                  'before_id':source[index+1]['id'] if index+1<len(source) else None,
                  'after_id':source[index-1]['id'] if index and index+1==len(source) else None}
            anchor_id=payload.before_id or payload.after_id
            if anchor_id:
                anchor=by_id.get(anchor_id)
                if anchor_id==tid:
                    raise HTTPException(422,'不能把卡片放到自身之前，请重新选择位置')
                if anchor is None and not payload.allow_missing_anchor:
                    raise HTTPException(404,'目标位置不存在，请刷新后重试')
                if anchor is not None and lane_for(anchor)!=payload.lane and not payload.allow_missing_anchor:
                    raise HTTPException(409,'目标卡片已经移动，已恢复最新位置，请重试')
                if anchor is None or lane_for(anchor)!=payload.lane:
                    anchor_id=None
            if payload.lane!='closed' and (task['status']=='cancelled' or task.get('action_excluded')):
                raise HTTPException(422,'这项待办已取消或选择不参加，请先在办理记录中恢复')
            status='done' if payload.lane=='closed' and source_lane!='closed' else 'pending' if payload.lane!='closed' else task['status']
            if status!=task['status']:
                task=update_task_record(conn,current['id'],tid,TaskUpdate(
                    version=task['version'],data=TaskData.model_validate(task['data']),status=status,
                    reason='本人通过看板调整完成状态'))
            destination=ordered([t for t in tasks if t['id']!=tid and lane_for(t)==payload.lane])
            insert=next((i for i,t in enumerate(destination) if t['id']==anchor_id),len(destination))
            if payload.after_id and anchor_id: insert+=1
            destination.insert(insert,task)
            now=int(time.time())
            for rank,item in enumerate(destination):
                data=dict(item['workflow']['data'])
                if item['id']==tid and payload.lane!='closed':
                    data['board_lane']=None if payload.automatic and lane_for(item,automatic=True)==payload.lane else payload.lane
                elif item['id']==tid and payload.automatic:
                    data['board_lane']=None
                data['board_order']=rank
                if data==item['workflow']['data']: continue
                conn.execute('INSERT INTO task_workflows VALUES(?,?,?,?) ON CONFLICT(task_id) DO UPDATE SET data=excluded.data,version=excluded.version,updated_at=excluded.updated_at',
                             (item['id'],dumps(data),item['workflow']['version']+1,now))
            audit(conn,current['id'],task['notice_id'],'board_move',task_id=tid,
                  before={'lane':source_lane,'position':index+1},
                  after={'lane':payload.lane,'position':insert+1,'reason':'调整了看板顺序与个人进度'})
            result=list_tasks(conn,current['id'])
            updated=next(t for t in result if t['id']==tid)
            undo.update(task_version=updated['version'],workflow_version=updated['workflow']['version'])
            return {'tasks':result,'undo':undo}
