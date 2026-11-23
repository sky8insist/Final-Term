import {readFileSync} from 'node:fs';
import test from 'node:test';
import assert from 'node:assert/strict';
import ts from 'typescript';

const source=readFileSync(new URL('../src/api/versionedCache.ts',import.meta.url),'utf8');
const compiled=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
const {readVersioned,mergeCacheNotices}=await import('data:text/javascript;base64,'+Buffer.from(compiled).toString('base64'));
const version=(value='a')=>({version:value,dataVersion:value,schemaVersion:2});
function setup(patch={}) {
  const saved=[],notices=[];
  const options={resource:'dashboard',owner:async()=> 'owner',version:async()=>version(),loader:async()=>({fresh:true}),
    load:async()=>({data:{cached:true},version:'a',schemaVersion:2,versionVerified:true,cachedAt:'2026-10-27T00:00:00Z'}),
    save:async(...values)=>saved.push(values),announce:notice=>notices.push(notice),
    failure:reason=>Object.assign(new Error(reason),{status:reason==='owner_changed'?401:409}),...patch};
  return {options,saved,notices};
}
test('successful primary uses bracketed version and scoped fresh notice',async()=>{
  const {options,saved,notices}=setup();assert.deepEqual(await readVersioned(options),{fresh:true});
  assert.deepEqual(saved,[[{fresh:true},'a']]);assert.equal(notices[0].cachedAt,null);assert.equal(notices[0].ownerId,'owner');
});
test('version outage does not fail primary success or save unversioned data',async()=>{
  const {options,saved}=setup({version:async()=>{throw Error('DB offline');}});
  assert.deepEqual(await readVersioned(options),{fresh:true});assert.equal(saved.length,0);
});
test('cache write failure preserves successful primary',async()=>{
  const {options}=setup({save:async()=>{throw Error('Redis offline');}});assert.deepEqual(await readVersioned(options),{fresh:true});
});
test('transient primary failure returns only a currently verified fallback',async()=>{
  const {options,notices}=setup({loader:async()=>{throw Error('network');}});assert.deepEqual(await readVersioned(options),{cached:true});assert.ok(notices[0].cachedAt);
});
for(const status of [401,403,404,409,422])test(`primary ${status} never falls back`,async()=>{
  const {options}=setup({loader:async()=>{throw Object.assign(Error('primary'),{status});},load:async()=>assert.fail('fallback reached')});
  await assert.rejects(readVersioned(options),{status});
});
for(const changes of [{schemaVersion:1},{versionVerified:false},{version:'old'}])test(`rejects invalid fallback ${JSON.stringify(changes)}`,async()=>{
  const base=setup().options;const {options}=setup({loader:async()=>{throw Error('primary');},load:async()=>({...await base.load(),...changes})});await assert.rejects(readVersioned(options),/primary/);
});
test('source change during loader retries once and saves only refreshed data',async()=>{
  let calls=0,v=0;const values=['a','b','b'];
  const {options,saved}=setup({version:async()=>version(values[v++]),loader:async()=>({call:++calls})});
  assert.deepEqual(await readVersioned(options),{call:2});assert.deepEqual(saved,[[{call:2},'b']]);
});
test('continuous source change returns conflict without writing a snapshot',async()=>{
  let v=0;const {options,saved}=setup({version:async()=>version(String(v++))});await assert.rejects(readVersioned(options),{status:409});assert.equal(saved.length,0);
});
test('account switch while loader is pending discards response and prevents cache write',async()=>{
  let owner='a';const {options,saved}=setup({owner:async()=>owner,loader:async()=>{owner='b';return {secret:'a'};}});
  await assert.rejects(readVersioned(options),{status:401});assert.equal(saved.length,0);
});
test('account switch while reading fallback discards snapshot',async()=>{
  let owner='a';const base=setup().options;const {options}=setup({owner:async()=>owner,loader:async()=>{throw Error('network');},load:async()=>{owner='b';return base.load();}});
  await assert.rejects(readVersioned(options),{status:401});
});
test('missing authenticated owner never attempts loading',async()=>{
  const {options}=setup({owner:async()=>null,loader:async()=>assert.fail('unauthenticated load')});await assert.rejects(readVersioned(options),{status:401});
});
test('success of an unrelated resource cannot hide a stale dashboard warning',()=>{
  const notice={ownerId:'a',resource:'dashboard',cachedAt:'timestamp'};
  assert.deepEqual(mergeCacheNotices([notice],{ownerId:'a',resource:'subjects',cachedAt:null}),[notice]);
});
test('success clears only the matching subject and owner warning',()=>{
  const notices=[{ownerId:'a',resource:'chat',subjectId:'one',cachedAt:'t'},{ownerId:'a',resource:'chat',subjectId:'two',cachedAt:'t'},{ownerId:'b',resource:'chat',subjectId:'one',cachedAt:'t'}];
  assert.deepEqual(mergeCacheNotices(notices,{ownerId:'a',resource:'chat',subjectId:'one',cachedAt:null}),notices.slice(1));
});
