"""Bounded Flow submissions correlated through observed browser requests.

Only visible browser controls submit work. No private endpoint is called here.
An exact prompt in an outgoing request acknowledges that Flow captured it;
URLs or generation IDs in that request's response identify its result images.
"""
from __future__ import annotations
import base64,hashlib,json,random,re,time
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from pathlib import Path
from urllib.parse import unquote,urlsplit,parse_qs
from .core import UserError,atomic_json,read_json
from . import flow_browser as B

def fingerprint_url(url):return hashlib.sha256(url.encode()).hexdigest()


def strings(value,depth=0):
    if depth>24:return
    if isinstance(value,str):
        yield value
        if value.lstrip().startswith(('{','[')):
            try:yield from strings(json.loads(value),depth+1)
            except (ValueError,TypeError):pass
    elif isinstance(value,dict):
        for child in value.values():yield from strings(child,depth+1)
    elif isinstance(value,list):
        if value and all(isinstance(child,dict) and isinstance(child.get('text'),str) for child in value):
            yield ' '.join(child['text'] for child in value)
        for child in value:yield from strings(child,depth+1)


def prompt_values(raw):
    if not raw:return set()
    try:data=json.loads(raw)
    except ValueError:data=parse_qs(raw) if '=' in raw else raw
    return {B.normalize(value) for value in strings(data)}


def identities(value,parent='',depth=0):
    """Extract explicit result URLs/IDs, excluding project/user/request context."""
    urls=set();ids=set()
    if depth>24:return urls,ids
    if isinstance(value,dict):
        for key,child in value.items():
            key=key.lower()
            if key in ('clientcontext','user','usercontext','project','projectcontext','request','requests','prompt','input','inputs','referenceimages','referenceimage','imageinputs'):continue
            if isinstance(child,str):
                if child.lstrip().startswith(('{','[')):
                    u,i=identities(child,key,depth+1);urls.update(u);ids.update(i)
                if re.search(r'(url|uri)$',key) and child.startswith(('https://','blob:https://')):urls.add(child)
                if (key in ('mediaid','media_id','generationid','generation_id','operationid','operation_id','operationname','imageid','image_id') or
                    key=='name' and re.search(r'(?:^|/)(?:operations|media)/',child) or
                    key in ('id','name') and parent in ('media','images','image','operations','operation','generations','generation','results')):
                    token=child.rstrip('/').rsplit('/',1)[-1]
                    if re.fullmatch(r'[A-Za-z0-9_-]{16,160}',token):ids.add(token)
            else:
                u,i=identities(child,key,depth+1);urls.update(u);ids.update(i)
    elif isinstance(value,list):
        for child in value:
            u,i=identities(child,parent,depth+1);urls.update(u);ids.update(i)
    elif isinstance(value,str) and value.lstrip().startswith(('{','[')):
        try:return identities(json.loads(value),parent,depth+1)
        except ValueError:pass
    return urls,ids


def record_prompts(data,depth=0):
    """Find prompts inside one result's metadata without crossing result lists."""
    if depth>12 or not isinstance(data,dict):return set()
    found=set()
    for key,value in data.items():
        key=key.lower()
        if key in ('prompt','textprompt','prompttext','structuredprompt'):
            found.update(B.normalize(s) for s in strings(value))
        elif key in ('metadata','imagemetadata','generationmetadata','generatedimage','image','media','request','input') and isinstance(value,dict):
            found.update(record_prompts(value,depth+1))
    return found


