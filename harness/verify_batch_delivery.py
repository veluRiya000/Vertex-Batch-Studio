# Offline Batch delivery regression; run from repository root.
from pathlib import Path
import os,subprocess,threading,queue,re,json,time
from playwright.sync_api import sync_playwright

root=Path.cwd();component=root/'harness/component'
subprocess.run(['python',str(component/'setup_profile.py')],check=True,capture_output=True)
acceptance=root/'.runtime'/('agent-basic-'+str(time.time_ns()))
workspace=acceptance/'workspaces/deepseek-harness/default-workspace'
workspace.mkdir(parents=True,exist_ok=True)
env={k:v for k,v in os.environ.items() if not re.search('KEY|TOKEN|SECRET|PASSWORD|GOOGLE_|DEEPSEEK_',k)}
env.update(DSH_HOME=str(acceptance/'home'),DSH_TELEMETRY_DISABLED='1',DSH_OTEL_SESSION_LOG_DISABLED='1',
    VBS_HARNESS_OFFLINE='1',VBS_HARNESS_OFFLINE_ACTIONS='1',VBS_HARNESS_WORKSPACE_PARENT=str(acceptance/'workspaces'),
    VBS_HARNESS_BROKER_URL='http://127.0.0.1:1',VBS_HARNESS_BROKER_TOKEN='offline-test')
proc=subprocess.Popen([str(component/'node/node.exe'),str(component/'upstream/apps/cli/lib/bin.js'),'--patch',str(component/'studio.patch.yml'),'--profile','web','--no-open','--host','127.0.0.1','--port','0'],env=env,cwd=component,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',creationflags=subprocess.CREATE_NO_WINDOW)
urls=queue.Queue();log=[]
def reader():
    for line in proc.stdout:
        found=re.search(r'http://127\.0\.0\.1:\d+/\?token=[A-Za-z0-9_.~%-]+',line)
        if found:urls.put(found[0])
        elif 'token=' not in line:log.append(line)
threading.Thread(target=reader,daemon=True).start()
try:
    url=urls.get(timeout=25)
    with sync_playwright() as p:
        browser=p.chromium.launch();page=browser.new_page(viewport={'width':1440,'height':900})
        page.goto(url,wait_until='domcontentloaded')
        editor=page.locator('[data-composer-input][contenteditable=true]')
        go=page.get_by_role('button',name=re.compile('Continue|继续'))
        try:
            go.first.wait_for(timeout=5000)
            go.first.click()
        except Exception:
            pass
        for _ in range(50):
            if editor.count():break
            go=page.get_by_role('button',name=re.compile('Continue|继续'))
            if go.count():go.first.click()
            chooser=page.get_by_text('选择工作区',exact=True)
            if chooser.count():
                chooser.click()
                page.get_by_role('menuitem',name=re.compile('默认工作区')).first.click()
            page.wait_for_timeout(200)
        editor.wait_for(timeout=10000)

        def steps():
            return [json.loads(line.split('VBS_OFFLINE_MODEL_STEP ',1)[1]) for line in log if 'VBS_OFFLINE_MODEL_STEP ' in line]
        def send(text):
            editor.click()
            editor.press('Control+A')
            editor.press_sequentially(text,delay=1)
            page.get_by_role('button',name='发送消息',exact=True).click()
        send('DELIVERY_TEST: create the complete file and finish locally in the same response.')
        try:
            page.get_by_text('BATCH_DELIVERY_LOCAL_DONE: created batch-delivery.md. No extra model round was used.',exact=True).wait_for(timeout=20000)
        except Exception:
            print(json.dumps({'body':page.locator('body').inner_text()[-6500:],'host':log[-12:]},ensure_ascii=True));raise
        page.wait_for_timeout(500)
        assert (workspace/'batch-delivery.md').read_text(encoding='utf-8')=='# Batch delivery\nComplete offline content\n'
        assert len(steps())==1,steps()
        assert '本地交付已确认' in page.locator('body').inner_text()
        print('SUCCESS: complete file + local final reply, exactly one model response')
        send('DELIVERY_TEST_FAIL: simulate a rejected write; never mark success.')
        page.get_by_text('DELIVERY_FAILURE_REPORTED_WITHOUT_FALSE_SUCCESS',exact=True).wait_for(timeout=15000)
        page.wait_for_timeout(300)
        assert len(steps())==3,steps()
        assert not (workspace/'never-created.md').exists()
        assert page.get_by_text('BATCH_DELIVERY_LOCAL_DONE: created never-created.md. No extra model round was used.',exact=True).count()==0
        print('FAILURE: write rejected, no false delivery, next model round allowed')
        send('/permission read-only')
        page.wait_for_timeout(400)
        send('DELIVERY_TEST_APPROVAL: request approval before writing the full delivery.')
        approve=page.get_by_role('button',name=re.compile('允许一次|批准一次|Allow once|Approve once|允许|批准'))
        try:
            approve.first.wait_for(timeout=15000)
            assert not (workspace/'batch-approved.md').exists()
            assert page.get_by_text('BATCH_DELIVERY_LOCAL_DONE: created batch-approved.md. No extra model round was used.',exact=True).count()==0
            approve.first.click()
            page.get_by_text('BATCH_DELIVERY_LOCAL_DONE: created batch-approved.md. No extra model round was used.',exact=True).wait_for(timeout=15000)
        except Exception:
            print(json.dumps({'body':page.locator('body').inner_text()[-6500:],'host':log[-12:]},ensure_ascii=True));raise
        page.wait_for_timeout(300)
        assert (workspace/'batch-approved.md').exists()
        assert len(steps())==4,steps()
        print('APPROVAL: no premature success; approved write + local final reply, exactly one model response')
        # Continuing the conversation must keep every function-response pair valid.
        send('DELIVERY_TEST_FAIL: check history replay after local finish.')
        page.get_by_text('DELIVERY_FAILURE_REPORTED_WITHOUT_FALSE_SUCCESS',exact=True).nth(1).wait_for(timeout=15000)
        assert len(steps())==6,steps()
        print('HISTORY: continued conversation replays local final reply and complete tool pairs correctly')
        browser.close()
finally:
    if proc.poll() is None:
        proc.stdin.write('vbs-shutdown\n');proc.stdin.flush()
        try:proc.wait(timeout=15)
        except subprocess.TimeoutExpired:proc.terminate();proc.wait(timeout=5)

# In-memory rendering alone cannot detect an out-of-step assistant/message.
# Close the host above, then reopen every durable log with DSH validation.
subprocess.run([str(component/'node/node.exe'),str(root/'harness/verify_stored_sessions.mjs'),str(acceptance/'home/sessions')],cwd=root,check=True)
print('PERSISTENCE: strict reopen succeeds after process exit')
