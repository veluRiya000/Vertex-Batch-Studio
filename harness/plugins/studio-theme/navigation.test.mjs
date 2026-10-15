import {test} from 'node:test';
import assert from 'node:assert/strict';
import {cloudSettingsHandler} from './navigation.mjs';

function fixture(overrides={}) {
  const calls=[];
  const handler=cloudSettingsHandler({authorize:()=>true,brokerUrl:'http://127.0.0.1:4321',brokerToken:'scoped-test',fetchBroker:async(...args)=>{calls.push(args);return {ok:true};},...overrides});
  const response={status:0,writeHead(status){this.status=status;},end(){}};
  const request={method:'POST',headers:{origin:'http://127.0.0.1:5678'},socket:{localPort:5678}};
  return {calls,handler,response,request};
}
test('authenticated same-origin button asks only for navigation, never for credentials or generation',async()=>{
  const {calls,handler,response,request}=fixture();
  await handler(request,response);
  assert.equal(response.status,204);
  assert.equal(calls.length,1);
  assert.equal(calls[0][0],'http://127.0.0.1:4321/harness/ui/cloud-settings');
  assert.equal(calls[0][1].method,'POST');
  assert.deepEqual(calls[0][1].headers,{'X-VBS-Harness-Token':'scoped-test'});
});
test('another page origin, missing cookie, or non-POST cannot open settings',async()=>{
  for(const variant of ['origin','cookie','method']) {
    const {calls,handler,response,request}=fixture(variant==='cookie'?{authorize:()=>false}:{});
    if(variant==='origin')request.headers.origin='http://127.0.0.1:9999';
    if(variant==='method')request.method='GET';
    await handler(request,response);
    assert.equal(calls.length,0);
    if(variant!=='cookie')assert.equal(response.status,variant==='origin'?403:405);
  }
});
test('standalone preview with no broker reports unavailable without leaking auth',async()=>{
  const {handler,response,request}=fixture({fetchBroker:async()=>{throw Error('scoped-test secret');}});
  let body='';response.end=value=>{body=value;};
  await handler(request,response);
  assert.equal(response.status,503);
  assert.equal(body,'Studio settings unavailable');
});
