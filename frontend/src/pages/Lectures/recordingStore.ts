export type SavedRecording = {blob:Blob;name:string};
async function database():Promise<IDBDatabase>{
  return new Promise((resolve,reject)=>{const request=indexedDB.open('examai-recordings',1);request.onupgradeneeded=()=>request.result.createObjectStore('drafts');request.onsuccess=()=>resolve(request.result);request.onerror=()=>reject(request.error);});
}
export async function readRecording(key:string):Promise<SavedRecording|null>{
  const db=await database();
  try{return await new Promise((resolve,reject)=>{const tx=db.transaction('drafts','readonly');const request=tx.objectStore('drafts').get(key);request.onsuccess=()=>resolve(request.result||null);request.onerror=()=>reject(request.error);});}
  finally{db.close();}
}
export async function writeRecording(key:string,value:SavedRecording|null){
  const db=await database();
  try{await new Promise<void>((resolve,reject)=>{const tx=db.transaction('drafts','readwrite');if(value)tx.objectStore('drafts').put(value,key);else tx.objectStore('drafts').delete(key);tx.oncomplete=()=>resolve();tx.onerror=()=>reject(tx.error);tx.onabort=()=>reject(tx.error);});}
  finally{db.close();}
}
