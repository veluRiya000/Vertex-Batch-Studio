import {afterEach,expect,it,vi} from 'vitest';
import {act,cleanup,render,screen,waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {HarnessPane} from './HarnessPane';
import {api} from './api';
vi.mock('./api',()=>({api:vi.fn()}));
afterEach(()=>{cleanup();delete window.studio;vi.clearAllMocks();});
it('native view follows mode and modal visibility without starting cloud generation',async()=>{
  const harnessView=vi.fn().mockResolvedValue(undefined);
  window.studio={harnessView} as never;
  vi.mocked(api).mockResolvedValue({available:true,running:true,ready:true,error:null,offline:true,validation_required:true});
  const {rerender}=render(<HarnessPane active blocked={false}/>);
  await waitFor(()=>expect(harnessView).toHaveBeenCalledWith(true,true,true));
  rerender(<HarnessPane active blocked/>);
  await waitFor(()=>expect(harnessView).toHaveBeenLastCalledWith(false,true,true));
  rerender(<HarnessPane active={false} blocked={false}/>);
  await waitFor(()=>expect(harnessView).toHaveBeenLastCalledWith(false,true,true));
  expect(vi.mocked(api).mock.calls.every(([p])=>p==='/harness/status')).toBe(true);
});
it('browser preview starts only on click and keeps the link local',async()=>{
  vi.mocked(api).mockImplementation(async path=>path==='/harness/start'?{available:true,running:true,ready:true,offline:true,url:'http://127.0.0.1:12345/?token=test'}:{available:true,running:false,ready:false,offline:null} as never);
  render(<HarnessPane active blocked={false}/>);
  const user=userEvent.setup();
  await waitFor(()=>expect(screen.getByRole('button',{name:'打开 Harness'}).hasAttribute('disabled')).toBe(false));
  expect(vi.mocked(api).mock.calls.some(([p])=>p==='/harness/start')).toBe(false);
  await user.click(screen.getByRole('button',{name:'打开 Harness'}));
  await waitFor(()=>expect(api).toHaveBeenCalledWith('/harness/start','POST',{offline:false}));
  expect(screen.getByRole('link',{name:'打开浏览器界面'}).getAttribute('href')).toContain('http://127.0.0.1:12345/');
});


it('new navigation receipt opens settings once; polling and modal changes do not replay it',async()=>{
  const opened=vi.fn();
  window.addEventListener('vbs:open-cloud-settings',opened);
  let seq=0;
  vi.mocked(api).mockImplementation(async()=>({available:true,running:true,ready:true,offline:true,ui_request_seq:seq}) as never);
  try {
    render(<HarnessPane active blocked={false}/>);
    await waitFor(()=>expect(api).toHaveBeenCalled());
    expect(opened).not.toHaveBeenCalled();
    seq=1;
    const user=userEvent.setup();
    await user.click(screen.getByRole('button',{name:'刷新'}));
    await waitFor(()=>expect(opened).toHaveBeenCalledOnce());
    await user.click(screen.getByRole('button',{name:'刷新'}));
    expect(opened).toHaveBeenCalledOnce();
    expect(vi.mocked(api).mock.calls.every(([p])=>p==='/harness/status')).toBe(true);
  } finally {window.removeEventListener('vbs:open-cloud-settings',opened);}
});

it('loaded native view never renders the startup hero while resuming or toggling a modal',async()=>{
  let resolveShow!:()=>void;
  const show=new Promise<void>(resolve=>{resolveShow=resolve;});
  const harnessView=vi.fn().mockImplementation((visible:boolean)=>visible?show:Promise.resolve());
  window.studio={harnessView} as never;
  vi.mocked(api).mockResolvedValue({available:true,running:true,ready:true,error:null,offline:false,validation_required:true});
  const {rerender}=render(<HarnessPane active blocked={false}/>);
  expect(screen.queryByRole('button',{name:'打开 Harness'})).toBeNull();
  await waitFor(()=>expect(harnessView).toHaveBeenCalledWith(true,false,true));
  expect(screen.queryByRole('button',{name:'打开 Harness'})).toBeNull();
  rerender(<HarnessPane active={false} blocked={false}/>);
  rerender(<HarnessPane active blocked={false}/>);
  expect(screen.queryByRole('button',{name:'打开 Harness'})).toBeNull();
  rerender(<HarnessPane active blocked/>);
  expect(screen.queryByRole('button',{name:'打开 Harness'})).toBeNull();
  rerender(<HarnessPane active blocked={false}/>);
  expect(screen.queryByRole('button',{name:'打开 Harness'})).toBeNull();
  await act(async()=>resolveShow());
});

it('an older pending status response cannot resurrect the launch page after ready arrives',async()=>{
  let oldResolve!:(value:unknown)=>void;
  const old=new Promise(resolve=>{oldResolve=resolve;});
  window.studio={harnessView:vi.fn().mockResolvedValue(undefined)} as never;
  vi.mocked(api).mockImplementationOnce(()=>old as never).mockResolvedValue({available:true,running:true,ready:true,offline:false});
  const {rerender}=render(<HarnessPane active blocked={false}/>);
  rerender(<HarnessPane active={false} blocked={false}/>);
  rerender(<HarnessPane active blocked={false}/>);
  await waitFor(()=>expect(window.studio!.harnessView).toHaveBeenCalledWith(true,false,true));
  await act(async()=>oldResolve({available:true,running:false,ready:false,offline:null}));
  expect(screen.queryByRole('button',{name:'打开 Harness'})).toBeNull();
  expect(screen.getByRole('region',{name:'Harness'}).getAttribute('data-view-ready')).toBe('true');
});

it('a genuinely stopped native runtime still exposes its startup entry',async()=>{
  window.studio={harnessView:vi.fn().mockResolvedValue(undefined)} as never;
  vi.mocked(api).mockResolvedValue({available:true,running:false,ready:false,offline:null});
  render(<HarnessPane active blocked={false}/>);
  await waitFor(()=>expect(screen.getByRole('button',{name:'打开 Harness'}).hasAttribute('disabled')).toBe(false));
});

it('switching a loaded view does not wait for another status check or restart',async()=>{
  const harnessView=vi.fn().mockResolvedValue(undefined);
  window.studio={harnessView} as never;
  vi.mocked(api).mockResolvedValueOnce({available:true,running:true,ready:true,offline:false});
  const {rerender}=render(<HarnessPane active blocked={false}/>);
  await waitFor(()=>expect(harnessView).toHaveBeenCalledWith(true,false,true));
  // Even with the next status request pending, cached readiness restores now.
  vi.mocked(api).mockImplementation(()=>new Promise(()=>{}));
  rerender(<HarnessPane active={false} blocked={false}/>);
  harnessView.mockClear();
  rerender(<HarnessPane active blocked={false}/>);
  expect(harnessView).toHaveBeenCalledWith(true,false,true);
  expect(screen.queryByRole('button',{name:'打开 Harness'})).toBeNull();
  expect(harnessView.mock.calls.every(call=>call[2]===true)).toBe(true);
});

it('an explicit start still verifies the runtime rather than restoring a stale view',async()=>{
  const harnessView=vi.fn().mockResolvedValue(undefined);
  window.studio={harnessView} as never;
  vi.mocked(api).mockResolvedValue({available:true,running:false,ready:false,offline:null});
  render(<HarnessPane active blocked={false}/>);
  await waitFor(()=>expect(screen.getByRole('button',{name:'打开 Harness'}).hasAttribute('disabled')).toBe(false));
  await userEvent.setup().click(screen.getByRole('button',{name:'打开 Harness'}));
  expect(harnessView).toHaveBeenCalledWith(true,false);
});

it('Harness reminder shortcut opens the notification tab, without opening Cloud settings',async()=>{
  const notifications=vi.fn(),cloud=vi.fn();let seq=0;
  window.addEventListener('vbs:open-notification-settings',notifications);
  window.addEventListener('vbs:open-cloud-settings',cloud);
  vi.mocked(api).mockImplementation(async()=>({available:true,running:true,ready:true,offline:false,ui_request_seq:seq,ui_request_tab:'notifications'}) as never);
  try {
    render(<HarnessPane active blocked={false}/>);
    await waitFor(()=>expect(api).toHaveBeenCalled());
    seq=1;
    await userEvent.setup().click(screen.getByRole('button',{name:'刷新'}));
    await waitFor(()=>expect(notifications).toHaveBeenCalledOnce());
    expect(cloud).not.toHaveBeenCalled();
    await userEvent.setup().click(screen.getByRole('button',{name:'刷新'}));
    expect(notifications).toHaveBeenCalledOnce();
  }finally {
    window.removeEventListener('vbs:open-notification-settings',notifications);
    window.removeEventListener('vbs:open-cloud-settings',cloud);
  }
});
