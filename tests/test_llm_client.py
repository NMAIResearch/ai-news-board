"""Offline regressions for the labelling client's model call."""

import io
import json
import unittest
from unittest.mock import patch

import llm_client


class LabelCallTests(unittest.TestCase):
    def test_call_disables_thinking_and_keeps_its_options(self):
        with patch.object(llm_client.urllib.request, 'urlopen',
                          return_value=io.BytesIO(b'{"response": "[]"}')) as call:
            self.assertEqual(llm_client.call('x'), '[]')
        payload = json.loads(call.call_args.args[0].data)
        self.assertIs(payload['think'], False)
        self.assertIs(payload['stream'], False)
        self.assertEqual(payload['options'], {'num_ctx': llm_client.NUM_CTX, 'temperature': 0.1,
                                              'num_predict': llm_client.NUM_PREDICT})
        self.assertEqual(call.call_args.kwargs['timeout'], llm_client.TIMEOUT)


if __name__ == '__main__':
    unittest.main()
