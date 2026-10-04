import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { LibraryPane } from './LibraryPane'

beforeEach(() => {
  localStorage.clear()
  Object.defineProperty(window, 'PointerEvent', { configurable: true, value: MouseEvent })
  HTMLElement.prototype.setPointerCapture = vi.fn()
  HTMLElement.prototype.releasePointerCapture = vi.fn()
})
afterEach(() => { cleanup(); vi.restoreAllMocks() })
const view = () => <div><LibraryPane><section>References</section></LibraryPane><section>Projects</section></div>
it('dragging uses exact intermediate heights and persists them across remounts', () => {
  const { unmount } = render(view())
  const handle = screen.getByRole('separator', { name: '调整图库高度' })
  fireEvent.pointerDown(handle, { clientY: 260, button: 0 })
  fireEvent.pointerMove(handle, { clientY: 337 })
  expect(handle.getAttribute('aria-valuenow')).toBe('337')
  fireEvent.pointerUp(handle, { clientY: 337 })
  expect(localStorage.getItem('vbs-library-height')).toBe('337')
  unmount(); render(view())
  expect(screen.getByRole('separator').getAttribute('aria-valuenow')).toBe('337')
})
it('resizing reserves space for projects, clamps bounds and supports the keyboard', () => {
  let available = 600
  vi.spyOn(HTMLElement.prototype, 'clientHeight', 'get').mockImplementation(() => available)
  render(view())
  const handle = screen.getByRole('separator')
  fireEvent.keyDown(handle, { key: 'End' })
  expect(handle.getAttribute('aria-valuenow')).toBe('440')
  available = 400; fireEvent(window, new Event('resize'))
  expect(handle.getAttribute('aria-valuenow')).toBe('240')
  available = 600; fireEvent(window, new Event('resize'))
  expect(handle.getAttribute('aria-valuenow')).toBe('440')
  fireEvent.keyDown(handle, { key: 'Home' })
  expect(handle.getAttribute('aria-valuenow')).toBe('144')
  fireEvent.keyDown(handle, { key: 'ArrowUp' })
  expect(handle.getAttribute('aria-valuenow')).toBe('144')
  fireEvent.keyDown(handle, { key: 'ArrowDown' })
  expect(handle.getAttribute('aria-valuenow')).toBe('164')
})
it('cancelled dragging stops responding and invalid stored values are ignored', () => {
  localStorage.setItem('vbs-library-height', 'Infinity')
  render(view())
  const handle = screen.getByRole('separator')
  expect(handle.getAttribute('aria-valuenow')).toBe('260')
  fireEvent.pointerDown(handle, { clientY: 260, button: 0 })
  fireEvent.pointerCancel(handle)
  fireEvent.pointerMove(handle, { clientY: 400 })
  expect(handle.getAttribute('aria-valuenow')).toBe('260')
})
