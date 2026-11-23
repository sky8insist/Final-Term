import {readFileSync} from 'node:fs';
import test from 'node:test';
import assert from 'node:assert/strict';
import ts from 'typescript';

const source=readFileSync(new URL('../src/api/recommendationExposure.ts',import.meta.url),'utf8');
const compiled=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
const {observeRecommendationImpressions}=await import('data:text/javascript;base64,'+Buffer.from(compiled).toString('base64'));
const settle=()=>new Promise(resolve=>setImmediate(resolve));
function setup(report=async()=>{}) {
  const calls=[];let callback,listener,disconnected=false;
  const element={getAttribute:()=> 'audit-id'};
  const page={visibilityState:'visible',addEventListener:(_,fn)=>{listener=fn;},removeEventListener:(_,fn)=>{assert.equal(fn,listener);listener=null;}};
  class Observer {constructor(fn){callback=fn;}observe(target){assert.equal(target,element);}disconnect(){disconnected=true;}}
  const root={querySelectorAll:()=>[element]};
  const stop=observeRecommendationImpressions(root,async id=>{calls.push(id);await report();},page,Observer);
  return {calls,page,stop,emit:(ratio,intersecting=true)=>callback([{target:element,intersectionRatio:ratio,isIntersecting:intersecting}]),
    visibility:()=>listener?.(),disconnected:()=>disconnected};
}
test('delivery and under-half or offscreen cards do not count as exposure',async()=>{
  const env=setup();assert.deepEqual(env.calls,[]);env.emit(.49);env.emit(.9,false);await settle();assert.deepEqual(env.calls,[]);env.stop();
});
test('visible half-card is recorded once despite repeated observer notifications',async()=>{
  const env=setup();env.emit(.5);env.emit(1);await settle();env.emit(.7);assert.deepEqual(env.calls,['audit-id']);env.stop();
});
test('background page waits for visibility before reporting',async()=>{
  const env=setup();env.page.visibilityState='hidden';env.emit(1);await settle();assert.deepEqual(env.calls,[]);
  env.page.visibilityState='visible';env.visibility();await settle();assert.deepEqual(env.calls,['audit-id']);env.stop();
});
test('failed report can retry on a later visibility notification without hot-looping',async()=>{
  let attempt=0;const env=setup(async()=>{if(++attempt===1)throw Error('offline');});env.emit(1);await settle();assert.equal(env.calls.length,1);
  env.visibility();await settle();env.visibility();assert.equal(env.calls.length,2);env.stop();
});
test('unmount disconnects and ignores late observer notifications',async()=>{
  const env=setup();env.stop();env.emit(1);await settle();assert.equal(env.disconnected(),true);assert.deepEqual(env.calls,[]);
});
test('missing IntersectionObserver does not fake exposure',()=>{
  const stop=observeRecommendationImpressions({},()=>assert.fail(),{},undefined);assert.equal(typeof stop,'function');stop();
});
