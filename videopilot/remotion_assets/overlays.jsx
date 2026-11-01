import React from 'react';
import {AbsoluteFill,Img,useCurrentFrame,useVideoConfig} from 'remotion';
import {motionState} from './motion.cjs';
const clamp=x=>Math.max(0,Math.min(1,x));
export const IllustratedGraphic=({image,imageMotion,camera=null,overlayPlan={elements:[]},transition='cut'})=>{
 const frame=useCurrentFrame(),{width,height,fps,durationInFrames}=useVideoConfig();
 const motion=motionState(frame,durationInFrames,[],imageMotion,camera);
 const unit=Math.min(width,height),stroke=unit*.005;
 return <AbsoluteFill style={{background:'#000',overflow:'hidden',opacity:transition==='fade'?clamp(frame/6):1}}>
  <AbsoluteFill style={{transform:`translate(${motion.x*width}px,${motion.y*height}px) scale(${motion.scale})`}}>
   <Img src={image} style={{width:'100%',height:'100%',objectFit:'contain'}}/>
   <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} style={{position:'absolute',inset:0,overflow:'hidden'}}>
    {(overlayPlan.elements||[]).map((e,i)=>{
     const age=frame/fps-e.start,duration=e.end-e.start;
     if(age<0||age>duration)return null;
     const reveal=clamp(age/Math.min(.9,duration*.5)),fade=clamp((duration-age)/.25);
     const p=e.points.map(([x,y])=>[x*width,y*height]);
     const d=p.map(([x,y],j)=>`${j?'L':'M'}${x},${y}`).join(' ');
     const a=p.at(-2),b=p.at(-1),angle=Math.atan2(b[1]-a[1],b[0]-a[0])*180/Math.PI;
     return <g key={i} opacity={fade} stroke={e.color} strokeWidth={stroke} strokeLinecap="round" strokeLinejoin="round" fill="none">
      {e.kind==='highlight'?<path d={d+' Z'} fill={e.color} fillOpacity={.32*reveal} strokeOpacity={reveal}/>:<>
       <path d={d} pathLength="1" strokeDasharray="1" strokeDashoffset={1-reveal} opacity={e.kind==='trail'?.45:1}/>
       {e.kind==='arrow'&&<path d={`M${-unit*.024},${-unit*.014}L0,0L${-unit*.024},${unit*.014}`} transform={`translate(${b}) rotate(${angle})`} opacity={clamp((reveal-.85)/.15)}/>}
       {e.kind==='bracket'&&<g opacity={reveal}>{[p[0],b].map((q,j)=><path key={j} d={`M0,${-unit*.015}V${unit*.015}`} transform={`translate(${q}) rotate(${angle})`}/>)}</g>}
       {e.kind==='trail'&&<path d={d} strokeDasharray={`${stroke} ${stroke*3}`} opacity={reveal*.3} transform={`translate(${stroke*2},${stroke*2})`}/>}
      </>}
      {e.label&&<text x={p[0][0]} y={p[0][1]-unit*.025} textAnchor={p[0][0]>width*.65?'end':'start'} fill={e.color} stroke="#000" strokeWidth={unit*.002} paintOrder="stroke" fontFamily="Arial,sans-serif" fontWeight="800" fontSize={unit*.03} opacity={reveal}>{e.label}</text>}
     </g>;
    })}
   </svg>
  </AbsoluteFill>
 </AbsoluteFill>;
};
