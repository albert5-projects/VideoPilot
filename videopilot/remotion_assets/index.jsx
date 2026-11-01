import React from 'react';
import {Composition, registerRoot} from 'remotion';
import {IllustratedGraphic} from './overlays';
const Root = () => <Composition id="VideoPilotGraphic" component={IllustratedGraphic} width={1080} height={1920} fps={30} durationInFrames={90}
  defaultProps={{width:1080,height:1920,frames:90,image:'',imageMotion:false,theme:'Editorial',accent:'#84e1cc',graphic:{kind:'focus',title:'A new perspective',items:[],icons:['globe']}}}
  calculateMetadata={({props}) => ({width:props.width,height:props.height,durationInFrames:props.frames})} />;
registerRoot(Root);

