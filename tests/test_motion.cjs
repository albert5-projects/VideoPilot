const test=require('node:test'),assert=require('node:assert/strict');
const {motionState,fitLabel}=require('../videopilot/remotion_assets/motion.cjs');
test('Preset movement is slow and static mode never moves the photo',()=>{
 for(let f=0;f<120;f++){
  const moving=motionState(f,120,[0,35,80],true),still=motionState(f,120,[0,35,80],false);
  assert.ok(moving.scale>=1.02&&moving.scale<=1.071);assert.equal(moving.rotation,0);assert.equal(moving.flash,0);
  if(f)assert.ok(Math.abs(moving.scale-motionState(f-1,120,[0,35,80],true).scale)<.001);
  assert.equal(still.scale,1);assert.equal(still.x,0);assert.equal(still.y,0);assert.equal(still.rotation,0);assert.equal(still.flash,0);
 }
 assert.equal(motionState(34,120,[35]).hit,0);assert.ok(motionState(38,120,[35]).hit>.9);
});
test('Explicit camera keys drive Codex and floating presets',()=>{
 const camera=[{at:0,scale:1.03,x:0,y:.006},{at:.5,scale:1.03,x:0,y:-.006},{at:1,scale:1.03,x:0,y:.006}];
 assert.equal(motionState(50,101,[],true,camera).y,-.006);
 assert.equal(motionState(100,101,[],true,camera).y,.006);
});
test('Graphic labels preserve long words and shrink excessive lines',()=>{
 const text='ExtraordinarilyLongTechnicalTerm '.repeat(4).trim(),fit=fitLabel(text,14,3);
 assert.equal(fit.lines.join('').replace(/\s/g,''),text.replace(/\s/g,''));
 assert.ok(fit.lines.every(s=>s.length<=14));assert.ok(fit.scale<1);
});
