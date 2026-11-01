/* Pure validation shared by the browser runner and Node tests. */
(function(root){
  const allowedPage=value=>{try{const u=new URL(value);return u.protocol==='https:'&&(u.hostname==='flow.google.com'||(u.hostname==='labs.google'&&/^\/fx\/(?:[a-z-]+\/)?tools\/flow(?:\/|$)/.test(u.pathname)));}catch{return false;}};
  const assetAllowed=value=>{try{const u=new URL(value);if(u.protocol==='blob:')return allowedPage(u.pathname+'/fx/tools/flow')||/^blob:https:\/\/(?:labs\.google|flow\.google\.com)\//.test(value);return u.protocol==='https:'&&(['labs.google','flow.google.com','storage.googleapis.com'].includes(u.hostname)||u.hostname.endsWith('.googleusercontent.com')||u.hostname.endsWith('.ggpht.com')||u.hostname.endsWith('.googleapis.com'));}catch{return false;}};
  function validateQueue(q){
    if(!q||q.version!==1||!/^[a-f0-9]{24}$/.test(q.queue_id))throw Error('Choose a valid VideoPilot FLOW_QUEUE.json.');
    if(!['9:16','16:9','1:1'].includes(q.aspect)||![1,2,3,4].includes(q.outputs))throw Error('Unsupported Flow settings.');
    if(!Array.isArray(q.shots)||q.shots.length<1||q.shots.length>1000)throw Error('Queue must contain 1–1000 shots.');
    const ids=new Set();
    for(const s of q.shots){if(!/^\d{3,4}_\d{2,4}$/.test(s.id)||ids.has(s.id)||typeof s.prompt!=='string'||!s.prompt.trim()||s.prompt.length>20000)throw Error('Invalid or duplicate shot.');ids.add(s.id);}
    return q;
  }
  function imageFits(width,height,aspect){const [w,h]=aspect.split(':').map(Number);return Math.min(width,height)>=512&&Math.abs((width/height)/(w/h)-1)<.10;}
  function safeFilename(queueId,shotId,variant){
    if(!/^[a-f0-9]{24}$/.test(queueId)||!/^\d{3,4}_\d{2,4}$/.test(shotId)||![1,2,3,4].includes(variant))throw Error('Unsafe download name.');
    return `VideoPilot/${queueId}/${shotId}__v${variant}.png`;
  }
  const api={allowedPage,assetAllowed,validateQueue,imageFits,safeFilename};
  root.VideoPilotFlowLogic=api;if(typeof module!=='undefined')module.exports=api;
})(globalThis);
