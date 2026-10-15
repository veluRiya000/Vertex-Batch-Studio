/** Stream durable snapshots, then reattach to the same receipt after a lost socket. */
export async function* snapshots(url, token, signal) {
  while (!signal?.aborted) {
    let reader;
    try {
      const response=await fetch(url,{headers:{'X-VBS-Harness-Token':token},signal});
      if(!response.ok || !response.body)throw Error('Batch event channel unavailable');
      reader=response.body.getReader();
      const decoder=new TextDecoder();let buffer='';
      while(!signal?.aborted) {
        const {value,done}=await reader.read();if(done)break;
        buffer+=decoder.decode(value,{stream:true}).replace(/\r/g,'');
        let end;
        while((end=buffer.indexOf('\n\n'))!==-1) {
          const event=buffer.slice(0,end);buffer=buffer.slice(end+2);
          const data=event.split('\n').filter(l=>l.startsWith('data:')).map(l=>l.slice(5).trim()).join('\n');
          if(!data)continue;
          const snapshot=JSON.parse(data);yield snapshot;
          if(['completed','failed','cancelled','budget_paused'].includes(snapshot.phase))return;
        }
      }
    } catch(error) {if(signal?.aborted)throw error;}
    finally {if(reader){await reader.cancel().catch(()=>{});reader.releaseLock();}}
    await new Promise((resolve,reject)=>{
      const stop=()=>{clearTimeout(timer);signal?.removeEventListener('abort',stop);reject(signal.reason || Error('Aborted'));};
      const timer=setTimeout(()=>{signal?.removeEventListener('abort',stop);resolve();},1000);
      signal?.addEventListener('abort',stop,{once:true});if(signal?.aborted)stop();
    });
  }
}
