"""Offline regressions for model transport and response validation."""

import io
import json
import unittest
import urllib.error
from unittest.mock import patch

import sovereign_watch as sw


class ModelResponseTests(unittest.TestCase):
    def test_runtime_options_disable_thinking_and_bound_generation(self):
        with patch.object(sw.urllib.request, 'urlopen', return_value=io.BytesIO(b'{}')) as call:
            self.analyse()
        payload = json.loads(call.call_args.args[0].data)
        self.assertIs(payload['think'], False)
        self.assertEqual(payload['options']['num_ctx'], 16384)
        self.assertEqual(payload['options']['num_predict'], 1024)
        self.assertEqual(call.call_args.kwargs['timeout'], 90)

    def test_oversized_prompt_never_reaches_model(self):
        with patch.object(sw.urllib.request, 'urlopen') as call:
            with self.assertRaisesRegex(sw.ModelCallError, 'manual review required'):
                sw.call_local_model('x' * (16384 - 1024 - 512 + 1))
            call.assert_not_called()

    def test_token_limited_response_remains_unassessed(self):
        body = json.dumps({'message': {'content': '{}'}, 'done_reason': 'length'}).encode()
        with patch.object(sw.urllib.request, 'urlopen', return_value=io.BytesIO(body)):
            self.assertEqual(self.analyse()['assessment_error'], 'model output token limit reached')

    def analyse(self):
        return sw.analyze_item_with_model(
            "Fixture", "", "Fixture feed", "https://example.test/doc",
            model="fixture", source_text="A sufficiently long captured source passage.")

    def test_timeout_is_not_a_schema_failure(self):
        with patch.object(sw.urllib.request, "urlopen", side_effect=TimeoutError()):
            result = self.analyse()
        self.assertIn("timeout", result["assessment_error"])
        self.assertEqual(result["evaluation_method"], "unassessed")
        self.assertIsNone(result["priority_score"])
        self.assertFalse(result["reviewed"])

    def test_wrapped_timeout_is_not_a_schema_failure(self):
        with patch.object(sw.urllib.request, "urlopen",
                          side_effect=urllib.error.URLError(TimeoutError())):
            result = self.analyse()
        self.assertIn("timeout", result["assessment_error"])

    def test_http_failure_has_no_response_body_or_address(self):
        error = urllib.error.HTTPError("http://private-host/api/chat", 503,
                                       "secret response", {}, io.BytesIO(b"private"))
        self.addCleanup(error.close)
        with patch.object(sw.urllib.request, "urlopen", side_effect=error):
            result = self.analyse()
        self.assertEqual(result["assessment_error"], "model HTTP status 503")

    def test_response_format_is_schema_constrained(self):
        with patch.object(sw.urllib.request, "urlopen",
                          return_value=io.BytesIO(b'{"message":{"content":"{}"}}')) as request:
            result = self.analyse()
        payload = json.loads(request.call_args.args[0].data)
        self.assertEqual(payload["format"]["type"], "object")
        self.assertIn("evidence_quote", payload["format"]["required"])
        self.assertFalse(payload["stream"])
        self.assertEqual(result["evaluation_method"], "unassessed")

    def test_bad_envelopes_remain_unassessed(self):
        for raw in [b"not JSON", b"[]", b'{"message":null}',
                    b'{"message":{"content":null}}',
                    b'{"message":{"content":"not JSON"}}']:
            with self.subTest(raw=raw), patch.object(sw.urllib.request, "urlopen",
                                                   return_value=io.BytesIO(raw)):
                result = self.analyse()
            self.assertEqual(result["evaluation_method"], "unassessed")
            self.assertIsNone(result["priority_score"])
            self.assertNotEqual(result["assessment_error"], "invalid model schema")

    def test_non_string_parser_input_is_rejected(self):
        for value in [None, [], {}, 5, True]:
            self.assertIsNone(sw.parse_llm_json_response(value))

    def test_invalid_enum_types_are_rejected(self):
        value = {"priority_score": 3, "is_operator_duty_shift": False,
                 "duty_type": [], "statutory_reference": None,
                 "quantitative_claim_present": False, "denominator_disclosed": "n/a",
                 "summary_finding": "Fixture", "actionable_trigger": "Review",
                 "document_status": "other", "ai_relevance": "uncertain",
                 "evidence_quote": "A sufficiently long captured source passage."}
        self.assertIsNone(sw.validate_model_analysis(value, "fixture"))

    def test_oversized_response_is_rejected(self):
        with patch.object(sw.urllib.request, "urlopen",
                          return_value=io.BytesIO(b"x" * (sw.MODEL_RESPONSE_LIMIT + 1))):
            self.assertEqual(self.analyse()["assessment_error"], "model response exceeds byte limit")

    def test_valid_response_and_schema_boundaries(self):
        value = {"priority_score": 4, "is_operator_duty_shift": False,
                 "duty_type": "none", "statutory_reference": None,
                 "quantitative_claim_present": False, "denominator_disclosed": "n/a",
                 "summary_finding": "Fixture", "actionable_trigger": "Review",
                 "document_status": "other", "ai_relevance": "uncertain",
                 "evidence_quote": "A sufficiently long captured source passage."}
        encoded = json.dumps({"message": {"content": json.dumps(value)}}).encode()
        with patch.object(sw.urllib.request, "urlopen", return_value=io.BytesIO(encoded)):
            result = self.analyse()
        self.assertEqual(result["evaluation_method"], "local-model")
        self.assertFalse(result["reviewed"])
        for field in value:
            invalid = dict(value)
            del invalid[field]
            with self.subTest(missing=field):
                self.assertIsNone(sw.validate_model_analysis(invalid, "fixture"))
        self.assertIsNone(sw.validate_model_analysis(dict(value, unexpected="field"), "fixture"))
        for field in value:
            with self.subTest(invalid_type=field):
                self.assertIsNone(sw.validate_model_analysis(dict(value, **{field: []}), "fixture"))
        value.update(duty_type="none", denominator_disclosed=[])
        self.assertIsNone(sw.validate_model_analysis(value, "fixture"))


if __name__ == "__main__":
    unittest.main()
