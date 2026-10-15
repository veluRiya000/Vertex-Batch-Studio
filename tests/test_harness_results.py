from copy import deepcopy
from unittest import TestCase
from backend.harness_results import request_matches, response_from_row


class HarnessResultsTests(TestCase):
    def setUp(self):
        self.request={'contents':[{'role':'user','parts':[{'text':'hello'},{'functionResponse':{'name':'read','response':{'explicit_null':None}}}]}],
            'tools':[{'functionDeclarations':[{'name':'read','parameters':{'type':'OBJECT','properties':{'file_path':{'type':'STRING'}}}}]}]}

    def test_documented_null_padding_and_empty_required_preserve_identity(self):
        echo=deepcopy(self.request)
        echo['contents'][0]['parts'][0]['functionResponse']=None
        echo['contents'][0]['parts'][1]['text']=None
        params=echo['tools'][0]['functionDeclarations'][0]['parameters']
        params['properties']['other_tool_argument']=None
        params['required']=[]
        self.assertTrue(request_matches(self.request,echo))
        response={'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':'done'}]}}]}
        self.assertEqual(response_from_row({'request':echo,'status':'','response':response},self.request),response)

    def test_real_changes_and_missing_explicit_null_are_not_associated(self):
        for kind in ['prompt','argument','missing_null','required']:
            echo=deepcopy(self.request)
            if kind=='prompt':echo['contents'][0]['parts'][0]['text']='other'
            if kind=='argument':echo['contents'][0]['parts'][1]['functionResponse']['response']['unexpected']='injected'
            if kind=='missing_null':del echo['contents'][0]['parts'][1]['functionResponse']['response']['explicit_null']
            if kind=='required':echo['tools'][0]['functionDeclarations'][0]['parameters']['required']=['file_path']
            self.assertFalse(request_matches(self.request,echo),kind)

    def test_provider_status_is_reported_without_internal_trace(self):
        status={'code':3,'message':"Failed to parse parameters_json_schema; RPC trace secret"}
        with self.assertRaisesRegex(ValueError,'云端拒绝工具参数格式'):
            response_from_row({'request':self.request,'status':__import__('json').dumps(status),'response':{}},self.request)

    def test_changed_request_does_not_borrow_another_rows_error(self):
        with self.assertRaisesRegex(ValueError,'无法关联'):
            response_from_row({'request':{},'status':'other error'},self.request)

    def test_repeated_field_padding_in_sibling_tool_calls(self):
        request={'contents':[{'role':'model','parts':[
            {'functionCall':{'name':'write','args':{'file_path':'a.svg','content':'svg'}}},
            {'functionCall':{'name':'present','args':{'files':[{'path':'a.svg'}]}}},
        ]}]}
        echo=deepcopy(request)
        echo['contents'][0]['parts'][0]['functionCall']['args']['files']=[]
        self.assertTrue(request_matches(request,echo))
        for kind in ['unknown_array','nonempty_padding','different_content','lost_files','wrong_shape']:
            changed=deepcopy(echo)
            args=changed['contents'][0]['parts'][0]['functionCall']['args']
            if kind=='unknown_array':args['unknown']=[]
            if kind=='nonempty_padding':args['files']=[{'path':'other.svg'}]
            if kind=='different_content':args['content']='changed'
            if kind=='lost_files':changed['contents'][0]['parts'][1]['functionCall']['args']['files']=[]
            if kind=='wrong_shape':changed['contents'][0]['parts'][0]['functionCall']['files']=[]
            self.assertFalse(request_matches(request,changed),kind)

    def test_empty_array_is_not_unconditionally_ignored(self):
        echo=deepcopy(self.request)
        echo['contents'][0]['parts'][1]['functionResponse']['response']['files']=[]
        self.assertFalse(request_matches(self.request,echo))
