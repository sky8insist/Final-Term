export type ResourceVersion = { version:string; dataVersion:string; schemaVersion:number };
export type VerifiedSnapshot<T> = { data:T; version:string; cachedAt:string; schemaVersion:number; versionVerified:boolean };
export type CacheNotice = { resource:string; subjectId?:string; ownerId:string; cachedAt:string|null; version?:string; dataVersion?:string };

export function mergeCacheNotices(existing:CacheNotice[],notice:CacheNotice):CacheNotice[] {
  return [...existing.filter(item=>!(item.ownerId===notice.ownerId&&item.resource===notice.resource&&item.subjectId===notice.subjectId)),...(notice.cachedAt?[notice]:[])];
}

type Options<T> = {
  resource:string; subjectId?:string; owner:()=>Promise<string|null>; loader:()=>Promise<T>;
  version:()=>Promise<ResourceVersion>; load:()=>Promise<VerifiedSnapshot<T>>;
  save:(data:T,version:string)=>Promise<unknown>; announce:(notice:CacheNotice)=>void;
  failure:(reason:'owner_changed'|'version_changed')=>Error;
};

export async function readVersioned<T>(options:Options<T>):Promise<T> {
  const ownerId=await options.owner();
  if(!ownerId)throw options.failure('owner_changed');
  const assertOwner=async()=>{if(await options.owner()!==ownerId)throw options.failure('owner_changed');};
  let before=await options.version().catch(()=>null);
  await assertOwner();
  for(let attempt=0;attempt<2;attempt++) {
    let data:T;
    try { data=await options.loader(); }
    catch(primaryError) {
      await assertOwner();
      if([401,403,404,409,422].includes((primaryError as {status?:number}|null)?.status??0))throw primaryError;
      let snapshot:VerifiedSnapshot<T>;
      let verified:ResourceVersion;
      try {
        snapshot=await options.load();
        const current=await options.version();verified=current;
        if(snapshot.schemaVersion!==2 || !snapshot.versionVerified || snapshot.version!==current.version)throw primaryError;
      } catch { throw primaryError; }
      await assertOwner();
      options.announce({resource:options.resource,subjectId:options.subjectId,ownerId,cachedAt:snapshot.cachedAt,version:snapshot.version,dataVersion:verified.dataVersion});
      return snapshot.data;
    }
    await assertOwner();
    const after=await options.version().catch(()=>null);
    await assertOwner();
    if(before && after && before.version!==after.version) {
      if(attempt===0){before=after;continue;}
      throw options.failure('version_changed');
    }
    if(before && after) {
      try {await options.save(data,before.version);}catch { /* A cache outage never fails a primary success. */ }
      await assertOwner();
    }
    options.announce({resource:options.resource,subjectId:options.subjectId,ownerId,cachedAt:null,version:after?.version,dataVersion:after?.dataVersion});
    return data;
  }
  throw options.failure('version_changed');
}