CARDS_JS=r'''prompts=>{
 const norm=s=>(s||'').normalize('NFC').replace(/[\u200b\ufeff]/g,'').replace(/\s+/g,' ').trim();
 const resultImage=i=>{const r=i.getBoundingClientRect();return i.naturalWidth>=512||r.width>=128&&r.height>=128;};
 // Match a complete text field, never a substring of a different prompt.
 // Inspect descendants because a history step also contains buttons/labels.
 const bestMatch=(el,prompts)=>{
   const values=new Set();
   for(const node of [el,...el.querySelectorAll('*')]){
     for(const value of [node.getAttribute('data-prompt'),node.getAttribute('aria-label'),node.getAttribute('title'),node.innerText]){
       if(value)values.add(norm(value));
     }
   }
   const hits=prompts.filter(p=>values.has(norm(p.prompt)));
   return hits.length===1?hits[0]:null;
 };
 const cards=[];
 // Current Flow: the prompt belongs to a history step, not to the preview,
 // navigation rail, or neighboring grid tile. Bind that step's own media ID.
 if(document.querySelector('flow-editor-page,flow-grid-tile-container')){
   for(const step of document.querySelectorAll('flow-editor-history-step-image')){
     const best=bestMatch(step,prompts);
     if(!best)continue;
     for(const img of step.querySelectorAll('img[data-media-id]')){
       if(!img.complete||img.naturalWidth<512||img.naturalHeight<512)continue;
       if(!img.srcset&&img.currentSrc&&img.currentSrc!==img.src)continue;
       cards.push({urls:[img.currentSrc||img.src],ids:[img.dataset.mediaId],owner:best.id,proof:'history-step'});
     }
   }
   // Grid tiles identify media, but never supply a prompt by proximity.
   for(const img of document.querySelectorAll('flow-grid-tile-container img[data-media-id]')){
     if(img.complete&&img.naturalWidth>=512)cards.push({urls:[img.currentSrc||img.src],ids:[img.dataset.mediaId],owner:null});
   }
   return cards;
 }
 for(const img of document.images){
   if(!img.complete||!img.getClientRects().length||img.naturalWidth<512||img.naturalHeight<512)continue;
   // Never associate an old decoded currentSrc with a newly assigned src.
   if(!img.srcset&&img.currentSrc&&img.currentSrc!==img.src)continue;
   const urls=[img.currentSrc||img.src].filter(Boolean),ids=[];
   let owner=null;
   for(let el=img,depth=0;el&&depth<12;el=el.parentElement,depth++){
     if(['BODY','HTML','MAIN'].includes(el.tagName)||[...el.querySelectorAll('img')].filter(resultImage).length>1||el.querySelector('textarea,input,[contenteditable]'))break;
     for(const name of ['data-media-id','data-generation-id','data-operation-id','data-image-id']){
       const id=el.getAttribute(name);if(id)ids.push(id);
     }
     const best=bestMatch(el,prompts);
     if(best)owner=best.id;
   }
   cards.push({urls,ids,owner});
 }
 return cards;
}'''

# Fetch the immutable resource first, never canvas-copy a recycled DOM element.
# Canvas fallback is limited to a fully decoded, unchanged matching image.
READ_IMAGE_JS=r'''async url=>{
 try{
   const address=new URL(url);
   if(!['https:','blob:','data:'].includes(address.protocol))return null;
   const response=await fetch(url,{signal:AbortSignal.timeout(2000)});
   if(response.ok&&response.headers.get('content-type')?.startsWith('image/')&&Number(response.headers.get('content-length')||0)<=33554432){
     const blob=await response.blob();if(blob.size>33554432)return null;
     return await new Promise(resolve=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result.split(',')[1]);reader.onerror=()=>resolve(null);reader.readAsDataURL(blob);});
   }
 }catch{}
 const img=[...document.images].find(i=>i.complete&&(i.currentSrc||i.src)===url&&(!i.srcset?i.src===url:true)&&i.naturalWidth>=512&&i.naturalHeight>=512);
 if(!img||img.naturalWidth*img.naturalHeight>20000000)return null;
 try{
   await img.decode();
   if(!img.complete||(img.currentSrc||img.src)!==url||(!img.srcset&&img.src!==url))return null;
   const canvas=document.createElement('canvas');canvas.width=img.naturalWidth;canvas.height=img.naturalHeight;
   canvas.getContext('2d').drawImage(img,0,0);
   if((img.currentSrc||img.src)!==url||(!img.srcset&&img.src!==url))return null;
   return canvas.toDataURL('image/png').split(',')[1];
 }catch{return null;}
}'''

SWEEP_JS=r'''()=>{
 const elements=[document.scrollingElement,...document.querySelectorAll('main,section,div')];
 const candidates=elements.filter(e=>e&&e.scrollHeight>e.clientHeight+100&&e.clientHeight>200&&e.querySelector('img'));
 const target=candidates.sort((a,b)=>b.scrollHeight-a.scrollHeight)[0];
 if(!target)return false;
 const end=target.scrollTop+target.clientHeight>=target.scrollHeight-5;
 target.scrollTop=end?0:target.scrollTop+Math.max(200,target.clientHeight*.75);
 return true;
}'''



