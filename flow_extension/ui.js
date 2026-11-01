/* Visible DOM interactions only. Synthetic events cannot guarantee acceptance. */
(function(root){
  function activate(button){
    button.scrollIntoView({block:'nearest',inline:'nearest'});
    button.focus({preventScroll:true});
    const r=button.getBoundingClientRect();
    const base={bubbles:true,cancelable:true,composed:true,view:root,clientX:r.left+r.width/2,clientY:r.top+r.height/2,button:0};
    for(const type of ['pointerdown','mousedown','pointerup','mouseup','click']){
      if(!button.isConnected||button.disabled||button.getAttribute('aria-disabled')==='true')break;
      const Event=type.startsWith('pointer')?root.PointerEvent:root.MouseEvent;
      button.dispatchEvent(new Event(type,{...base,buttons:type.endsWith('down')?1:0,pointerId:1,pointerType:'mouse',isPrimary:true,detail:1}));
    }
  }
  function createScanner({document,visible,style,Image,allowed}){
    const cache=new Map();
    return function scan(){
      const assets=new Map();
      const add=(url,width,height,loaded)=>{if(url&&!assets.has(url))assets.set(url,{src:url,naturalWidth:width,naturalHeight:height,complete:loaded,allowed:allowed(url)});};
      for(const img of document.images)if(visible(img))add(img.currentSrc||img.src,img.naturalWidth,img.naturalHeight,img.complete);
      // Result cards may use CSS backgrounds instead of <img> elements.
      for(const el of document.querySelectorAll('*')){
        if(!visible(el))continue;
        for(const match of (style(el).backgroundImage||'').matchAll(/url\(\s*(?:"([^"]*)"|'([^']*)'|([^)]*))\s*\)/g)){
          const url=(match[1]??match[2]??match[3]).trim();
          if(!allowed(url)){add(url,0,0,false);continue;}
          let img=cache.get(url);
          if(!img){img=new Image();cache.set(url,img);img.src=url;}
          add(url,img.naturalWidth,img.naturalHeight,img.complete);
        }
      }
      for(const url of cache.keys())if(!assets.has(url))cache.delete(url);
      return [...assets.values()];
    };
  }
  function classify(assets,before,aspect,fits){
    const fresh=assets.filter(a=>!before.has(a.src));
    const accepted=fresh.filter(a=>a.allowed&&a.complete&&fits(a.naturalWidth,a.naturalHeight,aspect));
    const reasons=[...new Set(fresh.filter(a=>!accepted.includes(a)).map(a=>!a.allowed?'unsupported image host':!a.complete||!a.naturalWidth?'image still loading':`${a.naturalWidth}x${a.naturalHeight} (need 512px minimum short side and ${aspect})`))];
    return {fresh,accepted,reasons};
  }
  const api={activate,createScanner,classify};root.VideoPilotFlowUI=api;
  if(typeof module!=='undefined')module.exports=api;
})(globalThis);
