export const modelProfiles=Object.freeze([
  {id:'gemini-4-argon',name:'Gemini 4 Argon · Batch',contextWindow:1048576,maxOutputTokens:1048576,defaultEffort:'medium'},
  {id:'gemini-3.8-flash',name:'Gemini 3.8 Flash · Batch',contextWindow:1048576,maxOutputTokens:65536,defaultEffort:'medium'},
  {id:'gemini-3.1-pro-preview',name:'Gemini 3.1 Pro Preview · Batch',contextWindow:1048576,maxOutputTokens:65536,defaultEffort:'high'},
]);
export function modelProfile(model='gemini-4-argon') {
  const value=modelProfiles.find(value=>value.id===model);
  if(!value)throw Error('Unsupported Batch model: '+model);
  return value;
}
export function validateModelOutput(model,cap) {
  const profile=modelProfile(model);
  if(!Number.isSafeInteger(cap)||cap<1||cap>profile.maxOutputTokens)
    throw Error(`${profile.name} 的官方输出额度上限为 ${profile.maxOutputTokens} Token；请在 Batch 运行设置中调整。`);
  return cap;
}
