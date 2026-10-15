import {afterEach,expect,it,vi} from 'vitest';
import {cleanup,render,screen} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {CloudConsoleLink,cloudConsoleUrl} from './CloudConsoleLink';
afterEach(()=>{cleanup();delete window.studio;});
it('project input remains a query value on the fixed Google Cloud host',()=>{
  const url=new URL(cloudConsoleUrl('credentials','my-project&redirect=https://example.org'));
  expect(url.hostname).toBe('console.cloud.google.com');
  expect(url.pathname).toBe('/iam-admin/serviceaccounts');
  expect(url.searchParams.get('redirect')).toBeNull();
  expect(url.searchParams.get('project')).toBe('my-project&redirect=https://example.org');
  expect(new URL(cloudConsoleUrl('project','')).search).toBe('');
});
it('desktop clicks use the external browser bridge with the current project',async()=>{
  const openCloudPage=vi.fn().mockResolvedValue(undefined);
  window.studio={openCloudPage} as never;
  const {rerender}=render(<CloudConsoleLink page="storage" project="old-project" label="打开存储桶" onError={()=>{}}/>);
  rerender(<CloudConsoleLink page="storage" project="new-project" label="打开存储桶" onError={()=>{}}/>);
  expect(screen.getByRole('link',{name:'打开存储桶'}).getAttribute('href')).toContain('project=new-project');
  await userEvent.setup().click(screen.getByRole('link',{name:'打开存储桶'}));
  expect(openCloudPage).toHaveBeenCalledWith('storage','new-project');
});
