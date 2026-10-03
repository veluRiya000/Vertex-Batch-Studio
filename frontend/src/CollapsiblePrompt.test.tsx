import { afterEach, expect, it, vi } from 'vitest'
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { CollapsiblePrompt } from './CollapsiblePrompt'

afterEach(() => { cleanup(); vi.restoreAllMocks() })
it('wrapped long text collapses, can expand, and responds to width changes', () => {
  let height = 180
  vi.spyOn(HTMLElement.prototype, 'scrollHeight', 'get').mockImplementation(() => height)
  const text = 'Long prompt without newlines '.repeat(40)
  const { container } = render(<CollapsiblePrompt text={text} />)
  const paragraph = container.querySelector('p')!
  expect(paragraph.textContent).toBe(text)
  expect(paragraph.className).toBe('prompt-collapsed')
  const toggle = screen.getByRole('button', { name: '展开全文' })
  expect(toggle.getAttribute('aria-expanded')).toBe('false')
  fireEvent.click(toggle)
  expect(screen.getByRole('button', { name: '收起' }).getAttribute('aria-expanded')).toBe('true')
  expect(paragraph.className).toBe('')
  fireEvent.click(screen.getByRole('button', { name: '收起' }))
  expect(paragraph.className).toBe('prompt-collapsed')
  height = 48
  act(() => window.dispatchEvent(new Event('resize')))
  expect(screen.queryByRole('button')).toBeNull()
  height = 240
  act(() => window.dispatchEvent(new Event('resize')))
  expect(screen.getByRole('button', { name: '展开全文' })).toBeTruthy()
})
it('short text needs no toggle and new text resets expansion', () => {
  let height = 48
  vi.spyOn(HTMLElement.prototype, 'scrollHeight', 'get').mockImplementation(() => height)
  const { rerender } = render(<CollapsiblePrompt text="short" />)
  expect(screen.queryByRole('button')).toBeNull()
  height = 240
  rerender(<CollapsiblePrompt text="long" />)
  fireEvent.click(screen.getByRole('button', { name: '展开全文' }))
  rerender(<CollapsiblePrompt text="different long" />)
  expect(screen.getByRole('button', { name: '展开全文' }).getAttribute('aria-expanded')).toBe('false')
})
