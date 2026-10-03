import { useState } from 'react'
import { Archive, Trash2 } from 'lucide-react'
import { useTranslation } from './i18n'
import type { Workspace } from './types'

export function ArchivePanel({ projects, remove }: { projects: Workspace[]; remove: (id: string) => Promise<void> }) {
  const t = useTranslation()
  const [confirm, setConfirm] = useState<Workspace>(), [busy, setBusy] = useState(false), [error, setError] = useState('')
  async function destroy() {
    if (!confirm || busy) return
    setBusy(true); setError('')
    try { await remove(confirm.id); setConfirm(undefined) }
    catch (e) { setError(e instanceof Error ? e.message : t('删除失败')) }
    finally { setBusy(false) }
  }
  return <section className="archive-panel">
    <div className="settings-subheading"><Archive size={17} />{t('归档')}</div>
    {confirm ? <div className="archive-confirm" role="alertdialog" aria-label={t('删除归档项目')}>
      <strong>{t('删除归档项目')}「{confirm.name}」？</strong>
      <p>{t('将永久删除此项目的本地任务、临时参考图和项目内输出。公共参考图库、外部输出目录及云端文件会保留。')}</p>
      <div className="archive-confirm-actions">
        <button className="secondary-button" disabled={busy} onClick={() => { setConfirm(undefined); setError('') }}>{t('取消')}</button>
        <button className="primary-button destructive" disabled={busy} onClick={() => void destroy()}><Trash2 size={14} />{t('确认删除')}</button>
      </div>
    </div> : <div className="archived-projects">
      {projects.map(project => <div className="archived-project" key={project.id}>
        <Archive size={16} />
        <div><strong>{project.name}</strong><small>{project.batches.at(-1)?.created_at.slice(0, 10)} · {project.batches.length} {t('个批次')}</small></div>
        <button className="icon-button danger" aria-label={t('删除归档项目 ') + project.name} title={t('删除归档项目')}
          onClick={() => { setConfirm(project); setError('') }}><Trash2 size={16} /></button>
      </div>)}
      {!projects.length && <p className="archive-empty">{t('暂无归档项目')}</p>}
    </div>}
    {error && <p className="settings-error" role="alert">{error}</p>}
  </section>
}
