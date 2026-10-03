import { useEffect, useRef } from 'react'
import { createPortal } from 'react-dom'
import { Archive, Pencil } from 'lucide-react'
import { useTranslation } from './i18n'

export function ProjectMenu({ x, y, allowed, close, archive, rename }: {
  x: number; y: number; allowed: boolean; close: () => void; archive: () => void; rename: () => void
}) {
  const t = useTranslation(), menu = useRef<HTMLDivElement>(null)
  useEffect(() => {
    menu.current?.querySelector<HTMLButtonElement>('button:not(:disabled)')?.focus()
    const dismiss = (event: PointerEvent) => {
      if (!menu.current?.contains(event.target as Node)) close()
    }
    const keyboard = (event: KeyboardEvent) => { if (event.key === 'Escape') close() }
    document.addEventListener('pointerdown', dismiss)
    document.addEventListener('keydown', keyboard)
    window.addEventListener('resize', close)
    window.addEventListener('scroll', close, true)
    return () => {
      document.removeEventListener('pointerdown', dismiss)
      document.removeEventListener('keydown', keyboard)
      window.removeEventListener('resize', close)
      window.removeEventListener('scroll', close, true)
    }
  }, [close])
  return createPortal(<div ref={menu} className="project-context-menu" role="menu" aria-label={t('项目操作')}
    style={{ left: Math.max(8, Math.min(x, window.innerWidth - 198)), top: Math.max(8, Math.min(y, window.innerHeight - 112)) }}>
    <button role="menuitem" onClick={() => { close(); rename() }}><Pencil size={15} />{t("重命名项目")}</button>
    <button role="menuitem" disabled={!allowed} title={!allowed ? t('请完成或取消运行中的任务后再归档') : undefined}
      onClick={() => { close(); archive() }}><Archive size={15} />{t('归档项目')}</button>
  </div>, document.body)
}
