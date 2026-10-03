import type { Batch, Reference, Workspace } from './types'
export const landscape = ['16:9', '4:3', '3:2', '21:9']
export const portrait = ['9:16', '3:4', '2:3', '9:21']
export const editable = (batch: Batch) => !batch.archived && ['draft', 'prepared'].includes(batch.phase)
export const terminal = (batch: Batch) => ['completed', 'completed_with_errors', 'failed', 'cancelled'].includes(batch.phase)
export function workspaceId(batch: Batch, batches: Batch[]): string {
  const visited = new Set<string>()
  let root = batch
  while (root.source_batch_id && !visited.has(root.id)) {
    visited.add(root.id)
    const source = batches.find(item => item.id === root.source_batch_id)
    if (!source) break
    root = source
  }
  return root.workspace_id || root.id
}
export function groupBatches(batches: Batch[]): Workspace[] {
  const map = new Map<string, Batch[]>()
  batches.forEach(batch => {
    const id = workspaceId(batch, batches)
    map.set(id, [...(map.get(id) || []), batch])
  })
  return Array.from(map, ([id, values]) => {
    const ordered = values.sort((a, b) => a.created_at.localeCompare(b.created_at))
    return { id, name: ordered[0].project_name, batches: ordered, archived: ordered.every(batch => batch.archived) }
  }).sort((a, b) => b.batches.at(-1)!.created_at.localeCompare(a.batches.at(-1)!.created_at))
}
export function matchRatio(reference?: Reference): string {
  if (!reference) throw new Error('先选一张参考图，再使用“匹配参考图”')
  if (reference.dimensions.some(value => value <= 0)) throw new Error('无法读取这张参考图的尺寸，请先导入本地图片')
  const ratio = reference.dimensions[0] / reference.dimensions[1]
  return [...landscape, ...portrait, '1:1'].reduce((best, candidate) => {
    const number = (value: string) => { const [w, h] = value.split(':').map(Number); return w / h }
    return Math.abs(Math.log(number(candidate) / ratio)) < Math.abs(Math.log(number(best) / ratio)) ? candidate : best
  })
}
export function phaseLabel(batch: Batch): string {
  return ({draft:'待提交',prepared:'待提交',uploading:'上传中',upload_failed:'上传失败',submitting:'提交中',
    submission_unknown:'核对提交中',submission_failed:'提交失败',monitoring:'生成中',completed:'已完成',
    completed_with_errors:'部分失败',failed:'失败',cancelled:'已取消',paused:'已暂停',downloading:'下载结果中'} as Record<string,string>)[batch.phase] || batch.phase
}
export function statusClass(batch: Batch, state?: string): string {
  if (state === 'succeeded') return 'completed'
  if (state === 'error' || state === 'missing' || ['failed','completed_with_errors','upload_failed','submission_failed'].includes(batch.phase)) return 'failed'
  if (['draft','prepared','paused','cancelled'].includes(batch.phase)) return 'pending'
  if (batch.phase === 'completed') return 'completed'
  return 'generating'
}
