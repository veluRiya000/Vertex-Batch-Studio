import { useLayoutEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { useTranslation } from './i18n'

const minimum = 144, storageKey = 'vbs-library-height'
export function LibraryPane({ children }: { children: ReactNode }) {
  const t = useTranslation(), pane = useRef<HTMLDivElement>(null)
  const drag = useRef<{ id: number; y: number; height: number } | undefined>(undefined)
  const [preferred, setPreferred] = useState(() => {
    try { const value = Number(localStorage.getItem(storageKey)); return Number.isFinite(value) && value >= minimum && value <= 1200 ? value : 260 }
    catch { return 260 }
  })
  const [available, setAvailable] = useState(600), [dragging, setDragging] = useState(false)
  const maximum = Math.max(minimum, available - 160), height = Math.min(preferred, maximum)
  const update = (value: number) => {
    const next = Math.round(Math.max(minimum, Math.min(maximum, value)))
    setPreferred(next)
    try { localStorage.setItem(storageKey, String(next)) } catch { /* Private sessions may disable storage. */ }
  }
  useLayoutEffect(() => {
    const parent = pane.current!.parentElement!
    const measure = () => { if (parent.clientHeight > 0) setAvailable(parent.clientHeight) }
    measure()
    const observer = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(measure) : undefined
    observer?.observe(parent)
    window.addEventListener('resize', measure)
    return () => { observer?.disconnect(); window.removeEventListener('resize', measure) }
  }, [])
  return <>
    <div ref={pane} className="reference-pane" style={{ height }}>{children}</div>
    <div className={'library-height-handle' + (dragging ? ' dragging' : '')}
      role="separator" aria-label={t('调整图库高度')} aria-orientation="horizontal"
      aria-valuemin={minimum} aria-valuemax={maximum} aria-valuenow={height} tabIndex={0}
      title={t('拖动调整图库与项目栏高度')}
      onPointerDown={event => {
        if (event.button !== 0) return
        event.preventDefault()
        drag.current = { id: event.pointerId, y: event.clientY, height }
        setDragging(true)
        event.currentTarget.setPointerCapture(event.pointerId)
      }}
      onPointerMove={event => {
        if (drag.current && drag.current.id === event.pointerId)
          update(drag.current.height + event.clientY - drag.current.y)
      }}
      onPointerUp={event => {
        if (!drag.current || drag.current.id !== event.pointerId) return
        update(drag.current.height + event.clientY - drag.current.y)
        drag.current = undefined; setDragging(false)
        event.currentTarget.releasePointerCapture(event.pointerId)
      }}
      onPointerCancel={() => { drag.current = undefined; setDragging(false) }}
      onLostPointerCapture={() => { drag.current = undefined; setDragging(false) }}
      onKeyDown={event => {
        const next = event.key === 'ArrowUp' ? height - 20 : event.key === 'ArrowDown' ? height + 20
          : event.key === 'Home' ? minimum : event.key === 'End' ? maximum : undefined
        if (next !== undefined) { event.preventDefault(); update(next) }
      }} />
  </>
}
