/** Feature switches: enable independently when native video input is implemented. */
export const attachmentPolicy = Object.freeze({
  showUnsupportedVideoOverlay: true,
  skipVideoAttachments: true,
  videoExtensions: Object.freeze(['mp4','m4v','mov','webm','avi','mkv','mpeg','mpg','mpe','mpegs','wmv','flv','3gp','3gpp','ogv','m2ts']),
});

export function isVideoAttachment(name='',mediaType='',policy=attachmentPolicy) {
  if(String(mediaType).toLowerCase().startsWith('video/'))return true;
  const leaf=String(name).split(/[\\/]/).at(-1);
  const extension=leaf.includes('.')?leaf.split('.').at(-1).toLowerCase():'';
  return policy.videoExtensions.includes(extension);
}

/** Filter only uploaded user attachments, leaving transcript and tool replay intact. */
export function skipUnsupportedAttachments(messages,parseHandle,policy=attachmentPolicy) {
  if(!policy.skipVideoAttachments)return {messages,skipped:[]};
  const skipped=[];
  const next=messages.map(message=>{
    if(message.role!=='user')return message;
    const content=message.content.filter(block=>{
      const ref=block.type==='text'?parseHandle(block.text):undefined;
      const structured=block.type==='video'||block.type==='file'?block.attachment:undefined;
      const video=ref?isVideoAttachment(ref.name,'',policy):structured?isVideoAttachment(structured.name,structured.mediaType,policy):block.type==='video';
      if(video){skipped.push({name:ref?.name||structured?.name||'video'});return false;}
      return true;
    });
    return content.length===message.content.length?message:{...message,content};
  });
  return {messages:next,skipped};
}
