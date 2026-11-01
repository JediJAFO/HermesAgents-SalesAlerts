import os, json, sys, tempfile, urllib.request, urllib.error
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from mcfarlane_wallet_aliases import alias_for_wallet

ROOT='__HERMES_HOME__/price-watches'
STATE=ROOT+'/mcfarlane-dc-sales.json'; ALIASES=ROOT+'/mcfarlane-wallet-aliases.json'; RATES=ROOT+'/mcfarlane-pol-usd-daily.json'
UA='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/140.0 Safari/537.36'
ARCHIVE_DAYS=180; RECAP_LIMIT=30; SEEN_LIMIT=2000
now=lambda: datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
def atomic(path,obj):
    fd,tmp=tempfile.mkstemp(dir=os.path.dirname(path),prefix='.tmp-',text=True)
    with os.fdopen(fd,'w',encoding='utf-8') as f: json.dump(obj,f,indent=2,ensure_ascii=False); f.write('\n')
    os.replace(tmp,path)
def load(p):
    with open(p,encoding='utf-8') as f:return json.load(f)
def fail(state,msg):
    state['last_activity_search_status']='safe failure: '+msg
    state['last_activity_search_attempt_at']=now(); state['last_activity_search_failed_at']=state['last_activity_search_attempt_at']
    # An HTTP 400 gets exactly three delayed retry attempts. The retry runner
    # marks its own invocation so a failed retry decrements the saved budget.
    if msg == 'Rarible HTTP 400':
        retry = state.get('http400_retry') or {}
        if os.environ.get('MTD_HTTP400_RETRY') == '1':
            remaining = max(0, int(retry.get('remaining', 0)) - 1)
        else:
            remaining = int(retry.get('remaining', 3))
        if remaining:
            due = datetime.now(timezone.utc) + timedelta(minutes=5)
            state['http400_retry'] = {
                'remaining': remaining,
                'next_attempt_at': due.isoformat().replace('+00:00', 'Z'),
                'reason': 'Rarible HTTP 400',
            }
        else:
            state.pop('http400_retry', None)
            state['last_activity_search_status'] += '; three scheduled 5-minute retries exhausted'
    atomic(STATE,state); print('[SILENT]')
def request(url,payload=None):
    key=os.environ.get('RARIBLE_API_KEY')
    if not key: raise RuntimeError('RARIBLE_API_KEY unavailable')
    data=json.dumps(payload).encode() if payload is not None else None
    req=urllib.request.Request(url,data=data,method='POST' if data else 'GET',headers={'X-API-KEY':key,'Accept':'application/json','User-Agent':UA, **({'Content-Type':'application/json'} if data else {})})
    try:
        with urllib.request.urlopen(req,timeout=45) as r:
            raw=r.read(); status=r.status
    except urllib.error.HTTPError as e: raise RuntimeError('Rarible HTTP '+str(e.code))
    except Exception as e: raise RuntimeError('Rarible request '+type(e).__name__)
    if status!=200: raise RuntimeError('Rarible HTTP '+str(status))
    try:return json.loads(raw)
    except Exception: raise RuntimeError('Rarible malformed JSON')
def wallet(s):
    if not isinstance(s,str): return None
    x=s.split(':',1)[-1].lower()
    return x if x.startswith('0x') and len(x)==42 else None
def tag(w,aliases):
    return alias_for_wallet(w,aliases)
def party(w,t): return t if t else ('...'+w[-9:] if w else 'Unknown')
def attrs(meta):
    # Rarible item meta attributes commonly sit under meta.attributes
    a=(meta.get('meta') or {}).get('attributes') or meta.get('attributes') or []
    for x in a:
        k=str(x.get('key',x.get('trait_type','')))
        if k=='Rarity': return str(x.get('value','Unknown'))
    return 'Unknown'
def _stamp(value):
    try:
        parsed=datetime.fromisoformat(str(value).replace('Z','+00:00'))
    except (TypeError,ValueError): return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
