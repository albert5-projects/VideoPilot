import React from 'react';
import {AbsoluteFill, Img, interpolate, spring, useCurrentFrame, useVideoConfig} from 'remotion';
import {compositionLayout} from './layout.cjs';
import {motionState,fitLabel} from './motion.cjs';

const clamp = (x) => Math.max(0, Math.min(1, x));

function Glyph({name, color, fill}) {
  const shapes = {
    light: <><path d="M40 78 C40 68 28 62 28 42 A32 32 0 0 1 92 42 C92 62 80 68 80 78Z" fill={fill}/><path d="M42 88H78 M46 99H74 M53 78V55L67 44 M67 78V55L53 44 M60 3V-5 M14 23L6 17 M106 23L114 17 M10 50H0 M110 50H120"/></>,
    clock: <><circle cx="60" cy="60" r="46" fill={fill}/><path d="M60 26V60L83 76 M60 14V20 M60 100V106 M14 60H20 M100 60H106"/><circle cx="60" cy="60" r="5" fill={color}/></>,
    water: <><path d="M60 8C48 31 23 55 23 77A37 37 0 0 0 97 77C97 55 72 31 60 8Z" fill={fill}/><path d="M38 80Q40 96 55 98 M34 70Q47 61 60 70T88 70"/></>,
    fire: <><path d="M61 8Q77 34 70 48Q91 45 91 31Q120 86 87 105Q60 122 33 101Q7 81 32 48Q33 67 43 63Q28 32 61 8Z" fill={fill}/><path d="M59 60Q41 84 49 97Q61 110 76 97Q87 85 69 74Q67 86 59 87Z" fill={color}/></>,
    leaf: <><path d="M21 98Q-1 17 107 12Q111 111 21 98Z" fill={fill}/><path d="M12 110L88 31 M37 82L38 48 M54 65L83 66 M69 50L68 29"/></>,
    bread: <><path d="M16 42Q17 20 60 20Q103 20 104 42L110 84Q109 101 60 101Q11 101 10 84Z" fill={fill}/><path d="M16 79Q60 99 104 79 M40 28L32 52 M64 25L55 51 M88 30L78 54"/></>,
    person: <><circle cx="60" cy="30" r="22" fill={fill}/><path d="M20 110V90Q21 60 60 60Q99 60 100 90V110Z" fill={fill}/><path d="M40 83V110 M80 83V110"/></>,
    globe: <><circle cx="60" cy="60" r="47" fill={fill}/><ellipse cx="60" cy="60" rx="23" ry="47"/><path d="M14 60H106 M22 34Q60 45 98 34 M22 86Q60 75 98 86 M60 13V107"/></>,
    book: <><path d="M60 30Q35 11 9 24V99Q35 87 60 104Q85 87 111 99V24Q85 11 60 30Z" fill={fill}/><path d="M60 30V104 M24 43Q39 40 48 48 M24 60Q39 57 48 65 M24 77Q39 74 48 82 M73 48Q87 40 98 43 M73 65Q87 57 98 60"/></>,
    shield: <><path d="M60 9L104 28V63Q102 91 60 113Q18 91 16 63V28Z" fill={fill}/><path d="M35 58L53 76L87 40" strokeWidth="7"/></>,
    heart: <path d="M60 108L18 65Q-3 38 17 19Q39 0 60 28Q81 0 103 19Q123 38 102 65Z" fill={fill}/>,
    gear: <><path d="M49 9H71L75 24L89 30L103 26L114 45L103 57V72L114 84L103 103L87 99L74 105L70 118H49L45 104L31 98L17 102L6 83L17 71V56L6 44L17 25L32 29L45 23Z" fill={fill}/><circle cx="60" cy="64" r="23"/></>,
    brain: <><path d="M58 20Q39 0 26 22Q5 25 15 48Q-1 65 16 79Q9 102 33 103Q43 121 60 103Q77 121 87 103Q111 102 104 79Q121 65 105 48Q115 25 94 22Q81 0 62 20Z" fill={fill}/><path d="M60 23V100 M29 34Q49 32 43 54 M20 69Q42 62 40 83 M88 34Q69 32 76 54 M100 69Q78 62 80 83"/></>,
    network: <><path d="M60 60L20 20 M60 60L101 25 M60 60L22 100 M60 60L103 98"/><circle cx="60" cy="60" r="20" fill={fill}/>{[[20,20],[101,25],[22,100],[103,98]].map(([x,y],i)=><circle key={i} cx={x} cy={y} r="12" fill={fill}/>)}</>,
    coin: <><ellipse cx="60" cy="63" rx="43" ry="47" fill={fill}/><ellipse cx="60" cy="57" rx="43" ry="47"/><path d="M43 48Q43 35 60 35Q78 35 78 47Q78 58 60 58Q43 58 43 71Q43 84 61 84Q78 84 78 71 M60 27V92"/></>,
    house: <><path d="M8 54L60 10L112 54 M22 44V108H98V44" fill={fill}/><path d="M48 108V73H72V108 M31 56H42V68H31Z M82 25V9H98V39"/></>,
    mountain: <><path d="M2 108L43 20L72 76L91 43L119 108Z" fill={fill}/><path d="M27 55L39 62L47 48L57 49 M78 71L91 80L101 69"/></>,
    moon: <path d="M94 18A49 49 0 1 0 105 91A44 44 0 0 1 94 18Z" fill={fill}/>,
    sun: <><circle cx="60" cy="60" r="29" fill={fill}/>{Array.from({length:8},(_,i)=><path key={i} d="M60 7V17" transform={`rotate(${i*45} 60 60)`}/>)}</>,
    door: <><path d="M20 111V10H101V111 M20 10L78 24V110H20" fill={fill}/><circle cx="64" cy="69" r="3" fill={color}/></>,
    spark: <><circle cx="60" cy="60" r="22" fill={fill}/>{Array.from({length:8},(_,i)=><path key={i} d="M60 5V24" transform={`rotate(${i*45} 60 60)`}/>)}</>,
  };
  return <g stroke={color} strokeWidth="4" strokeLinecap="round" strokeLinejoin="round" fill="none">{shapes[name] || shapes.spark}</g>;
}