def inspect_next_asset(page,tracker,advance_completed=False):
    """Open existing Flow assets read-only, never Reuse prompt or Generate."""
    navigation=getattr(tracker,'recovery_navigation',None)
    if not page.locator('flow-editor-page,flow-grid-tile-container').count():
        if navigation:navigation.sweep()
        else:page.evaluate(SWEEP_JS)
        return
    if page.locator('flow-editor-page').count():
        # Give lazy history metadata and full-size images time to load. Observe
        # runs between visits; leaving immediately used to miss cached results.
        if tracker.inspect_opened is None:tracker.inspect_opened=time.monotonic()
        cards=None
        if time.monotonic()-tracker.inspect_opened<3:
            if not advance_completed:return
            cards=page.evaluate(CARDS_JS,tracker.queue['shots'])
            # Only skip the loading grace after every identified image in the
            # panel has been captured and released by recovery.
            if not cards or any(card.get('proof')!='history-step' or not card.get('owner') or
                                card['owner'] in tracker.active for card in cards):return
        if cards is None:cards=page.evaluate(CARDS_JS,tracker.queue['shots'])
        if navigation:navigation.remember(cards)
        for card in cards:
            if card.get('proof')=='history-step':tracker.inspected_assets.update(card['ids'])
        back=page.get_by_role('button',name='Back button to go to previous page',exact=True)
        if not back.count():return
        back.click(timeout=2500)
        # Also advance past unrelated assets; previously the first unrelated
        # tile was reopened forever, starving every missing result after it.
        if tracker.inspect_id:tracker.inspected_assets.add(tracker.inspect_id)
        tracker.inspect_id=None;tracker.inspect_opened=None
    if navigation:navigation.prepare()
    ids=page.locator('flow-grid-tile-container img[data-media-id]').evaluate_all('(images)=>images.map(i=>i.dataset.mediaId)')
    if navigation and navigation.order=='forward':ids=list(reversed(ids))
    for media_id in ids:
        if media_id in tracker.inspected_assets or not re.fullmatch(r'[A-Za-z0-9_-]{16,160}',media_id):continue
        if navigation and media_id in navigation.owners and navigation.owners[media_id] not in tracker.active:continue
        image=page.locator(f'flow-grid-tile-container img[data-media-id="{media_id}"]')
        try:
            if navigation:navigation.opening()
            image.first.dblclick(timeout=2500)
            tracker.inspect_id=media_id;tracker.inspect_opened=time.monotonic()
            page.locator(f'flow-editor-history-step-image img[data-media-id="{media_id}"]').wait_for(state='visible',timeout=3000)
        except Exception:
            tracker.errors.append('An asset history panel did not finish loading; it will be checked again.')
        return
    # A virtualized gallery may expose additional assets after scrolling.
    if navigation:navigation.sweep()
    else:page.evaluate(SWEEP_JS)
    # Revisit after a complete pass: a panel may have exceeded the loading
    # grace period or its first image read may have failed transiently.
    tracker.inspected_assets.clear()



