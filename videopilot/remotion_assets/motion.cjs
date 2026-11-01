// Deterministic, bounded motion shared by previews and renders.
const clamp=x=>Math.max(0,Math.min(1,x));
function motionState(frame,frames,cues=[0],enabled=true,camera=null){
  const progress=clamp(frame/Math.max(1,frames-1));
  const hit=Math.max(0,...cues.map(c=>{
    const age=frame-c;return age<0?0:age<3?age/3:Math.exp(-(age-3)/5);
  }));
  let scale=enabled?1.02+.05*progress:1,x=0,y=0;
  if(enabled&&camera?.length){
    const right=camera.findIndex(k=>k.at>=progress),b=camera[right<0?camera.length-1:right],a=camera[Math.max(0,right-1)];
    const t=clamp((progress-a.at)/Math.max(.00001,b.at-a.at));
    const mix=k=>a[k]+(b[k]-a[k])*t;scale=mix('scale');x=mix('x');y=mix('y');
  }
  return {progress,hit,scale,x,y,rotation:0,flash:0};
}
function fitLabel(text,max=25,maxLines=3){
  const words=String(text).split(/\s+/).filter(Boolean),lines=[];let line='';
  for(let word of words){
    while(word.length>max){if(line){lines.push(line);line='';}lines.push(word.slice(0,max));word=word.slice(max);}
    if(line&&line.length+word.length+1>max){lines.push(line);line='';}
    if(word)line+=(line?' ':'')+word;
  }
  if(line)lines.push(line);
  return {lines,scale:Math.min(1,maxLines/Math.max(1,lines.length))};
}
module.exports={motionState,fitLabel};
