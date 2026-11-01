/* Operates only visible UI after user calibration. No hidden APIs, cookie access,
   network interception, login handling, anti-bot evasion, or automatic retries. */
(async()=>{
  const L=globalThis.VideoPilotFlowLogic;
  const E=globalThis.VideoPilotFlowEditor;
  const U=globalThis.VideoPilotFlowUI;
  if(!L.allowedPage(location.href))return;
  if(globalThis.__videoPilotPanel){globalThis.__videoPilotPanel.hidden=false;return;}
  const host=document.createElement('div');globalThis.__videoPilotPanel=host;
  host.style.cssText='position:fixed;right:12px;top:80px;width:340px;z-index:2147483647;';
  const shadow=host.attachShadow({mode:'closed'});document.documentElement.append(host);
  shadow.innerHTML=`<style>:host{all:initial}*{box-sizing:border-box}section{background:#142130;color:#edf5ff;border:1px solid #496374;border-radius:16px;padding:16px;font:13px/1.45 system-ui;box-shadow:0 10px 40px #0008;max-height:80vh;overflow:auto}h2{font-size:18px;margin:0 0 8px}p{color:#b9d0de}button{cursor:pointer;background:#2b4f64;color:white;border:0;border-radius:7px;padding:8px;margin:3px}button.primary{background:#62dbc2;color:#092421;font-weight:700}button:disabled{opacity:.4;cursor:default}input[type=file]{width:100%;margin:10px 0}small{display:block;color:#a9bdcb}#status{white-space:pre-wrap;background:#0a1520;padding:10px;border-radius:8px;margin-top:10px}summary{cursor:pointer;margin:8px 0}label{display:block;margin:10px 0}</style>
  <section><h2>VideoPilot · Flow 0.2.5 <button id="hide" style="float:right">×</button></h2><small>Uses this tab's normal session. No API key.</small>
  <input id="file" type="file" accept=".json,application/json"><div id="info">Load FLOW_QUEUE.json from your VideoPilot project.</div>
  <details open><summary>One-time controls for this page</summary><p>Choose the prompt box, then click inside Flow's typing area. To enable a disabled Generate button, first type a temporary word such as "test" without submitting it. Then choose Generate below and click Flow's button. Selection does not submit a generation. Run queue replaces the temporary text.</p><button id="pickPrompt">Choose prompt box</button><button id="pickGenerate">Choose Generate button</button><small id="mapped">Controls not selected.</small></details>
  <label><input id="confirmed" type="checkbox"> I set Flow to <b>Image</b> mode, the ratio/output count shown above, and checked its model/usage cost.</label>
  <button class="primary" id="start">Run queue</button><button id="stop">Stop</button><button id="retry">Retry unresolved shot</button>
  <div id="status">Ready. Keep this Flow tab open and avoid other generation while the queue runs.</div>
  <details><summary>If the page changes</summary><p>This experimental helper saves newly visible Google-hosted image assets. It requires a 512px minimum short side and matching aspect ratio. It cannot guarantee the original full-resolution download. If Flow shows only smaller previews, a menu, login or a challenge, stop and use Flow's own download button, then import images in VideoPilot.</p><p>The first returned variant is selected automatically. Other variants stay available for review in VideoPilot.</p></details></section>`;
  const $=id=>shadow.getElementById(id);const say=text=>{$('status').textContent=text;};
  let queue=null,state=null,running=false,stopped=false,promptNode=null,generateNode=null,selectors={},controlLabels={};
  const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
  const stateKey=()=>`queue:${queue.queue_id}`;
  const save=()=>chrome.storage.local.set({[stateKey()]:state});
  function visible(el){return el instanceof Element&&el.getClientRects().length>0&&getComputedStyle(el).visibility!=='hidden';}
  function css(el){
    if(el.id&&document.querySelectorAll('#'+CSS.escape(el.id)).length===1)return '#'+CSS.escape(el.id);
    for(const attr of ['data-testid','aria-label','placeholder']){
      const value=el.getAttribute(attr);if(value){const sel=el.tagName.toLowerCase()+`[${attr}=${JSON.stringify(value)}]`;if(document.querySelectorAll(sel).length===1)return sel;}
    }
    const parts=[];let n=el;
    while(n&&n!==document.documentElement){let s=n.tagName.toLowerCase();if(n.parentElement){const siblings=[...n.parentElement.children].filter(x=>x.tagName===n.tagName);if(siblings.length>1)s+=`:nth-of-type(${siblings.indexOf(n)+1})`;}parts.unshift(s);n=n.parentElement;}
    return 'html > '+parts.join(' > ');
  }
  function map(kind){
    if(running)return;say('Click the Flow '+(kind==='prompt'?'prompt text box':'Generate button')+'. Press Escape to cancel.');
    host.style.pointerEvents='none';
    const block=e=>{e.preventDefault();e.stopImmediatePropagation();};
    const pointerEvents=['pointerdown','mousedown','pointerup','mouseup'];
    const cancel=()=>{document.removeEventListener('click',click,true);document.removeEventListener('keydown',escape,true);for(const type of pointerEvents)document.removeEventListener(type,block,true);host.style.pointerEvents='auto';};
    const escape=e=>{if(e.key==='Escape'){cancel();say('Control selection cancelled.');}};
    const click=e=>{
      e.preventDefault();e.stopImmediatePropagation();
      let chosen=kind==='prompt'?e.target.closest('textarea,[contenteditable="true"],[contenteditable=""],[contenteditable="plaintext-only"],[role="textbox"],input[type="text"]'):e.target.closest('button,[role="button"]');
      cancel();
      if(!chosen){say('That is not a supported '+kind+' control. Try again.');return;}
      if(kind==='prompt'){try{chosen=E.editorRoot(chosen);}catch(error){say(error.message);return;}}
      if(kind==='prompt'&&chosen.tagName==='INPUT'&&chosen.type==='password'){say('Password fields are never supported.');return;}
      if(kind==='prompt')promptNode=chosen;else generateNode=chosen;
      selectors[kind]=css(chosen);controlLabels[kind]=(chosen.getAttribute('aria-label')||'').trim();$('mapped').textContent=`Prompt: ${promptNode?'selected':'missing'} · Generate: ${generateNode?'selected':'missing'}`;say('Control selected.');
    };
    document.addEventListener('click',click,true);document.addEventListener('keydown',escape,true);
    for(const type of pointerEvents)document.addEventListener(type,block,true);
  }
  function resolve(kind){
    const check=el=>{if(kind==='generate'&&controlLabels[kind]&&(el.getAttribute('aria-label')||'').trim()!==controlLabels[kind])throw Error('Generate control label changed. Re-select it before continuing.');return el;};
    const node=kind==='prompt'?promptNode:generateNode;if(node?.isConnected&&visible(node))return check(node);
    const nodes=selectors[kind]?[...document.querySelectorAll(selectors[kind])].filter(visible):[];
    if(nodes.length!==1)throw Error('Flow changed its '+kind+' control. Select it again; the queue has paused.');
    const found=nodes[0];
    if(kind==='generate'&&!found.matches('button,[role="button"]'))throw Error('Generate control changed. Re-select it.');
    if(kind==='prompt'&&!found.matches('textarea,[contenteditable="true"],[contenteditable=""],[contenteditable="plaintext-only"],[role="textbox"],input[type="text"]'))throw Error('Prompt control changed. Re-select it.');
    return check(found);
  }
  function checkBeforeSubmit(){
    if(stopped)throw Error('Stopped before Generate. Run queue can resume this shot.');
    if(!L.allowedPage(location.href))throw Error('Flow page changed.');problem();
  }
  async function readyToGenerate(text){
    const end=Date.now()+8000;
    while(Date.now()<=end){
      checkBeforeSubmit();
      if(!E.promptMatches(resolve('prompt'),text))throw Error('Flow changed the prompt before submission. No Generate click was sent. Re-select the prompt box and run again.');
      const button=resolve('generate');
      if(!button.disabled&&button.getAttribute('aria-disabled')!=='true')return button;
      await sleep(200);
    }
    throw Error('Generate is still disabled after the prompt was entered. Check Flow settings or finish the current generation. No Generate click was sent.');
  }
  const scanImages=U.createScanner({document,visible,style:getComputedStyle,Image,allowed:L.assetAllowed});
  function problem(){
    const text=document.body.innerText.toLowerCase();
    if(/verify (?:that )?you(?:'re| are) (?:a )?human|unusual traffic|not enough credits|insufficient credits|daily limit reached|too many requests/.test(text))throw Error('Flow shows a usage limit or verification message. Complete it yourself; VideoPilot will not bypass it or retry automatically.');
  }
  async function results(before,start){
    let stable='',since=Date.now(),detail='';
    while(Date.now()-start<240000){
      if(stopped)throw Error('Stopped with a submitted shot unresolved. Check Flow results before choosing Retry.');
      if(!L.allowedPage(location.href))throw Error('Flow page changed.');problem();
      const detected=U.classify(scanImages(),before,queue.aspect,L.imageFits);
      const unique=detected.accepted;
      const elapsed=Math.floor((Date.now()-start)/1000);
      detail=detected.reasons.join('; ');
      say(`Shot ${state.pending}: ${elapsed}s since Generate was requested.\nDetected ${unique.length}/${queue.outputs} usable new image(s).`+
        (detail?`\nOther new assets: ${detail}. Open the generated image at full size in Flow if only a small preview is shown.`:'')+
        (!detected.fresh.length&&elapsed>=15?'\nNo new image detected yet. If Flow has not started, click its Generate button once; this helper will keep watching.':'')+
        (unique.length===queue.outputs?'\nWaiting for results to settle before downloading.':''));
      if(unique.length>queue.outputs)throw Error('More new images appeared than expected. Stopped to avoid assigning unrelated images to this shot.');
      const key=unique.map(img=>img.currentSrc||img.src).sort().join('|');
      if(key!==stable){stable=key;since=Date.now();}
      if(unique.length===queue.outputs&&Date.now()-since>=8000&&Date.now()-start>=10000)return unique;
      await sleep(1000);
    }
    throw Error('No unambiguous full set of images appeared within 4 minutes. '+(detail?`Detected: ${detail}. `:'No usable new image detected. ')+'Open the result at full size in Flow or use manual download/import. No automatic retry was sent.');
  }
  async function message(msg){const r=await chrome.runtime.sendMessage(msg);if(!r?.ok)throw Error(r?.error||'Browser helper disconnected.');return r;}
  async function completed(id,expected){
    const start=Date.now();while(Date.now()-start<120000){
      const r=await message({type:'downloadStatus',id});
      if(r.state==='complete'){if(r.filename!==expected)throw Error('Browser renamed the download. Check your download settings and import it manually.');return;}
      if(r.state==='interrupted'||r.state==='missing')throw Error('Image download failed: '+r.error);await sleep(750);
    }throw Error('Download did not complete within two minutes. Check the browser downloads panel.');
  }
  async function run(){
    if(running)return;
    if(!queue){say('Load FLOW_QUEUE.json first.');return;}
    if(!$('confirmed').checked){say('Set and confirm Flow Image mode, aspect ratio, output count and model cost before running.');return;}
    if(!promptNode||!generateNode){say('Choose the two Flow controls first.');return;}
    if(state.pending){say(`Shot ${state.pending} may already have been submitted. Check Flow first. Use manual downloads/imports or explicitly choose Retry unresolved shot.`);return;}
    running=true;stopped=false;$('start').disabled=true;$('file').disabled=true;
    try{
      for(const shot of queue.shots){
        if(state.done.includes(shot.id))continue;if(stopped)break;problem();
        say(`Shot ${shot.id} · ${state.done.length}/${queue.shots.length} complete\nEntering prompt…`);
        await E.fillPrompt(()=>resolve('prompt'),shot.prompt,{check:checkBeforeSubmit});
        // A DOM click doesn't blur the prompt as a real button interaction does.
        // Let blur-driven editor state settle, then resolve the current button.
        E.editorRoot(resolve('prompt')).blur();await sleep(250);
        say(`Shot ${shot.id}: prompt entered. Waiting for Generate to become enabled...`);
        await readyToGenerate(shot.prompt);
        const before=new Set([...scanImages().map(i=>i.src),...[...document.images].map(i=>i.currentSrc||i.src)]);
        state.pending=shot.id;await save(); // checkpoint BEFORE submission; never blindly duplicate requests
        // Storage is asynchronous: recheck the current editor and button after
        // saving. Clear the checkpoint if no submission was attempted.
        let generate;
        try{generate=await readyToGenerate(shot.prompt);}
        catch(error){state.pending=null;await save();throw error;}
        U.activate(generate);say(`Generate requested for ${shot.id}. Watching Flow for new images...`);
        const found=await results(before,Date.now());const variants=[];
        for(let i=0;i<found.length;i++){
          if(stopped)throw Error('Stopped before remaining downloads. Check Flow before retrying.');
          const img=found[i],filename=`${shot.id}__v${i+1}.png`;
          const {id}=await message({type:'downloadImage',queueId:queue.queue_id,shotId:shot.id,variant:i+1,url:img.currentSrc||img.src});
          await completed(id,filename);variants.push({filename,width:img.naturalWidth,height:img.naturalHeight});
        }
        const receipt={queue_id:queue.queue_id,shot_id:shot.id,complete:true,variants,source:'Flow visible image assets',created_at:new Date().toISOString()};
        const {id}=await message({type:'downloadReceipt',receipt});await completed(id,`${shot.id}.receipt.json`);
        state.done.push(shot.id);state.pending=null;await save();say(`Saved ${shot.id}. ${state.done.length}/${queue.shots.length} complete.`);await sleep(3000);
      }
      if(state.done.length===queue.shots.length)say('Image queue finished. VideoPilot will collect the downloads. Review the selected images before finishing your CapCut edit.');
      else say('Stopped between shots. Run queue resumes the remaining shots.');
    }catch(e){say(e.message);}
    finally{running=false;$('start').disabled=false;$('file').disabled=false;}
  }
  $('file').addEventListener('change',async()=>{
    try{
      const file=$('file').files[0];if(!file||file.size>20*1024*1024)throw Error('Queue file missing or too large.');
      queue=L.validateQueue(JSON.parse(await file.text()));state=(await chrome.storage.local.get(stateKey()))[stateKey()]||{done:[],pending:null};
      $('info').textContent=`${queue.shots.length} shots · ${queue.aspect} · ${queue.outputs} image(s) per prompt\nDownloads/${queue.download_folder}`;
      $('confirmed').checked=false;say(`Queue loaded. ${state.done.length} shots already saved.`);
    }catch(e){queue=null;say(e.message);}
  });
  $('pickPrompt').onclick=()=>map('prompt');$('pickGenerate').onclick=()=>map('generate');
  $('start').onclick=run;$('stop').onclick=()=>{stopped=true;say('Stop requested. A submitted generation may still finish in Flow.');};
  $('hide').onclick=()=>{if(running){stopped=true;say('Stop requested. Close the panel after the queue stops.');}else host.hidden=true;};
  $('retry').onclick=async()=>{
    if(running||!queue||!state.pending){say('No paused unresolved shot to retry.');return;}
    if(confirm(`Retry shot ${state.pending}? It may have generated already. This can consume additional Flow usage. Only continue after checking Flow.`)){
      $('retry').disabled=true;
      try{state.pending=null;await save();await run();}
      catch(error){say(error.message);}
      finally{$('retry').disabled=false;}
    }
  };
})();