class Tracker:
    def __init__(self,page,queue,folder,before,checkpoint,capture_images=True):
        self.page=page;self.queue=queue;self.folder=Path(folder);self.before=set(before)
        self.capture_images=capture_images
        self.checkpoint=checkpoint;self.active={};self.requests={};self.polls=set();self.expected=None
        self.inspected_assets=set();self.claims={};self.images={};self.blobs_seen=set();self.errors=[];self.fatal=None;self.read_attempts={}
        self.inspect_id=None;self.inspect_opened=None

    def restore(self):
        for path in self.folder.glob('*.png'):
            if not re.fullmatch(r'[a-f0-9]{64}',path.stem):continue
            try:
                meta=read_json(path.with_suffix('.json'))
                image=B.decode_image(path.read_bytes(),self.queue['aspect'])
                if image and image['hash']==path.stem:self._store(image,meta.get('urls',[]))
            except (OSError,ValueError,TypeError):continue

    def add(self,shot):
        self.active[shot['id']]={'shot':shot,'ack':False,'urls':set(),'ids':set(),'stable':None,'since':time.monotonic(),'submitted':time.monotonic()}
        self.expected=shot['id']

    def requested(self,request):
        try:
            if request.resource_type not in ('xhr','fetch'):return
            address=urlsplit(request.url)
            if address.scheme!='https' or not (address.hostname in ('labs.google','flow.google.com') or (address.hostname or '').endswith('.googleapis.com')):return
            if re.search(r'analytics|telemetry|/log(?:/|$)|/metrics(?:/|$)',address.path,re.I):return
            raw=request.post_data
            if raw and len(raw)>512*1024:return
            values=prompt_values(raw)
            if request.method=='POST' and re.search(r'generate',address.path,re.I):
                matches=[sid for sid,item in self.active.items() if B.normalize(item['shot']['prompt']) in values]
                if len(matches)==1:
                    sid=matches[0];self.requests[request]=sid;self.active[sid]['ack']=True
                    self.checkpoint();return
                if len(matches)>1:return
            tokens=set(re.findall(r'[A-Za-z0-9_-]{16,160}',unquote(request.url)))
            for value in values:tokens.update(re.findall(r'[A-Za-z0-9_-]{16,160}',value))
            linked=tuple(sid for sid,item in self.active.items() if tokens & item['ids'])
            if linked:
                self.requests[request]=linked;self.polls.add(request);return
        except (ValueError,TypeError,AttributeError):return

    def _poll_results(self,data,depth=0,default_owner=None):
        if depth>24:return
        if isinstance(data,str) and data.lstrip().startswith(('{','[')):
            try:self._poll_results(json.loads(data),depth+1,default_owner)
            except ValueError:pass
            return
        if isinstance(data,list):
            for child in data:self._poll_results(child,depth+1,default_owner)
            return
        if not isinstance(data,dict):return
        # Require an ID on this record (or its explicit operation metadata).
        # A gallery with one known and several unknown jobs is NOT one result.
        direct={value for value in data.values() if isinstance(value,str)}
        for key in ('operation','generation'):
            if isinstance(data.get(key),dict):direct.update(value for value in data[key].values() if isinstance(value,str))
        owners={sid for sid,item in self.active.items() if any(value==identifier or value.endswith('/'+identifier)
                for value in direct for identifier in item['ids'])}
        # Gallery/status responses may carry the original prompt before an
        # operation ID was observed. Match within this record, not its siblings.
        prompts=record_prompts(data)
        prompt_matches=[shot['id'] for shot in self.queue['shots'] if B.normalize(shot['prompt']) in prompts]
        if prompts:
            # Explicit result metadata outranks the request envelope. Never label
            # a previous result with the prompt that happened to request a gallery.
            if len(prompt_matches)!=1 or prompt_matches[0] not in self.active:return
            owners.add(prompt_matches[0])
        if len(owners)>1:
            self.fatal='Flow returned conflicting prompt/result identities; queue paused.';return
        # Even an envelope with a prompt can contain results for other shots.
        collections=[v for k,v in data.items() if k.lower() in ('media','images','results','operations','generations') and isinstance(v,list)]
        if collections:
            inherited=next(iter(owners)) if owners else default_owner
            for values in collections:self._poll_results(values,depth+1,inherited)
            return
        # Wrappers can contain multiple independently prompted results even
        # without a known collection key. Resolve those children before taking
        # any URLs from their parent under the generating request's identity.
        nested=[v for v in data.values() if isinstance(v,(dict,list))]
        def has_prompt(value):
            if isinstance(value,list):return any(has_prompt(v) for v in value)
            if isinstance(value,dict):return bool(record_prompts(value)) or any(has_prompt(v) for v in value.values() if isinstance(v,(dict,list)))
            return False
        if not prompts and any(has_prompt(v) for v in nested):
            inherited=next(iter(owners)) if owners else default_owner
            for child in nested:self._poll_results(child,depth+1,inherited)
            return
        if not owners and not prompts and default_owner in self.active:
            if not any(record_prompts(v) for v in data.values() if isinstance(v,dict)):
                owners.add(default_owner)
        if len(owners)==1:
            sid=next(iter(owners));urls,ids=identities(data,parent='results')
            if any(self.claims.get(url,sid)!=sid for url in urls):
                self.fatal='Flow reused a result identity for different shots; no reassignment was made.';return
            self.claims.update({url:sid for url in urls})
            item=self.active[sid];item['urls'].update(urls);item['ids'].update(ids);return
        # A batched status response can contain several generations. Attribute
        # each record separately, never its combined list of result URLs.
        if isinstance(data,dict):
            for child in data.values():
                if isinstance(child,(dict,list,str)):self._poll_results(child,depth+1,default_owner)

    def _store(self,image,urls):
        key=image['hash']
        if key not in self.images:
            path=self.folder/(key+'.png');temporary=path.with_suffix('.partial.png')
            temporary.write_bytes(image['data']);temporary.replace(path)
            self.images[key]={'path':path,'hash':key,'width':image['width'],'height':image['height'],'size':len(image['data']),'urls':set()}
        self.images[key]['urls'].update(urls)
        atomic_json(self.folder/(key+'.json'),{'urls':sorted(self.images[key]['urls'])})

    def finished(self,request):
        try:
            response=request.response()
            if not response or not response.ok:return
            kind=response.headers.get('content-type','').lower()
            owner=self.requests.pop(request,None)
            polling=request in self.polls;self.polls.discard(request)
            host=urlsplit(request.url).hostname or ''
            flow_response=host in ('labs.google','flow.google.com') or host.endswith('.googleapis.com')
            if flow_response and ('json' in kind or 'text/plain' in kind):
                if int(response.headers.get('content-length','0'))>4*1024*1024:return
                body=response.body()
                if len(body)>4*1024*1024:return
                data=json.loads(body)
                if owner and isinstance(data,dict) and data.get('error'):
                    self.fatal='Flow reported a generation error. Submitted shots remain unresolved; check the browser before retrying.'
                    return
                if not polling and isinstance(owner,str) and owner in self.active:
                    self._poll_results(data,default_owner=owner)
                else:self._poll_results(data)
                self.checkpoint();return
            if not self.capture_images or not kind.startswith('image/'):return
            aliases=set();prior=request
            while prior is not None:aliases.add(prior.url);prior=prior.redirected_from
            if aliases & self.before:return
            if int(response.headers.get('content-length','0'))>32*1024*1024:return
            image=B.decode_image(response.body(),self.queue['aspect'])
            if image:self._store(image,aliases)
        except (ValueError,TypeError,AttributeError,OSError):self.errors.append('A Flow response could not be matched.')
        except Exception:self.errors.append('A Flow response became unavailable.')

    def downloaded(self,download):
        # Downloads without a source identity are intentionally not assigned.
        url=getattr(download,'url','')
        if not isinstance(url,str) or len(self.owners({url}))!=1:
            self.errors.append('An unlinked download was ignored; import it by shot filename.');return
        path=self.folder/'native-download.partial'
        try:
            download.save_as(str(path));image=B.decode_image(path.read_bytes(),self.queue['aspect'])
            if image:
                self._store(image,{url})
                if image['hash'] in self.images:self.images[image['hash']].setdefault('native_urls',set()).add(url)
        except Exception:self.errors.append('A linked native download could not be read.')
        finally:path.unlink(missing_ok=True)

    def owners(self,urls,ids=()):
        owners=set()
        for sid,item in self.active.items():
            if set(urls)&item['urls'] or set(ids)&item['ids']:
                owners.add(sid);continue
            for url in urls:
                tokens=set(re.findall(r'[A-Za-z0-9_-]{16,160}',unquote(url)))
                if tokens & item['ids']:owners.add(sid);break
        return owners

    def observe(self):
        if self.fatal:return {sid:{} for sid in self.active},set()
        visible=set(self.page.evaluate(B.ASSETS_JS))-self.before
        cards=self.page.evaluate(CARDS_JS,self.queue['shots'])
        for card in cards:
            urls=set(card['urls']) & visible
            owners=self.owners(urls,card.get('ids',[]))
            if card.get('owner') in self.active:owners.add(card['owner'])
            if len(owners)>1:
                self.fatal='Flow showed conflicting prompt/result identities. Submitted shots remain unresolved.';continue
            if len(owners)==1:
                sid=next(iter(owners))
                if any(self.claims.get(url,sid)!=sid for url in urls):
                    self.errors.append('Ignored a recycled card URL already owned by another shot.');continue
                self.claims.update({url:sid for url in urls})
                self.active[sid]['urls'].update(urls)
                if card.get('proof')=='history-step':self.active[sid]['ids'].update(card.get('ids',[]))
        # Recover cached/missed response bodies only after proving ownership.
        captured=set().union(*(im['urls'] for im in self.images.values())) if self.images else set()
        sources=[set(card['urls']) & visible for card in cards]
        sources.extend({url} for item in self.active.values() for url in item['urls']
                       if url.startswith('https://') and url not in captured)
        reads=0
        for urls in sources:
            if reads>=2:break
            if urls & captured:continue
            for url in urls:
                if len(self.owners({url}))!=1:continue
                attempts,last=self.read_attempts.get(url,(0,-100.))
                if attempts>=3 or time.monotonic()-last<5:continue
                reads+=1
                self.read_attempts[url]=(attempts+1,time.monotonic())
                try:
                    encoded=self.page.evaluate(READ_IMAGE_JS,url)
                    image=B.decode_image(base64.b64decode(encoded),self.queue['aspect']) if encoded and len(encoded)<45*1024*1024 else None
                    if image:self._store(image,urls);captured.update(urls)
                except Exception:self.errors.append('A matched visible image could not be read; use its Download button.')
                break
        # Blob URLs sometimes replace the fetched image URL. Decode visible
        # blobs so their pixel hash can be joined to an identified response.
        # An unmatched blob is never assigned just because it appeared next.
        blobs={url for url in visible if url.startswith(('blob:https://labs.google/','blob:https://flow.google.com/')) and url not in self.blobs_seen}
        if blobs:
            reader=B.Results(self.page,self.queue['aspect'],self.before,self.folder)
            reader.visible_blobs(blobs);self.blobs_seen.update(reader.blobs_seen)
            for image in reader.candidates.values():self._store(image,image['urls'])
        found={sid:{} for sid in self.active}
        for key,image in self.images.items():
            proven=self.owners(image['urls'])
            if len(proven)==1:
                self.active[next(iter(proven))]['urls'].update(url for url in image['urls'] & visible if url.startswith('blob:'))
            # Check each URL separately: identical pixels can belong to separate
            # generations, while one ambiguous URL must never choose a winner.
            # A decoded response with a proven generation identity is enough.
            # Flow can virtualize finished cards out of the visible gallery.
            for url in image['urls']:
                owners=self.owners({url})
                if len(owners)>1:self.fatal='An image has conflicting generation identities; queue paused.'
                elif owners:found[next(iter(owners))][key]=image
        self.checkpoint()
        return found,visible

    def release(self,sid):
        item=self.active.pop(sid);self.before.update(item['urls'])
        if self.expected==sid:self.expected=None
        self.requests={request:owner for request,owner in self.requests.items() if owner!=sid}
        keep_urls=set().union(*(v['urls'] for v in self.active.values())) if self.active else set()
        for key,image in list(self.images.items()):
            if image['urls'] & item['urls'] and not image['urls'] & keep_urls:
                image['path'].unlink(missing_ok=True);image['path'].with_suffix('.json').unlink(missing_ok=True);del self.images[key]


