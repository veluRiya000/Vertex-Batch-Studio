import { useId, useLayoutEffect, useRef, useState } from 'react'
import { ChevronDown, ChevronUp } from 'lucide-react'
import { useTranslation } from './i18n'

// Measure wrapped text rather than counting newlines; resizing can change its line count.
export function CollapsiblePrompt({ text }: { text: string }) {
  const t = useTranslation(), id = useId(), paragraph = useRef<HTMLParagraphElement>(null)
  const [expanded, setExpanded] = useState(false), [overflow, setOverflow] = useState(false)
  useLayoutEffect(() => { setExpanded(false) }, [text])
  useLayoutEffect(() => {
    const element = paragraph.current!
    const measure = () => {
      const lineHeight = parseFloat(getComputedStyle(element).lineHeight) || 24.05
      setOverflow(element.scrollHeight > lineHeight * 5 + 1)
    }
    measure()
    const observer = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(measure) : undefined
    observer?.observe(element)
    window.addEventListener('resize', measure)
    return () => { observer?.disconnect(); window.removeEventListener('resize', measure) }
  }, [text, expanded])
  return <div className="collapsible-prompt">
    <p ref={paragraph} id={id} className={expanded ? undefined : 'prompt-collapsed'}>{text}</p>
    {overflow && <button className="text-button prompt-toggle" aria-expanded={expanded} aria-controls={id}
      onClick={() => setExpanded(value => !value)}>
      {expanded ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
      {t(expanded ? '收起' : '展开全文')}
    </button>}
  </div>
}
