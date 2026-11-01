/* Local browser controller UI. No extension or synthetic Generate events. */
(settings)=>{
  window.__vpBrowser?.cleanup?.();
  document.getElementById('videopilot-browser-panel')?.remove();
  const host=document.createElement('div');host.id='videopilot-browser-panel';
  host.style.cssText='position:fixed;top:16px;right:16px;z-index:2147483647;width:330px';
  const ui=host.attachShadow({mode:'open'});document.documentElement.append(host);
  // Flow enforces Trusted Types. Build the panel with DOM nodes rather than
  // HTML strings, leaving the site's policy intact (no permissive policy).
  function element(tag,parent,text='',id=''){
    const node=document.createElement(tag);
    if(id)node.id=id;
    node.textContent=text;
    if(tag==='button')node.type='button';
    parent.append(node);return node;
  }
  element('style',ui,'*{box-sizing:border-box}section{background:#142130;color:white;padding:18px;border:1px solid #62dbc2;border-radius:12px;font:14px/1.5 system-ui}button{padding:8px;margin:5px 3px;cursor:pointer}label{display:block;margin:10px 0}#status{white-space:pre-wrap}');
  const section=element('section',ui);
  element('b',section,'VideoPilot browser connection');
  element('p',section,'','settings');
  element('p',section,'Choose each control below, then click it in Flow. Selection does not generate.');
  element('button',section,'Choose prompt','prompt');
  element('button',section,'Choose Generate','generate');
  const parallelLabel=element('label',section,'Submission timing ');
  const parallel=element('select',parallelLabel,'','parallel');
  for(const [value,text] of [['timed','Random 6–11 seconds (recommended)'],['1','Wait for each image'],['2','Up to 2 in flight'],['3','Up to 3 in flight']]){
    const option=element('option',parallel,text);option.value=value;
  }
  parallel.value='timed';
  element('p',section,'Timed mode submits the next prompt after a new random delay of 6–11 seconds, including decimals, from the previous click, without waiting for images. Flow can delay submissions if Generate is unavailable. Images are captured later using Recover generated images.');
  const label=element('label',section);
  element('input',label,'','confirm').type='checkbox';
  element('span',label,' I checked Image mode, ratio, output count and model cost.');
  element('button',section,'Start queue','ready');
  element('p',section,"Choose Flow's prompt and Generate controls.",'status');
  const $=id=>ui.getElementById(id),say=s=>{$('status').textContent=s;};
  $('settings').textContent=`${settings.shots} remaining shots / ${settings.aspect} / ${settings.outputs} image(s) per prompt`;
  const state=window.__vpBrowser={ready:false,controls:{},selectors:{}};
  const editable='textarea,input[type="text"],[contenteditable="true"],[contenteditable=""],[contenteditable="plaintext-only"]';
  function selector(el){
    if(el.id&&document.querySelectorAll('#'+CSS.escape(el.id)).length===1)return '#'+CSS.escape(el.id);
    for(const attr of ['data-testid','aria-label','placeholder']){
      const val=el.getAttribute(attr);if(!val)continue;
      const s=el.tagName.toLowerCase()+`[${attr}=${JSON.stringify(val)}]`;
      if(document.querySelectorAll(s).length===1)return s;
    }
    const parts=[];
    for(let n=el;n&&n!==document.documentElement;n=n.parentElement){
      const sib=[...n.parentElement.children].filter(x=>x.tagName===n.tagName);
      parts.unshift(n.tagName.toLowerCase()+`:nth-of-type(${sib.indexOf(n)+1})`);
    }
    return 'html>'+parts.join('>');
  }
  let selecting=false;
  function pick(kind){
    if(selecting)return;selecting=true;host.style.pointerEvents='none';say('Click Flow\'s '+kind+' control. Escape cancels.');
    const types=['pointerdown','pointerup','mousedown','mouseup'];
    const block=e=>{e.preventDefault();e.stopImmediatePropagation();};
    const cleanup=()=>{selecting=false;host.style.pointerEvents='auto';for(const t of types)document.removeEventListener(t,block,true);document.removeEventListener('click',click,true);document.removeEventListener('keydown',key,true);};
    state.cleanup=cleanup;
    const key=e=>{if(e.key==='Escape'){cleanup();say('Selection cancelled.');}};
    const click=e=>{
      block(e);cleanup();let el=e.target.closest(kind==='prompt'?editable:'button,[role="button"]');
      // Select the editing host, not a nested rich-text block.
      if(kind==='prompt'&&el){
        while(el.parentElement?.isContentEditable)el=el.parentElement;
      }
      if(!el){say('Select the actual '+kind+' control.');return;}
      state.controls[kind]=el;state.selectors[kind]=selector(el);
      say(`Prompt: ${state.controls.prompt?'selected':'missing'} / Generate: ${state.controls.generate?'selected':'missing'}`);
    };
    for(const t of types)document.addEventListener(t,block,true);
    document.addEventListener('click',click,true);document.addEventListener('keydown',key,true);
  }
  $('prompt').onclick=()=>pick('prompt');$('generate').onclick=()=>pick('generate');
  $('ready').onclick=()=>{
    if(!state.controls.prompt?.isConnected||!state.controls.generate?.isConnected){say('Select both current controls first.');return;}
    if(!$('confirm').checked){say('Check Flow settings and confirm them first.');return;}
    state.selectors.interval=parallel.value==='timed'?6:0;
    state.selectors.parallel=parallel.value==='timed'?0:Number(parallel.value);
    state.ready=true;host.remove();
  };
}