function lines(text, max = 25) {
  const result = []; let line = '';
  for (const word of String(text).split(/\s+/)) {
    if (line.length && (line + ' ' + word).length > max) {result.push(line);line = '';}
    line += (line ? ' ' : '') + word;
  }
  if (line) result.push(line);
  return result;
}

function Label({text, x, y, color, size = 24, max = 25, anchor='middle'}) {
  const fitted=fitLabel(text,max,3),font=size*fitted.scale;
  return <text x={x} y={y} fill={color} textAnchor={anchor} fontSize={font} fontWeight="750" fontFamily="Trebuchet MS, Arial, sans-serif">
    {fitted.lines.map((line,i)=><tspan key={i} x={x} dy={i ? font*1.16 : 0}>{line}</tspan>)}
  </text>;
}

function KineticTitle({text,frame,color}) {
  const fitted=fitLabel(text.toUpperCase(),36,2);let wordIndex=0;
  return <text x="500" y="65" textAnchor="middle" fontSize={38*fitted.scale} fontWeight="900" fontFamily="Arial Black, Arial, sans-serif">
    {fitted.lines.map((line,i)=><tspan key={i} x="500" dy={i?44*fitted.scale:0}>
      {line.split(' ').map((word,j)=>{const index=wordIndex++;return <tspan key={j} opacity={clamp((frame-index*2)/3)} fill={index%3===1?'#ffd166':color}>{j?' ':''}{word}</tspan>;})}
    </tspan>)}
  </text>;
}

