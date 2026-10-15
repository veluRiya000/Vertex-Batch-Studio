"""Catalogue contract, lifecycle, fallback, selection and frozen-job regressions."""
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from backend.api import create_app
from backend.config import Settings
from backend.files import read_json, write_json
from backend.model_catalog import (BATCH_URL, CatalogueError, ModelCatalogue,
    OfficialCatalogue, batch_links, parse_card, official_url, select_model)
from backend.models import TaskInput
from backend.service import Studio
from tests.fakes import FakeCloud


def card(model='gemini-future-image', *, image='Input and output', batch='Supported',
         generate='Supported', region='global', lifecycle='', size=True):
    api = '' if generate is None else f'<li><a>GenerateContent API</a>{generate}</li>'
    return f'''<html><h1>Future Image</h1><table>
      <tr><th>Model ID</th><td><code>{model}</code></td></tr>
      <tr><th>Modalities</th><td>
        <section class="geap-modality-support">Text Input and output</section>
        <section class="geap-modality-support">Image {image}</section></td></tr>
      <tr><th>Consumption options</th><td><ul><li><a>Batch inference</a>{batch}</li></ul></td></tr>
      <tr><th>APIs</th><td><ul>{api}</ul></td></tr>
      <tr><th>Technical specifications</th><td><ul>
        <li>Maximum images per prompt: 3</li><li>Supported aspect ratios: 1:1, 16:9</li>
        {'<li>Supported resolutions: 1K, 2K, 4K</li>' if size else ''}</ul></td></tr>
      <tr><th>Supported regions</th><td><code>{region}</code></td></tr>
      <tr><th>Versions</th><td><ul><li><code>{model}</code></li><ul><li>{lifecycle}</li></ul></ul></td></tr>
    </table></html>'''


def guide(*slugs):
    return '<nav><a href="/models/gemini/not-batch">Ignore me</a></nav>' + \
        '<h2>Gemini models that support batch inference</h2><ul>' + ''.join(
        f'<li><a href="/vertex-ai/generative-ai/docs/models/gemini/{s}">Unfamiliar model</a></li>' for s in slugs) + \
        '</ul><h2>Embedding models</h2><a href="/models/gemini/embedding">Ignore</a>'


URL = 'https://docs.cloud.google.com/vertex-ai/generative-ai/docs/models/gemini/future?hl=en'


class Source:
    def __init__(self, models):
        self.models = models
        self.calls = 0

    def discover(self, settings):
        self.calls += 1
        if isinstance(self.models, Exception):
            raise self.models
        return self.models


class CardTests(unittest.TestCase):
    def test_navigation_capability_labels_do_not_override_model_table(self):
        html='<nav><li><a>Batch inference</a>Not supported</li></nav>'+card()
        self.assertIsNotNone(parse_card(html,URL,'global'))

    def test_catalogue_total_timeout_is_bounded(self):
        def get(url,timeout):
            if url==BATCH_URL: return guide('slow')
            time.sleep(.05); return card()
        with patch('backend.model_catalog.TOTAL_TIMEOUT',.01):
            with self.assertRaises(TimeoutError):
                OfficialCatalogue(get).discover(Settings(Path('.'),Path('unused')))
        time.sleep(.06) # Let the intentionally delayed daemon fixture finish.
    def test_unknown_future_model_uses_capabilities_not_name_allowlist(self):
        model = parse_card(card('gemini-new-name'), URL, 'global')
        self.assertEqual(model['id'], 'gemini-new-name')
        self.assertEqual(model['max_references'], 3)
        self.assertEqual(model['batch_image_sizes'], ['1K'])

    def test_image_input_only_never_qualifies(self):
        self.assertIsNone(parse_card(card(image='Input only'), URL, 'global'))

    def test_explicit_batch_or_api_incompatibility_excluded(self):
        self.assertIsNone(parse_card(card(batch='Not supported'), URL, 'global'))
        self.assertIsNone(parse_card(card(generate='Not supported'), URL, 'global'))

    def test_new_card_omitting_api_section_uses_batch_contract(self):
        self.assertIsNotNone(parse_card(card(generate=None), URL, 'global'))

    def test_region_filter(self):
        self.assertIsNone(parse_card(card(), URL, 'us-central1'))
        self.assertIsNotNone(parse_card(card(region='us-central1'), URL, 'us-central1'))

    def test_retirement_and_deprecation_and_sibling_lifecycle(self):
        for lifecycle in ('Launch stage: Deprecated', 'Launch stage: Retired',
                          'Retirement date: October 1, 2026'):
            self.assertIsNone(parse_card(card(lifecycle=lifecycle), URL, 'global', date(2026,10,14)))
        model = parse_card(card(lifecycle='Retirement date: March 15, 2027'), URL, 'global', date(2026,10,14))
        self.assertEqual(model['retirement_date'], '2027-03-15')
        self.assertIsNotNone(parse_card(card(lifecycle='Retirement date: October 1, 2026 or later'), URL, 'global', date(2026,10,14)))

    def test_missing_metadata_is_a_parse_failure_not_confirmed_removal(self):
        with self.assertRaises(CatalogueError):
            parse_card('<h1>Access denied</h1>', URL, 'global')
        with self.assertRaises(CatalogueError):
            parse_card(card().replace('Supported regions', 'New format'), URL, 'global')

    def test_links_complete_deduplicated_and_scoped_to_support_section(self):
        self.assertEqual(len(batch_links(guide('one','two','one'))), 2)
        with self.assertRaises(CatalogueError): batch_links('<h2>Wrong page</h2>')
        with self.assertRaises(CatalogueError): batch_links(guide())
        with self.assertRaises(CatalogueError): official_url('https://evil.example/models/gemini/foo')
        with self.assertRaises(CatalogueError): official_url('http://cloud.google.com/foo')

    def test_complete_discovery_handles_all_links_and_authoritative_404(self):
        def get(url, timeout):
            self.assertGreater(timeout, 0)
            if url == BATCH_URL: return guide('future','text','removed')
            if '/removed?' in url: return None
            if '/text?' in url: return card('gemini-text',image='Input only')
            return card()
        settings=Settings(Path('.'),Path('unused'),location='global')
        self.assertEqual([m['id'] for m in OfficialCatalogue(get).discover(settings)],['gemini-future-image'])
        self.assertEqual(OfficialCatalogue(get).discover(replace(settings,location='europe-west9')),[])

    def test_partial_permission_failure_does_not_publish_partial_list(self):
        def get(url, timeout):
            if url == BATCH_URL: return guide('future','denied')
            if '/denied?' in url: raise PermissionError('403')
            return card()
        with self.assertRaises(PermissionError):
            OfficialCatalogue(get).discover(Settings(Path('.'),Path('unused')))


class CatalogueTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.settings=Settings(self.root,self.root/'data',project='demo',bucket='bucket')
        self.models=[parse_card(card(),URL,'global')]
        self.source=Source(self.models)
        self.catalog=ModelCatalogue(self.settings,self.source)

    def tearDown(self):
        self.catalog.close()
        if self.catalog._thread: self.catalog._thread.join(2)
        self.temp.cleanup()

    def refresh(self, catalog=None):
        catalog=catalog or self.catalog
        catalog.refresh()
        catalog._thread.join(2)
        self.assertFalse(catalog.snapshot()['refreshing'])

    def test_cold_start_refreshes_even_with_fresh_cache(self):
        self.refresh()
        new=ModelCatalogue(self.settings,self.source)
        self.assertEqual(new.snapshot()['source'],'cache')
        self.refresh(new)
        self.assertEqual(self.source.calls,2)

    def test_offline_permission_and_timeout_use_cache_without_sensitive_details(self):
        self.refresh()
        for failure in (TimeoutError('secret'),ConnectionError('secret'),PermissionError('secret')):
            self.source.models=failure
            self.refresh()
            state=self.catalog.snapshot()
            self.assertEqual(state['source'],'cache')
            self.assertEqual(state['models'],self.models)
            self.assertNotIn('secret',state['message'])

    def test_no_cache_failure_has_no_invented_dynamic_models(self):
        self.source.models=TimeoutError()
        self.refresh()
        self.assertEqual(self.catalog.snapshot()['source'],'unavailable')
        self.assertEqual(self.catalog.snapshot()['models'],[])
        self.catalog.validate(self.settings.model) # Legacy configured fallback is explicitly unverified.

    def test_successful_empty_catalog_removes_every_old_model_and_persists(self):
        self.refresh()
        self.source.models=[]
        self.refresh()
        self.assertEqual(self.catalog.snapshot()['source'],'official')
        self.assertEqual(ModelCatalogue(self.settings).snapshot()['models'],[])
        with self.assertRaises(ValueError): self.catalog.validate('gemini-future-image')
        self.source.models=TimeoutError()
        self.refresh()
        self.assertEqual(self.catalog.snapshot()['models'],[])

    def test_expired_corrupt_wrong_scope_and_future_cache_ignored(self):
        self.refresh()
        cached=read_json(self.catalog.path)
        for delta in (timedelta(days=31),timedelta(days=-2)):
            value={**cached,'fetched_at':(datetime.now(timezone.utc)-delta).isoformat()}
            write_json(self.catalog.path,value)
            self.assertEqual(ModelCatalogue(self.settings).snapshot()['source'],'unavailable')
        write_json(self.catalog.path,{**cached,'scope':{'project':'other','location':'global'}})
        self.assertEqual(ModelCatalogue(self.settings).snapshot()['source'],'unavailable')
        self.catalog.path.write_text('{broken',encoding='utf-8')
        self.assertEqual(ModelCatalogue(self.settings).snapshot()['models'],[])

    def test_malformed_retirement_and_capability_cache_fall_back_cleanly(self):
        self.refresh()
        original=read_json(self.catalog.path)
        for field,value in [('retirement_date','invalid'),('batch_image_sizes',['4K']),('max_references','bad')]:
            cached={**original,'models':[{**original['models'][0],field:value}]}
            write_json(self.catalog.path,cached)
            self.assertEqual(ModelCatalogue(self.settings).snapshot()['source'],'unavailable')

    def test_known_retirement_is_honored_during_offline_startup(self):
        self.refresh()
        value=read_json(self.catalog.path)
        value['models'][0]['retirement_date']='2020-01-01'
        write_json(self.catalog.path,value)
        self.assertEqual(ModelCatalogue(self.settings).snapshot()['models'],[])

    def test_refresh_nonblocking_singleflight_and_shutdown_nonblocking(self):
        entered=threading.Event(); finish=threading.Event()
        def discover(settings):
            entered.set(); finish.wait(2); return self.models
        self.source.discover=discover
        self.catalog.refresh()
        self.assertTrue(entered.wait(1))
        before=self.catalog._thread
        self.catalog.refresh()
        self.assertIs(self.catalog._thread,before)
        with self.assertRaises(ValueError): self.catalog.validate(self.settings.model)
        self.catalog.close()
        finish.set(); before.join(2)

    def test_cache_write_failure_still_publishes_live_models(self):
        with patch('backend.model_catalog.write_json',side_effect=OSError('readonly')):
            self.refresh()
        self.assertEqual(self.catalog.snapshot()['source'],'official')
        self.assertEqual(self.catalog.snapshot()['models'],self.models)


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory(); root=Path(self.temp.name)
        self.source=Source([parse_card(card('gemini-3.1-flash-image'),URL,'global'),
                            parse_card(card('gemini-future-image',size=False),URL,'global')])
        self.studio=Studio(Settings(root,root/'data',project='demo',bucket='bucket'),FakeCloud(),self.source)
        self.studio.model_catalog.refresh(); self.studio.model_catalog._thread.join(2)
        self.client=TestClient(create_app(self.studio,'test-token',background=False))
        self.client.__enter__(); self.client.headers['X-VBS-Token']='test-token'

    def tearDown(self):
        if self.studio.model_catalog._thread: self.studio.model_catalog._thread.join(2)
        self.client.__exit__(None,None,None); self.temp.cleanup()

    def batch(self,size='1K',ratio='16:9'):
        batch=self.studio.repo.create('test')
        self.studio.append_task(batch['id'],TaskInput(name='image',prompt='draw',image_size=size,aspect_ratio=ratio))
        return batch['id']

    def test_authenticated_selection_persists_and_unknown_models_rejected(self):
        self.assertEqual(self.client.post('/models/selection',json={'model':'gemini-future-image'},headers={'X-VBS-Token':'bad'}).status_code,401)
        self.assertEqual(self.client.post('/models/selection',json={'model':'imagen-4.0-generate-001'}).status_code,400)
        result=self.client.post('/models/selection',json={'model':'gemini-future-image'})
        self.assertEqual(result.json()['model'],'gemini-future-image')
        new=Studio(self.studio.settings,FakeCloud(),self.source)
        self.assertEqual(new.settings.model,'gemini-future-image'); new.close()
        self.assertEqual(self.client.get('/config').json()['model_catalog']['source'],'official')

    def test_prepared_and_submitted_jobs_keep_manifest_model_after_selection_removal(self):
        bid=self.batch()
        manifest=self.studio.prepare(bid)
        select_model(self.studio,'gemini-future-image')
        self.source.models=[self.source.models[1]]
        self.studio.model_catalog.refresh(); self.studio.model_catalog._thread.join(2)
        self.studio.submit(bid)
        self.assertEqual(self.studio.manifest(bid)['model'],manifest['model'])
        self.assertEqual(self.studio.repo.get(bid)['phase'],'monitoring')
        self.assertEqual(self.studio.submit(bid)['job_name'],self.studio.repo.get(bid)['job_name'])

    def test_new_prepare_uses_selected_model_and_omits_unsupported_size_field(self):
        select_model(self.studio,'gemini-future-image')
        manifest=self.studio.prepare(self.batch())
        self.assertEqual(manifest['model'],'gemini-future-image')
        self.assertNotIn('imageSize',manifest['requests'][0]['request']['generationConfig']['imageConfig'])

    def test_invalid_known_resolution_and_ratio_rejected_without_changing_task(self):
        for size,ratio in [('4K','16:9'),('1K','9:21')]:
            bid=self.batch(size,ratio)
            with self.assertRaises(ValueError): self.studio.prepare(bid)
            self.assertEqual(self.studio.repo.tasks(bid)[0].image_size,size)

    def test_live_removal_blocks_new_drafts_without_rewriting_selected_preference(self):
        self.source.models=[]
        self.studio.model_catalog.refresh(); self.studio.model_catalog._thread.join(2)
        self.assertEqual(self.studio.settings.model,'gemini-3.1-flash-image')
        result=self.client.post('/batches/'+self.batch()+'/submit')
        self.assertEqual(result.status_code,400)

    def test_selection_during_queued_operation_is_rejected(self):
        self.studio._inflight.add('queued')
        self.assertEqual(self.client.post('/models/selection',json={'model':'gemini-future-image'}).status_code,409)
        self.studio._inflight.clear()