def button_ready(button):
    if not button.is_enabled() or button.get_attribute('aria-disabled')=='true':return False
    try:button.click(trial=True,timeout=1000)
    except Exception as error:
        if type(error).__name__=='TimeoutError':return False
        raise
    return True


class ImageImporter:
    """One disk-backed import worker; browser objects never leave their thread."""
    def __init__(self,job,folder,log,replace_existing=False):
        self.job=job;self.folder=folder;self.log=log;self.pending={};self.replace_existing=replace_existing
        self.failures={};self.attempts={};self.shots={}
        self.worker=ThreadPoolExecutor(max_workers=1,thread_name_prefix='flow-image-import')

    def submit(self,shot):
        self.shots[shot['id']]=shot
        self.attempts[shot['id']]=self.attempts.get(shot['id'],0)+1
        self.pending[shot['id']]=self.worker.submit(self._import,shot)

    def _import(self,shot):
        from .pipeline import cached_image
        B.flow.collect_downloads(self.job,self.folder,shot_ids={shot['id']},replace_existing=self.replace_existing)
        if not cached_image(self.job,shot):
            raise UserError(f'Image import for {shot["id"]} did not validate. Its receipt is retained; collect completed images to recover it.')

    def poll(self):
        for sid,future in list(self.pending.items()):
            if not future.done():continue
            del self.pending[sid]
            try:future.result()
            except Exception as error:
                if self.attempts[sid]<2:
                    self.log(f'Retrying local import for {sid}; its captured receipt is retained.')
                    self.submit(self.shots[sid])
                    continue
                self.failures[sid]=str(error);continue
            self.log(f'Imported Flow shot {sid}: images/{sid}.png is ready in the project.')

    def close(self):
        # Finish already captured images even if generation stops or times out.
        # Keep the project lock until the worker has stopped writing.
        self.worker.shutdown(wait=True)


