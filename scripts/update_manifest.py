from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


def sha256(path: Path) -> str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()


def main() -> int:
    ap=argparse.ArgumentParser()
    ap.add_argument('--manifest',default='update.json')
    ap.add_argument('--channel',choices=['developer','beta','stable'],required=True)
    ap.add_argument('--version',required=True)
    ap.add_argument('--installer',required=True)
    ap.add_argument('--installer-url',required=True)
    ap.add_argument('--release-tag',required=True)
    ap.add_argument('--release-notes-file',default='')
    ap.add_argument('--promoted-from',default='')
    ns=ap.parse_args()
    path=Path(ns.manifest)
    try:data=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    except Exception:data={}
    data.setdefault('schema_version',1);data['product']='SurveySync';data['generated_utc']=datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00','Z');data['publisher_tool']='GitHub Actions'
    channels=data.setdefault('channels',{})
    installer=Path(ns.installer)
    notes=''
    if ns.release_notes_file and Path(ns.release_notes_file).exists():notes=Path(ns.release_notes_file).read_text(encoding='utf-8').strip()
    digest=sha256(installer)
    rel={
        'version':ns.version,'channel':ns.channel,'publisher':'Clever Bird Development','installer_url':ns.installer_url,
        'size_bytes':installer.stat().st_size,'sha256':digest,'artifact_identity':f'sha256:{digest}','release_tag':ns.release_tag,
        'release_notes':notes,'required':False,'published_utc':data['generated_utc'],
    }
    if ns.promoted_from:
        source = channels.get(ns.promoted_from) or {}
        if not source:
            raise SystemExit(f"Cannot promote: source channel {ns.promoted_from!r} is missing from the manifest.")
        if str(source.get('version') or '') != ns.version:
            raise SystemExit(f"Cannot promote: {ns.promoted_from} is version {source.get('version')!r}, not {ns.version!r}.")
        if str(source.get('sha256') or '').lower() != digest.lower():
            raise SystemExit("Cannot promote: downloaded artifact SHA-256 does not match the tested source-channel artifact.")
        if str(source.get('installer_url') or '') != ns.installer_url:
            raise SystemExit("Cannot promote: installer URL differs from the tested source-channel artifact.")
        rel['promoted_from']=ns.promoted_from;rel['promoted_utc']=data['generated_utc']
        # Stable promotion deliberately reuses the exact Beta publication time/tag/hash.
        rel['tested_channel_published_utc']=source.get('published_utc','')
    channels[ns.channel]=rel
    path.write_text(json.dumps(data,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    print(json.dumps(rel,indent=2))
    return 0

if __name__=='__main__':raise SystemExit(main())