def _activity_id(row): return row.get('activity_id') or row.get('id') if isinstance(row,dict) else None
def _merge_rows(existing,new_rows):
    merged={}
    for row in list(existing or [])+list(new_rows or []):
        aid=_activity_id(row)
        if aid: merged[str(aid)]=row
    return sorted(merged.values(),key=lambda row:(str(row.get('date') or ''),str(_activity_id(row) or '')),reverse=True)
def merge_completed_sales(state,normalized,as_of=None):
    """Merge normalized completed sales without coupling recap retention to analytics."""
    as_of=(as_of or datetime.now(timezone.utc)).astimezone(timezone.utc)
    from mtd_sales_history import retain_completed_sales
    retain_completed_sales(state,normalized,as_of=as_of)
    seen=state.get('seen_activity_ids') if isinstance(state.get('seen_activity_ids'),list) else []
    state['seen_activity_ids']=list(dict.fromkeys([*seen,*[str(_activity_id(row)) for row in normalized if _activity_id(row)]]))[-SEEN_LIMIT:]
    return state
def main():
    state=load(STATE); aliases=load(ALIASES); rates=load(RATES)
    key=os.environ.get('RARIBLE_API_KEY')
    if not key: return fail(state,'RARIBLE_API_KEY unavailable')
    ids=[c['id'] for c in state['collections']]
    baseline=(state.get('baseline',{}).get('newest_sale',{}).get('date') or state.get('last_successful_check_at'))
    payload={'size':1000,'sort':'LATEST','filter':{'blockchains':['POLYGON'],'types':['SELL'],'collections':ids},'from':baseline}
    try: result=request('https://api.rarible.org/v0.1/activities/search',payload)
    except Exception as e: return fail(state,str(e))
    acts=result.get('activities')
    if not isinstance(acts,list): return fail(state,'Rarible malformed response (activities missing)')
    # Alert dedupe must outlive the bounded display recap; the latter keeps only fifty rows.
    seen=state.get('seen_activity_ids')
    if not isinstance(seen,list):
        seen=[x.get('activity_id',x.get('id')) for x in state.get('recent_sales',[]) if x.get('activity_id',x.get('id'))]
        state['seen_activity_ids']=seen[-2000:]
    known=set(seen)
    b_id=state.get('baseline',{}).get('newest_sale',{}).get('id'); known.add(b_id)
    byid={c['id']:c for c in state['collections']}
    category_baselines=state.get('category_baselines') or {}
    fresh=[]
    for a in acts:
        aid=a.get('id'); typ=a.get('@type',a.get('type'))
        nft=a.get('nft') or {}; nt=nft.get('type') or {}; col=nt.get('collection') or nt.get('contract')
        if typ!='SELL' or a.get('reverted') or aid in known or col not in byid: continue
        category=byid[col].get('category','DC')
        collection_baseline=(byid[col].get('collection_baseline') or {}).get('newest_sale') or {}
        # A corrected/replaced contract can have its own onboarding baseline
        # inside an already-active category. Suppress its pre-baseline history
        # without weakening alerts for the category's older collections.
        if collection_baseline.get('date') and str(a.get('date','')) <= str(collection_baseline['date']): continue
        category_baseline=(category_baselines.get(category) or state.get('baseline') or {}).get('newest_sale') or {}
        # Each category begins alerting only after its own verified baseline.
        # This prevents newly added UFC collections from replaying old sales.
        if category_baseline.get('date') and str(a.get('date','')) <= str(category_baseline['date']): continue
        fresh.append(a)
    # Deduplicate query itself
    uniq={a.get('id'):a for a in fresh if a.get('id')}; fresh=list(uniq.values())
    if not fresh:
        state['last_successful_check_at']=now(); state['last_activity_search_status']='verified: HTTP 200 parsed; no qualifying new sales'; state['last_activity_search_attempt_at']=state['last_successful_check_at']; state.pop('last_activity_search_failed_at',None); state.pop('http400_retry',None)
        atomic(STATE,state); print('MTD DC Sales Alert — update completed; no new sales activity since the last review.'); return
    # oldest first. Enrich collection only if absent display metadata, then item.
    fresh.sort(key=lambda x:x.get('date',''))
    out=[]; normalized=[]
    for a in fresh:
        nt=(a.get('nft') or {}).get('type') or {}; col=nt.get('collection') or nt.get('contract'); token=str(nt.get('tokenId',''))
        c=byid[col]; category=c.get('category','DC')
        if not c.get('display_name'):
            try:
                cm=request('https://api.rarible.org/v0.1/collections/'+urllib.parse.quote(col,safe=':'))
                c['display_name']=((cm.get('meta') or {}).get('name') or c.get('display_name') or col); c['metadata_status']='verified'
            except Exception: c['display_name']=c.get('display_name') or col
            import time; time.sleep(10)
        item={}
        try:
            item=request('https://api.rarible.org/v0.1/items/'+urllib.parse.quote(col+':'+token,safe=':'))
        except Exception: item={}
        import time; time.sleep(10)
        item_name=((item.get('meta') or {}).get('name') or item.get('name') or 'Unknown')
        rarity=attrs(item)
        bw=wallet(a.get('buyer')); sw=wallet(a.get('seller')); bt=tag(bw,aliases); st=tag(sw,aliases)
        a['activity_id']=a.get('id'); a['collection']=col; a['category']=category; a['token_id']=token; a['quantity']=str((a.get('nft') or {}).get('value','1')); a['item_name']=item_name; a['rarity']=rarity; a['rarity_source']='Rarible item metadata attribute Rarity' if rarity!='Unknown' else 'Unknown'; a['buyer_wallet']=bw; a['seller_wallet']=sw
        if bt:a['buyer_name_tag']=bt
        if st:a['seller_name_tag']=st
        usd=a.get('priceUsd')
        source='Rarible completed-activity priceUsd captured once at sale time'
        if usd is None: usd=a.get('amountUsd'); source='Rarible completed-activity amountUsd captured once at sale time'
        if usd is not None:
            try:a['usd_amount']=float(usd);a['usd_source']=source
            except Exception:usd=None
        if usd is None:
            day=a.get('date','')[:10]; rate=(rates.get('rates',{}).get(day) or {}).get('usd_per_pol')
            if rate is not None:
                amount=a.get('price') or ((a.get('payment') or {}).get('value'))
                a['usd_amount']=float(Decimal(str(amount))*Decimal(str(rate))); a['usd_source']='cached POL/USD daily rate '+day
        amount=a.get('price') or ((a.get('payment') or {}).get('value')) or 'Unknown'
        usd_text=('USD unavailable' if a.get('usd_amount') is None else '$'+format(Decimal(str(a['usd_amount'])).quantize(Decimal('0.01')),'.2f'))
        sold=a.get('date','').replace('T',' ')[:16]
        out.append(f"• **[{category}] {c.get('display_name') or col}** — Item: **{item_name}**; Rarity: **{rarity}**; Price: **{amount} POL ({usd_text})**; Buy: **{party(bw,bt)}**; Sell: **{party(sw,st)}**; Sold: {sold}")
        c['last_sale']=a; normalized.append(a)
    # The analytics archive and delivery recap have independent retention rules.
    merge_completed_sales(state,normalized)
    newest=max(fresh,key=lambda x:x.get('date','')); state['last_activity_search_cursor']=newest.get('cursor',state.get('last_activity_search_cursor')); state['last_successful_check_at']=now(); state['last_activity_search_status']='verified: HTTP 200 parsed; '+str(len(normalized))+' qualifying new sales'; state['last_activity_search_attempt_at']=state['last_successful_check_at']; state.pop('last_activity_search_failed_at',None); state.pop('http400_retry',None)
    state['pending_whatsapp_sale_alert']={'activity_ids':[a['activity_id'] for a in normalized],'alert_text':'\r\n'.join(out),'delivered':False,'created_at':now()}
    atomic(STATE,state); print('\r\n'.join(out))
if __name__=='__main__': main()