def submit_queue(job,queue,remaining,page,controls,state,path,cancel,log,timeout=240):
    """Submit prompts and retain identity metadata; capture belongs to recovery."""
    timed=controls.get('interval')==6
    limit=len(remaining) if timed else max(1,min(3,int(controls.get('parallel',1))))
    tracker=None
    def checkpoint():
        records={sid:{'prompt_hash':fingerprint_url(item['shot']['prompt']),'request_seen':item['ack'],
            'result_url_hashes':sorted(fingerprint_url(url) for url in item['urls']),
            'generation_ids':sorted(item['ids']),'result_urls':sorted(item['urls'])} for sid,item in tracker.active.items()}
        state['matching_version']=5;state['inflight']=records;state['pending']=next(iter(records),None)
        atomic_json(path,state)
    tracker=Tracker(page,queue,job.folder,set(),checkpoint,capture_images=False)
    page.on('request',tracker.requested);page.on('requestfinished',tracker.finished)
    todo=list(remaining);prepared=None;prepared_since=0.;next_due=0.;last_submission=None;last_delay=''
    try:
        log('Flow submission only: images will be captured with Recover generated images.')
        while todo:
            B.guard(page,cancel)
            if tracker.fatal:raise UserError(tracker.fatal)
            now=time.monotonic()
            # Legacy concurrency choices still wait for result metadata, without
            # reading image bytes. Timed mode never waits for image completion.
            pending=[item for item in tracker.active.values() if len(item['urls'])<queue['outputs']]
            if not timed and pending and all(now-item['submitted']>timeout for item in pending):
                raise UserError('Flow submissions timed out awaiting result metadata. Use Recover generated images before retrying unresolved shots.')
            acknowledged=all(item['ack'] for item in tracker.active.values())
            unique=all(B.normalize(item['shot']['prompt'])!=B.normalize(todo[0]['prompt']) for item in pending)
            can_prepare=not timed or last_submission is None or acknowledged or now>=next_due-1
            if (timed or len(pending)<limit and acknowledged) and unique and can_prepare:
                shot=todo[0]
                if prepared!=shot['id']:
                    B.fill_prompt(page,controls['prompt'],shot['prompt'],cancel)
                    prepared=shot['id'];prepared_since=time.monotonic()
                    if last_submission is None:next_due=prepared_since+6.0
                    log(f'Flow shot {shot["id"]}: next original prompt prepared.')
                button=page.locator(controls['generate'])
                if button.count()!=1:raise UserError('Flow changed its Generate control. Submitted shots remain unresolved.')
                if now-prepared_since>timeout:raise UserError('Flow Generate stayed unavailable. The prepared prompt was not submitted; check the browser and continue.')
                due=time.monotonic()>=next_due
                ready=button_ready(button) if due else False
                if due and not ready and last_delay!=shot['id']:
                    log(f'Flow shot {shot["id"]}: scheduled submission is due, but Flow Generate is unavailable; waiting for its control.');last_delay=shot['id']
                if ready:
                    B.guard(page,cancel)
                    if tracker.fatal:raise UserError(tracker.fatal)
                    if B.normalize(page.locator(controls['prompt']).evaluate('(e)=>e.value ?? e.innerText'))!=B.normalize(shot['prompt']):
                        raise UserError('The next prompt changed before Generate; no new click was sent.')
                    tracker.add(shot);checkpoint()
                    submitted_at=time.monotonic();button.click(timeout=10000)
                    gap='' if last_submission is None else f' ({submitted_at-last_submission:.1f}s after previous submission)'
                    last_submission=submitted_at;next_due=submitted_at+(random.uniform(6.0,11.0) if timed else 0.)
                    todo.pop(0);prepared=None;last_delay=''
                    log(f'Flow shot {shot["id"]}: submitted{gap}; saved for later recovery.')
            if todo:page.wait_for_timeout(50 if timed and 0<next_due-time.monotonic()<1 else 250)
        log('All queued prompts submitted. Wait for Flow to finish, then click Recover generated images.')
    finally:
        page.remove_listener('request',tracker.requested);page.remove_listener('requestfinished',tracker.finished)


