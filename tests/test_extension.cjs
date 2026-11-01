const test=require('node:test');const assert=require('node:assert/strict');
const L=require('../flow_extension/logic.js');
test('Flow scope excludes accounts, other sites and lookalike domains',()=>{
 assert.ok(L.allowedPage('https://labs.google/fx/tools/flow/project/abc'));
 assert.ok(L.allowedPage('https://labs.google/fx/en/tools/flow'));
 assert.ok(L.allowedPage('https://flow.google.com/project/abc'));
 for(const url of ['https://accounts.google.com','https://evil.example','https://flow.google.com.evil.example','https://labs.google/fx/tools/whisk','http://flow.google.com'])assert.equal(L.allowedPage(url),false);
});
test('Downloads cannot be redirected to unrelated hosts or local files',()=>{
 assert.ok(L.assetAllowed('https://lh3.googleusercontent.com/example'));
 for(const url of ['file:///C:/secret','https://evil.example/a.png','https://googleusercontent.com.evil.example/a.png','javascript:alert(1)'])assert.equal(L.assetAllowed(url),false);
});
test('Queue validation rejects duplicate IDs and unsafe filenames',()=>{
 const q={version:1,queue_id:'a'.repeat(24),aspect:'9:16',outputs:2,shots:[{id:'001_01',prompt:'A scene'}]};assert.equal(L.validateQueue(q),q);
 assert.throws(()=>L.validateQueue({...q,shots:[...q.shots,...q.shots]}));assert.throws(()=>L.safeFilename('../escape','001_01',1));assert.throws(()=>L.safeFilename('a'.repeat(24),'../escape',1));
 assert.equal(L.safeFilename('a'.repeat(24),'001_01',2),`VideoPilot/${'a'.repeat(24)}/001_01__v2.png`);
});
test('Small previews and wrong aspect ratios cannot pass the image gate',()=>{
 assert.ok(L.imageFits(768,1344,'9:16'));assert.ok(L.imageFits(1024,1024,'1:1'));
 assert.equal(L.imageFits(256,448,'9:16'),false);assert.equal(L.imageFits(1344,768,'9:16'),false);
});

const vm=require('node:vm');const fs=require('node:fs');
function editorHarness(handled,initial=''){
 let value=initial,nativeCalls=0,model=initial,modelSelected=false;
 const el={isConnected:true,childNodes:[{nodeType:3,nodeValue:initial}],matches:s=>s.includes('contenteditable'),focus(){},contains:node=>node===el,dispatchEvent(event){
   if(handled){model=(modelSelected?'':model)+event.clipboardData.getData('text/plain');value=model;this.childNodes=[{nodeType:3,nodeValue:value}];event.defaultPrevented=true;}
 }};
 class DataTransfer{setData(type,text){this.text=text;}getData(){return this.text;}}
 class ClipboardEvent{constructor(type,options){Object.assign(this,options);this.type=type;this.defaultPrevented=false;}}
 const selection={rangeCount:1,anchorNode:el,focusNode:el,removeAllRanges(){},addRange(){modelSelected=false;}};
 const context={DataTransfer,ClipboardEvent,Event:class{constructor(type){this.type=type;}},setTimeout,getSelection:()=>selection,document:{dispatchEvent(event){if(event.type==='selectionchange')setTimeout(()=>{modelSelected=true;},10);},createRange:()=>({selectNodeContents(){}}),execCommand(command,ui,text){nativeCalls++;value=text;el.childNodes=[{nodeType:3,nodeValue:text}];return true;}}};
 vm.createContext(context);vm.runInContext(fs.readFileSync(require.resolve('../flow_extension/editor.js'),'utf8'),context);
 return {el,api:context.VideoPilotFlowEditor,nativeCalls:()=>nativeCalls,model:()=>model};
}
test('Rich editor paste updates application model without a duplicate native insertion',async()=>{
 const h=editorHarness(true);
 await h.api.fillPrompt(()=>h.el,'New image prompt',{stableMs:0});
 assert.equal(h.model(),'New image prompt');assert.equal(h.nativeCalls(),0);
});
test('Contenteditable without a paste handler falls back to native insertion',async()=>{
 const h=editorHarness(false);
 await h.api.fillPrompt(()=>h.el,'New image prompt',{stableMs:0});
 assert.equal(h.nativeCalls(),1);assert.ok(h.api.promptMatches(h.el,'New image prompt'));
});

