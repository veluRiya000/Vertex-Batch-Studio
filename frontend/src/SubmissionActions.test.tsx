import {afterEach,it,expect,vi} from 'vitest';
import {render,screen,cleanup} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {SubmissionActions} from './SubmissionActions';
import type {Batch} from './types';
vi.mock('./i18n',()=>({useTranslation:()=>((s:string)=>s)}));
afterEach(cleanup);
const batch={id:'a',phase:'submission_unknown',job_name:null} as Batch;
it('结果不明核对并重试，未找到后可直接重试原轮次',async()=>{
 const action=vi.fn(),user=userEvent.setup();
 const view=render(<SubmissionActions batch={batch} action={action}/>);
 await user.click(screen.getByRole('button',{name:'核对并重试'}));expect(action).toHaveBeenLastCalledWith(batch,'recover');
 const next={...batch,phase:'submission_unconfirmed',reconciliation_status:'not_found' as const};
 view.rerender(<SubmissionActions batch={next} action={action}/>);
 await user.click(screen.getByRole('button',{name:'重新提交本轮'}));expect(action).toHaveBeenLastCalledWith(next,'recover');
});
it('核对失败与未找到不同，风险提交需要行内确认，返回不提交',async()=>{
 const value={...batch,reconciliation_status:'failed' as const},action=vi.fn(),user=userEvent.setup();
 render(<SubmissionActions batch={value} action={action}/>);
 await user.click(screen.getByRole('button',{name:'重试核对'}));expect(action).toHaveBeenCalledWith(value,'poll');
 action.mockClear();await user.click(screen.getByRole('button',{name:'仍要重新提交'}));expect(action).not.toHaveBeenCalled();
 await user.click(screen.getByRole('button',{name:'返回'}));expect(action).not.toHaveBeenCalled();
 await user.click(screen.getByRole('button',{name:'仍要重新提交'}));
 await user.click(screen.getByRole('button',{name:'确认重新提交'}));expect(action).toHaveBeenCalledWith(value,'recover_force');
});
it('正常生成和完成始终保留刷新结果，活动查询禁止重复点击',async()=>{
 const action=vi.fn(),user=userEvent.setup();
 const value={...batch,job_name:'cloud-job',phase:'monitoring'};
 const view=render(<SubmissionActions batch={value} action={action}/>);
 await user.click(screen.getByRole('button',{name:'刷新结果'}));expect(action).toHaveBeenCalledWith(value,'poll');
 view.rerender(<SubmissionActions batch={{...value,phase:'completed'}} action={action}/>);
 expect(screen.getByRole('button',{name:'刷新结果'})).toBeTruthy();
 view.rerender(<SubmissionActions batch={{...value,active_action:'poll',action_started_at:new Date().toISOString()}} action={action}/>);
 expect((screen.getByRole('button',{name:'刷新结果'}) as HTMLButtonElement).disabled).toBe(true);
 expect(screen.getByRole('status').textContent).toContain('正在刷新结果');
});
it('上传失败直接提交，不查询云端；排队与运行提示不同',async()=>{
 const action=vi.fn(),user=userEvent.setup(),value={...batch,phase:'upload_failed'};
 const view=render(<SubmissionActions batch={value} action={action}/>);
 await user.click(screen.getByRole('button',{name:'重新提交本轮'}));expect(action).toHaveBeenCalledWith(value,'submit');
 view.rerender(<SubmissionActions batch={{...value,active_action:'submit'}} action={action}/>);
 expect(screen.getByRole('status').textContent).toBe('操作已排队');
 view.rerender(<SubmissionActions batch={{...value,phase:'uploading',active_action:'submit',
   action_started_at:new Date().toISOString(),operation:{stage:'uploading_refs',started_at:new Date().toISOString(),completed:1,total:4}}} action={action}/>);
 expect(screen.getByRole('status').textContent).toContain('正在上传参考图 · 2/4');
 expect(screen.queryByRole('button',{name:'核对并重试'})).toBeNull();
});
