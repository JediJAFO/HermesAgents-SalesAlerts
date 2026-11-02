"""Permanent exact-activity sales storage. Windows/recaps are derived views only.

No network, notifications, alert-ledger edits, age limits or count limits here.
"""
from __future__ import annotations
import copy
from datetime import datetime, timedelta, timezone

WINDOW_DAYS=180
RECAP_LIMIT=30

def activity_id(row):
    return str(row.get('activity_id') or row.get('id') or '') if isinstance(row,dict) else ''

def timestamp(value):
    try: value=datetime.fromisoformat(str(value).replace('Z','+00:00'))
    except (TypeError,ValueError): return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)

def _enrich(saved,incoming):
    result=copy.deepcopy(saved)
    for key,value in incoming.items():
        # Sale-time USD must not be recomputed by a later observation/backfill.
        if key in {'usd_amount','usd_source','priceUsd','amountUsd'} and saved.get('usd_amount') is not None and result.get(key) is not None:
            continue
        if isinstance(value,dict) and isinstance(result.get(key),dict):
            result[key]=_enrich(result[key],value)
        elif value is not None and value != '' and value != 'Unknown':
            result[key]=copy.deepcopy(value)
        elif key not in result:
            result[key]=copy.deepcopy(value)
    return result

def merge_rows(*sources):
    merged={}
    for source in sources:
        for row in source if isinstance(source,list) else ():
            aid=activity_id(row)
            if aid: merged[aid]=_enrich(merged[aid],row) if aid in merged else copy.deepcopy(row)
    return sorted(merged.values(),key=lambda row:(timestamp(row.get('date')) or datetime.min.replace(tzinfo=timezone.utc),activity_id(row)),reverse=True)

def saved_history(state):
    """Union legacy stores, preferring canonical evidence on duplicate IDs."""
    return merge_rows(state.get('sales_history'),state.get('sales_history_180d'),state.get('recent_sales'))

def retain_completed_sales(state,normalized=(),*,as_of=None):
    """Merge forever, then rebuild bounded compatibility views; no alert effects."""
    as_of=timestamp(as_of) if as_of is not None else datetime.now(timezone.utc)
    if as_of is None: raise ValueError('as_of must be a timestamp')
    history=merge_rows(saved_history(state),list(normalized))
    state['sales_history']=history
    cutoff=as_of-timedelta(days=WINDOW_DAYS)
    # Keep post-snapshot live rows in the compatibility view during a backfill.
    # Analytics applies its own inclusive [cutoff, as_of] selection.
    state['sales_history_180d']=[row for row in history if (stamp:=timestamp(row.get('date'))) is not None and stamp>=cutoff]
    state['recent_sales']=copy.deepcopy(history[:RECAP_LIMIT])
    return state

def migrate_file(path,*,before_commit=None,retries=3):
    """Saved-only migration: latest-state union, preserve every other field.

    Optimistic conflict check matches the existing backfill commit discipline.
    No migration marker is written; repeating an unchanged migration is a no-op.
    """
    import hashlib,json,os,tempfile
    from pathlib import Path
    path=Path(path)
    for attempt in range(retries):
        before=path.read_bytes();latest=json.loads(before.decode('utf-8'))
        updated=copy.deepcopy(latest);updated['sales_history']=saved_history(latest)
        if before_commit: before_commit(attempt)
        if path.read_bytes()!=before: continue
        changed=updated!=latest
        if changed:
            fd,temp=tempfile.mkstemp(dir=path.parent,prefix='.tmp-',suffix='.json',text=True)
            try:
                with os.fdopen(fd,'w',encoding='utf-8') as handle:
                    json.dump(updated,handle,ensure_ascii=False,indent=2);handle.write('\n');handle.flush();os.fsync(handle.fileno())
                if path.read_bytes()!=before: continue
                os.replace(temp,path)
            finally:
                if os.path.exists(temp):os.unlink(temp)
        readback=path.read_bytes();saved=json.loads(readback.decode('utf-8'))
        if saved!=updated: raise RuntimeError('permanent sales migration readback mismatch')
        def counts(state):return {key:len(state.get(key) or []) for key in ('sales_history','sales_history_180d','recent_sales','seen_activity_ids')}
        return {'changed':changed,'before':counts(latest),'after':counts(saved),'unrelated_fields_unchanged':{k:v for k,v in latest.items() if k!='sales_history'}=={k:v for k,v in saved.items() if k!='sales_history'},'before_sha256':hashlib.sha256(before).hexdigest(),'after_sha256':hashlib.sha256(readback).hexdigest(),'notifications_sent':0}
    raise RuntimeError('sales state changed during bounded migration retries')
