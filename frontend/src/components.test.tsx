import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Picker } from './components'
afterEach(cleanup)
it('数量菜单只包含数字，单位在按钮外，选中后关闭菜单并回传数量',async()=>{
  const changed=vi.fn(),user=userEvent.setup()
  render(<Picker label="图片数量" value="1" onChange={changed} unit="张" options={['1','2','3','4'].map(value=>({value,label:value}))}/> )
  await user.click(screen.getByRole('button',{name:'图片数量：1'}))
  expect(screen.getAllByRole('option').map(item=>item.textContent)).toEqual(['1','2','3','4'])
  await user.click(screen.getByRole('option',{name:'3'}))
  expect(changed).toHaveBeenCalledWith('3')
  expect(screen.queryByRole('listbox')).toBeNull()
  expect(screen.getByText('张').parentElement?.tagName).toBe('SPAN')
})
it('比例菜单分横竖两列，键盘可选择，Escape 返回输入按钮',async()=>{
  const user=userEvent.setup()
  render(<Picker label="比例" value="16:9" onChange={()=>{}} groups={[{label:'横屏',options:[{value:'16:9',label:'16:9'}]},{label:'竖屏',options:[{value:'9:16',label:'9:16'}]}]} options={[{value:'reference',label:'匹配参考图'}]}/> )
  await user.click(screen.getByRole('button',{name:'比例：16:9'}))
  expect(screen.getByRole('group',{name:'横屏'})).toBeTruthy()
  expect(screen.getByRole('group',{name:'竖屏'})).toBeTruthy()
  await user.keyboard('{ArrowDown}')
  expect(document.activeElement).toBe(screen.getByRole('option',{name:'16:9'}))
  await user.keyboard('{ArrowDown}')
  expect(document.activeElement).toBe(screen.getByRole('option',{name:'9:16'}))
  await user.keyboard('{Escape}')
  expect(screen.queryByRole('listbox')).toBeNull()
  expect(document.activeElement).toBe(screen.getByRole('button',{name:'比例：16:9'}))
})
