/** A cookie-authenticated UI intent. Never give the DSH page Studio's owner token. */
export function cloudSettingsHandler({authorize,brokerUrl,brokerToken,fetchBroker=fetch, tab="cloud"}) {
  return async (req,res) => {
    if(req.method!=='POST'){res.writeHead(405,{'allow':'POST'});res.end();return;}
    if(!authorize(req,res))return;
    // The browser may only request navigation from this Host's own page.
    if(req.headers.origin!==`http://127.0.0.1:${req.socket.localPort}`){res.writeHead(403);res.end();return;}
    if(!/^http:\/\/127\.0\.0\.1:\d+$/.test(brokerUrl || '')){res.writeHead(503);res.end();return;}
    try {
      const response=await fetchBroker(brokerUrl+(tab==='notifications' ? '/harness/ui/notification-settings' : '/harness/ui/cloud-settings'),{
        method:'POST',headers:{'X-VBS-Harness-Token':brokerToken},signal:AbortSignal.timeout(5000),
      });
      if(!response.ok)throw Error('Navigation rejected');
      res.writeHead(204,{'cache-control':'no-store'});res.end();
    } catch {res.writeHead(503);res.end('Studio settings unavailable');}
  };
}
