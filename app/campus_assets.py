"""Immutable publication originals, reached only through an owned source.

Recipient source rows retain independent evidence/processing state. Their binary
original is stored once with the publication version, never once per student.
Every HTTP caller must authorize the parent notice before using this helper.
"""
import hashlib
import json

from fastapi import HTTPException


SCHEMA = """
CREATE TABLE IF NOT EXISTS campus_material_refs(
 source_id TEXT PRIMARY KEY REFERENCES sources(id) ON DELETE CASCADE,
 publication_id TEXT NOT NULL, version INTEGER NOT NULL, position INTEGER NOT NULL,
 FOREIGN KEY(publication_id,version,position)
 REFERENCES campus_materials(publication_id,version,position) ON DELETE RESTRICT);
CREATE INDEX IF NOT EXISTS campus_material_refs_original
 ON campus_material_refs(publication_id,version,position);
"""


def hydrate_source(conn, source):
    """Resolve existing references without granting access to another notice."""
    if source is None:
        return None
    result = dict(source)
    if result.get('content') is not None or not result.get('id'):
        return result
    original = conn.execute("""SELECT m.content,m.sha256,m.kind FROM campus_material_refs r
        JOIN campus_materials m ON m.publication_id=r.publication_id
          AND m.version=r.version AND m.position=r.position
        JOIN sources s ON s.id=r.source_id
        WHERE r.source_id=? AND s.sha256=m.sha256 AND s.kind=m.kind""", (result['id'],)).fetchone()
    if original is not None:
        if (result.get('sha256', original['sha256']) != original['sha256'] or
                hashlib.sha256(original['content']).hexdigest() != original['sha256']):
            raise HTTPException(409, '共享原件校验未通过，请联系发布者核对；未返回其他版本')
        result['content'] = original['content']
        result['shared_original'] = True
    return result


def shared_storage_bytes(conn, uid):
    """Logical account usage stays stable when physical storage is shared."""
    return conn.execute("""SELECT COALESCE(SUM(length(m.content)),0)
        FROM campus_material_refs r JOIN sources s ON s.id=r.source_id
        JOIN notices n ON n.id=s.notice_id
        JOIN campus_materials m ON m.publication_id=r.publication_id
          AND m.version=r.version AND m.position=r.position
        WHERE n.user_id=? AND s.content IS NULL""", (uid,)).fetchone()[0]


def check_publication_storage(conn,uid,extra,*,replace_draft=None):
    """Charge immutable versions to their actual author, including corrections.

    A college manager may correct another publisher's notice. Charging by the
    publication's first author would let those manager-written versions escape
    the manager's bound while also consuming the first author's capacity.
    """
    from .usage_limits import limits_for
    published=conn.execute('''SELECT COALESCE(SUM(length(m.content)),0) FROM campus_materials m
        JOIN campus_publication_versions v ON v.publication_id=m.publication_id
          AND v.version=m.version WHERE v.actor_id=?''',(uid,)).fetchone()[0]
    drafts=conn.execute('''SELECT COALESCE(SUM(length(content)),0) FROM campus_draft_files
        WHERE user_id=? AND (? IS NULL OR draft_id<>?)''',(uid,replace_draft,replace_draft)).fetchone()[0]
    if published+drafts+extra>limits_for(conn).storage_bytes:
        raise HTTPException(413,'本人发布原件与草稿已达到当前存储容量，请整理草稿或由管理员调整容量；未重复分发')


def bind_material_refs(conn, notice_id, publication_id, version):
    """Bind only exact immutable originals inserted into this owned receipt."""
    from .db import audit
    grouped={}
    for material in conn.execute('SELECT position,name,kind,sha256 FROM campus_materials WHERE publication_id=? AND version=? ORDER BY position',
                                 (publication_id,version)).fetchall():
        grouped.setdefault((material['kind'],material['sha256']),[]).append(material)
    for materials in grouped.values():
        material=materials[0]
        source = conn.execute('SELECT id,name,warning FROM sources WHERE notice_id=? AND kind=? AND sha256=? AND active=1',
                              (notice_id, material['kind'], material['sha256'])).fetchone()
        if source is None:
            raise HTTPException(409, '附件接收记录不完整，可重试本人的分发')
        conn.execute('INSERT OR IGNORE INTO campus_material_refs VALUES(?,?,?,?)',
                     (source['id'], publication_id, version, material['position']))
        names=list(dict.fromkeys(item['name'] for item in materials))
        if source['name'] not in names:
            # Content de-duplication deliberately preserves source IDs and all
            # task citations. An official filename correction still has to be
            # visible, without mutating the immutable historical material.
            uid=conn.execute('SELECT user_id FROM notices WHERE id=?',(notice_id,)).fetchone()[0]
            previous=conn.execute('SELECT delivered_version FROM campus_deliveries WHERE notice_id=? AND publication_id=?',
                                  (notice_id,publication_id)).fetchone()
            last_change=conn.execute("""SELECT after_json FROM audit WHERE notice_id=?
                AND action='campus_attachment_renamed' AND json_extract(after_json,'$.source_id')=?
                ORDER BY id DESC LIMIT 1""",(notice_id,source['id'])).fetchone()
            prior_note=json.loads(last_change['after_json']).get('rename_warning','') if last_change else ''
            base_warning=source['warning']
            if prior_note and base_warning.endswith(prior_note):base_warning=base_warning[:-len(prior_note)].rstrip('\n')
            rename_note=f'发布方第{version}版将“{source["name"]}”改名为“{names[0]}”；原件内容一致，旧名称保留在办理历史。'
            warning=(base_warning+'\n' if base_warning else '')+rename_note
            conn.execute('UPDATE sources SET name=?,warning=? WHERE id=?',(names[0],warning,source['id']))
            audit(conn,uid,notice_id,'campus_attachment_renamed',
                  before={'source_id':source['id'],'name':source['name'],'sha256':material['sha256'],
                          'publication_version':previous['delivered_version'] if previous else None},
                  after={'source_id':source['id'],'name':names[0],'names':names,'sha256':material['sha256'],
                         'publication_id':publication_id,'publication_version':version,'rename_warning':rename_note})