test('Retry replaces existing editor text after asynchronous model selection settles',async()=>{
 const prompt='A'.repeat(882),h=editorHarness(true,'test');
 await h.api.fillPrompt(()=>h.el,prompt,{stableMs:0});
 assert.equal(h.model(),prompt);assert.ok(h.api.promptMatches(h.el,prompt));
 await h.api.fillPrompt(()=>h.el,prompt,{stableMs:0});
 assert.equal(h.model(),prompt);assert.equal(h.nativeCalls(),0);
});

test('Stop during selection synchronization prevents paste',async()=>{
 const h=editorHarness(true,'old prompt');let checks=0;
 await assert.rejects(h.api.fillPrompt(()=>h.el,'new prompt',{check(){if(++checks===2)throw Error('Stopped');}}),/Stopped/);
 assert.equal(h.model(),'old prompt');
});

function runnerHarness({pending=null,mismatch=false,background=false,noResult=false,small=false,manual=false}={}){
 const q={version:1,queue_id:'a'.repeat(24),aspect:'1:1',outputs:1,shots:[{id:'001_01',prompt:'Original prompt one'},{id:'001_02',prompt:'Original prompt two'}]};
 const state={done:[],pending},controls={},listeners={},clicks=[],fills=[],downloads=new Map();
 let now=0,current='',downloadId=0,enabledAt=0,pressed=false,manualAt=null;
 const cards=[],statuses=[];
 class Element{
   constructor(tag='BUTTON'){this.tagName=tag;this.isConnected=true;this.disabled=false;this.id=tag;}
   getClientRects(){return [1];}getAttribute(){return null;}
   matches(){return true;}closest(){return this;}
   scrollIntoView(){}focus(){}blur(){}getBoundingClientRect(){return {left:0,top:0,width:20,height:20};}
 }
 const prompt=new Element('TEXTAREA'),generate=new Element();
 const document={body:{innerText:''},images:[],documentElement:{append(){}},
   createElement:()=>({style:{},attachShadow:()=>({set innerHTML(value){},getElementById:id=>controls[id]??=( {addEventListener(type,fn){this[type]=fn;}})})}),
   querySelectorAll:selector=>selector==='*'?cards:selector==='#TEXTAREA'?[prompt]:[generate],
   addEventListener(type,fn){listeners[type]=fn;},removeEventListener(type){delete listeners[type];}};
 generate.click=()=>{
   assert.equal(generate.disabled,false);assert.equal(state.pending,q.shots[clicks.length].id);
   clicks.push(current);
   if(noResult)return;
   const url=`https://lh3.googleusercontent.com/image${clicks.length}`;
   if(background)cards.push(Object.assign(new Element('DIV'),{backgroundImage:`url("${url}")`}));
   else document.images.push(Object.assign(new Element('IMG'),{complete:true,naturalWidth:small?256:1024,naturalHeight:small?256:1024,src:url}));
 };
 generate.dispatchEvent=event=>{
   if(event.type==='pointerdown')pressed=true;
   if(event.type==='click'){
     assert.ok(pressed,'Generate requires pointerdown before click');pressed=false;
     if(manual)manualAt=now+20000;else generate.click();
   }
 };
 class Image{constructor(){this.complete=true;this.naturalWidth=1024;this.naturalHeight=1024;}}
 class UIEvent{constructor(type,options){this.type=type;Object.assign(this,options);}}
 const context={VideoPilotFlowLogic:L,VideoPilotFlowEditor:{editorRoot:el=>el,async fillPrompt(resolve,text){resolve();fills.push(text);current=text;generate.disabled=true;enabledAt=now+400;},promptMatches:()=>!mismatch},
   location:{href:'https://flow.google.com/project/test'},document,Element,Image,PointerEvent:UIEvent,MouseEvent:UIEvent,CSS:{escape:s=>s},getComputedStyle:el=>({visibility:'visible',backgroundImage:el.backgroundImage||'none'}),
   Date:class extends Date{static now(){return now;}},setTimeout(fn,ms){now+=ms;if(now>=enabledAt)generate.disabled=false;if(manualAt!==null&&now>=manualAt){manualAt=null;generate.click();}fn();},confirm:()=>true,
   chrome:{storage:{local:{async get(){return {[`queue:${q.queue_id}`]:state};},async set(){}}},runtime:{async sendMessage(msg){
     if(msg.type==='downloadStatus')return {ok:true,state:'complete',filename:downloads.get(msg.id)};
     const id=++downloadId;downloads.set(id,msg.type==='downloadImage'?`${msg.shotId}__v${msg.variant}.png`:`${msg.receipt.shot_id}.receipt.json`);return {ok:true,id};
   }}}};
 vm.createContext(context);
 vm.runInContext(fs.readFileSync(require.resolve('../flow_extension/ui.js'),'utf8'),context);
 vm.runInContext(fs.readFileSync(require.resolve('../flow_extension/flow.js'),'utf8'),context);
 let status='';Object.defineProperty(controls.status??={},'textContent',{get:()=>status,set:value=>{status=value;statuses.push(value);}});
 async function prepare(){
   controls.file.files=[{size:100,text:async()=>JSON.stringify(q)}];await controls.file.change();
   for(const [id,target] of [['pickPrompt',prompt],['pickGenerate',generate]]){
     controls[id].onclick();listeners.click({target,preventDefault(){},stopImmediatePropagation(){}});
   }
   controls.confirmed.checked=true;
 }
 return {prepare,controls,state,clicks,fills,q,statuses};
}

