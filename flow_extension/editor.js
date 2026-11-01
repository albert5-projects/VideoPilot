/* Visible prompt editor interaction. No framework state or hidden APIs. */
(function(root){
  const editable='textarea,input[type="text"],[contenteditable="true"],[contenteditable=""],[contenteditable="plaintext-only"]';
  function normalizePrompt(value){
    return String(value??'').normalize('NFC').replace(/[\u200b\ufeff]/g,'').replace(/\s+/gu,' ').trim();
  }
  function editorRoot(selected){
    if(!selected?.isConnected)throw Error('The prompt field was replaced. Re-select the current Flow prompt box.');
    if(selected.matches(editable))return selected;
    const parent=selected.closest(editable);
    if(parent)return parent;
    const children=[...selected.querySelectorAll(editable)];
    // Only a unique, outermost editable area is safe to target.
    const outer=children.filter(node=>!children.some(other=>other!==node&&other.contains(node)));
    if(outer.length!==1)throw Error('Select inside the actual Flow typing area, rather than its surrounding panel.');
    return outer[0];
  }
  function readPrompt(selected){
    const el=editorRoot(selected);
    if(el.matches('textarea,input'))return el.value;
    const blocks=new Set(['DIV','P','LI','UL','OL','PRE','BLOCKQUOTE','H1','H2','H3','H4','H5','H6']);
    function text(node){
      if(node.nodeType===3)return node.nodeValue||'';
      if(node.nodeType!==1)return '';
      if(node.hidden||node.getAttribute('aria-hidden')==='true'||node.hasAttribute('data-slate-placeholder')||['SCRIPT','STYLE'].includes(node.tagName))return '';
      if(node.tagName==='BR')return '\n';
      const value=[...node.childNodes].map(text).join('');
      return blocks.has(node.tagName)?'\n'+value+'\n':value;
    }
    return [...el.childNodes].map(text).join('');
  }
  const promptMatches=(selected,expected)=>normalizePrompt(readPrompt(selected))===normalizePrompt(expected);
  async function fillPrompt(resolve,text,options={}){
    const sleep=options.sleep||(ms=>new Promise(r=>setTimeout(r,ms)));
    const check=options.check||(()=>{});
    check();
    const el=editorRoot(resolve());el.focus();
    if(el.matches('textarea,input')){
      const ctor=el.tagName==='TEXTAREA'?root.HTMLTextAreaElement:root.HTMLInputElement;
      Object.getOwnPropertyDescriptor(ctor.prototype,'value').set.call(el,text);
      el.dispatchEvent(new root.InputEvent('input',{bubbles:true,composed:true,inputType:'insertText',data:text}));
      el.dispatchEvent(new root.Event('change',{bubbles:true}));
    }else{
      const selection=root.getSelection(),range=root.document.createRange();
      range.selectNodeContents(el);selection.removeAllRanges();selection.addRange(range);
      // Rich editors (including Slate) synchronize their model selection from
      // selectionchange asynchronously. Pasting in this same turn can insert
      // at the old caret and leave the previous prompt or calibration word.
      root.document.dispatchEvent(new root.Event('selectionchange'));
      await sleep(options.selectionSettleMs??250);
      check();
      if(editorRoot(resolve())!==el)throw Error('Flow replaced the prompt field while selecting its text. Run queue again. No Generate click was sent.');
      if(!selection.rangeCount||!el.contains(selection.anchorNode)||!el.contains(selection.focusNode))throw Error('Prompt selection moved before insertion. Select the prompt box and run again. No Generate click was sent.');
      // Slate handles paste through its own model. execCommand alone can
      // change the visible DOM without enabling Generate in the application.
      const clipboard=new root.DataTransfer();clipboard.setData('text/plain',text);
      const paste=new root.ClipboardEvent('paste',{clipboardData:clipboard,bubbles:true,cancelable:true,composed:true});
      el.dispatchEvent(paste);
      // An unhandled synthetic paste has no browser default action. Fall back
      // only when the editor did not handle it, avoiding duplicate insertion.
      if(!paste.defaultPrevented){
        const inserted=root.document.execCommand('insertText',false,text);
        if(!inserted&&!promptMatches(resolve(),text))throw Error('Flow rejected text insertion. Re-select inside its prompt typing area.');
      }
    }
    const end=Date.now()+(options.timeoutMs??4000),stableMs=options.stableMs??300;
    let since=null,actual='',lastError='';
    while(Date.now()<=end){
      check();
      try{
        // Re-resolve after every render instead of reading a detached node.
        actual=readPrompt(resolve());
        if(normalizePrompt(actual)===normalizePrompt(text)){
          since??=Date.now();
          if(Date.now()-since>=stableMs)return;
        }else since=null;
        lastError='';
      }catch(error){since=null;lastError=error.message;}
      await sleep(options.intervalMs??100);
    }
    if(lastError)throw Error(lastError+' No Generate click was sent.');
    throw Error(`Prompt check failed: expected ${normalizePrompt(text).length} characters, read ${normalizePrompt(actual).length}. No Generate click was sent. Re-select inside the prompt typing area and run again. If it still fails, use Flow's manual Generate and import its downloaded image in VideoPilot.`);
  }
  const api={normalizePrompt,editorRoot,readPrompt,promptMatches,fillPrompt};
  root.VideoPilotFlowEditor=api;if(typeof module!=='undefined')module.exports=api;
})(globalThis);
