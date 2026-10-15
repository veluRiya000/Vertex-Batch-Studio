import json
from unittest import TestCase
import httpx
from google import genai
from google.oauth2.credentials import Credentials
from backend.cloud import GoogleCloud

class HarnessGoogleWireTests(TestCase):
    def adapter(self,transport):
        value=GoogleCloud.__new__(GoogleCloud)
        value.genai=genai.Client(vertexai=True,project='offline-project',location='global',credentials=Credentials(token='offline-only'),
          http_options={'api_version':'v1','client_args':{'transport':httpx.MockTransport(transport),'trust_env':False}})
        self.addCleanup(value.genai.close)
        return value
    def test_paid_creation_does_not_hide_http_retries(self):
        calls=[]
        def transport(request):
            calls.append(request)
            return httpx.Response(500,json={'error':{'code':500,'message':'Uncertain simulated server response','status':'INTERNAL'}})
        cloud=self.adapter(transport)
        with self.assertRaises(Exception):
            cloud.create_job('gemini-4-argon','gs://offline/input.jsonl','gs://offline/outputs/','test')
        self.assertEqual(len(calls),1)
    def test_token_count_includes_system_and_native_tool_schema(self):
        calls=[]
        def transport(request):
            calls.append(request)
            return httpx.Response(200,json={'totalTokens':123})
        cloud=self.adapter(transport)
        request={'contents':[{'role':'user','parts':[{'text':'read the fixture'}]}],
          'systemInstruction':{'parts':[{'text':'Read-only acceptance'}]},
          'tools':[{'functionDeclarations':[{'name':'read','parametersJsonSchema':{'type':'object','properties':{'file_path':{'type':'string'}},'required':['file_path']}}]}]}
        self.assertEqual(cloud.count_request_tokens(request),123)
        body=json.loads(calls[0].content)
        self.assertEqual(body['systemInstruction']['parts'][0]['text'],'Read-only acceptance')
        self.assertEqual(body['tools'][0]['functionDeclarations'][0]['name'],'read')
        self.assertIn('gemini-4-argon',str(calls[0].url))

    def test_selected_model_is_used_by_token_counter(self):
        for model in ('gemini-3.8-flash','gemini-3.1-pro-preview'):
            calls=[]
            def transport(request):
                calls.append(request)
                return httpx.Response(200,json={'totalTokens':321})
            cloud=self.adapter(transport)
            self.assertEqual(cloud.count_request_tokens({'contents':[{'role':'user','parts':[{'text':'test'}]}]},model=model),321)
            self.assertIn(model,str(calls[0].url))
