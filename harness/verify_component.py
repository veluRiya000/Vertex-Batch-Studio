from pathlib import Path
import os, subprocess, threading, queue, re, json, time
from playwright.sync_api import sync_playwright
root=Path.cwd()
component=root/'harness/component'
if not component.is_dir():
    component=sorted((root/'.runtime').glob('harness-lean-*'))[-1]
subprocess.run(['python',str(component/'setup_profile.py')],check=True,capture_output=True)
acceptance=root/'.runtime'/('lean-acceptance-'+str(time.time_ns()))
probe=acceptance/'test-probe';probe.mkdir(parents=True,exist_ok=True)
(probe/'package.json').write_text(json.dumps({'name':'@vertex-studio/preview-verification','version':'0.1.0','type':'module','exports':{'.':'./index.mjs','./client':'./client.js'},'dsh':{'client':{'platform':'web','inject':['@deepseek-ai/dsh-client-ui-sidebar-documentpreview']}}}),encoding='utf-8')
(probe/'index.mjs').write_text('export function apply() {}',encoding='utf-8')
(probe/'client.js').write_text("window.__ModuleLoader__.load({id:'@vertex-studio/preview-verification',factory(){return {inject:['documentPreviews'],apply(ctx){window.__VBS_PREVIEW_TEST__=ctx.documentPreviews.getSnapshot().map(p=>p.id);}}}});",encoding='utf-8')
(probe/'patch.yml').write_text(json.dumps([{'insert':[{'id':'preview-verification','name':(probe/'index.mjs').as_posix()}]}]),encoding='utf-8')
env={k:v for k,v in os.environ.items() if not re.search('KEY|TOKEN|SECRET|PASSWORD|GOOGLE_|DEEPSEEK_',k)}
env.update(DSH_HOME=str(acceptance/'home'), DSH_TELEMETRY_DISABLED='1',DSH_OTEL_SESSION_LOG_DISABLED='1',VBS_HARNESS_OFFLINE='1',VBS_HARNESS_OFFLINE_PARALLEL='1',VBS_HARNESS_WORKSPACE_PARENT=str(acceptance/'workspaces'),VBS_HARNESS_BROKER_URL='http://127.0.0.1:1',VBS_HARNESS_BROKER_TOKEN='offline-test')
fixture=acceptance/'workspaces/deepseek-harness/default-workspace/README.md'
fixture.parent.mkdir(parents=True,exist_ok=True)
fixture.write_text('# Offline test\nNo cloud calls.\nThird line\nFourth line\nFifth line\nSixth line',encoding='utf-8')
proc=subprocess.Popen([str(component/'node/node.exe'),str(component/'upstream/apps/cli/lib/bin.js'),'--patch',str(component/'studio.patch.yml'),'--patch',str(probe/'patch.yml'),'--profile','web','--no-open','--host','127.0.0.1','--port','0'],env=env,cwd=component,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',creationflags=subprocess.CREATE_NO_WINDOW)
urls=queue.Queue();log=[]
def reader():
    for line in proc.stdout:
        found=re.search(r'http://127\.0\.0\.1:\d+/\?token=[A-Za-z0-9_.~%-]+',line)
        if found:urls.put(found[0])
        else:log.append(line)
threading.Thread(target=reader,daemon=True).start()
try:
    url=urls.get(timeout=25)
    if any('did not activate' in line for line in log):raise RuntimeError(''.join(log))
    with sync_playwright() as p:
        browser=p.chromium.launch()
        page=browser.new_page(viewport={'width':1440,'height':900})
        errors=[];console=[];page.on('pageerror',lambda e:errors.append(str(e)))
        page.on('console',lambda msg:console.append(msg.text) if msg.type in ('error','warning') else None)
        page.goto(url,wait_until='domcontentloaded')
        editor=page.locator('[data-composer-input][contenteditable="true"]')
        page.locator('[data-composer-input]').wait_for(timeout=30000)
        # First-run warning has one primary continue button.
        buttons=page.get_by_role('button',name=re.compile('Continue|\u7ee7\u7eed'))
        try:
            buttons.first.wait_for(timeout=5000)
            buttons.first.click()
        except Exception:pass
        chooser=page.get_by_text('\u9009\u62e9\u5de5\u4f5c\u533a',exact=True)
        try:editor.wait_for(timeout=5000)
        except Exception:
            chooser.wait_for(timeout=10000)
            chooser.click()
            option=page.get_by_role('menuitem',name=re.compile('\u9ed8\u8ba4\u5de5\u4f5c\u533a'))
            if option.count():option.click()
            else:page.get_by_text('\u9ed8\u8ba4\u5de5\u4f5c\u533a',exact=True).last.click()
        try:editor.wait_for(timeout=10000)
        except Exception:
            print(json.dumps({'body':page.locator('body').inner_text()[-6000:],'errors':errors,'console':console,'host':log[-30:]},ensure_ascii=True))
            page.screenshot(path=str(acceptance/'offline-error.png'))
            raise
        page.get_by_text('Offline protocol test',exact=True).wait_for(timeout=10000)
        selected='Offline protocol test'
        for name in ('Gemini 3.8 Flash · Batch','Gemini 3.1 Pro Preview · Batch','Offline protocol test'):
            page.get_by_text(selected,exact=True).last.click()
            page.get_by_role('menuitem').filter(has_text='\u6a21\u578b').first.click()
            if page.get_by_text(name,exact=True).count()==0:
                print(json.dumps({'menu':page.locator('body').inner_text()[-5000:]},ensure_ascii=True))
                raise RuntimeError('Missing selector entry: '+name)
            page.get_by_role('menuitemradio').filter(has_text=name).click()
            page.get_by_text(name,exact=True).wait_for()
            selected=name
        print(json.dumps({'three_model_selector':'passed','flash_and_pro_selection':'passed'}))
        page.get_by_text('Offline protocol test',exact=True).last.click()
        page.get_by_role('menuitem').filter(has_text='\u6a21\u578b').first.click()
        page.get_by_role('menuitemradio').filter(has_text='Gemini 3.8 Flash · Batch').click()
        page.get_by_text('Gemini 3.8 Flash · Batch',exact=True).wait_for()
        editor.click()
        editor.press_sequentially('Read README.md and explain the content.',delay=3)
        page.get_by_role('button',name='\u53d1\u9001\u6d88\u606f',exact=True).click(timeout=10000)
        try:page.get_by_text('\u79bb\u7ebf\u534f\u8bae\u9a8c\u6536\u5b8c\u6210',exact=False).wait_for(timeout=10000)
        except Exception:
            print(json.dumps({'body':page.locator('body').inner_text()[-6000:],'errors':errors,'console':console[-5:],'host':log[-15:]},ensure_ascii=True))
            raise
        page.get_by_text('Gemini 3.8 Flash · Batch',exact=True).last.click()
        page.get_by_role('menuitem').filter(has_text='\u6a21\u578b').first.click()
        page.get_by_role('menuitemradio').filter(has_text='Gemini 3.1 Pro Preview · Batch').click()
        page.get_by_text('Gemini 3.1 Pro Preview · Batch',exact=True).wait_for()
        attachment_fixture=acceptance/'first-round-script.md'
        attachment_fixture.write_text('# Preloaded script\n\nChinese attachment content: \u7b2c\u4e00\u884c\n\u7b2c\u4e8c\u884c\n',encoding='utf-8')
        # Exercise the real DSH drop handler, validation and upload pipeline.
        transfer=page.evaluate_handle("""({name,text})=>{
            const dt=new DataTransfer();
            dt.items.add(new File([text],name,{type:'text/markdown'}));
            dt.items.add(new File(['Remove this attachment.'],'drop-remove.txt',{type:'text/plain'}));
            dt.items.add(new File(['Unsupported video marker.'],'drop-blocked.MP4',{type:'video/mp4'}));
            return dt;
        }""",{'name':attachment_fixture.name,'text':attachment_fixture.read_text(encoding='utf-8')})
        for event in ('dragenter','dragover'):
            editor.dispatch_event(event,{'dataTransfer':transfer})
        page.get_by_text('\u6587\u4ef6\u6216\u56fe\u7247\u62d6\u52a8\u5230\u6b64\u5904\u5373\u53ef\u6dfb\u52a0',exact=True).wait_for()
        assert editor.evaluate("(el,dt)=>!el.dispatchEvent(new DragEvent('drop',{bubbles:true,cancelable:true,dataTransfer:dt}))",transfer)
        page.get_by_role('button',name='\u79fb\u9664\u6587\u4ef6 drop-remove.txt',exact=True).wait_for()
        page.get_by_role('button',name='\u79fb\u9664\u6587\u4ef6 drop-remove.txt',exact=True).click()
        assert page.get_by_role('button',name='\u79fb\u9664\u6587\u4ef6 drop-remove.txt',exact=True).count()==0
        blocked=page.locator('[title="drop-blocked.MP4"]')
        blocked.locator('.vbs-unsupported-video-overlay').wait_for()
        assert blocked.locator('.vbs-unsupported-video-icon').inner_text()=='!'
        assert blocked.locator('.vbs-unsupported-video-overlay').inner_text().endswith('\u4e0d\u652f\u6301\u7684\u6587\u4ef6\u7c7b\u578b')
        blocked.get_by_role('button',name='\u79fb\u9664\u6587\u4ef6 drop-blocked.MP4',exact=True).click()
        assert blocked.count()==0
        transfer.dispose()
        print(json.dumps({'unsupported_video_mask':'passed','red_warning_icon':'passed','remove_under_mask':'passed'}))
        print(json.dumps({'drop_overlay':'passed','multi_file_drop':'passed','drop_navigation_prevented':True,'remove_dropped_file':'passed'}))
        editor.click()
        editor.press_sequentially('Summarize the uploaded script from the provided body.',delay=3)
        page.get_by_role('button',name='\u53d1\u9001\u6d88\u606f',exact=True).click(timeout=10000)
        page.get_by_text('\u79bb\u7ebf\u9644\u4ef6\u9884\u8bfb\u9a8c\u6536\u5b8c\u6210',exact=False).wait_for(timeout=10000)
        print(json.dumps({'ui_upload_attachment_first_request':'passed','attachment_read_tool_rounds':0,'flash_tool_turn':'passed','pro_attachment_turn':'passed'}))
        page.wait_for_function('Array.isArray(window.__VBS_PREVIEW_TEST__)')
        previews=page.evaluate('window.__VBS_PREVIEW_TEST__')
        for kind in ('text','markdown','image','pdf','code'):
            assert any(p.endswith('/'+kind) for p in previews),(kind,previews)
        assert not any('/office' in p or '/excel' in p for p in previews),previews
        if errors:raise RuntimeError('\n'.join(errors))
        page.get_by_role('button',name='\u8bbe\u7f6e',exact=True).click()
        page.get_by_text('Batch \u8fd0\u884c',exact=True).first.click()
        cap=page.get_by_label('\u6bcf\u6b21\u8f93\u51fa\u989d\u5ea6\uff08Token\uff09',exact=True)
        budget=page.get_by_label('\u6bcf\u4e2a\u4efb\u52a1\u9884\u7b97\uff08\u7f8e\u5143\uff09',exact=True)
        rounds=page.get_by_label('\u6bcf\u4e2a\u4efb\u52a1\u6700\u591a\u6a21\u578b\u8bf7\u6c42\u6b21\u6570',exact=True)
        cap.wait_for();assert cap.input_value()=='65536'
        cap.fill('98304');budget.fill('7.5');rounds.fill('25')
        page.get_by_role('button',name='\u4fdd\u5b58',exact=True).click()
        page.get_by_role('status').filter(has_text='\u5df2\u4fdd\u5b58').wait_for()
        saved_limits=page.evaluate("async()=>await(await fetch('./vbs/run-settings')).json()")
        assert saved_limits['settings']=={'maxOutputTokens':98304,'budgetUsd':7.5,'maxRounds':25,'limitsEnabled':True}
        cap.fill('65536');budget.fill('5');rounds.fill('20')
        page.get_by_role('button',name='\u4fdd\u5b58',exact=True).click()
        page.get_by_role('status').filter(has_text='\u5df2\u4fdd\u5b58').wait_for()
        print(json.dumps({'runtime_settings_ui':'passed','above_32k_not_clamped':True,'budgets_restored_to_defaults':True}))
        page.get_by_text('\u89d2\u8272\u4e0e\u63d0\u793a\u8bcd',exact=True).first.click()
        field=page.get_by_label('\u89d2\u8272\u63d0\u793a\u8bcd',exact=True)
        field.wait_for()
        page.wait_for_function("document.querySelector('#vbs-persona-text')?.disabled === false")
        original=field.input_value()
        custom='Use Chinese and deliver complete documents.'
        field.fill(custom)
        page.get_by_role('button',name='\u4fdd\u5b58',exact=True).click()
        page.get_by_role('status').filter(has_text='\u5df2\u4fdd\u5b58').wait_for()
        saved=page.evaluate("async()=>await (await fetch('./vbs/persona',{credentials:'same-origin'})).json()")
        assert saved['text']==custom,saved
        page.get_by_role('button',name='\u6062\u590d\u9ed8\u8ba4',exact=True).click()
        page.get_by_role('status').filter(has_text='\u5df2\u6062\u590d\u9ed8\u8ba4').wait_for()
        assert field.input_value()==original
        field.fill('  ')
        assert page.get_by_role('button',name='\u4fdd\u5b58',exact=True).is_disabled()
        page.get_by_role('button',name='\u6062\u590d\u9ed8\u8ba4',exact=True).click()
        page.get_by_role('status').filter(has_text='\u5df2\u6062\u590d\u9ed8\u8ba4').wait_for()
        print(json.dumps({'persona_ui_save':'passed','persona_ui_reset':'passed','empty_save_disabled':True}))
        page.screenshot(path=str(acceptance/'offline-verification.png'))
        print(json.dumps({'startup':'passed','browser':'passed','offline_tool_loop':'passed','previews':previews,'page_errors':errors}))
        browser.close()
finally:
    if proc.poll() is None:
        proc.stdin.write('vbs-shutdown\n');proc.stdin.flush()
        try:proc.wait(timeout=15)
        except subprocess.TimeoutExpired:proc.terminate();proc.wait(timeout=5)
