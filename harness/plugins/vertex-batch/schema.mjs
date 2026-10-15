/** Gemini typed parameters; local DSH validators retain the full original schema. */
const types=new Set(['OBJECT','ARRAY','STRING','NUMBER','INTEGER','BOOLEAN','NULL']);
const textFields=new Set(['description','format','title','pattern']);
const numericFields=new Set(['minimum','maximum','minItems','maxItems','minLength','maxLength','minProperties','maxProperties']);
export function toParameters(schema,root=schema,depth=0) {
  if(depth>32)throw Error('Recursive tool schema is not supported by Batch');
  if(!schema || typeof schema!=='object' || Array.isArray(schema))throw Error('Tool schema must be an object');
  if(schema.$ref) {
    if(typeof schema.$ref!=='string'||!schema.$ref.startsWith('#/'))throw Error('External tool schema references are not supported');
    let target=root;
    for(const part of schema.$ref.slice(2).split('/'))target=target?.[part.replace(/~1/g,'/').replace(/~0/g,'~')];
    if(!target)throw Error('Missing tool schema reference');
    return toParameters(target,root,depth+1);
  }
  const result={};
  for(const [key,value] of Object.entries(schema)) {
    if(['$schema','$defs','definitions','default','examples'].includes(key))continue;
    if(key==='type') {
      if(Array.isArray(value)) {
        const nonNull=value.filter(v=>v!=='null');
        if(nonNull.length===1){result.type=String(nonNull[0]).toUpperCase();result.nullable=value.includes('null');}
        else result.anyOf=value.map(type=>toParameters({type},root,depth+1));
      } else {
        if(typeof value!=='string' || !types.has(value.toUpperCase()))throw Error('Unsupported tool schema type');
        result.type=value.toUpperCase();
      }
    } else if(key==='properties') {
      if(!value || typeof value!=='object' || Array.isArray(value))throw Error('Tool properties must be an object');
      result.properties=Object.fromEntries(Object.entries(value).map(([name,child])=>[name,toParameters(child,root,depth+1)]));
    } else if(key==='items')result.items=toParameters(value,root,depth+1);
    else if(key==='oneOf'||key==='anyOf') {
      if(!Array.isArray(value)||!value.length)throw Error('Invalid tool union schema');
      result.anyOf=value.map(child=>toParameters(child,root,depth+1));
    } else if(key==='required'||key==='propertyOrdering') {
      if(!Array.isArray(value)||value.some(v=>typeof v!=='string'))throw Error(`Tool ${key} must be strings`);
      result[key]=[...value];
    } else if(key==='enum'||key==='const') {
      const values=key==='const'?[value]:value;
      if(!Array.isArray(values)||!values.length)throw Error('Invalid tool enum');
      if(values.every(v=>typeof v==='string'))result.enum=[...values];
      else result.description=(result.description||schema.description||'')+' Allowed values: '+JSON.stringify(values);
    } else if(key==='nullable') {
      if(typeof value!=='boolean')throw Error('Tool nullable must be boolean');
      result.nullable=value;
    } else if(key==='additionalProperties') {
      result.additionalProperties=typeof value==='boolean'?value:toParameters(value,root,depth+1);
    } else if(textFields.has(key)) {
      if(typeof value!=='string')throw Error(`Tool ${key} must be text`);
      result[key]=value;
    } else if(numericFields.has(key)) {
      if(typeof value!=='number'||!Number.isFinite(value))throw Error(`Tool ${key} must be numeric`);
      result[key]=value;
    } else throw Error(`Unsupported tool schema field: ${key}`);
  }
  if(!result.type && !result.anyOf)throw Error('Tool schema has no type');
  return result;
}
