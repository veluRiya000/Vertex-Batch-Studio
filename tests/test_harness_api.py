from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from fastapi.testclient import TestClient
from backend.api import create_app
from backend.config import Settings
from backend.service import Studio
from .test_harness_batch import HarnessCloud

class HarnessApiTests(TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.studio=Studio(Settings(self.root,self.root/'data',project='demo',bucket='bucket'),HarnessCloud())
        with patch('backend.api.secrets.token_urlsafe',return_value='scoped-harness-only'):
            self.client=TestClient(create_app(self.studio,'owner-token',background=False))
        self.client.__enter__()
        self.client.headers['X-VBS-Harness-Token']='scoped-harness-only'
    def tearDown(self):
        self.client.__exit__(None,None,None)
        self.temp.cleanup()
    def test_scoped_adapter_cannot_read_or_mutate_image_studio_or_start_runtime(self):
        for route in ['/config','/references','/batches','/harness/status']:
            self.assertEqual(self.client.get(route).status_code,401,route)
        for route in ['/shutdown','/cloud/configuration','/harness/start','/harness/stop']:
            self.assertEqual(self.client.post(route,json={}).status_code,401,route)
        self.assertEqual(self.client.get('/harness/requests').status_code,200)
    def test_configured_limits_and_large_output_are_not_silently_clamped(self):
        run={'run_id':'a'*64,'session_id':'s','workspace':str(self.root),'budget_usd':100,'max_rounds':100}
        result=self.client.post('/harness/runs',json=run)
        self.assertEqual(result.status_code,201)
        self.assertEqual(result.json()['budget_usd'],100)
        self.assertEqual(result.json()['max_rounds'],100)
        result=self.client.post('/harness/runs/'+'a'*64+'/resume',json={'budget_usd':300,'max_rounds':100})
        self.assertEqual(result.json()['budget_usd'],300)
        req={'request_id':'b'*64,'run_id':'a'*64,'session_id':'s','step_id':'1', 'request':{'contents':[{'role':'user','parts':[{'text':'hello'}]}],'generationConfig':{'maxOutputTokens':65536}}}
        self.assertEqual(self.client.post('/harness/requests',json=req).status_code,202)
        self.assertEqual(self.studio.cloud.creates,0)
    def test_cloud_configuration_is_frozen_while_harness_request_is_pending(self):
        self.client.post('/harness/runs',json={'run_id':'a'*64,'session_id':'s','workspace':str(self.root)})
        self.client.post('/harness/requests',json={'request_id':'b'*64,'run_id':'a'*64,'session_id':'s','step_id':'1',
          'request':{'contents':[{'role':'user','parts':[{'text':'hello'}]}],'generationConfig':{'maxOutputTokens':2048}}})
        result=self.client.put('/cloud/configuration',json={'project':'changed','bucket':'changed'},headers={'X-VBS-Token':'owner-token'})
        self.assertEqual(result.status_code,400)
        self.assertIn('Harness',result.json()['detail'])
        self.assertEqual(self.studio.settings.project,'demo')


    def test_scoped_ui_intent_opens_only_cloud_settings_and_never_submits(self):
        route='/harness/ui/cloud-settings'
        self.assertEqual(self.client.post(route,headers={'X-VBS-Harness-Token':'invalid'}).status_code,401)
        self.assertEqual(self.client.get(route).status_code,401)
        self.assertEqual(self.client.post('/harness/ui/anything-else').status_code,401)
        owner={'X-VBS-Token':'owner-token'}
        self.assertEqual(self.client.get('/harness/status',headers=owner).json()['ui_request_seq'],0)
        self.assertEqual(self.client.post(route).json()['ui_request_seq'],1)
        self.assertEqual(self.client.get('/harness/status',headers=owner).json()['ui_request_seq'],1)
        self.assertEqual(self.client.post(route).json()['ui_request_seq'],2)
        self.assertEqual(self.client.get('/config').status_code,401)
        self.assertEqual(self.studio.cloud.creates,0)