def run_queue(job,queue,remaining,page,controls,state,path,cancel,log,timeout=240):
    from .pipeline import cached_image
    interval=6.0 if controls.get('interval')==6 else 0.0
    limit=len(remaining) if interval else max(1,min(3,int(controls.get('parallel',1))))
    folder=job.folder/'browser-downloads';folder.mkdir(exist_ok=True)
    spool=folder/('capture-v3-'+queue['queue_id']);spool.mkdir(exist_ok=True)
    with nullcontext(spool) as temporary:
        tracker=None;last_record=None
        def checkpoint():
            nonlocal last_record
            if tracker is None:return
            records={sid:{'prompt_hash':fingerprint_url(item['shot']['prompt']),'request_seen':item['ack'],
                'result_url_hashes':sorted(fingerprint_url(url) for url in item['urls']),
                'generation_ids':sorted(item['ids']),'result_urls':sorted(item['urls'])} for sid,item in tracker.active.items()}
            encoded=json.dumps(records,sort_keys=True)
            if encoded==last_record:return
            state['matching_version']=5;state['inflight']=records;state['pending']=next(iter(records),None);atomic_json(path,state);last_record=encoded
        tracker=Tracker(page,queue,temporary,page.evaluate(B.ASSETS_JS),checkpoint)
        tracker.restore()
        page.on('request',tracker.requested);page.on('requestfinished',tracker.finished);page.on('download',tracker.downloaded)
        todo=list(remaining);prepared=None;prepared_since=0;last_log=0
        next_due=0.;last_submission=None;last_delay='';last_observed=-1.;found={};last_sweep=0.;retry_started=None
        importer=ImageImporter(job,folder,log)
        try:
            log('Flow timed queue: next submission targeted a random 6–11 seconds after each click; image completion does not gate submissions.' if interval else
                f'Flow overlapping queue: up to {limit} prompts in flight; results matched by prompt and generation identity.')
            while todo or tracker.active:
                B.guard(page,cancel)
                importer.poll()
                now=time.monotonic()
                # Leave the final second before a timed click free of expensive
                # page scans. Import/cleanup runs on its own single worker.
                imminent=interval and todo and next_due and next_due-1<=now<=next_due+1
                if not imminent and (not interval or now-last_observed>=1):
                    found,visible=tracker.observe();last_observed=time.monotonic()
                if tracker.fatal:raise UserError(tracker.fatal)
                now=time.monotonic()
                for sid,item in list(tracker.active.items()):
                    images=found.get(sid,{});keys=tuple(sorted(images))
                    if keys!=item['stable']:item['stable']=keys;item['since']=now
                    if len(images)>=queue['outputs'] and now-item['since']>=0.5:
                        payload=[dict(image,data=image['path'].read_bytes()) for image in images.values()]
                        B.save_results(job,queue,item['shot'],payload,import_now=False)
                        importer.submit(item['shot'])
                        tracker.release(sid);checkpoint();log(f'Saved Flow shot {sid} by identity ({len(tracker.active)} still generating).')
                if tracker.active and (not todo or all(now-item['submitted']>timeout for item in tracker.active.values())) and now-last_sweep>=1:
                    inspect_next_asset(page,tracker);tracker.read_attempts.clear();last_sweep=now
                    if retry_started is None:
                        log('Checking generated but unimported shots across the Flow gallery; no new Generate clicks.')
                        retry_started=now
                if tracker.active and (not todo or not interval) and all(now-item['submitted']>timeout for item in tracker.active.values()) and retry_started is not None and now-retry_started>=90:
                    detail=' '+tracker.errors[-1] if tracker.errors else ''
                    raise UserError('Flow shots '+', '.join(tracker.active)+' timed out without complete, identified results. Other captured images are retained; no automatic retry was sent.'+detail)
                # A captured request freezes the previous prompt. Until then,
                # changing the editor could change what Flow actually submits.
                acknowledged=all(item['ack'] for item in tracker.active.values())
                unique=not todo or all(B.normalize(item['shot']['prompt'])!=B.normalize(todo[0]['prompt']) for item in tracker.active.values())
                can_prepare=not interval or last_submission is None or acknowledged or time.monotonic()>=next_due-1
                if todo and len(tracker.active)<limit and (interval or acknowledged) and unique and can_prepare:
                    shot=todo[0]
                    if prepared!=shot['id']:
                        B.fill_prompt(page,controls['prompt'],shot['prompt'],cancel);prepared=shot['id'];prepared_since=now
                        log(f'Flow shot {shot["id"]}: next original prompt prepared.')
                    button=page.locator(controls['generate'])
                    if button.count()!=1:raise UserError('Flow changed its Generate control. Submitted shots remain unresolved.')
                    if now-prepared_since>timeout:raise UserError('Flow Generate stayed unavailable. The prepared prompt was not submitted; check the browser and continue.')
                    due=not interval or time.monotonic()>=next_due
                    ready=button_ready(button) if due else False
                    if due and not ready and last_delay!=shot['id']:
                        log(f'Flow shot {shot["id"]}: scheduled submission is due, but Flow Generate is unavailable; waiting for its control.');last_delay=shot['id']
                    if ready:
                        B.guard(page,cancel)
                        if tracker.fatal:raise UserError(tracker.fatal)
                        if B.normalize(page.locator(controls['prompt']).evaluate('(e)=>e.value ?? e.innerText'))!=B.normalize(shot['prompt']):
                            raise UserError('The next prompt changed before Generate; no new click was sent.')
                        tracker.add(shot);checkpoint() # Durable before any possibly successful click.
                        submitted_at=time.monotonic()
                        button.click(timeout=10000)
                        gap='' if last_submission is None else f' ({submitted_at-last_submission:.1f}s after previous submission)'
                        last_submission=submitted_at;next_due=submitted_at+(random.uniform(6.0,11.0) if interval else 0.0)
                        todo.pop(0);prepared=None;last_delay='';log(f'Flow shot {shot["id"]}: submitted{gap}; earlier results remain tracked.')
                if now-last_log>=10:
                    unlinked=sum(not item['ack'] for item in tracker.active.values())
                    detail=f' {unlinked} submitted prompt(s) awaiting identity metadata; timed scheduling continues.' if interval and unlinked else ''
                    if interval and not unique:detail+=' The next prompt duplicates one still in flight; waiting to keep its results distinct.'
                    log('Flow in flight: '+(', '.join(tracker.active) or 'none')+
                        f'; {len(todo)} prompts awaiting submission; {len(importer.pending)} image set(s) importing.'+detail);last_log=now
                if todo or tracker.active:
                    wait=50 if interval and todo and 0<next_due-time.monotonic()<1 else 250
                    page.wait_for_timeout(wait)
            while importer.pending:
                B.check_cancel(cancel);importer.poll()
                if importer.pending:page.wait_for_timeout(100)
            missing=[s['id'] for s in remaining if not cached_image(job,s)]
            if missing:B.flow.collect_downloads(job,folder,shot_ids=set(missing))
            missing=[s['id'] for s in remaining if not cached_image(job,s)]
            if missing:raise UserError('Capture finished but images still need import: '+', '.join(missing)+'. Receipts are retained; no shots were reassigned.')
        finally:
            page.remove_listener('request',tracker.requested);page.remove_listener('requestfinished',tracker.finished);page.remove_listener('download',tracker.downloaded)
            importer.close()
            try:spool.rmdir()
            except OSError:pass  # Retain unidentified captures for recovery.
