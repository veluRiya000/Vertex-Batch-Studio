import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from backend.config import Settings
from backend.service import Studio
from backend.harness_batch import HarnessBatch
from backend.harness_models import HarnessRun, HarnessRequest
from .fakes import FakeCloud

class HarnessCloud(FakeCloud):
    def count_request_tokens(self, request, model="gemini-4-argon"):
        return 100

class HarnessBatchTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.cloud=HarnessCloud()
        self.studio=Studio(Settings(self.root,self.root/'data',project='demo',bucket='bucket'),self.cloud)
        self.broker=HarnessBatch(self.studio)
        self.run_id='a'*64
        self.broker.create_run(HarnessRun(run_id=self.run_id,session_id='s',workspace=str(self.root),limits_enabled=True))
        self.value=HarnessRequest(request_id='b'*64,run_id=self.run_id,session_id='s',step_id='1',request={
            'contents':[{'role':'user','parts':[{'text':'hello'}]}],
            'generationConfig':{'maxOutputTokens':2048,'thinkingConfig':{'thinkingLevel':'MEDIUM'}}})
    def tearDown(self):
        self.broker.close()
        self.studio.close()
        self.temp.cleanup()
    def test_same_receipt_never_creates_two_jobs(self):
        self.broker.create(self.value)
        self.broker.advance(self.value.request_id)
        self.broker.create(self.value)
        self.broker.advance(self.value.request_id)
        self.assertEqual(self.cloud.creates,1)
        data=self.cloud.objects[('bucket','harness/requests/'+self.value.request_id+'/input.jsonl')][0]
        self.assertEqual(len(data.decode().splitlines()),1)
    def test_changed_request_cannot_reuse_identity(self):
        self.broker.create(self.value)
        other=self.value.model_copy(deep=True)
        other.request['contents'][0]['parts'][0]['text']='different'
        with self.assertRaises(ValueError): self.broker.create(other)
    def test_unknown_submission_is_reconciled_after_restart(self):
        self.cloud.create_timeout=True
        self.broker.create(self.value)
        self.assertEqual(self.broker.advance(self.value.request_id)['phase'],'submission_unknown')
        self.broker.close()
        self.broker=HarnessBatch(self.studio)
        self.broker.advance(self.value.request_id)
        self.assertEqual(self.cloud.creates,1)
        self.assertTrue(self.broker.get(self.value.request_id)['job_name'])
    def test_cancel_without_cloud_configuration_is_local(self):
        self.broker.create(self.value)
        result=self.broker.cancel(self.value.request_id)
        self.assertEqual(result['phase'],'cancelled')
        self.assertEqual(self.cloud.creates,0)
    def test_budget_pauses_before_upload_and_creation(self):
        self.broker.set_run_phase(self.run_id,'active',budget_usd=.001)
        self.broker.create(self.value)
        self.assertEqual(self.broker.advance(self.value.request_id)['phase'],'budget_paused')
        self.assertEqual(self.cloud.creates,0)
        self.assertEqual(self.cloud.uploads,[])
    def test_text_result_and_usage_are_retained(self):
        self.broker.create(self.value)
        result=self.broker.advance(self.value.request_id)
        response={'candidates':[{'finishReason':'STOP','content':{'role':'model','parts':[{'text':'done'}]}}],
                  'usageMetadata':{'promptTokenCount':100,'candidatesTokenCount':20,'thoughtsTokenCount':10}}
        self.cloud.finish(result['job_name'],{'part.jsonl':[{'request':self.value.request,'response':response}]})
        done=self.broker.advance(self.value.request_id)
        self.assertEqual(done['phase'],'completed')
        self.assertEqual(done['response'],response)
        self.assertAlmostEqual(done['actual_usd'],.0005)
        self.assertEqual(done['reserved_usd'],0)
    def test_truncated_response_is_retained_and_releases_run(self):
        self.broker.create(self.value)
        result=self.broker.advance(self.value.request_id)
        row={'request':self.value.request,'response':{'candidates':[{'finishReason':'MAX_TOKENS','content':{'parts':[{'functionCall':{'name':'write','args':{}}}]}}]}}
        self.cloud.finish(result['job_name'],{'part.jsonl':[row]})
        done=self.broker.advance(self.value.request_id)
        self.assertEqual(done['phase'],'completed')
        self.assertTrue(done['truncated'])
        self.assertEqual(done['response'],row['response'])
        self.assertEqual(self.broker.run(self.run_id)['phase'],'paused')
    def test_old_image_model_setting_is_not_modified(self):
        self.broker.create(self.value)
        self.broker.advance(self.value.request_id)
        self.assertEqual(self.studio.settings.model,'gemini-3.1-flash-image')
    def test_definitive_permission_rejection_is_not_unknown_or_stuck(self):
        class Rejected(Exception):code=403
        self.broker.create(self.value)
        with patch.object(self.cloud,'create_job',side_effect=Rejected()):
            result=self.broker.advance(self.value.request_id)
        self.assertEqual(result['phase'],'failed')
        self.assertEqual(result['reserved_usd'],0)
        self.assertIn('403',result['error'])
        self.assertEqual(self.broker.cancel(self.value.request_id)['phase'],'failed')
        self.assertEqual(self.broker.finish_run(self.run_id)['phase'],'paused')
    def test_completed_finish_event_does_not_clear_budget_pause(self):
        self.broker.set_run_phase(self.run_id,'active',budget_usd=.001)
        self.broker.create(self.value)
        self.broker.advance(self.value.request_id)
        self.assertEqual(self.broker.finish_run(self.run_id)['phase'],'paused')

    def _new_run(self, workspace=None, run_id='c'*64):
        return self.broker.create_run(HarnessRun(run_id=run_id,session_id='new',workspace=str(workspace or self.root)))

    def test_failed_request_releases_workspace_without_finish_callback(self):
        self.broker.create(self.value)
        with patch.object(self.cloud,'count_request_tokens',side_effect=ValueError('invalid input')):
            self.assertEqual(self.broker.advance(self.value.request_id)['phase'],'failed')
        self.assertEqual(self.broker.run(self.run_id)['phase'],'paused')
        self.assertEqual(self._new_run()['phase'],'active')
        self.assertEqual(self.cloud.creates,0)

    def test_legacy_failed_active_run_repaired_before_new_turn(self):
        self.broker.create(self.value)
        receipt=self.broker.get(self.value.request_id)
        receipt.update(phase='failed',error='old failure')
        with self.broker.connection() as db:
            db.execute('UPDATE requests SET data=? WHERE id=?',(json.dumps(receipt),self.value.request_id))
        self.assertEqual(self.broker.run(self.run_id)['phase'],'active')
        self._new_run()
        self.assertEqual(self.broker.run(self.run_id)['phase'],'paused')
        self.assertEqual(self.broker.get(self.value.request_id)['error'],'old failure')
        self.assertEqual(self.cloud.creates,0)

    def test_restart_releases_orphan_empty_run(self):
        self.broker.close();self.broker=HarnessBatch(self.studio)
        self.assertEqual(self.broker.run(self.run_id)['phase'],'paused')
        self._new_run()
        self.assertEqual(self.cloud.creates,0)

    def test_restart_preserves_pending_and_unknown_requests(self):
        self.cloud.create_timeout=True
        self.broker.create(self.value)
        self.assertEqual(self.broker.advance(self.value.request_id)['phase'],'submission_unknown')
        self.broker.close();self.broker=HarnessBatch(self.studio)
        with self.assertRaisesRegex(ValueError,'活动任务'):self._new_run()
        self.assertEqual(self.broker.run(self.run_id)['phase'],'active')
        self.assertEqual(self.broker.get(self.value.request_id)['phase'],'submission_unknown')
        self.assertEqual(self.cloud.creates,1)

    def test_finish_does_not_release_pending_or_paused_cloud_job(self):
        self.broker.create(self.value)
        self.assertEqual(self.broker.finish_run(self.run_id)['phase'],'active')
        self.broker.set_run_phase(self.run_id,'paused')
        with self.assertRaisesRegex(ValueError,'活动任务'):self._new_run()

    def test_successful_step_stays_active_between_tool_rounds(self):
        self.broker.create(self.value)
        receipt=self.broker.get(self.value.request_id)
        receipt.update(phase='completed')
        self.broker.save(receipt)
        self.assertEqual(self.broker.run(self.run_id)['phase'],'active')
        with self.assertRaisesRegex(ValueError,'活动任务'):self._new_run()
        self.assertEqual(self.broker.finish_run(self.run_id)['phase'],'completed')
        self._new_run()

    def test_large_output_and_input_below_model_total_are_accepted(self):
        value=self.value.model_copy(deep=True)
        value.request['generationConfig']['maxOutputTokens']=65536
        self.broker.create(value)
        with patch.object(self.cloud,'count_request_tokens',return_value=250000):
            result=self.broker.advance(value.request_id)
        self.assertEqual(result['phase'],'queued')
        self.assertEqual(self.cloud.creates,1)

    def test_real_model_total_is_validated_before_paid_submission(self):
        self.broker.create(self.value)
        with patch.object(self.cloud,'count_request_tokens',return_value=1048576):
            result=self.broker.advance(self.value.request_id)
        self.assertEqual(result['phase'],'failed')
        self.assertIn('1048576',result['error'])
        self.assertEqual(self.cloud.creates,0)

    def test_flash_and_pro_submit_selected_model_and_snapshot_distinct_costs(self):
        from backend.harness_profiles import estimate_cost, price_snapshot
        for model in ('gemini-3.8-flash','gemini-3.1-pro-preview'):
            value=self.value.model_copy(deep=True)
            value.model=model
            self.broker.create(value)
            with patch.object(self.cloud,'count_request_tokens',return_value=100) as count, patch.object(self.cloud,'create_job',wraps=self.cloud.create_job) as create:
                receipt=self.broker.advance(value.request_id)
                count.assert_called_once_with(value.request,model=model)
                self.assertEqual(create.call_args.args[0],model)
            self.assertAlmostEqual(receipt['reserved_usd'],estimate_cost(100,2048,price_snapshot(model)))
            self.assertEqual(receipt['model'],model)
            self.broker.cancel(value.request_id)
            # Independent fixture ledger for the second model; never reset a live receipt.
            with self.broker.connection() as db:
                db.execute('DELETE FROM requests')
            self.broker.set_run_phase(self.run_id,'active')
        pro=price_snapshot('gemini-3.1-pro-preview')
        self.assertAlmostEqual(estimate_cost(200001,1000,pro),(200001*2+1000*9)/1000000)


    def test_malformed_response_still_settles_usage_without_executing_tools(self):
        self.broker.create(self.value)
        result=self.broker.advance(self.value.request_id)
        response={'candidates':[{'finishReason':'MALFORMED_RESPONSE','content':{'parts':[{'text':'incomplete'}]}}],
                  'usageMetadata':{'promptTokenCount':100,'cachedContentTokenCount':80,'candidatesTokenCount':20,'thoughtsTokenCount':10}}
        self.cloud.finish(result['job_name'],{'part.jsonl':[{'request':self.value.request,'response':response}]})
        done=self.broker.advance(self.value.request_id)
        self.assertEqual(done['phase'],'failed')
        self.assertAlmostEqual(done['actual_usd'],.000348)
        self.assertEqual(done['reserved_usd'],0)
        self.assertEqual(done['usage'],response['usageMetadata'])
        again=self.broker.advance(self.value.request_id)
        self.assertEqual(again['actual_usd'],done['actual_usd'])
        self.assertEqual(self.cloud.creates,1)

    def test_missing_usage_keeps_unresolved_estimate_out_of_actual(self):
        self.broker.create(self.value)
        result=self.broker.advance(self.value.request_id)
        reserve=result['reserved_usd']
        response={'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':'done'}]}}]}
        self.cloud.finish(result['job_name'],{'part.jsonl':[{'request':self.value.request,'response':response}]})
        done=self.broker.advance(self.value.request_id)
        self.assertEqual(done['phase'],'completed')
        self.assertEqual(done['actual_usd'],0)
        self.assertEqual(done['reserved_usd'],reserve)

    def test_validation_error_without_generation_releases_reserve(self):
        self.broker.create(self.value)
        result=self.broker.advance(self.value.request_id)
        row={'request':self.value.request,'status':json.dumps({'code':3,'message':'invalid input'}),'response':{'candidates':None}}
        self.cloud.finish(result['job_name'],{'part.jsonl':[row]})
        done=self.broker.advance(self.value.request_id)
        self.assertEqual(done['phase'],'failed')
        self.assertEqual(done['actual_usd'],0)
        self.assertEqual(done['reserved_usd'],0)

    def test_large_output_reservation_pauses_before_any_paid_request(self):
        value=self.value.model_copy(deep=True)
        value.request['generationConfig']['maxOutputTokens']=655360
        self.broker.create(value)
        with patch.object(self.cloud,'count_request_tokens',return_value=89619):
            done=self.broker.advance(value.request_id)
        self.assertEqual(done['phase'],'budget_paused')
        self.assertAlmostEqual(done['budget_check']['next_reservation_usd'],6.732838)
        self.assertIn('预留不是已扣费',done['error'])
        self.assertEqual(done['actual_usd'],0)
        self.assertEqual(done['reserved_usd'],0)
        self.assertEqual(self.cloud.creates,0)


    def test_disabled_limits_allow_further_rounds_and_keep_usage_accounting(self):
        self.broker.set_run_phase(self.run_id,'active',budget_usd=.00001,max_rounds=1,limits_enabled=False)
        value=self.value.model_copy(deep=True)
        del value.request['generationConfig']['maxOutputTokens']
        self.broker.create(value)
        first=self.broker.advance(value.request_id)
        self.assertEqual(first['phase'],'queued')
        self.assertFalse(first['limits_enabled'])
        response={'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':'done'}]}}],
                  'usageMetadata':{'promptTokenCount':100,'candidatesTokenCount':20}}
        self.cloud.finish(first['job_name'],{'part.jsonl':[{'request':value.request,'response':response}]})
        done=self.broker.advance(value.request_id)
        self.assertGreater(done['actual_usd'],.00001)
        other=value.model_copy(deep=True);other.request_id='c'*64;other.step_id='2'
        self.broker.create(other)
        self.assertEqual(self.broker.advance(other.request_id)['phase'],'queued')
        self.assertEqual(self.cloud.creates,2)

    def test_disable_switch_does_not_bypass_explicit_pause(self):
        self.broker.create(self.value)
        self.broker.set_run_phase(self.run_id,'paused',limits_enabled=False)
        self.assertEqual(self.broker.advance(self.value.request_id)['phase'],'budget_paused')
        self.assertEqual(self.cloud.creates,0)

    def test_next_run_request_can_toggle_limits_without_resetting_its_identity(self):
        changed=self.broker.create_run(HarnessRun(run_id=self.run_id,session_id='s',workspace=str(self.root),limits_enabled=False))
        self.assertFalse(changed['limits_enabled'])
        self.assertEqual(changed['run_id'],self.run_id)

    def test_omitted_output_cap_does_not_impose_64k_local_output_reservation_on_context(self):
        self.broker.set_run_phase(self.run_id,'active',limits_enabled=False)
        value=self.value.model_copy(deep=True)
        del value.request['generationConfig']['maxOutputTokens']
        self.broker.create(value)
        with patch.object(self.cloud,'count_request_tokens',return_value=1048500):
            self.assertEqual(self.broker.advance(value.request_id)['phase'],'queued')


    def _old_association_failure(self, parts=None):
        self.broker.create(self.value)
        receipt=self.broker.advance(self.value.request_id)
        response={'candidates':[{'finishReason':'STOP','content':{'role':'model','parts':parts or [{'text':'Final answer'}]}}],
                  'usageMetadata':{'promptTokenCount':100,'candidatesTokenCount':20,'thoughtsTokenCount':10}}
        self.cloud.finish(receipt['job_name'],{'part.jsonl':[{'request':self.value.request,'response':response}]})
        with patch('backend.harness_batch.request_matches',return_value=False):
            self.assertEqual(self.broker.advance(self.value.request_id)['phase'],'failed')
        return response

    def test_local_answer_recovery_never_calls_cloud_and_is_idempotent(self):
        response=self._old_association_failure()
        with patch.object(self.cloud,'get_job',side_effect=AssertionError('network forbidden')),patch.object(self.cloud,'create_job',side_effect=AssertionError('submission forbidden')):
            self.assertTrue(self.broker.recover_local_answer(self.value.request_id))
            self.assertFalse(self.broker.recover_local_answer(self.value.request_id))
        recovered=self.broker.get(self.value.request_id)
        self.assertEqual(recovered['phase'],'completed')
        self.assertEqual(recovered['response'],response)
        self.assertEqual(recovered['local_recovery']['text'],'Final answer')
        self.assertIn('无法关联',recovered['local_recovery']['previous_error'])
        self.assertEqual(recovered['reserved_usd'],0)
        self.assertEqual(self.broker.run(self.run_id)['phase'],'paused')
        self.assertEqual(self.cloud.creates,1)

    def test_restart_recovers_only_finished_local_text_answer(self):
        self._old_association_failure()
        self.broker.close()
        with patch.object(self.cloud,'get_job',side_effect=AssertionError('network forbidden')):
            self.broker=HarnessBatch(self.studio)
        self.assertEqual(self.broker.get(self.value.request_id)['phase'],'completed')
        self.assertEqual(self.cloud.creates,1)

    def test_local_recovery_does_not_replay_tool_calls_or_changed_output(self):
        self._old_association_failure([{'functionCall':{'name':'write','args':{'content':'do not run'}}}])
        self.assertFalse(self.broker.recover_local_answer(self.value.request_id))
        self.assertEqual(self.broker.get(self.value.request_id)['phase'],'failed')
        raw=next((self.broker.root/'requests'/self.value.request_id/'raw').glob('*.jsonl'))
        row=json.loads(raw.read_text(encoding='utf-8'))
        row['response']['candidates'][0]['content']['parts']=[{'text':'done'}]
        row['request']['contents'][0]['parts'][0]['text']='different request'
        raw.write_text(json.dumps(row),encoding='utf-8')
        self.assertFalse(self.broker.recover_local_answer(self.value.request_id))
        self.assertEqual(self.broker.get(self.value.request_id)['phase'],'failed')

if __name__=='__main__': unittest.main()
