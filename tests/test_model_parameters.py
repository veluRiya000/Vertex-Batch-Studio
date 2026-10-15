"""Parameter filtering must preserve source tasks and other models' behavior."""
import copy
from dataclasses import replace
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from backend.api import create_app
from backend.config import Settings
from backend.files import read_json, sha256_file, write_json
from backend.jsonl import fingerprint, prepare
from backend.model_catalog import ModelCatalogue, parse_card
from backend.model_parameters import filter_generation_parameters, unsupported_generation_parameters
from backend.models import TaskInput
from backend.service import Studio
from tests.fakes import FakeCloud
from tests.test_model_catalog import card, URL

MODEL = 'gemini-nano-banana-2.1'
BLOCKED = {'temperature', 'topP', 'topK', 'seed', 'logprobs', 'responseLogprobs'}


class ParameterPolicyTests(unittest.TestCase):
    def test_exact_bare_and_publisher_model_ids(self):
        for model in (MODEL, 'publishers/google/models/' + MODEL,
                      'projects/demo/locations/global/publishers/google/models/' + MODEL,
                      'publishers/google/models/' + MODEL + '@001'):
            self.assertEqual(unsupported_generation_parameters(model), BLOCKED)
        self.assertFalse(unsupported_generation_parameters('gemini-3.1-flash-image'))
        self.assertFalse(unsupported_generation_parameters(MODEL+'-unrelated'))

    def test_filter_handles_aliases_zero_false_and_keeps_other_controls(self):
        config={'temperature':0, 'top_p':.8, 'topK':0, 'seed':0, 'logprobs':0,
                'response_logprobs':False, 'maxOutputTokens':1024, 'thinkingConfig':{'thinkingLevel':'HIGH'}}
        original=copy.deepcopy(config)
        filtered=filter_generation_parameters(MODEL,config)
        self.assertEqual(filtered,{'maxOutputTokens':1024,'thinkingConfig':{'thinkingLevel':'HIGH'}})
        self.assertEqual(config,original)
        self.assertEqual(filter_generation_parameters('gemini-3.1-flash-image',config),config)

    def test_model_card_parameter_defaults_drive_dynamic_restrictions(self):
        html=card('gemini-future-image').replace('</table>',
            '<tr><td>Parameter defaults <span aria-hidden="true">tune</span></td>'
            '<td><ul><li>Temperature, topP, topK, seed, logprobs: Not supported</li>'
            '<li>candidateCount: 1</li></ul></td></tr></table>')
        model=parse_card(html,URL,'global')
        self.assertEqual(set(model['unsupported_parameters']),BLOCKED)
        self.assertEqual(filter_generation_parameters(model['id'],{'temperature':1,'seed':2,'maxOutputTokens':50},model),{'maxOutputTokens':50})


class ParameterIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory(); self.root=Path(self.temp.name)
        self.cloud=FakeCloud()
        self.studio=Studio(Settings(self.root,self.root/'data',project='demo',bucket='bucket',model=MODEL),self.cloud)

    def tearDown(self):
        self.studio.close(); self.temp.cleanup()

    def batch(self,temperature=1.5):
        batch=self.studio.repo.create('parameters')
        self.studio.append_task(batch['id'],TaskInput(name='test',prompt='draw',temperature=temperature,
            generation_config={'temperature':.2,'top_p':.8,'top_k':20,'seed':3,'logprobs':2,
                               'responseLogprobs':True,'max_output_tokens':2048,
                               'thinking_config':{'thinkingLevel':'HIGH'}}))
        return batch['id']

    def config(self,bid):
        return self.studio.manifest(bid)['requests'][0]['request']['generationConfig']

    def test_offline_fallback_filters_final_jsonl_and_preserves_task_bytes(self):
        bid=self.batch(); path=self.studio.repo.directory(bid)/'inputs/tasks.json'
        before=path.read_bytes()
        manifest=self.studio.prepare(bid)
        config=self.config(bid)
        self.assertFalse(BLOCKED.intersection(config))
        self.assertEqual(config['maxOutputTokens'],2048)
        self.assertEqual(config['thinkingConfig'],{'thinkingLevel':'HIGH'})
        self.assertEqual(path.read_bytes(),before)
        row=json.loads((path.parent/'prompts.jsonl').read_text())
        self.assertEqual(row['request'],manifest['requests'][0]['request'])
        self.assertEqual(manifest['requests'][0]['fingerprint'],fingerprint(row['request']))
        self.studio.submit(bid)
        self.assertEqual(self.cloud.creates,1)

    def test_default_temperature_still_filters_imported_temperature_and_sampling(self):
        bid=self.batch(None)
        self.studio.prepare(bid)
        self.assertFalse(BLOCKED.intersection(self.config(bid)))

    def test_other_models_and_switch_back_retain_original_task_parameters(self):
        bid=self.batch()
        self.studio.prepare(bid)
        settings=replace(self.studio.settings,model='gemini-3.1-flash-image')
        self.studio.settings=self.studio.repo.settings=settings
        self.studio.prepare(bid)
        config=self.config(bid)
        self.assertTrue(BLOCKED.issubset(config))
        self.assertEqual(config['temperature'],1.5)
        self.assertEqual(config['topP'],.8)

    def old_snapshot(self,bid):
        # Simulate a pre-fix prepared snapshot with a correctly persisted digest.
        with patch('backend.jsonl.filter_generation_parameters',side_effect=lambda model,config,cap:config):
            self.studio.prepare(bid)
        return self.studio.manifest(bid)

    def test_old_prepared_snapshot_rejected_before_upload_then_reprepare_fixes(self):
        bid=self.batch(); self.old_snapshot(bid)
        directory=self.studio.repo.directory(bid)
        before=(directory/'inputs/prompts.jsonl').read_bytes()
        with self.assertRaisesRegex(ValueError,'重新准备'):
            self.studio.submit(bid)
        self.assertEqual(self.cloud.creates,0)
        self.assertEqual(self.cloud.uploads,[])
        self.assertEqual((directory/'inputs/prompts.jsonl').read_bytes(),before)
        self.assertEqual(self.studio.repo.get(bid)['phase'],'prepared')
        self.studio.prepare(bid)
        self.studio.submit(bid)
        self.assertEqual(self.cloud.creates,1)

    def test_api_exposes_offline_restrictions_and_rejects_old_snapshot(self):
        bid=self.batch(); self.old_snapshot(bid)
        with TestClient(create_app(self.studio,'test-token',background=False)) as client:
            client.headers['X-VBS-Token']='test-token'
            self.assertEqual(set(client.get('/config').json()['unsupported_generation_parameters']),BLOCKED)
            response=client.post('/batches/'+bid+'/submit')
            self.assertEqual(response.status_code,400)
            self.assertEqual(self.cloud.uploads,[])

    def test_existing_submitted_snapshot_and_job_unchanged(self):
        bid=self.batch()
        self.old_snapshot(bid)
        with patch.object(self.studio,'validate_manifest_parameters'):
            self.studio.submit(bid)
        directory=self.studio.repo.directory(bid)
        before=(directory/'inputs/manifest.json').read_bytes()
        job=self.studio.repo.get(bid)['job_name']
        self.studio.validate_submission(bid)
        self.assertEqual(self.studio.submit(bid)['job_name'],job)
        self.studio.poll(bid)
        self.assertEqual((directory/'inputs/manifest.json').read_bytes(),before)
        self.assertEqual(self.cloud.creates,1)

    def test_unknown_submission_reconciles_without_revalidating_old_snapshot(self):
        bid=self.batch(); self.old_snapshot(bid)
        self.cloud.create_timeout=True
        with patch.object(self.studio,'validate_manifest_parameters'):
            with self.assertRaises(TimeoutError): self.studio.submit(bid)
        self.studio.validate_submission(bid)
        self.studio.submit(bid)
        self.assertEqual(self.studio.repo.get(bid)['phase'],'monitoring')
        self.assertEqual(self.cloud.creates,1)

    def test_old_cache_without_parameter_metadata_is_upgraded_in_memory(self):
        catalog=self.studio.model_catalog
        model=parse_card(card(MODEL),URL,'global')
        model.pop('unsupported_parameters')
        from datetime import datetime,timezone
        write_json(catalog.path,{'schema_version':1,'scope':catalog.scope,
            'fetched_at':datetime.now(timezone.utc).isoformat(),'models':[model]})
        restored=ModelCatalogue(self.studio.settings)
        state=restored.snapshot()
        self.assertEqual(state['source'],'cache')
        self.assertEqual(set(state['models'][0]['unsupported_parameters']),BLOCKED)
