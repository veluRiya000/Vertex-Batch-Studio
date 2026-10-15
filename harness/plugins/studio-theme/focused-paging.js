/** Keep native editor paging inside its focused draft, not its sticky ancestors. */
(() => {
  // Also allow a development window to receive the fix without losing its draft.
  window.__VBS_FOCUSED_PAGING__?.dispose();
  let active = null, releaseTimer = 0;
  const keys = new Set(['PageUp', 'PageDown']);
  function clear() {
    clearTimeout(releaseTimer);
    active = null;
  }
  function currentEditor(target) {
    return target instanceof Element
      ? target.closest('[data-composer-input][contenteditable="true"]') : null;
  }
  function restore() {
    if (!active) return;
    const {editor, host, top, left} = active;
    if (!editor.isConnected || !host.isConnected || currentEditor(document.activeElement) !== editor) {
      clear();
      return;
    }
    // Scroll events run before paint. Do not touch the editor's own scrollport,
    // DOM selection, key default, Lexical history or conversation follow state.
    if (host.scrollTop !== top) host.scrollTop = top;
    if (host.scrollLeft !== left) host.scrollLeft = left;
  }
  function keydown(event) {
    if (!keys.has(event.key) || event.altKey || event.ctrlKey || event.metaKey || event.isComposing) {
      clear();
      return;
    }
    const editor = currentEditor(event.target);
    const host = editor?.closest('[data-conversation-scroll]');
    if (!editor || !host || currentEditor(document.activeElement) !== editor) return;
    if (active?.editor !== editor || active.host !== host) {
      active = {editor, host, top: host.scrollTop, left: host.scrollLeft};
    }
    clearTimeout(releaseTimer);
    // A missed keyup must never leave a permanent scroll lock. Repeats renew it.
    releaseTimer = setTimeout(clear, 1200);
  }
  function keyup(event) {
    if (!active || !keys.has(event.key)) return;
    restore();
    clearTimeout(releaseTimer);
    // Native caret reveal can continue after keyup; keep only this short tail.
    releaseTimer = setTimeout(clear, 220);
  }
  function scroll(event) {
    if (event.target === active?.host) restore();
  }
  function focusout(event) {
    if (active && currentEditor(event.relatedTarget) !== active.editor) clear();
  }
  const listeners = [
    ['keydown', keydown], ['keyup', keyup], ['scroll', scroll], ['focusout', focusout],
    ['pointerdown', clear], ['wheel', clear], ['touchstart', clear], ['beforeinput', clear],
  ];
  for (const [type, handler] of listeners) document.addEventListener(type, handler, {capture:true, passive:true});
  window.addEventListener('blur', clear);
  function dispose() {
    clear();
    for (const [type, handler] of listeners) document.removeEventListener(type, handler, true);
    window.removeEventListener('blur', clear);
    window.removeEventListener('pagehide', dispose);
    delete window.__VBS_FOCUSED_PAGING__;
  }
  window.addEventListener('pagehide', dispose, {once:true});
  window.__VBS_FOCUSED_PAGING__ = {dispose};
})();
