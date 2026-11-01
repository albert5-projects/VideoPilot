"""User-signed-in, dedicated Chrome/Edge browser; Playwright drives visible UI.

No passwords, cookie export, undocumented generation API, or automatic retries.
The external browser stays open when the controller disconnects.
"""
from __future__ import annotations
import base64, hashlib, io, json, os, re, subprocess, time, unicodedata
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import build_opener, ProxyHandler
from .core import DATA, UserError, Cancelled, atomic_json, read_json
from . import flow

PROFILE=DATA/'flow-browser-profile'
UI=Path(__file__).with_name('flow_browser_ui.js')

def allowed_page(url):
    u=urlsplit(url)
    return u.scheme=='https' and (u.hostname=='flow.google.com' or
        (u.hostname=='labs.google' and re.match(r'^/fx/(?:[a-z-]+/)?tools/flow(?:/|$)',u.path) is not None))

def browser_executable():
    for env,relative in [('PROGRAMFILES','Google/Chrome/Application/chrome.exe'),
                         ('PROGRAMFILES(X86)','Microsoft/Edge/Application/msedge.exe'),
                         ('LOCALAPPDATA','Google/Chrome/Application/chrome.exe'),
                         ('PROGRAMFILES','Microsoft/Edge/Application/msedge.exe')]:
        base=os.environ.get(env)
        if base and (path:=Path(base)/relative).is_file():return path
    raise UserError('Install Google Chrome or Microsoft Edge, then open the Flow browser again.')

def endpoint(profile=PROFILE):
    """Accept only the loopback endpoint written by our dedicated browser."""
    try:
        lines=(profile/'DevToolsActivePort').read_text().splitlines()
        port=int(lines[0]); path=lines[1]
        if not 1024<=port<=65535 or not re.fullmatch(r'/devtools/browser/[a-zA-Z0-9-]+',path):return None
        address=f'http://127.0.0.1:{port}'
        with build_opener(ProxyHandler({})).open(address+'/json/version',timeout=1) as response:
            data=json.load(response)
        ws=urlsplit(data.get('webSocketDebuggerUrl',''))
        if ws.hostname not in ('localhost','127.0.0.1') or ws.port!=port or ws.path!=path:return None
        return address
    except (OSError,ValueError,IndexError):return None

def profile_processes(profile):
    """Check only browser processes using our profile; never inspect stored sessions."""
    if os.name!='nt':raise UserError('This browser launcher currently supports Windows only.')
    env=os.environ.copy();env['VIDEOPILOT_PROFILE']=str(profile.resolve())
    script="""Get-CimInstance Win32_Process -Filter \"Name = 'chrome.exe' OR Name = 'msedge.exe'\" -ErrorAction Stop |
      Where-Object { $_.CommandLine -and $_.CommandLine.IndexOf($env:VIDEOPILOT_PROFILE,[StringComparison]::OrdinalIgnoreCase) -ge 0 } |
      Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress"""
    try:
        result=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',script],
            env=env,capture_output=True,text=True,timeout=15,creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode:raise ValueError('Process inspection failed')
        records=json.loads(result.stdout or '[]')
        if isinstance(records,dict):records=[records]
        pattern=r'(?:^|\s)(?:"--user-data-dir=([^"]+)"|--user-data-dir="([^"]+)"|--user-data-dir=([^\s"]+))(?=\s|$)'
        matches=[]
        for record in records:
            match=re.search(pattern,record.get('CommandLine',''))
            if match and Path(next(v for v in match.groups() if v is not None)).resolve()==profile.resolve():
                matches.append(record)
        return matches
    except (OSError,ValueError,subprocess.SubprocessError):
        raise UserError('Could not check whether the dedicated browser is running. Close its windows and try again; VideoPilot has not launched another browser.') from None

