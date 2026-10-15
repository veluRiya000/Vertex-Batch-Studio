from unittest import TestCase
from backend.harness_profiles import price_snapshot, usage_cost

class HarnessCostTests(TestCase):
    def test_returned_cached_input_is_not_counted_twice(self):
        usage={"promptTokenCount":92210,"cachedContentTokenCount":90112,
               "candidatesTokenCount":4652,"thoughtsTokenCount":22436}
        cost=usage_cost(usage,price_snapshot("gemini-4-argon"),"gemini-4-argon","2026-10-15")
        self.assertAlmostEqual(cost["estimated_usd"],.2840872)
        self.assertAlmostEqual(cost["promotional_estimated_usd"],.1420436)
        self.assertEqual(cost["cached_input_rate"],.1)

    def test_thinking_and_candidates_are_output_once(self):
        cost=usage_cost({"promptTokenCount":100,"candidatesTokenCount":20,"thoughtsTokenCount":10,"totalTokenCount":130},price_snapshot("gemini-4-argon"),"gemini-4-argon","2026-10-15")
        self.assertAlmostEqual(cost["estimated_usd"],.0005)

    def test_missing_usage_is_not_assumed_to_be_paid_reservation(self):
        self.assertIsNone(usage_cost({},price_snapshot("gemini-4-argon"),"gemini-4-argon","2026-10-15"))

    def test_invalid_cache_count_does_not_make_cost_negative(self):
        with self.assertRaises(ValueError):
            usage_cost({"promptTokenCount":10,"cachedContentTokenCount":11},price_snapshot("gemini-4-argon"),"gemini-4-argon","2026-10-15")

    def test_legacy_snapshot_preserves_rates_and_recognizes_cache(self):
        old={"base":[2,10],"long":[2,10],"long_input_threshold":200000}
        cost=usage_cost({"promptTokenCount":100,"cachedContentTokenCount":80},old,"gemini-4-argon","2026-10-15")
        self.assertAlmostEqual(cost["estimated_usd"],.000048)

    def test_pro_long_context_keeps_batch_rates_without_inventing_cache_discount(self):
        cost=usage_cost({"promptTokenCount":200001,"cachedContentTokenCount":100000,"candidatesTokenCount":1000},price_snapshot("gemini-3.1-pro-preview"),"gemini-3.1-pro-preview","2026-10-15")
        self.assertAlmostEqual(cost["estimated_usd"],.409002)
        self.assertEqual(cost["estimated_usd"],cost["promotional_estimated_usd"])

    def test_batch_null_padding_is_not_a_corrupt_usage_counter(self):
        cost=usage_cost({"promptTokenCount":100,"cachedContentTokenCount":None,"candidatesTokenCount":20,"thoughtsTokenCount":None},price_snapshot("gemini-4-argon"),"gemini-4-argon","2026-10-15")
        self.assertAlmostEqual(cost["estimated_usd"],.0004)
        self.assertIsNone(usage_cost({"promptTokenCount":None},price_snapshot("gemini-4-argon"),"gemini-4-argon","2026-10-15"))