test('Run queue waits for enabled Generate, submits each original prompt and completes downloads',async()=>{
 const h=runnerHarness();await h.prepare();await h.controls.start.onclick();
 assert.deepEqual(h.clicks,h.q.shots.map(s=>s.prompt));
 assert.deepEqual(h.state.done,h.q.shots.map(s=>s.id));assert.equal(h.state.pending,null);
 assert.match(h.controls.status.textContent,/Image queue finished/);
});

test('Retry unresolved shot resumes automatic generation using the original queue prompt',async()=>{
 const h=runnerHarness({pending:'001_01'});await h.prepare();await h.controls.retry.onclick();
 assert.deepEqual(h.clicks,h.q.shots.map(s=>s.prompt));assert.equal(h.state.pending,null);
});

test('Prompt mismatch prevents automatic Generate and leaves the shot resumable',async()=>{
 const h=runnerHarness({mismatch:true});await h.prepare();await h.controls.start.onclick();
 assert.deepEqual(h.clicks,[]);assert.equal(h.state.pending,null);
 assert.match(h.controls.status.textContent,/No Generate click was sent/);
});

test('CSS background results are downloaded and advance the queue',async()=>{
 const h=runnerHarness({background:true});await h.prepare();await h.controls.start.onclick();
 assert.deepEqual(h.state.done,h.q.shots.map(s=>s.id));
});

test('Ignored activation reports no new image without resubmitting',async()=>{
 const h=runnerHarness({noResult:true});await h.prepare();await h.controls.start.onclick();
 assert.equal(h.clicks.length,1);assert.equal(h.state.pending,'001_01');assert.deepEqual(h.state.done,[]);
 assert.ok(h.statuses.some(s=>s.includes('If Flow has not started')));
 assert.match(h.controls.status.textContent,/No usable new image detected/);
});

test('A later manual Generate result is collected and advances to the next prompt',async()=>{
 const h=runnerHarness({manual:true});await h.prepare();await h.controls.start.onclick();
 assert.deepEqual(h.state.done,h.q.shots.map(s=>s.id));assert.deepEqual(h.clicks,h.q.shots.map(s=>s.prompt));
});

test('Small results explain why the queue cannot advance',async()=>{
 const h=runnerHarness({small:true});await h.prepare();await h.controls.start.onclick();
 assert.match(h.controls.status.textContent,/256x256/);assert.match(h.controls.status.textContent,/full size/);
 assert.equal(h.state.pending,'001_01');assert.deepEqual(h.state.done,[]);
});