def open_signin_browser(cancel=None,profile=PROFILE):
    """Manual sign-in in ordinary Chrome/Edge: no debugger or controller attached."""
    check_cancel(cancel)
    # Chrome forwards new launches to an existing process for this profile.
    # Refuse reuse so a sign-in launch cannot inherit its debugging switches.
    if profile_processes(profile) or endpoint(profile):
        raise UserError('Close all VideoPilot browser windows first, then click Open Flow / sign in again. Your everyday Chrome/Edge windows can stay open.')
    profile.mkdir(parents=True,exist_ok=True)
    subprocess.Popen([str(browser_executable()),f'--user-data-dir={profile.resolve()}',
        '--no-first-run',flow.FLOW_URL],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)

def open_browser(cancel=None,profile=PROFILE):
    check_cancel(cancel)
    if address:=endpoint(profile):return address
    if profile_processes(profile):
        raise UserError('Close the dedicated sign-in browser window after signing in, then click Run Flow queue. VideoPilot will reopen that same profile for generation.')
    profile.mkdir(parents=True,exist_ok=True)
    # Visible browser explicitly requested by the user. Never use their everyday profile.
    process=subprocess.Popen([str(browser_executable()),f'--user-data-dir={profile.resolve()}',
        '--remote-debugging-address=127.0.0.1','--remote-debugging-port=0','--no-first-run',flow.FLOW_URL],
        stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    until=time.monotonic()+20
    while time.monotonic()<until:
        check_cancel(cancel)
        if address:=endpoint(profile):return address
        if process.poll() is not None and process.returncode:break
        time.sleep(.25)
    raise UserError('Could not connect to the dedicated Flow browser. Close all its windows and try Run Flow queue again. Your normal Chrome/Edge windows can stay open.')

def check_cancel(cancel):
    if cancel is not None and cancel.is_set():raise Cancelled('Flow browser stopped. Completed images are retained; submitted shots are not retried automatically.')

@contextmanager
def connect(cancel=None):
    try:from playwright.sync_api import sync_playwright
    except ImportError:raise UserError('Run Setup_Flow_Browser.bat once to install browser control, then restart VideoPilot.') from None
    address=open_browser(cancel)
    lock=PROFILE/'controller.lock'
    try:fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
    except FileExistsError:raise UserError('Another controller holds the Flow browser lock. Stop it first. If it crashed, close VideoPilot and remove controller.lock from the dedicated profile before restarting.') from None
    os.close(fd)
    try:
        with sync_playwright() as p:
            browser=p.chromium.connect_over_cdp(address,timeout=15000)
            context=browser.contexts[0]
            pages=[page for page in context.pages if allowed_page(page.url)]
            if len(pages)>1:raise UserError('Keep only one Flow tab open in the dedicated VideoPilot browser, then try again.')
            if not pages:
                raise UserError('Sign-in is required. Close the dedicated browser and use Open Flow / sign in. After signing in, close it and run the queue again.')
            page=pages[0];page.set_default_timeout(10000);page.bring_to_front()
            # Stop Playwright to disconnect; never close the external browser.
            yield page
    finally:lock.unlink(missing_ok=True)

def refresh_browser(cancel,log):
    """Clear dedicated-browser cookies/cache and Flow site data, then reload."""
    check_cancel(cancel)
    with connect(cancel) as page:
        session=page.context.new_cdp_session(page)
        try:
            log('Clearing Flow browser cookies, cache and site data. Google may require sign-in again.')
            session.send('Network.clearBrowserCache')
            session.send('Network.clearBrowserCookies')
            for origin in ('https://labs.google','https://flow.google.com'):
                session.send('Storage.clearDataForOrigin',{'origin':origin,'storageTypes':'all'})
            page.evaluate('()=>sessionStorage.clear()')
            session.send('Network.setCacheDisabled',{'cacheDisabled':True})
            session.send('Network.setBypassServiceWorker',{'bypass':True})
            check_cancel(cancel)
            page.reload(wait_until='domcontentloaded',timeout=60000)
            page.bring_to_front()
        finally:
            try:
                session.send('Network.setCacheDisabled',{'cacheDisabled':False})
                session.send('Network.setBypassServiceWorker',{'bypass':False})
            finally:session.detach()
    log('Flow browser cookies, cache and Flow site data cleared; page reloaded. Project files and submission records were kept. If Google requests sign-in, close the dedicated browser and use Open Flow / sign in. Recover existing results before retrying unresolved shots.')


def guard(page,cancel):
    check_cancel(cancel)
    if not allowed_page(page.url):raise UserError('Flow navigated away. If sign-in is required, close this browser and use Open Flow / sign in; then close it and run the queue again.')
    text=page.locator('body').inner_text(timeout=5000).lower()
    if re.search(r"unusual\s+activity|extensions?\s+that\s+modify\s+the\s+page",text):
        raise UserError('Flow rejected activity in this browser. Queue stopped; no further prompts will be submitted. Check Flow manually and disable page-modifying extensions in this dedicated profile. Recover any completed images before using Retry unresolved. Your script and narration are retained.')
    if re.search(r"verify (?:that )?you(?:'re| are) (?:a )?human|unusual traffic|not enough credits|insufficient credits|daily limit reached|too many requests",text):
        raise UserError('Flow shows a verification or usage-limit message. Complete it yourself in the browser; the queue has paused.')

def calibrate(page,queue,cancel,log):
    guard(page,cancel)
    page.evaluate(UI.read_text(encoding='utf-8'),{'shots':len(queue['shots']),'aspect':queue['aspect'],'outputs':queue['outputs']})
    log('In the Flow browser panel, choose the prompt and Generate controls, confirm settings, then click Start queue.')
    end=time.monotonic()+600
    try:
        while time.monotonic()<end:
            check_cancel(cancel)
            if not allowed_page(page.url):raise UserError('Sign-in is required. Close this browser and use Open Flow / sign in; then close it and run the queue again.')
            if not page.evaluate('Boolean(window.__vpBrowser)'):
                page.evaluate(UI.read_text(encoding='utf-8'),{'shots':len(queue['shots']),'aspect':queue['aspect'],'outputs':queue['outputs']})
            if page.evaluate('Boolean(window.__vpBrowser?.ready)'):
                return page.evaluate('window.__vpBrowser.selectors')
            page.wait_for_timeout(250)
    finally:
        try:page.evaluate("()=>{window.__vpBrowser?.cleanup?.();document.getElementById('videopilot-browser-panel')?.remove();}")
        except Exception:pass  # Navigation/closed tab already removed the panel.
    raise UserError('Browser setup timed out. Run the queue again when your Flow project is ready.')

def normalize(text):
    return ' '.join(unicodedata.normalize('NFC',text).replace('\u200b','').replace('\ufeff','').split())

def fill_prompt(page,selector,text,cancel):
    guard(page,cancel);field=page.locator(selector)
    if field.count()!=1:raise UserError('Flow changed its prompt field. Run again and choose the current control.')
    field.click();field.press('ControlOrMeta+A');field.press('Backspace')
    # Commit an actual deletion to rich-editor state before inserting text.
    # Replacing a selection alone can leave the calibration word in that state.
    field.press('Tab');page.wait_for_timeout(200)
    if normalize(field.evaluate('(e)=>e.value ?? e.innerText')):
        raise UserError('Flow did not clear its prompt editor. No Generate click was sent. Select the full prompt field again.')
    field.click()
    # Browser input updates the editor model (not just its DOM).
    page.keyboard.insert_text(text)
    page.wait_for_timeout(350)
    actual=field.evaluate('(e)=>e.value ?? e.innerText')
    if normalize(actual)!=normalize(text):
        raise UserError(f'Prompt did not match ({len(normalize(text))} expected, {len(normalize(actual))} read). No Generate click was sent.')
    field.press('Tab');page.wait_for_timeout(200)
    if normalize(field.evaluate('(e)=>e.value ?? e.innerText'))!=normalize(text):
        raise UserError('Flow changed the prompt after entry. No Generate click was sent.')

ASSETS_JS=r'''()=>{
 const urls=new Set();
 const add=value=>{if(value)try{urls.add(new URL(value,location.href).href);}catch{}};
 for(const img of document.images){add(img.currentSrc);add(img.src);}
 for(const el of document.querySelectorAll('*')){
   if(!el.getClientRects().length)continue;
   for(const pseudo of [null,'::before','::after']){
     const style=getComputedStyle(el,pseudo);
     for(const m of (style.backgroundImage||'').matchAll(/url\(\s*(?:"([^"]*)"|'([^']*)'|([^)]*))\s*\)/g))add(m[1]??m[2]??m[3]);
   }
 }
 return [...urls];
}'''

def decode_image(blob,aspect):
    from PIL import Image
    if len(blob)>32*1024*1024:return None
    try:
        with Image.open(io.BytesIO(blob)) as im:
            width,height=im.size;w,h=map(int,aspect.split(':'))
            if im.format not in ('PNG','JPEG','WEBP') or min(width,height)<512 or abs((width/height)/(w/h)-1)>.10:return None
            im.load();image=im.convert('RGB');out=io.BytesIO();image.save(out,'PNG')
            return {'data':out.getvalue(),'width':width,'height':height,'hash':hashlib.sha256(image.tobytes()).hexdigest()}
    except (OSError,ValueError):return None

class Results:
    """Observe image responses; associate them with new page assets, not any network image."""
    def __init__(self,page,aspect,before,folder):
        self.page=page;self.aspect=aspect;self.before=set(before);self.folder=folder
        self.candidates={};self.downloads={};self.received=0;self.errors=[];self.blobs_seen=set()
    def visible_blobs(self,urls):
        # A visible blob image may have been decoded from a fetch response, so
        # its displayed URL does not match the underlying network response URL.
        # Read only new blob assets actually referenced by the Flow page.
        for url in set(urls)-self.before-self.blobs_seen:
            if not url.startswith(('blob:https://labs.google/','blob:https://flow.google.com/')):continue
            self.blobs_seen.add(url)
            try:
                encoded=self.page.evaluate('''async url=>{
                  const response=await fetch(url,{signal:AbortSignal.timeout(5000)});
                  const blob=await response.blob();
                  if(!blob.type.startsWith('image/')||blob.size>32*1024*1024)return null;
                  return await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result.split(',')[1]);reader.onerror=reject;reader.readAsDataURL(blob);});
                }''',url)
                if encoded:
                    image=decode_image(base64.b64decode(encoded),self.aspect)
                    if image:
                        item=self.candidates.setdefault(image['hash'],{**image,'urls':set()});item['urls'].add(url)
            except Exception:self.errors.append('A visible blob image could not be read; use its native Download control.')
    def finished(self,request):
        try:
            response=request.response()
            if not response or not response.ok or not response.headers.get('content-type','').startswith('image/'):return
            aliases=set();r=request
            while r is not None:aliases.add(r.url);r=r.redirected_from
            if aliases & self.before:return
            self.received+=1
            if int(response.headers.get('content-length','0'))>32*1024*1024:return
            image=decode_image(response.body(),self.aspect)
            if image:
                item=self.candidates.setdefault(image['hash'],{**image,'urls':set()})
                item['urls'].update(aliases)
        except Exception:self.errors.append('An image response could not be read.')
    def downloaded(self,download):
        # Also accepts Flow's native download control while this shot is pending.
        path=self.folder/'browser-download.partial'
        try:
            download.save_as(str(path));image=decode_image(path.read_bytes(),self.aspect)
            if image:self.downloads[image['hash']]=image
            else:self.errors.append('Downloaded file was not a matching image of at least 512px.')
        except Exception:self.errors.append('Flow download failed.')
        finally:path.unlink(missing_ok=True)
    def accepted(self,visible):
        fresh=set(visible)-self.before
        found={key:item for key,item in self.candidates.items() if item['urls']&fresh}
        found.update(self.downloads)
        return found

def wait_results(page,results,outputs,cancel,log,timeout=240):
    start=time.monotonic();stable=None;since=start;last_log=-10
    while time.monotonic()-start<timeout:
        guard(page,cancel)
        visible=page.evaluate(ASSETS_JS);results.visible_blobs(visible)
        found=results.accepted(visible);keys=tuple(sorted(found))
        if len(found)>outputs:raise UserError('More matching images appeared than expected. The shot is unresolved; check Flow before retrying.')
        if keys!=stable:stable=keys;since=time.monotonic()
        if len(found)==outputs and time.monotonic()-since>=5:return list(found.values())
        elapsed=int(time.monotonic()-start)
        if elapsed-last_log>=10:
            log(f'Flow: {elapsed}s; {len(found)}/{outputs} matching images; {results.received} new image responses. '+
                ('If the result is visible but not captured, use its Download button in Flow; the controller is listening.' if elapsed>=30 else 'Waiting for results.'))
            last_log=elapsed
        page.wait_for_timeout(250)
    reason=' '+results.errors[-1] if results.errors else ''
    raise UserError('No complete matching image set arrived within four minutes.'+reason+' Check Flow. The shot remains unresolved and was not retried.')

def validate_queue(q):
    if (not isinstance(q,dict) or q.get('version')!=1 or not re.fullmatch(r'[a-f0-9]{24}',str(q.get('queue_id',''))) or
        q.get('aspect') not in ('9:16','16:9','1:1') or q.get('outputs') not in (1,2,3,4) or
        not isinstance(q.get('shots'),list) or not 1<=len(q['shots'])<=1000):
        raise UserError('Invalid Flow queue. Continue the project to rebuild it.')
    ids=set()
    for s in q['shots']:
        if (not isinstance(s,dict) or not re.fullmatch(r'\d{3,4}_\d{2,4}',str(s.get('id',''))) or s['id'] in ids or
            not isinstance(s.get('prompt'),str) or not s['prompt'].strip() or len(s['prompt'])>20000):
            raise UserError('Invalid or duplicate shot in Flow queue.')
        ids.add(s['id'])
    return q

def state_path(job,queue):
    validate_queue(queue)
    return job.folder/('flow-browser-'+queue['queue_id']+'.json')

def pending_shot(job):
    pending=pending_shots(job)
    return pending[0] if pending else None


def pending_shots(job):
    if not (job.folder/'FLOW_QUEUE.json').exists():return []
    q=read_json(job.folder/'FLOW_QUEUE.json');path=state_path(job,q)
    if not path.exists():return []
    state=read_json(path);ids=list(state.get('inflight',{}))
    if state.get('pending') and state['pending'] not in ids:ids.insert(0,state['pending'])
    return ids

def clear_pending(job):
    job.require_mutable();q=read_json(job.folder/'FLOW_QUEUE.json');path=state_path(job,q)
    if path.exists():
        state=read_json(path);state['pending']=None;state['inflight']={};atomic_json(path,state)

def save_results(job,queue,shot,images,import_now=True):
    root=job.folder/'browser-downloads';folder=root/'VideoPilot'/queue['queue_id'];folder.mkdir(parents=True,exist_ok=True)
    variants=[]
    for i,image in enumerate(images,1):
        name=f'{shot["id"]}__v{i}.png';path=folder/name;temp=path.with_suffix('.partial')
        temp.write_bytes(image['data']);os.replace(temp,path)
        captured=image.get('path')
        if captured and Path(captured).is_file() and Path(captured).resolve().is_relative_to(root.resolve()):
            from .storage import share_identical_file
            share_identical_file(captured,path)
        variants.append({'filename':name,'width':image['width'],'height':image['height'],
                         'result_urls':sorted(image.get('urls',[])),'pixel_hash':image.get('hash'),'sha256':hashlib.sha256(image['data']).hexdigest()})
    atomic_json(folder/f'{shot["id"]}.receipt.json',{'queue_id':queue['queue_id'],'shot_id':shot['id'],'complete':True,'variants':variants,'prompt_hash':hashlib.sha256(normalize(shot['prompt']).encode()).hexdigest(),'matching_version':5,'source':'Flow signed-in browser'})
    if import_now:flow.collect_downloads(job,root)

def recover(job,cancel,log,verify_existing=False,order='reverse'):
    if order not in ('reverse','forward'):raise UserError('Choose reverse or normal recovery order.')
    job.require_mutable()
    if not (job.folder/'FLOW_QUEUE.json').exists():raise UserError('Prepare the Flow queue first.')
    lock=job.folder/'run.lock'
    try:fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
    except FileExistsError:raise UserError('Stop the current project operation before recovering images.') from None
    os.close(fd)
    try:
        q=validate_queue(read_json(job.folder/'FLOW_QUEUE.json'));path=state_path(job,q)
        state=read_json(path) if path.exists() else {'pending':None}
        from .pipeline import cached_image
        flow.collect_downloads(job)
        from .image_audit import audit_images
        if audit_images(job,q)['near_duplicate_automatic_imports']:verify_existing=True
        for shot in q['shots']:
            metadata=job.folder/'images'/(shot['id']+'.json')
            if metadata.is_file():
                meta=read_json(metadata)
                if meta.get('source')=='Google Flow browser helper' and meta.get('matching_version')!=5:verify_existing=True
        if not verify_existing and all(cached_image(job,shot) for shot in q['shots']):
            log('All Flow images are imported; no browser recovery needed.')
            return
        with connect(cancel) as page:
            from .flow_recovery import recover_queue
            recover_queue(job,q,page,state,path,cancel,log,verify_existing=verify_existing,imports_collected=True,order=order)
    finally:lock.unlink(missing_ok=True)


def run(job,cancel,log):
    from .pipeline import cached_image
    job.require_mutable()
    if not (job.folder/'FLOW_QUEUE.json').exists():raise UserError('Continue the project to prepare narration and the Flow queue first.')
    lock=job.folder/'run.lock'
    try:fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
    except FileExistsError:raise UserError('Another operation holds run.lock. Close other project operations before generating images.') from None
    os.close(fd)
    try:
        q=read_json(job.folder/'FLOW_QUEUE.json');path=state_path(job,q)
        state=read_json(path) if path.exists() else {'pending':None}
        # Recover receipt-written/import-interrupted runs without new generation.
        flow.collect_downloads(job,job.folder/'browser-downloads')
        remaining=[s for s in q['shots'] if not cached_image(job,s)]
        remaining_ids={s['id'] for s in remaining}
        if state.get('inflight'):
            state['inflight']={sid:item for sid,item in state['inflight'].items() if sid in remaining_ids}
            state['pending']=next(iter(state['inflight']),None);atomic_json(path,state)
        if state.get('pending') and state['pending'] not in [s['id'] for s in remaining]:
            state['pending']=None;atomic_json(path,state)
        if state.get('pending'):
            ids=', '.join(state.get('inflight') or [state['pending']])
            raise UserError(f'Flow shots {ids} are unresolved. Use Recover generated images to collect existing Flow results before considering Retry unresolved.')
        if not remaining:log('All Flow images are already collected.');return
        with connect(cancel) as page:
            controls=calibrate(page,{**q,'shots':remaining},cancel,log)
            from .flow_concurrent import submit_queue
            submit_queue(job,q,remaining,page,controls,state,path,cancel,log)
    finally:lock.unlink(missing_ok=True)
