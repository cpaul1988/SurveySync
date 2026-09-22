from __future__ import annotations

from pathlib import Path
from typing import Iterable

import fitz
from PIL import Image

from .models import AppState, ResultRecord


def _page_image_path(page) -> Path:
    p=Path(page.enhanced_image_path or page.image_path)
    return p


def _note_for_result(r: ResultRecord) -> str:
    lines=[f'Point {r.point_id}  |  Status: {r.status.value}  |  Dip: {r.dip_status.value}']
    if r.elevation is not None:lines.append(f'Survey elevation / rim: {r.elevation:.3f}')
    for i,p in enumerate(r.pipes,start=1):
        vals=[f'Pipe {i}']
        if p.dip is not None:vals.append(f'Dip {p.dip:.3f}')
        if p.invert_elevation is not None:vals.append(f'Invert {p.invert_elevation:.3f}')
        if p.diameter_in is not None:vals.append(f'{p.diameter_in:g}"')
        if p.material:vals.append(str(p.material))
        if p.azimuth_deg is not None:vals.append(f'Az {p.azimuth_deg:.1f}°')
        if p.connected_point_id:vals.append(f'→ Pt {p.connected_point_id}')
        if p.connection_score is not None:vals.append(f'Conn {p.connection_score:.0f}%')
        lines.append(' · '.join(vals))
    if r.qc_flags:lines.append('QC: '+' | '.join(r.qc_flags))
    if r.notes:lines.append('Notes: '+r.notes)
    return '\n'.join(lines)


def export_annotated_fieldbook_pdf(state: AppState, output_path: Path, *, include_unmatched: bool=True) -> Path:
    """Rebuild field-book page images as a PDF and overlay reviewed dip/pipe notes."""
    output_path=Path(output_path);output_path.parent.mkdir(parents=True,exist_ok=True)
    by_page:dict[str,list[ResultRecord]]={}
    for r in state.results:
        ids={e.page_id for e in r.evidence_records if e.page_id}
        for pid in ids:by_page.setdefault(pid,[]).append(r)
    unmatched_by_page={}
    if include_unmatched:
        for u in state.unmatched:unmatched_by_page.setdefault(u.page_id,[]).append(u)
    doc=fitz.open()
    for page_info in sorted(state.fieldbook_pages,key=lambda p:(p.source_name,p.page_number)):
        img_path=_page_image_path(page_info)
        if not img_path.is_file():continue
        with Image.open(img_path) as im:
            w,h=im.size
        # preserve image aspect while reserving a note panel below it
        scale=612/max(w,1); image_h=h*scale; note_h=max(90,40+58*len(by_page.get(page_info.page_id,[])))
        ph=image_h+note_h
        page=doc.new_page(width=612,height=ph)
        page.insert_image(fitz.Rect(0,0,612,image_h),filename=str(img_path),keep_proportion=True)
        y=image_h+10
        page.draw_line(fitz.Point(18,image_h+2),fitz.Point(594,image_h+2),color=(0.25,0.35,0.5),width=1)
        heading=f'{page_info.source_name} · Page {page_info.page_number} · {page_info.page_type.replace("_"," ").title()}'
        page.insert_textbox(fitz.Rect(18,y,594,y+18),heading,fontsize=9,fontname='hebo',color=(0.04,0.18,0.34));y+=18
        records=by_page.get(page_info.page_id,[])
        if not records:page.insert_textbox(fitz.Rect(18,y,594,y+26),'No matched structure results on this page.',fontsize=8,fontname='helv',color=(0.4,0.4,0.4));y+=28
        for r in records:
            note=_note_for_result(r);height=max(42,12*(note.count('\n')+2))
            page.insert_textbox(fitz.Rect(18,y,594,y+height),note,fontsize=7.8,fontname='helv',lineheight=1.15);y+=height+6
        if include_unmatched and unmatched_by_page.get(page_info.page_id):
            raw=', '.join((u.point_id_raw or '?') for u in unmatched_by_page[page_info.page_id])
            page.insert_textbox(fitz.Rect(18,y,594,y+24),f'Unmatched OCR evidence: {raw}',fontsize=7.5,fontname='helv',color=(0.65,0.2,0.1))
    if len(doc)==0:raise ValueError('No rendered field-book pages are available for annotated PDF export.')
    doc.set_metadata({'title':f'{state.project_name} — Annotated Field Book','creator':'SurveySync FieldBookSync'})
    doc.save(output_path,garbage=4,deflate=True);doc.close();return output_path
