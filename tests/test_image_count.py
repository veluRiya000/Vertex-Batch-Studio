"""One GUI task expands to N cloud rows and aggregates N independent results."""
from pathlib import Path
from tempfile import TemporaryDirectory
import copy,json,unittest
from fastapi.testclient import TestClient
from backend.api import create_app
from backend.config import Settings
from backend.files import read_json,write_json,sha256_file
from backend.jsonl import fingerprint,import_jsonl
from backend.models import TaskInput
from backend.service import Studio
from .fakes import FakeCloud,response,image_bytes


class ImageCountTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();root=Path(self.temp.name)
        self.cloud=FakeCloud()
        self.studio=Studio(Settings(root,root/'data',project='demo',bucket='bucket'),self.cloud)
        self.repo=self.studio.repo;self.bid=self.repo.create('数量测试')['id']

    def tearDown(self):
        self.studio.close();self.temp.cleanup()

    def compiled(self,count=1):
        manifest=self.studio.prepare(self.bid)
        lines=(self.repo.directory(self.bid)/'inputs/prompts.jsonl').read_text(encoding='utf-8').splitlines()
        self.assertEqual(len(lines),count)
        self.assertEqual(len({item['request_id'] for item in manifest['requests']}),count)
        for line,item in zip(lines,manifest['requests']):
            request=json.loads(line)['request']
            self.assertEqual(item['fingerprint'],fingerprint(request))
        return [json.loads(line)['request'] for line in lines]

    def test_legacy_tasks_default_to_one_without_rewriting(self):
        self.repo.replace_tasks(self.bid,[TaskInput(name='旧任务',prompt='原文\n  ')])
        path=self.repo.directory(self.bid)/'inputs/tasks.json';old=read_json(path);old[0].pop('image_count');write_json(path,old)
        before=path.read_bytes()
        self.assertEqual(self.repo.tasks(self.bid)[0].image_count,1)
        self.assertEqual(self.compiled()[0]['contents'][0]['parts'][0]['text'],'原文\n  ')
        self.assertEqual(path.read_bytes(),before)

    def test_all_counts_repeat_exact_original_request_without_prompt_suffix(self):
        original='街道全景\n保留这一行和末尾空格  '
        for count in range(1,5):
            with self.subTest(count=count):
                task=self.repo.replace_tasks(self.bid,[TaskInput(name='街道',prompt=original,image_count=count)])[0]
                requests=self.compiled(count)
                self.assertTrue(all(request==requests[0] for request in requests))
                self.assertEqual(requests[0]['contents'][0]['parts'][0]['text'],original)
                self.assertEqual(self.repo.tasks(self.bid)[0].prompt,original)
                self.assertEqual(len(self.repo.tasks(self.bid)),1)
                self.assertEqual({x['task_id'] for x in self.studio.manifest(self.bid)['requests']},{task.id})

    def test_reprepare_and_count_changes_are_idempotent(self):
        task=self.repo.replace_tasks(self.bid,[TaskInput(name='图',prompt='draw',image_count=4)])[0]
        self.assertEqual(self.compiled(4),self.compiled(4))
        for count in (2,1,4):
            self.studio.update_task(self.bid,task.id,TaskInput(name='图',prompt='draw',image_count=count))
            self.assertEqual(self.compiled(count)[0]['contents'][0]['parts'][0]['text'],'draw')
            self.assertEqual(self.repo.tasks(self.bid)[0].id,task.id)

    def test_gcs_references_and_prompt_are_reused_in_one_job(self):
        source=self.repo.settings.root/'reference.png';source.write_bytes(image_bytes())
        ref=self.studio.assets.import_file(str(source),category='styles')
        self.repo.replace_tasks(self.bid,[TaskInput(name='图',prompt='same',refs=[ref['path']],image_count=4)])
        batch=self.studio.submit(self.bid);manifest=self.studio.manifest(self.bid)
        self.assertEqual(len(manifest['assets']),1)
        self.assertEqual(len(manifest['requests']),4)
        uris=[r['request']['contents'][0]['parts'][1]['fileData']['fileUri'] for r in manifest['requests']]
        self.assertEqual(len(set(uris)),1)
        self.assertEqual(len(self.cloud.uploads),2) # one image, one JSONL
        self.assertEqual(self.cloud.creates,1)
        self.studio.submit(self.bid)
        self.assertEqual(self.cloud.creates,1)
        self.assertEqual(self.repo.get(self.bid)['job_name'],batch['job_name'])

    def test_partial_results_remain_one_pending_task_and_restart_keeps_assignments(self):
        task=self.repo.replace_tasks(self.bid,[TaskInput(name='图',prompt='same',image_count=4)])[0]
        batch=self.studio.submit(self.bid);request=self.studio.manifest(self.bid)['requests'][0]['request']
        first=response(request,(1,2,3))
        self.cloud.finish(batch['job_name'],{'z.jsonl':[first]},state='JOB_STATE_RUNNING')
        self.studio.poll(self.bid);report=self.studio.results(self.bid)
        self.assertEqual(len(report['tasks']),1)
        self.assertEqual(report['tasks'][0]['state'],'pending')
        self.assertEqual(report['tasks'][0]['completed_requests'],1)
        self.assertEqual(report['tasks'][0]['total_requests'],4)
        old_assignments=dict(self.repo.get(self.bid)['row_assignments'])
        old_image=Path(report['tasks'][0]['images'][0]['path']);mtime=old_image.stat().st_mtime_ns
        self.studio.close();self.studio=Studio(self.repo.settings,self.cloud);self.repo=self.studio.repo
        others=[response(request,(i,3,9)) for i in range(4,7)]
        self.cloud.finish(batch['job_name'],{'a.jsonl':others,'z.jsonl':[first]})
        self.assertEqual(self.studio.poll(self.bid)['phase'],'completed')
        result=self.studio.results(self.bid)['tasks'][0]
        self.assertEqual(result['task_id'],task.id)
        self.assertEqual(len(result['images']),4)
        self.assertEqual(len({i['path'] for i in result['images']}),4)
        self.assertEqual(result['completed_requests'],4)
        self.assertEqual(old_image.stat().st_mtime_ns,mtime)
        for key,value in old_assignments.items():self.assertEqual(self.repo.get(self.bid)['row_assignments'][key],value)
        self.assertEqual(self.cloud.creates,1)

    def test_byte_identical_rows_are_not_deduplicated_or_overwritten(self):
        self.repo.replace_tasks(self.bid,[TaskInput(name='图',prompt='same',image_count=4)])
        batch=self.studio.submit(self.bid);request=self.studio.manifest(self.bid)['requests'][0]['request']
        row=response(request)
        self.cloud.finish(batch['job_name'],{'same.jsonl':[row,row,row,row]})
        self.assertEqual(self.studio.poll(self.bid)['phase'],'completed')
        report=self.studio.results(self.bid)
        self.assertEqual(len(report['tasks']),1);self.assertEqual(report['counts']['images'],4)
        images=report['tasks'][0]['images'];self.assertEqual(len({i['path'] for i in images}),4)
        self.assertEqual(len({i['sha256'] for i in images}),1)
        self.studio.extract_local(self.bid)
        self.assertEqual(self.studio.results(self.bid)['counts']['images'],4)

    def test_identical_prompts_with_different_counts_keep_group_sizes(self):
        tasks=self.repo.replace_tasks(self.bid,[TaskInput(name='一张',prompt='same'),TaskInput(name='四张',prompt='same',image_count=4)])
        batch=self.studio.submit(self.bid);records=self.studio.manifest(self.bid)['requests']
        self.assertEqual(len(records),5)
        self.cloud.finish(batch['job_name'],{'part.jsonl':[response(records[0]['request'],(i,4,5)) for i in range(5)]})
        self.studio.poll(self.bid)
        results={t['task_id']:t for t in self.studio.results(self.bid)['tasks']}
        self.assertEqual(len(results[tasks[0].id]['images']),1)
        self.assertEqual(len(results[tasks[1].id]['images']),4)

    def test_failed_and_missing_rows_keep_successful_images_and_do_not_auto_generate(self):
        self.repo.replace_tasks(self.bid,[TaskInput(name='图',prompt='draw',image_count=4)])
        batch=self.studio.submit(self.bid);request=self.studio.manifest(self.bid)['requests'][0]['request']
        rows=[response(request),{'request':request,'status':'blocked'},response(request,(7,8,9))]
        self.cloud.finish(batch['job_name'],{'part.jsonl':rows})
        self.assertEqual(self.studio.poll(self.bid)['phase'],'completed_with_errors')
        task=self.studio.results(self.bid)['tasks'][0]
        self.assertEqual(len(task['images']),2)
        self.assertEqual(task['state'],'error')
        self.assertEqual(task['succeeded_requests'],2)
        self.assertEqual({v['state'] for v in task['generations']},{'succeeded','error','missing'})
        self.assertEqual(task['completed_requests'],4)
        self.assertEqual(self.cloud.creates,1)

    def test_all_returned_images_are_kept_including_multiple_from_one_row(self):
        self.repo.replace_tasks(self.bid,[TaskInput(name='图',prompt='draw',image_count=2)])
        batch=self.studio.submit(self.bid);request=self.studio.manifest(self.bid)['requests'][0]['request']
        row=response(request)
        row['response']['candidates'][0]['content']['parts'].append(response(request,(4,5,6))['response']['candidates'][0]['content']['parts'][0])
        self.cloud.finish(batch['job_name'],{'part.jsonl':[row,response(request,(7,8,9))]})
        self.studio.poll(self.bid)
        self.assertEqual(self.studio.results(self.bid)['counts']['images'],3)

    def legacy_preparation(self):
        self.repo.replace_tasks(self.bid,[TaskInput(name='图',prompt='draw',image_count=4)])
        manifest=self.studio.prepare(self.bid);item=copy.deepcopy(manifest['requests'][0])
        item.pop('request_id');item.pop('image_index')
        item['request']['contents'][0]['parts'][0]['text']='draw\n\n请生成4张独立图片，每张单独输出，不要将多张图片拼成一张。'
        item['fingerprint']=fingerprint(item['request'])
        manifest.update(schema_version=1,requests=[item])
        directory=self.repo.directory(self.bid)
        (directory/'inputs/prompts.jsonl').write_text(json.dumps({'request':item['request']})+'\n',encoding='utf-8')
        manifest['jsonl_sha256']=sha256_file(directory/'inputs/prompts.jsonl')
        write_json(directory/'inputs/manifest.json',manifest)
        return manifest

    def test_never_submitted_legacy_preparation_upgrades_when_submitted(self):
        old=self.legacy_preparation()
        self.studio.submit(self.bid);new=self.studio.manifest(self.bid)
        self.assertEqual(new['model'],old['model'])
        self.assertEqual(len(new['requests']),4)
        self.assertEqual(new['requests'][0]['request']['contents'][0]['parts'][0]['text'],'draw')
        self.assertEqual(self.cloud.creates,1)

    def test_legacy_upload_or_existing_job_is_not_rewritten(self):
        self.legacy_preparation();directory=self.repo.directory(self.bid)
        old=(directory/'inputs/prompts.jsonl').read_bytes()
        batch=self.repo.get(self.bid);batch['phase']='uploading';self.repo.save(batch)
        batch=self.studio.submit(self.bid);manifest=self.studio.manifest(self.bid)
        self.assertEqual((directory/'inputs/prompts.jsonl').read_bytes(),old)
        self.assertEqual(manifest['schema_version'],1)
        self.cloud.finish(batch['job_name'],{'part.jsonl':[response(manifest['requests'][0]['request'])]})
        self.studio.poll(self.bid)
        self.assertEqual(len(self.studio.results(self.bid)['tasks'][0]['images']),1)

    def test_clone_and_failed_retry_preserve_count(self):
        self.repo.replace_tasks(self.bid,[TaskInput(name='图',prompt='draw',image_count=3)])
        clone=self.studio.retry(self.bid,failed_only=False)
        self.assertEqual(self.repo.tasks(clone['id'])[0].image_count,3)
        batch=self.studio.submit(self.bid);request=self.studio.manifest(self.bid)['requests'][0]['request']
        self.cloud.finish(batch['job_name'],{'part.jsonl':[{'request':request,'status':'blocked'}]})
        self.studio.poll(self.bid);retry=self.studio.retry(self.bid)
        self.assertEqual(self.repo.tasks(retry['id'])[0].image_count,3)

    def test_api_keeps_one_task_and_exposes_four_preview_images(self):
        with TestClient(create_app(self.studio,'test-token',background=False)) as client:
            client.headers['X-VBS-Token']='test-token';url=f'/batches/{self.bid}/tasks'
            task=client.post(url,json={'name':'图','prompt':'original','image_count':4}).json()
            for invalid in [0,5,-1,True,1.5,1.0,'2',None]:
                self.assertEqual(client.put(url,json={'tasks':[{'name':'图','prompt':'x','image_count':invalid}]}).status_code,422)
            self.assertEqual(len(client.get(url).json()),1)
            batch=self.studio.submit(self.bid);request=self.studio.manifest(self.bid)['requests'][0]['request']
            self.cloud.finish(batch['job_name'],{'part.jsonl':[response(request) for _ in range(4)]})
            self.studio.poll(self.bid)
            report=client.get(f'/batches/{self.bid}/results').json()
            self.assertEqual(len(report['tasks']),1)
            self.assertEqual(len(report['tasks'][0]['images']),4)
            for index in range(4):self.assertEqual(client.get(f'/batches/{self.bid}/images/{task["id"]}/{index}').status_code,200)

    def test_imported_jsonl_keeps_existing_prompt_as_literal_text(self):
        text='draw\n\n请生成4张独立图片，每张单独输出，不要将多张图片拼成一张。'
        source=self.repo.settings.root/'legacy.jsonl'
        source.write_text(json.dumps({'request':{'contents':[{'role':'user','parts':[{'text':text}]}]}}),encoding='utf-8')
        imported=import_jsonl(self.repo,self.bid,str(source))
        self.assertEqual(imported[0].image_count,1)
        self.assertEqual(self.compiled()[0]['contents'][0]['parts'][0]['text'],text)
