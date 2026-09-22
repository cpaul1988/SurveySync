from __future__ import annotations

import hashlib
import mimetypes
import re
import shutil
from pathlib import Path
from uuid import uuid4

from .audit import utc_now
from .project import SurveyProject, safe_name

IMAGE_EXTENSIONS={'.jpg','.jpeg','.png','.webp','.tif','.tiff','.heic','.bmp'}


def sha256_file(path: Path) -> str:
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()


def attach_file(project: SurveyProject, path: Path, *, module: str, object_type: str, object_id: str, caption: str='', metadata: dict|None=None) -> dict:
    src=Path(path).expanduser().resolve()
    if not src.is_file():raise FileNotFoundError(src)
    attachment_id=uuid4().hex
    digest=sha256_file(src)
    folder=project.paths.attachments/safe_name(module)/safe_name(object_type)/safe_name(object_id)
    folder.mkdir(parents=True,exist_ok=True)
    dest=folder/src.name
    if dest.exists() and sha256_file(dest)!=digest:
        dest=folder/f'{src.stem}_{digest[:8]}{src.suffix}'
    if not dest.exists():shutil.copy2(src,dest)
    rel=str(dest.relative_to(project.paths.root))
    import json
    with project.db.connect() as conn:
        conn.execute('INSERT INTO attachments(attachment_id,ts_utc,module,object_type,object_id,source_path,stored_path,sha256,media_type,caption,metadata_json) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                     (attachment_id,utc_now(),module,object_type,object_id,str(src),rel,digest,mimetypes.guess_type(src.name)[0] or '',caption,json.dumps(metadata or {},sort_keys=True)))
    project.db.audit(module,'ATTACHMENT_ADDED',object_type=object_type,object_id=object_id,details={'attachment_id':attachment_id,'filename':src.name,'sha256':digest,'caption':caption})
    return {'attachment_id':attachment_id,'filename':src.name,'stored_path':str(dest),'sha256':digest,'media_type':mimetypes.guess_type(src.name)[0] or '', 'caption':caption, 'metadata':metadata or {}}


def list_attachments(project: SurveyProject, *, object_type: str|None=None, object_id: str|None=None) -> list[dict]:
    import json
    sql='SELECT * FROM attachments';params=[];where=[]
    if object_type:where.append('object_type=?');params.append(object_type)
    if object_id:where.append('object_id=?');params.append(object_id)
    if where:sql+=' WHERE '+' AND '.join(where)
    sql+=' ORDER BY ts_utc DESC'
    with project.db.connect() as conn:rows=conn.execute(sql,tuple(params)).fetchall()
    out=[]
    for row in rows:
        d=dict(row);d['metadata']=json.loads(d.pop('metadata_json') or '{}');d['absolute_path']=str(project.paths.root/d['stored_path']);out.append(d)
    return out


def point_id_tokens(filename: str) -> set[str]:
    stem=Path(filename).stem
    return set(re.findall(r'(?<!\d)(\d{1,12})(?!\d)',stem))


def auto_attach_photos(project: SurveyProject, folder: Path, point_ids: list[str], *, module: str='UtilitySync', object_type: str='utility_structure') -> dict:
    root=Path(folder).expanduser().resolve()
    if not root.is_dir():raise ValueError('Photo folder was not found.')
    valid={str(x).strip() for x in point_ids if str(x).strip()}
    matched=[];unmatched=[];ambiguous=[]
    for path in sorted(p for p in root.rglob('*') if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS):
        hits=sorted(point_id_tokens(path.name)&valid)
        if len(hits)==1:
            matched.append(attach_file(project,path,module=module,object_type=object_type,object_id=hits[0],caption=f'Auto-matched from filename {path.name}',metadata={'auto_match':'filename_point_id'}))
        elif len(hits)>1:ambiguous.append({'path':str(path),'candidate_point_ids':hits})
        else:unmatched.append(str(path))
    project.db.audit(module,'PHOTO_AUTO_ATTACH_BATCH',object_type='photo_batch',object_id=root.name,details={'matched':len(matched),'unmatched':len(unmatched),'ambiguous':len(ambiguous)})
    return {'matched':matched,'unmatched':unmatched,'ambiguous':ambiguous}
