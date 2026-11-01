const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync(require.resolve('../videopilot/flow_browser_ui.js'),'utf8');

function harness(){
  class Element{
    constructor(tag){this.tagName=tag.toUpperCase();this.children=[];this.style={};this.id='';this.textContent='';}
    set innerHTML(value){throw new TypeError("This document requires 'TrustedHTML' assignment.");}
    set outerHTML(value){throw new TypeError('TrustedHTML required');}
    insertAdjacentHTML(){throw new TypeError('TrustedHTML required');}
    append(child){child.parentElement=this;this.children.push(child);}
    attachShadow(){this.shadowRoot=new Element('shadow-root');return this.shadowRoot;}
    getElementById(id){for(const child of this.children){if(child.id===id)return child;const found=child.getElementById(id);if(found)return found;}return null;}
    remove(){if(this.parentElement)this.parentElement.children=this.parentElement.children.filter(n=>n!==this);this.parentElement=null;}
    get isConnected(){return this===document.documentElement||Boolean(this.parentElement?.isConnected);}
    getAttribute(){return null;}
    closest(){return this;}
  }
  const listeners=new Map();
  const document={documentElement:new Element('html'),
    createElement(tag){assert.notEqual(tag.toLowerCase(),'script');return new Element(tag);},
    getElementById(id){return this.documentElement.getElementById(id);},
    querySelectorAll(selector){const node=this.getElementById(selector.slice(1));return node?[node]:[];},
    addEventListener(type,listener){if(!listeners.has(type))listeners.set(type,new Set());listeners.get(type).add(listener);},
    removeEventListener(type,listener){listeners.get(type)?.delete(listener);}
  };
  const context={document,CSS:{escape:s=>s},trustedTypes:{createPolicy(){throw Error('New Trusted Types policies are forbidden');}}};
  context.window=context;vm.createContext(context);
  const render=vm.runInContext(source,context);
  const host=()=>document.getElementById('videopilot-browser-panel');
  const control=id=>host().shadowRoot.getElementById(id);
  const fire=(type,target)=>{let prevented=false;const event={target,preventDefault(){prevented=true;},stopImmediatePropagation(){}};for(const fn of [...listeners.get(type)||[]])fn(event);return prevented;};
  return {render,host,control,context,document,listeners,fire};
}

test('Panel renders with HTML string assignment and policy creation forbidden',()=>{
  const h=harness();h.render({shots:2,aspect:'9:16',outputs:1});
  assert.equal(h.control('settings').textContent,'2 remaining shots / 9:16 / 1 image(s) per prompt');
  assert.equal(h.control('confirm').type,'checkbox');
  assert.equal(h.control('parallel').value,'timed');
  for(const id of ['prompt','generate','ready'])assert.equal(h.control(id).type,'button');
  assert.equal(h.context.__vpBrowser.ready,false);
});

test('Settings containing markup stay plain text',()=>{
  const h=harness(),aspect='<img src=x onerror=alert(1)>';
  h.render({shots:1,aspect,outputs:1});
  assert.ok(h.control('settings').textContent.includes(aspect));
  assert.equal(h.control('settings').children.length,0);
});

test('Controls must be selected and settings confirmed before queue is ready',()=>{
  const h=harness();h.render({shots:2,aspect:'1:1',outputs:1});
  h.control('ready').onclick();assert.equal(h.context.__vpBrowser.ready,false);
  for(const [kind,tag] of [['prompt','textarea'],['generate','button']]){
    const target=h.document.createElement(tag);target.id='flow-'+kind;h.document.documentElement.append(target);
    h.control(kind).onclick();assert.equal(h.fire('click',target),true);
  }
  h.control('ready').onclick();assert.equal(h.context.__vpBrowser.ready,false);
  h.control('confirm').checked=true;h.control('ready').onclick();
  assert.equal(h.context.__vpBrowser.ready,true);assert.equal(h.host(),null);
  assert.equal(h.context.__vpBrowser.selectors.prompt,'#flow-prompt');
  assert.equal(h.context.__vpBrowser.selectors.generate,'#flow-generate');
  assert.equal(h.context.__vpBrowser.selectors.parallel,0);
  assert.equal(h.context.__vpBrowser.selectors.interval,6);
});

test('Reopening the panel removes old selection listeners and panel nodes',()=>{
  const h=harness();h.render({shots:1,aspect:'1:1',outputs:1});
  const old=h.host();h.control('prompt').onclick();assert.equal(h.listeners.get('click').size,1);
  h.render({shots:3,aspect:'16:9',outputs:2});
  assert.equal(old.isConnected,false);assert.equal(h.listeners.get('click').size,0);
  assert.equal(h.document.documentElement.children.length,1);
  assert.equal(h.control('settings').textContent,'3 remaining shots / 16:9 / 2 image(s) per prompt');
});
