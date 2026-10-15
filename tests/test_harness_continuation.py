"""Paid cloud jobs are replaced with a deterministic one-row provider."""
from copy import deepcopy
import json
from unittest.mock import patch
import unittest
from . import test_harness_batch as fixtures
from backend.harness_batch import HarnessBatch
from backend.harness_continuation import next_request, merge_responses


class NativeContinuationTests(unittest.TestCase):
    setUp = fixtures.HarnessBatchTests.setUp
    tearDown = fixtures.HarnessBatchTests.tearDown
    def start_chain(self, *, enabled=False, cap=None):
        self.broker.set_run_phase(self.run_id, 'active', limits_enabled=enabled)
        self.value.request['generationConfig'].pop('maxOutputTokens')
        if cap is not None:
            self.value.request['generationConfig']['maxOutputTokens'] = cap
        self.original = deepcopy(self.value.request)
        self.broker.create(self.value)
        return self.broker.advance(self.value.request_id)

    def finish_segment(self, receipt, reason='CONTINUATION', token='token-one', parts=None, prompt=100, output=32768):
        stored = self.broker.get(self.value.request_id)
        response = {'candidates': [{'finishReason': reason, 'content': {'role': 'model', 'parts': parts if parts is not None else [{'text': 'segment'}]}}],
                    'usageMetadata': {'promptTokenCount': prompt, 'candidatesTokenCount': output, 'thoughtsTokenCount': 0, 'totalTokenCount': prompt+output}}
        if token:
            response['candidates'][0]['continuationToken'] = token
        self.cloud.finish(receipt['job_name'], {'part.jsonl': [{'request': self.broker.wire_request(stored), 'response': response}]})
        return self.broker.advance(self.value.request_id), response

    def test_three_segments_only_publish_final_stop_and_keep_native_parts(self):
        first = self.start_chain()
        buffered, one = self.finish_segment(first, 'MAX_TOKENS', parts=[{'text': 'abc', 'thoughtSignature': 'sig-a'}])
        self.assertEqual(buffered['phase'], 'preparing')
        self.assertIsNone(buffered['response'])
        self.assertNotIn('token-one', json.dumps(buffered))
        second = self.broker.advance(self.value.request_id)
        wire = self.broker.wire_request(self.broker.get(self.value.request_id))
        self.assertEqual(wire['contents'], self.original['contents'])
        self.assertEqual(wire['generationConfig']['maxOutputTokens'], 1048476)
        self.assertEqual(self.broker.get(self.value.request_id)['request'], self.original)
        buffered, two = self.finish_segment(second, token='token-two', parts=[{'text':'def'}], prompt=32868)
        self.assertIsNone(buffered['response'])
        third = self.broker.advance(self.value.request_id)
        done, three = self.finish_segment(third, 'STOP', None, parts=[{'functionCall': {'id':'write-1','name':'write','args':{'content':'whole file'}}}], prompt=65636, output=20)
        self.assertEqual(done['phase'], 'completed')
        self.assertFalse(done['truncated'])
        self.assertEqual(done['response']['candidates'][0]['content']['parts'], [*one['candidates'][0]['content']['parts'], *two['candidates'][0]['content']['parts'], *three['candidates'][0]['content']['parts']])
        self.assertEqual(done['response']['usageMetadata']['candidatesTokenCount'], 65556)
        self.assertEqual(done['response']['initialPromptTokenCount'], 100)
        self.assertAlmostEqual(done['actual_usd'], (100+32868+65636)*2/1e6 + 65556*10/1e6)
        self.assertEqual(self.cloud.creates, 3)
        self.broker.advance(self.value.request_id)
        self.assertEqual(self.cloud.creates, 3)

    def test_thinking_only_segment_does_not_finish_or_publish_empty_content(self):
        receipt=self.start_chain()
        buffered,_=self.finish_segment(receipt,parts=[{'text':'','thought':True}])
        self.assertEqual(buffered['phase'],'preparing')
        self.assertIsNone(buffered['response'])

    def test_repeat_token_stops_paid_loop_and_keeps_partial_raw(self):
        first=self.start_chain()
        self.finish_segment(first)
        second=self.broker.advance(self.value.request_id)
        stopped,_=self.finish_segment(second)
        self.assertEqual(stopped['phase'],'failed')
        self.assertIn('相同续传令牌',stopped['error'])
        self.assertIsNone(stopped['response'])
        self.assertEqual(self.cloud.creates,2)
        self.assertEqual(len(list((self.broker.root/'requests'/self.value.request_id).rglob('response.json'))),2)

    def test_second_submission_timeout_recovers_same_segment_after_restart(self):
        first=self.start_chain()
        self.finish_segment(first)
        self.cloud.create_timeout=True
        self.assertEqual(self.broker.advance(self.value.request_id)['phase'],'submission_unknown')
        self.broker.close();self.broker=HarnessBatch(self.studio)
        second=self.broker.advance(self.value.request_id)
        self.assertEqual(second['phase'],'queued')
        self.assertEqual(self.cloud.creates,2)
        self.assertIn('/segments/0001/',self.cloud.job_inputs[second['job_name']][1])

    def test_restart_at_checkpoint_requires_resume_before_new_paid_job(self):
        first=self.start_chain()
        self.finish_segment(first)
        self.broker.close();self.broker=HarnessBatch(self.studio)
        stopped=self.broker.advance(self.value.request_id)
        self.assertEqual(stopped['phase'],'budget_paused')
        self.assertEqual(self.cloud.creates,1)
        self.broker.set_run_phase(self.run_id,'active')
        self.broker.resume(self.value.request_id)
        self.assertEqual(self.broker.advance(self.value.request_id)['phase'],'queued')
        self.assertEqual(self.cloud.creates,2)

    def _assert_guard(self, **limits):
        first=self.start_chain(enabled=True,cap=65536)
        self.finish_segment(first,output=32768)
        self.broker.set_run_phase(self.run_id,'active',**limits)
        stopped=self.broker.advance(self.value.request_id)
        self.assertEqual(stopped['phase'],'budget_paused')
        self.assertGreater(stopped['actual_usd'],0)
        self.assertEqual(self.cloud.creates,1)

    def test_round_limit_counts_each_native_segment(self):
        self._assert_guard(max_rounds=1)

    def test_budget_guard_counts_paid_segments_and_next_reserve(self):
        self._assert_guard(budget_usd=.5)

    def test_cancellation_between_segments_never_creates_next_job(self):
        first=self.start_chain()
        buffered,_=self.finish_segment(first)
        paid=buffered['actual_usd']
        stopped=self.broker.cancel(self.value.request_id)
        self.assertEqual(stopped['phase'],'cancelled')
        self.assertEqual(stopped['actual_usd'],paid)
        self.broker.advance(self.value.request_id)
        self.assertEqual(self.cloud.creates,1)

    def test_cancel_accepted_continuation_targets_current_job(self):
        first=self.start_chain()
        self.finish_segment(first)
        second=self.broker.advance(self.value.request_id)
        self.broker.cancel(self.value.request_id)
        stopped=self.broker.advance(self.value.request_id)
        self.assertEqual(stopped['phase'],'cancelled')
        self.assertEqual(self.cloud.jobs[second['job_name']].state,'JOB_STATE_CANCELLED')
        self.assertNotEqual(self.cloud.jobs[first['job_name']].state,'JOB_STATE_CANCELLED')

    def test_explicit_output_cap_is_not_bypassed(self):
        first=self.start_chain(enabled=True,cap=32768)
        stopped,_=self.finish_segment(first,'MAX_TOKENS')
        self.assertEqual(stopped['phase'],'failed')
        self.assertIn('本轮输出额度',stopped['error'])
        self.assertIsNone(stopped['response'])

    def test_final_safety_failure_preserves_all_paid_usage_but_no_tools(self):
        first=self.start_chain();self.finish_segment(first)
        second=self.broker.advance(self.value.request_id)
        stopped,_=self.finish_segment(second,'SAFETY',None,output=2)
        self.assertEqual(stopped['phase'],'failed')
        self.assertGreater(stopped['actual_usd'],.32768)
        self.assertIsNone(stopped['response'])

    def test_unknown_fields_and_signed_parts_remain_frozen(self):
        first=self.start_chain()
        self.finish_segment(first)
        stored=self.broker.get(self.value.request_id)
        self.assertEqual(stored['request'],self.original)
        self.assertEqual(stored['fingerprint'],self.broker.get(self.value.request_id)['fingerprint'])
        second=self.broker.advance(self.value.request_id)
        original=self.broker.wire_request(self.broker.get(self.value.request_id))
        changed=deepcopy(original);changed['contents'][0]['parts'][0]['text']='wrong'
        self.cloud.finish(second['job_name'],{'part.jsonl':[{'request':changed,'response':{'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':'unsafe'}]}}]}}]})
        self.assertEqual(self.broker.advance(self.value.request_id)['phase'],'failed')

    def test_no_progress_or_missing_token_does_not_loop(self):
        first=self.start_chain()
        stopped,_=self.finish_segment(first,output=0)
        self.assertEqual(stopped['phase'],'failed')
        self.assertEqual(self.cloud.creates,1)

    def test_duplicate_native_tool_ids_rejected_before_dispatch(self):
        part={'functionCall':{'id':'same','name':'write','args':{'content':'partial'}}}
        first=self.start_chain();self.finish_segment(first,parts=[part])
        second=self.broker.advance(self.value.request_id)
        stopped,_=self.finish_segment(second,'STOP',None,parts=[part],output=20)
        self.assertEqual(stopped['phase'],'failed')
        self.assertIsNone(stopped['response'])

    def test_unknown_gcs_continuation_rejection_is_not_a_real_time_fallback(self):
        first=self.start_chain();self.finish_segment(first)
        second=self.broker.advance(self.value.request_id)
        stored=self.broker.get(self.value.request_id)
        self.cloud.finish(second['job_name'],{'part.jsonl':[{'request':self.broker.wire_request(stored),'status':{'code':3,'message':'continuationToken is unsupported'}}]})
        stopped=self.broker.advance(self.value.request_id)
        self.assertEqual(stopped['phase'],'failed')
        self.assertEqual(stopped['reserved_usd'],0)
        self.assertGreater(stopped['actual_usd'],0)
        self.assertEqual(self.cloud.creates,2)

    def test_gcs_null_thinking_counter_is_zero_not_missing_progress(self):
        first=self.start_chain()
        stored=self.broker.get(self.value.request_id)
        response={'candidates':[{'finishReason':'CONTINUATION','continuationToken':'abc','content':{'parts':[{'text':'body'}]}}], 'usageMetadata':{'promptTokenCount':100,'candidatesTokenCount':32768,'thoughtsTokenCount':None}}
        self.cloud.finish(first['job_name'],{'part.jsonl':[{'request':self.broker.wire_request(stored),'response':response}]})
        self.assertEqual(self.broker.advance(self.value.request_id)['phase'],'preparing')

    def test_cancel_during_download_is_not_overwritten_by_usage_settlement(self):
        first=self.start_chain()
        stored=self.broker.get(self.value.request_id)
        row={'request':self.broker.wire_request(stored),'response':{'candidates':[{'finishReason':'CONTINUATION','continuationToken':'abc','content':{'parts':[{'text':'body'}]}}], 'usageMetadata':{'promptTokenCount':100,'candidatesTokenCount':32768}}}
        self.cloud.finish(first['job_name'],{'part.jsonl':[row]})
        download=self.cloud.download
        def cancel_and_download(*args):
            self.broker.cancel(self.value.request_id)
            return download(*args)
        with patch.object(self.cloud,'download',side_effect=cancel_and_download):
            stopped=self.broker.advance(self.value.request_id)
        self.assertEqual(stopped['phase'],'cancelled')
        self.assertIsNone(stopped['response'])
        self.assertGreater(stopped['actual_usd'],0)
        self.assertEqual(self.cloud.creates,1)

    def test_thought_only_usage_can_continue_and_signature_is_retained(self):
        first=self.start_chain()
        response={'candidates':[{'finishReason':'CONTINUATION','continuationToken':'abc','content':{'parts':[{'text':'private reasoning','thought':True,'thoughtSignature':'keep'}]}}], 'usageMetadata':{'promptTokenCount':100,'candidatesTokenCount':0,'thoughtsTokenCount':32768}}
        self.cloud.finish(first['job_name'],{'part.jsonl':[{'request':self.original,'response':response}]})
        buffered=self.broker.advance(self.value.request_id)
        self.assertEqual(buffered['phase'],'preparing')
        self.assertIsNone(buffered['response'])
        self.assertNotIn('private reasoning',json.dumps(buffered))
        with self.broker.connection() as db:
            events=''.join(r[0] for r in db.execute('SELECT data FROM events'))
        self.assertNotIn('private reasoning',events)
        self.assertNotIn('continuationToken',events)
        second=self.broker.advance(self.value.request_id)
        done,_=self.finish_segment(second,'STOP',None,parts=[{'text':'answer'}],output=10)
        self.assertEqual(done['response']['candidates'][0]['content']['parts'][0],response['candidates'][0]['content']['parts'][0])

    def test_maximum_model_window_stops_even_with_unlimited_local_settings(self):
        initial={'candidates':[{'finishReason':'MAX_TOKENS','continuationToken':'last','content':{'parts':[{'text':'body'}]}}], 'usageMetadata':{'promptTokenCount':1048476,'candidatesTokenCount':100}}
        wire,reason=next_request(self.value.request,self.value.request,[initial],'gemini-4-argon',1048476,False)
        self.assertIsNone(wire)
        self.assertIn('1048576',reason)

    def test_native_parts_merge_does_not_stitch_tool_arguments_speculatively(self):
        response={'candidates':[{'finishReason':'STOP','content':{'parts':[{'functionCall':{'id':'w','name':'write','args':{},'willContinue':True}}]}}]}
        with self.assertRaisesRegex(ValueError,'参数仍未完整'):
            merge_responses([response])
