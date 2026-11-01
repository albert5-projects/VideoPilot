importScripts('logic.js');
const L=VideoPilotFlowLogic;
chrome.action.onClicked.addListener(async tab=>{
  if(!L.allowedPage(tab.url||''))return;
  await chrome.scripting.executeScript({target:{tabId:tab.id},files:['logic.js','editor.js','ui.js','flow.js']});
});
chrome.runtime.onMessage.addListener((msg,sender,respond)=>{
  if(sender.id!==chrome.runtime.id||!L.allowedPage(sender.tab?.url||'')){respond({ok:false,error:'Flow tab required.'});return;}
  (async()=>{
    if(msg.type==='downloadImage'){
      if(!L.assetAllowed(msg.url))throw Error('Result URL is outside supported Google image hosts. Use the manual download fallback.');
      const filename=L.safeFilename(msg.queueId,msg.shotId,msg.variant);
      const id=await chrome.downloads.download({url:msg.url,filename,saveAs:false,conflictAction:'overwrite'});
      await chrome.storage.local.set({['download:'+id]:{tabId:sender.tab.id,queueId:msg.queueId,shotId:msg.shotId}});
      return {id};
    }
    if(msg.type==='downloadReceipt'){
      const r=msg.receipt;L.safeFilename(r.queue_id,r.shot_id,1);
      if(r.complete!==true||!Array.isArray(r.variants)||r.variants.length>4)throw Error('Invalid receipt.');
      for(let i=0;i<r.variants.length;i++)if(r.variants[i].filename!==`${r.shot_id}__v${i+1}.png`)throw Error('Invalid variant name.');
      const filename=`VideoPilot/${r.queue_id}/${r.shot_id}.receipt.json`;
      const id=await chrome.downloads.download({url:'data:application/json;charset=utf-8,'+encodeURIComponent(JSON.stringify(r,null,2)),filename,saveAs:false,conflictAction:'overwrite'});
      await chrome.storage.local.set({['download:'+id]:{tabId:sender.tab.id,queueId:r.queue_id,shotId:r.shot_id}});
      return {id};
    }
    if(msg.type==='downloadStatus'){
      const owned=(await chrome.storage.local.get('download:'+msg.id))['download:'+msg.id];
      if(!owned||owned.tabId!==sender.tab.id)throw Error('Download does not belong to this Flow tab.');
      const [item]=await chrome.downloads.search({id:msg.id});
      return {state:item?.state||'missing',error:item?.error||'',filename:item?.filename?.split(/[\\/]/).pop()||''};
    }
    throw Error('Unknown message.');
  })().then(data=>respond({ok:true,...data}),err=>respond({ok:false,error:err.message}));
  return true;
});
