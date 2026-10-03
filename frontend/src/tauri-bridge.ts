import { Channel, invoke, isTauri } from '@tauri-apps/api/core'
import { getCurrentWindow } from '@tauri-apps/api/window'
import type { Batch, Preferences, Reference, Snapshot, Task } from './types'

export async function notifyRendererReady(): Promise<void> {
  if (!isTauri()) return
  await invoke('studio_api', { method: 'GET', path: '/health', body: null })
  const smoke = await invoke<boolean>('smoke_mode')
  if (smoke) {
    const bridge = window.studio!
    const config = await bridge.api('GET', '/config') as { project: string; bucket: string }
    if (config.project || config.bucket) throw new Error('Smoke tests require an unconfigured isolated directory')
    const batch = await bridge.api('POST', '/batches', { project_name: '桌面迁移验收' }) as Batch
    const png = await fetch(new URL('../src-tauri/icons/icon.png', import.meta.url)).then(response => response.arrayBuffer())
    const reference = await bridge.upload(`验收参考图-${batch.id}.png`, png, { category: 'styles' })
    const image = await bridge.image('/references/file?' + new URLSearchParams({ path: reference.path }))
    if (!image.startsWith('data:image/png;base64,')) throw new Error('Image bridge failed')
    const task = await bridge.api('POST', `/batches/${batch.id}/tasks`, {
      name: '桌面离线任务', prompt: '夏日祭灯笼', refs: [reference.path], image_count: 3,
    }) as Task
    if (task.image_count !== 3 || task.refs[0] !== reference.path) throw new Error('Task bridge failed')
    const preferences = await bridge.api('GET', '/preferences') as Preferences
    await bridge.setPreferences({ ...preferences, theme: 'dark', language: 'en' })
    await bridge.setPreferences(preferences)
    await new Promise<void>((resolve, reject) => {
      let stop = () => {}
      const timer = setTimeout(() => { stop(); reject(new Error('SSE bridge timed out')) }, 10000)
      stop = bridge.watch(batch.id, snapshot => {
        clearTimeout(timer); stop()
        if (snapshot.batch.id === batch.id) resolve()
        else reject(new Error('SSE batch mismatch'))
      })
    })
    let rejected = false
    try { await bridge.api('POST', `/batches/${batch.id}/submit`) } catch { rejected = true }
    if (!rejected) throw new Error('Unconfigured submission should be rejected')
    const cancelled = await bridge.api('POST', `/batches/${batch.id}/cancel`) as Batch
    if (cancelled.phase !== 'cancelled') throw new Error('Local cancellation failed')
    const referencePath = '/references?' + new URLSearchParams({ path: reference.path })
    let protectedReference = false
    try { await bridge.api('DELETE', referencePath) } catch { protectedReference = true }
    if (!protectedReference) throw new Error('Referenced library image was not protected')
    const archived = await bridge.api('POST', `/workspaces/${batch.workspace_id}/archive`) as Batch[]
    if (!archived.every(value => value.archived)) throw new Error('Project archive failed')
    await bridge.api('DELETE', `/workspaces/${batch.workspace_id}`)
    const remaining = await bridge.api('DELETE', referencePath) as Reference[]
    if (remaining.some(value => value.path === reference.path)) throw new Error('Library deletion failed')
    await invoke('window_action', { action: 'maximize' })
    await invoke('window_action', { action: 'maximize' })
    if (!document.querySelector('.titlebar') || !document.querySelector('.composer')) throw new Error('Studio UI did not render')
    if (!document.querySelector('.connection')?.textContent?.includes('未配置')) throw new Error('Unconfigured cloud indicator failed')
  }
  await invoke('renderer_ready')
}

export function reportRendererFailure(error: unknown): void {
  console.error(error)
  if (isTauri()) void invoke('renderer_failed', { message: String(error) })
}

// Keep the existing renderer contract. The backend token never enters JavaScript.
if (isTauri()) {
  window.studio = {
    api: (method, path, body) => invoke('studio_api', { method, path, body: body ?? null }),
    image: path => invoke<string>('studio_image', { path }),
    upload: (name, bytes, options) => invoke<Reference>('studio_upload', {
      name, bytes: Array.from(new Uint8Array(bytes)), options,
    }),
    chooseDirectory: () => invoke<string | null>('choose_directory'),
    openOutput: id => invoke('open_output', { id }),
    setPreferences: value => invoke<Preferences>('set_preferences', { value }),
    window: action => { void invoke('window_action', { action }).catch(console.error) },
    watch: (id, callback) => {
      const key = crypto.randomUUID()
      const channel = new Channel<Snapshot>()
      let disposed = false
      channel.onmessage = snapshot => { if (!disposed) callback(snapshot) }
      // Unsubscribe after registration, including when React unmounts immediately.
      const registered = invoke('watch_batch', { key, id, channel })
      void registered.catch(error => { if (!disposed) console.error(error) })
      return () => {
        disposed = true
        void registered.then(() => invoke('unwatch_batch', { key })).catch(console.error)
      }
    },
  }
  document.addEventListener('pointerdown', event => {
    const element = event.target as HTMLElement
    if (event.button === 0 && element.closest('.titlebar') &&
        !element.closest('button, input, select, a, .top-menu, .window-controls')) {
      void getCurrentWindow().startDragging()
    }
  })
}
