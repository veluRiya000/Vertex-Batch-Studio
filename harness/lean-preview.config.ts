import {fileURLToPath} from 'node:url';
import original from './upstream/packages/client/ui-sidebar-documentpreview/tsdown.config.ts';
export default (options) => original(options).filter(c => c.name?.endsWith('/client')).map(c => ({
  ...c, entry: {client:fileURLToPath(new URL('./upstream/packages/client/ui-sidebar-documentpreview/lib/types/client/index.js',import.meta.url))}, outDir: fileURLToPath(new URL('../.runtime/lean-preview',import.meta.url)), sourcemap: false, clean: false,
  plugins: [{name:'vbs-no-office-preview', transform(code,id) {
    if (!id.replaceAll('\\','/').endsWith('/lib/types/client/index.js')) return null;
    return {code:code.replace(/^import .*register(?:Office|Excel).*$/gm,'')
      .replace(/^.*registerOffice\(ctx, config.office\).*$/gm,'')
      .replace(/^.*registerExcel\(ctx, config.excel\).*$/gm,''), map:null};
  }}, c.plugins]
}));
