import {readFileSync} from 'node:fs';
import test from 'node:test';
import assert from 'node:assert/strict';
import ts from 'typescript';

const source=readFileSync(new URL('../src/api/learningMetrics.ts',import.meta.url),'utf8');
const compiled=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
const {percent,decimal,points,assessedMastery,appendUnique,requestEpoch}=await import('data:text/javascript;base64,'+Buffer.from(compiled).toString('base64'));

for(const value of [null,undefined,NaN,Infinity])test(`missing/nonfinite metric ${value} remains unavailable`,()=>{
  assert.equal(percent(value),'—');assert.equal(decimal(value),'—');assert.equal(points(value),'—');
});
test('zero denominator result is distinct from an observed zero and rates are not points',()=>{
  assert.equal(percent(0),'0.0%');assert.equal(decimal(0),'0.000');assert.equal(points(12),'+12.0 个百分点');assert.equal(points(-5),'-5.0 个百分点');
});
test('default mastery without assessment evidence is not a measured baseline',()=>{
  assert.equal(assessedMastery({masteryScore:.5,assessmentCount:0}),null);
  assert.equal(assessedMastery({masteryScore:.5}),null);assert.equal(assessedMastery(null),null);
  assert.equal(assessedMastery({masteryScore:0,assessmentCount:2}),0);
});
test('append preserves seek order and avoids repeated IDs across and within pages',()=>{
  const original=[{id:'a',value:1}];
  assert.deepEqual(appendUnique(original,[{id:'a',value:2},{id:'b',value:3},{id:'b',value:4}]),[{id:'a',value:1},{id:'b',value:3}]);
  assert.deepEqual(original,[{id:'a',value:1}]);
});
test('refresh or account/record reset invalidates an older page response and finally handler',async()=>{
  const epoch=requestEpoch();let done;
  const old=epoch.reset();let state='loading-new';
  const pending=new Promise(resolve=>{done=resolve;}).then(()=>{if(epoch.accepts(old))state='stale';}).finally(()=>{if(epoch.accepts(old))state='cleared';});
  const current=epoch.reset();done();await pending;
  assert.equal(state,'loading-new');assert.equal(epoch.accepts(current),true);assert.equal(epoch.accepts(old),false);
});
