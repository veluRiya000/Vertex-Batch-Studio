/** Optional, non-nullable permission fields may arrive as JSONL null padding. */
export function executionArguments(args, schema, paddingFields=new Map()) {
  if (!schema || typeof schema !== 'object') return args;
  const required = new Set(schema.required || []);
  let result = args;
  // A Batch record can share one inferred args shape across different tools.
  // Only drop unknown padding proven by another declared argument in THIS
  // response, and only when this tool explicitly rejects additional fields.
  if(schema.additionalProperties===false)for(const [key,value] of Object.entries(args)) {
    if(Object.hasOwn(schema.properties||{},key) || !paddingFields.has(key))continue;
    if(value!==null && !(Array.isArray(value)&&value.length===0&&paddingFields.get(key)==='array'))continue;
    if(result===args)result={...args};
    delete result[key];
  }

  for (const key of ['sandbox_permissions', 'justification']) {
    const field = schema.properties?.[key];
    // Only these declared, optional string fields mean "use session defaults"
    // when absent. Never coerce numbers, drop required/null-able arguments, or
    // touch arbitrary user JSON. Real escalation still reaches DSH validation.
    if (args[key] !== null || !field || required.has(key) ||
        !['string', 'STRING'].includes(field.type) || field.nullable === true ||
        field.anyOf || field.oneOf || field.enum?.includes(null)) continue;
    if (result === args) result = {...args};
    delete result[key];
  }
  return result;
}
