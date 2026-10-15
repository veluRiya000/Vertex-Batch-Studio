import {ExternalLink} from 'lucide-react';
export type CloudPage = 'project' | 'storage' | 'credentials';
const routes:Record<CloudPage,string>={project:'/welcome',storage:'/storage/browser',credentials:'/iam-admin/serviceaccounts'};
export function cloudConsoleUrl(page:CloudPage,project:string) {
  const url=new URL(routes[page],'https://console.cloud.google.com');
  if(project.trim())url.searchParams.set('project',project.trim());
  return url.href;
}
export function CloudConsoleLink({page,project,label,onError}:{page:CloudPage;project:string;label:string;onError:(message:string)=>void}) {
  return <a className="cloud-console-link" href={cloudConsoleUrl(page,project)} target="_blank" rel="noopener noreferrer" title={label} aria-label={label}
    onClick={event=>{
      if(!window.studio?.openCloudPage)return;
      event.preventDefault();
      void window.studio.openCloudPage(page,project.trim()).catch(error=>onError((error as Error).message));
    }}><ExternalLink size={13} strokeWidth={1.7}/></a>;
}
