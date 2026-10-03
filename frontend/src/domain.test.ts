import { describe, expect, it } from 'vitest'
import { groupBatches, matchRatio, statusClass } from './domain'
import type { Batch, Reference } from './types'

const batch = (id:string, source?:string) => ({id,workspace_id:id,source_batch_id:source,project_name:'夏日祭',created_at:id,phase:'draft',archived:false} as Batch)
describe('项目和图片参数',()=>{
  it('旧数据和多轮重试都归入同一项目，独立同名项目仍独立',()=>{
    const groups=groupBatches([batch('c','b'),batch('a'),batch('b','a'),batch('d')])
    expect(groups).toHaveLength(2)
    expect(groups.find(item=>item.id==='a')!.batches.map(item=>item.id)).toEqual(['a','b','c'])
  })
  it('按第一张参考图匹配可用比例，不把特殊选项发给云端',()=>{
    expect(matchRatio({dimensions:[1920,1080]} as Reference)).toBe('16:9')
    expect(matchRatio({dimensions:[1000,1500]} as Reference)).toBe('2:3')
    expect(matchRatio({dimensions:[1200,1200]} as Reference)).toBe('1:1')
    expect(()=>matchRatio()).toThrow('先选一张参考图')
    expect(()=>matchRatio({dimensions:[0,0]} as Reference)).toThrow('无法读取')
  })
  it('按实际任务结果区分已完成、部分失败和生成中',()=>{
    const active={...batch('a'),phase:'monitoring'}
    expect(statusClass(active,'succeeded')).toBe('completed')
    expect(statusClass(active,'error')).toBe('failed')
    expect(statusClass(active,'pending')).toBe('generating')
  })
})