export const IllustratedGraphic = ({image, imageMotion, graphic, theme, accent, scene=1, cueFrames=[0],camera=null,transition='cut'}) => {
  const frame=useCurrentFrame();const {width,height,fps,durationInFrames}=useVideoConfig();
  const layout=compositionLayout(width,height,scene);
  const portrait=layout.diagramTall;const H=portrait?1100:graphic.kind==='orbit'?700:560;
  const light=theme==='Minimal';const ink=light?'#152e3c':'#f4fbff';const line=light?'#197c77':accent;
  const fill=light?'#d3eeeb':'#234951';
  const kind={title:'focus',steps:'process'}[graphic.kind]||graphic.kind;
  const items=graphic.items||[];const icons=graphic.icons||['spark'];
  const progress=frame/Math.max(1,durationInFrames-1);
  const motion=motionState(frame,durationInFrames,cueFrames,imageMotion,camera);
  const reveal=clamp(frame/Math.min(12,durationInFrames/4));
  const fade=interpolate(frame,[0,6,Math.max(7,durationInFrames-5),durationInFrames],[0,1,1,0],{extrapolateLeft:'clamp',extrapolateRight:'clamp'});
  const cue=(i)=>cueFrames[i]??i*Math.min(6,durationInFrames/10);
  const entry=(i)=>frame<cue(i)?0:spring({frame:frame-cue(i),fps,config:{damping:13,stiffness:240,mass:.65}});
  const node=(x,y,icon,label,i,r=80)=>{
    const e=entry(i);const scale=.72+.28*e;
    return <g key={`node-${i}`} opacity={e}>
      <g filter="url(#pencil-edge)" transform={`translate(${x} ${y}) rotate(${(1-e)*(i%2?12:-12)}) scale(${scale})`}>
        <circle r={r+14} fill={accent} opacity=".10"/>
        <path d={`M${-r} -8 Q${-r-9} ${-r} 0 ${-r} Q${r+9} ${-r+2} ${r} 4 Q${r+7} ${r+4} -4 ${r} Q${-r-9} ${r+8} ${-r} -8Z`} fill={light?'#fffaf0':'#183344'} stroke={line} strokeWidth="3"/>
        <circle r={r+5} fill="none" stroke={line} strokeWidth="1.3" strokeDasharray="13 5 3 7" opacity=".5"/>
        <g transform={`translate(${-r*.68} ${-r*.68}) scale(${r*1.36/120})`}><Glyph name={icon} color={line} fill={fill}/></g>
      </g>
      {label && (portrait && ['process','timeline'].includes(kind)
        ? <Label text={label} x={x+r+45} y={y+8} color={ink} max={22} anchor="start"/>
        : <Label text={label} x={x} y={y+r+37} color={i%2?'#ffd166':ink} max={portrait?32:23}/>)}
    </g>;
  };
  const link=(a,b,i,ra=103,rb=103)=>{
    const dx=b[0]-a[0],dy=b[1]-a[1],length=Math.hypot(dx,dy),ux=dx/length,uy=dy/length;
    const start=[a[0]+ux*ra,a[1]+uy*ra],end=[b[0]-ux*rb,b[1]-uy*rb];
    const t=clamp((frame-cue(i+1))/Math.max(4,Math.min(14,durationInFrames/4)));
    return <g key={`edge-${i}`} opacity={reveal}>
      <path d={`M${start}L${end}`} stroke={line} opacity=".18" strokeWidth="6" fill="none"/>
      <path d={`M${start}L${end}`} stroke={line} strokeWidth="4" fill="none" strokeDasharray="10 7" strokeDashoffset={-frame*.8} opacity={t}/>
      <path d="M-15 -10L0 0L-15 10" transform={`translate(${start[0]+(end[0]-start[0])*t} ${start[1]+(end[1]-start[1])*t}) rotate(${Math.atan2(dy,dx)*180/Math.PI})`} stroke={line} strokeWidth="4" fill="none" opacity={t}/>
      <circle cx={start[0]+(end[0]-start[0])*t} cy={start[1]+(end[1]-start[1])*t} r="8" fill={line}/>
    </g>;
  };
  let diagram;
  if (kind==='process'||kind==='timeline') {
    const labels=items.length?items:[graphic.title];
    const points=labels.map((_,i)=>portrait?[300,labels.length===1?550:280+i*(580/(labels.length-1))]:[labels.length===1?500:180+i*(640/(labels.length-1)),300]);
    diagram=<>{points.slice(1).map((p,i)=>link(points[i],p,i))}{points.map((p,i)=><g key={i}>{node(p[0],p[1],icons[i]||'spark',labels[i],i)}
      <text x={p[0]-80} y={p[1]-80} fill={line} opacity={entry(i)} fontSize="20" fontWeight="700">{String(i+1).padStart(2,'0')}</text></g>)}</>;
  } else if (kind==='cycle') {
    const labels=items.length?items:[graphic.title];
    const points=labels.map((_,i)=>{const a=-Math.PI/2+i*Math.PI*2/labels.length;return portrait?[500+Math.cos(a)*260,580+Math.sin(a)*285]:[labels.length===1?500:210+i*580/(labels.length-1),300];});
    diagram=<>{points.length>1&&points.slice(0,-1).map((point,i)=>link(point,points[i+1],i,80,80))}
      {points.length>1&&(portrait?link(points.at(-1),points[0],points.length-1,80,80):<g opacity={clamp(entry(points.length-1))}>
        <path d={`M${points.at(-1)[0]} 230C${points.at(-1)[0]} 145 ${points[0][0]} 145 ${points[0][0]} 230`} fill="none" stroke={line} strokeWidth="3" strokeDasharray="10 7" strokeDashoffset={-frame*.8}/>
        <path d={`M${points[0][0]-9} 215L${points[0][0]} 230L${points[0][0]+9} 215`} fill="none" stroke={line} strokeWidth="3"/>
      </g>)}
      {points.map((point,i)=>node(...point,icons[i]||'person',labels[i],i,64))}</>;
  } else if (kind==='comparison') {
    const points=portrait?[[500,340],[500,800]]:[[265,300],[735,300]];
    diagram=<><path d={portrait?'M130 570H870':'M500 155V490'} stroke={line} strokeWidth="2" strokeDasharray="8 12" opacity={reveal*.6}/>
      {points.map((p,i)=><g key={i} transform={`translate(${(1-entry(i))*(i?70:-70)} 0)`}>
        {node(p[0],p[1],icons[i]||'spark',items[i]||'',i,105)}
        <path d={`M${p[0]-125} ${p[1]-140}h${250*entry(i)}`} stroke={line} strokeWidth={i?3:7}/>
      </g>)}</>;
  } else if (kind==='orbit') {
    const center=[500,portrait?580:350];const satellites=portrait?[[220,290],[780,290],[500,900]]:[[190,210],[810,210],[500,565]];
    diagram=<>{items.map((item,i)=>link(center,satellites[i],i,116,72))}{node(...center,icons[0]||'network','',0,100)}
      {items.map((item,i)=>node(...satellites[i],icons[i+1]||'spark',item,i+1,56))}</>;
  } else {
    const cy=portrait?560:325;const hero=icons[0]||'spark';
    diagram=<><circle cx="500" cy={cy} r="173" stroke={line} strokeWidth="1" opacity=".2" fill="none"/>
      <circle cx="500" cy={cy} r="145" stroke={line} strokeWidth="3" opacity=".5" fill="none" pathLength="1" strokeDasharray=".65 .35" transform={`rotate(${frame*.3} 500 ${cy})`}/>
      {[0,1,2].map(i=>{const a=(frame*.008+i*2.094);return <circle key={i} cx={500+Math.cos(a)*173} cy={cy+Math.sin(a)*173} r={i===0?9:5} fill={line} opacity={.9-i*.2}/>;})}
      {node(500,cy,hero,'',0,112)}
      {['fire','bread','water'].includes(hero)&&[0,1,2].map(i=><path key={i} d={`M${470+i*30} ${cy-130}q-12 -16 0 -32t0 -32`} stroke={line} strokeWidth="3" fill="none" opacity={.2+.35*Math.sin(frame*.1+i)**2} transform={`translate(0 ${-8*Math.sin(frame*.07+i)})`}/>)}
      <path d={`M${portrait?240:100} ${cy+220}H${portrait?760:900}`} stroke={line} opacity=".2" strokeWidth="2"/>
    </>;
  }
  const active=Math.max(0,cueFrames.filter(c=>frame>=c).length-1);
  return <AbsoluteFill style={{background:light?'#f5f1e8':'#101b27',fontFamily:'Arial, sans-serif',overflow:'hidden',opacity:transition==='fade'?clamp(frame/6):1}}>
    <AbsoluteFill style={{opacity:.14,backgroundImage:`radial-gradient(${ink} 0.7px, transparent 0.7px)`,backgroundSize:'9px 11px',transform:`translateY(${imageMotion?-progress*5:0}px)`}}/>
    <div style={{position:'absolute',...layout.image,display:'flex',alignItems:'center',justifyContent:'center',overflow:'hidden'}}>
      <div style={{position:'absolute',inset:'7%',border:`2px dashed ${accent}`,transform:`rotate(${-motion.rotation*2}deg) translateX(${-motion.x}px)`,opacity:.4}}/>
      <Img src={image} style={{width:'100%',height:'100%',objectFit:'contain',
        transform:`translate(${motion.x*layout.image.width}px,${motion.y*layout.image.height}px) scale(${motion.scale})`,filter:'drop-shadow(6px 9px 0px #00000055)',borderRadius:4}}/>
    </div>
    <div style={{position:'absolute',...layout.graphic,overflow:'hidden',opacity:fade}}>
      <svg viewBox={`0 0 1000 ${H}`} width="100%" height="100%" preserveAspectRatio="xMidYMid meet" role="img" aria-label={graphic.title}>
        <defs><filter id="pencil-edge" x="-12%" y="-12%" width="124%" height="124%"><feTurbulence type="fractalNoise" baseFrequency=".045" numOctaves="2" seed={scene}/><feDisplacementMap in="SourceGraphic" scale="1.8" xChannelSelector="R" yChannelSelector="G"/></filter></defs>
        <path d={`M190 104Q500 95 ${190+620*clamp(frame/8)} 108`} stroke="#ffd166" strokeWidth="12" opacity=".65" fill="none"/>
        <g transform={`translate(${(1-entry(0))*-60} 0) rotate(${(1-entry(0))*-3} 500 70)`} opacity={clamp(entry(0))}>
          <KineticTitle text={graphic.title} frame={frame} color={ink}/>
        </g>
        {diagram}
        <g transform={`translate(75 ${H-42})`}>
          <path d="M0 0L850 -3L847 19L-3 22Z" fill="none" stroke={line} strokeWidth="2"/>
          {Array.from({length:20},(_,i)=><path key={i} d={`M${i*42+4} 4l32 -1l-2 10l-32 2Z`} fill={i/20<=progress?line:'none'} opacity={.65+(i%3)*.15}/>)}
          {items.length>0&&<text x="850" y="-12" textAnchor="end" fill="#ffd166" fontSize="19" fontWeight="800">{Math.min(items.length,active+1)} / {items.length} BEATS</text>}
        </g>
      </svg>
    </div>
    {motion.flash>0&&<AbsoluteFill style={{background:'#fff5da',opacity:motion.flash,pointerEvents:'none'}}/>}
    <div style={{position:'absolute',left:width*.04,top:height*.805,height:Math.max(2,height*.002),width:width*.92,background:light?'#d7ded9':'#273d49'}}>
      <div style={{height:'100%',width:`${progress*100}%`,background:line}}/>
    </div>
  </AbsoluteFill>;
};
