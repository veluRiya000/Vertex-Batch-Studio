import {ExternalLink} from 'lucide-react';
import type {CloudPage} from './types';

const routes: Record<CloudPage, string> = {
  project: '/welcome',
  storage: '/storage/browser',
  credentials: '/iam-admin/serviceaccounts',
  billing_reports: '/billing/reports',
  billing_credits: '/billing/credits',
};
export function cloudConsoleUrl(page:CloudPage,project:string) {
  const url=new URL(routes[page],'https://console.cloud.google.com');
  if (project.trim() && !page.startsWith('billing_')) {
    url.searchParams.set('project', project.trim());
  }
  return url.href;
}
export function CloudConsoleLink({
  page, project = '', label, onError, showLabel = false,
}: {
  page: CloudPage;
  project?: string;
  label: string;
  onError: (message: string) => void;
  showLabel?: boolean;
}) {
  return <a className={showLabel ? 'top-cloud-link' : 'cloud-console-link'} href={cloudConsoleUrl(page,project)} target="_blank" rel="noopener noreferrer" title={label} aria-label={label}
    onClick={event=>{
      if(!window.studio?.openCloudPage)return;
      event.preventDefault();
      void window.studio.openCloudPage(page,project.trim()).catch(error=>onError((error as Error).message));
    }}>
      {showLabel && label}
      <ExternalLink size={13} strokeWidth={1.7} aria-hidden />
    </a>;
}
