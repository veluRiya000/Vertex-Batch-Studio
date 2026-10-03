import type { ImportOptions, Reference, Snapshot } from './types'

export async function api<T>(path: string, method = 'GET', body?: unknown): Promise<T> {
  if (window.studio) return window.studio.api(method, path, body) as Promise<T>
  const response = await fetch('/api' + path, {
    method, headers: body === undefined ? {} : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!response.ok) {
    const value = await response.json().catch(() => null)
    throw new Error(typeof value?.detail === 'string' ? value.detail : value?.detail ? '参数有误，请检查输入内容' : '无法连接本地后端')
  }
  return response.status === 204 ? undefined as T : response.json()
}
export async function upload(file: File, options: ImportOptions): Promise<Reference> {
  if (file.size > 30 * 1024 * 1024) throw new Error('参考图不能超过 30 MB')
  if (window.studio) return window.studio.upload(file.name, await file.arrayBuffer(), options)
  const query = new URLSearchParams({ name: file.name, ...options })
  const response = await fetch('/api/references/upload?' + query, { method: 'POST', body: file })
  if (!response.ok) {
    const value = await response.json().catch(() => null)
    throw new Error(value?.detail || '图片导入失败')
  }
  return response.json()
}
export async function imageUrl(path: string): Promise<string> {
  return window.studio ? window.studio.image(path) : '/api' + path
}
export function watchBatch(id: string, callback: (snapshot: Snapshot) => void): () => void {
  if (window.studio) return window.studio.watch(id, callback)
  const controller = new AbortController()
  async function watch() {
    while (!controller.signal.aborted) {
      try {
        const response = await fetch(`/api/batches/${id}/events`, { signal: controller.signal })
        if (!response.ok || !response.body) throw new Error('进度连接暂时断开')
        const reader = response.body.getReader()
        const decoder = new TextDecoder()
        let buffer = ''
        while (!controller.signal.aborted) {
          const { done, value } = await reader.read()
          if (done) break
          buffer += decoder.decode(value, { stream: true }).replace(/\r/g, '')
          let end: number
          while ((end = buffer.indexOf('\n\n')) >= 0) {
            const event = buffer.slice(0, end); buffer = buffer.slice(end + 2)
            const data = event.split('\n').filter(line => line.startsWith('data:')).map(line => line.slice(5).trim()).join('\n')
            if (data) {
              const snapshot: Snapshot = JSON.parse(data)
              callback(snapshot)
              if (['completed','completed_with_errors','failed','cancelled'].includes(snapshot.batch.phase)) { controller.abort(); return }
            }
          }
        }
      } catch { if (controller.signal.aborted) return }
      await new Promise<void>(resolve => {
        const done = () => { clearTimeout(timer); controller.signal.removeEventListener('abort',done); resolve() }
        const timer = setTimeout(done, 3000)
        controller.signal.addEventListener('abort', done, { once: true })
      })
    }
  }
  void watch()
  return () => controller.abort()
}
