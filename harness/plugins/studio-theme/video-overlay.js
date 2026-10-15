/** Optional decoration of upstream attachment cards; no uploader or React state changes. */
(() => {
  const policy=window.__VBS_ATTACHMENT_POLICY__;
  if(!policy?.showUnsupportedVideoOverlay)return;
  const selector='[data-composer-card] div[title]';
  function video(name) {
    const extension=String(name).split('.').at(-1).toLowerCase();
    return policy.videoExtensions.includes(extension);
  }
  function reconcile() {
    for(const card of document.querySelectorAll(selector)) {
      // Only full attachment cards, never editor file mentions or preview controls.
      const remove=card.querySelector('button[aria-label]');
      if(!remove||!video(card.getAttribute('title')))continue;
      card.classList.add('vbs-unsupported-video');
      if(card.querySelector(':scope > .vbs-unsupported-video-overlay'))continue;
      const overlay=document.createElement('div');
      overlay.className='vbs-unsupported-video-overlay';
      overlay.setAttribute('role','note');
      overlay.setAttribute('aria-label','不支持的文件类型');
      const icon=document.createElement('span');
      icon.className='vbs-unsupported-video-icon';icon.textContent='!';icon.setAttribute('aria-hidden','true');
      const label=document.createElement('span');label.textContent='不支持的文件类型';
      overlay.append(icon,label);card.append(overlay);
    }
    for(const card of document.querySelectorAll('.vbs-unsupported-video')) {
      if(!card.isConnected||video(card.getAttribute('title')))continue;
      card.classList.remove('vbs-unsupported-video');
      card.querySelector(':scope > .vbs-unsupported-video-overlay')?.remove();
    }
  }
  let scheduled=false;
  const observer=new MutationObserver(()=>{
    if(scheduled)return;scheduled=true;
    queueMicrotask(()=>{scheduled=false;reconcile();});
  });
  observer.observe(document.body,{childList:true,subtree:true,attributes:true,attributeFilter:['title']});
  reconcile();
  window.addEventListener('pagehide',()=>observer.disconnect(),{once:true});
})();
