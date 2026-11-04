"""Execute generated market refresh JavaScript with local DOM and fetch stubs."""

import contextlib
import io
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import build


NODE = shutil.which("node")
DOM_HARNESS = r"""
const fs = require('fs');
const vm = require('vm');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
function cell(attributes) {
  const fields = {};
  for (const name of ['mktval', 'mktpct', 'mktvintage', 'mktcarried']) {
    fields['.' + name] = {textContent: 'old', style: {},
      setAttribute(key, value) { this[key] = value; }};
  }
  return {
    attributes, fields,
    classList: {contains(name) { return (attributes.class || '').split(' ').includes(name); }},
    getAttribute(name) { return attributes[name] || null; },
    setAttribute(name, value) { attributes[name] = value; },
    querySelector(selector) { return fields[selector] || null; },
  };
}
const indices = [cell({'data-mkt-idx': 'spx'}), cell({'data-mkt-idx': 'other'})];
const equities = [cell({'data-mkt': 'TEST'}), cell({'data-mkt': 'ABSENT'}),
  cell({'data-mkt': 'TEST', class: 'mktchip', 'data-mkt-note': 'Context note',
    title: 'TEST 100.00 as of 2026-11-02; Context note. Market context only: no causal link to this item is asserted.'})];
const reference = {textContent: '2026-11-02'};
let interval, current = 0;
const context = {
  document: {
    getElementById(id) { return id === 'mktstrip' ? {} : id === 'mktidxasof' ? reference : null; },
    querySelectorAll(selector) {
      return selector === '[data-mkt-idx]' ? indices : selector === '[data-mkt]' ? equities : [];
    },
  },
  fetch: async () => ({ok: input.payloads[current] !== null,
    json: async () => input.payloads[current]}),
  setInterval(callback) { interval = callback; },
};
function snapshot() {
  function read(el) {
    return {attributes: {...el.attributes}, value: el.fields['.mktval'].textContent,
      percentage: el.fields['.mktpct'].textContent,
      vintage: el.fields['.mktvintage'].textContent,
      vintageTitle: el.fields['.mktvintage'].title || '',
      carried: el.fields['.mktcarried'].textContent};
  }
  return {reference: reference.textContent, indices: indices.map(read), equities: equities.map(read)};
}
(async () => {
  vm.runInNewContext(input.script, context);
  const result = [];
  for (current = 0; current < input.payloads.length; current++) {
    if (current) interval();
    await new Promise(resolve => setImmediate(resolve));
    result.push(snapshot());
  }
  process.stdout.write(JSON.stringify(result));
})().catch(error => { console.error(error); process.exitCode = 1; });
"""


def market_script(page):
    return re.search(r'\(function \(\) \{\n  var NEG = .*?\}\)\(\);', page, re.S).group()


def refresh_market(script, payloads):
    result = subprocess.run(
        [NODE, "-e", DOM_HARNESS],
        input=json.dumps({"script": script, "payloads": payloads}),
        capture_output=True, text=True, check=True, timeout=10,
    )
    return json.loads(result.stdout)


@unittest.skipUnless(NODE, "Node.js is required to execute client refresh tests")
class MarketRefreshTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "index.html"
            with patch.object(build, "OUT", str(output)), patch("sys.argv", ["build.py"]), \
                    contextlib.redirect_stdout(io.StringIO()):
                build.main()
            cls.script = market_script(output.read_text())

    def payload(self, index_date="2026-11-03", equity_date="2026-11-04", stale=False):
        return {"indices": {"spx": {"value": 6000, "change_pct": 0.5, "asof": index_date}},
                "equities": {"TEST": {"value": 110, "change_pct": 10,
                                      "asof": equity_date, "stale": stale}}}

    def test_newer_equity_sets_reference_and_updates_older_index_marker(self):
        result = refresh_market(self.script, [self.payload()])[0]
        self.assertEqual(result["reference"], "2026-11-04")
        self.assertEqual(result["indices"][0]["vintage"], " 11-03")
        self.assertIn("2026-11-04", result["indices"][0]["vintageTitle"])
        self.assertEqual(result["equities"][0]["vintage"], "")
        self.assertEqual(result["equities"][0]["value"], "110.00")
        self.assertEqual(result["equities"][0]["percentage"], "+10.00%")
        self.assertEqual(result["equities"][1]["value"], "old")

    def test_newer_other_index_sets_reference_without_spx(self):
        payload = self.payload()
        payload["indices"] = {"other": {"value": 7000, "change_pct": -3, "asof": "2026-11-05"}}
        result = refresh_market(self.script, [payload])[0]
        self.assertEqual(result["reference"], "2026-11-05")
        self.assertEqual(result["indices"][1]["vintage"], "")
        self.assertEqual(result["equities"][0]["vintage"], " 11-04")

    def test_subsequent_refresh_clears_old_dates_and_carried_forward_state(self):
        first = self.payload(stale=True)
        second = self.payload(index_date="2026-11-05", equity_date="2026-11-05")
        old, new = refresh_market(self.script, [first, second])
        self.assertIn("previous close carried forward", old["equities"][2]["carried"])
        self.assertEqual(new["reference"], "2026-11-05")
        self.assertEqual(new["indices"][0]["vintage"], "")
        self.assertEqual(new["indices"][0]["vintageTitle"], "")
        self.assertEqual(new["equities"][2]["carried"], "")
        self.assertIn("TEST 110.00 as of 2026-11-05; Context note.",
                      new["equities"][2]["attributes"]["title"])
        self.assertIn("no causal link", new["equities"][2]["attributes"]["title"])

    def test_missing_dates_and_failed_fetch_do_not_invent_freshness(self):
        payload = self.payload(index_date="", equity_date="")
        unavailable, unchanged = refresh_market(self.script, [payload, None])
        self.assertEqual(unavailable["reference"], "")
        self.assertEqual(unavailable["indices"][0]["vintage"], "")
        self.assertEqual(unavailable, unchanged)


class MarketMarkerTests(unittest.TestCase):
    def test_date_marker_exists_for_both_fresh_and_older_strip_cells(self):
        for date in ("2026-11-03", "2026-11-04", ""):
            with self.subTest(date=date):
                marker = build._vintage({"asof": date}, "2026-11-04")
                self.assertIn('class="mktvintage"', marker)
                self.assertEqual(" 11-03" in marker, date == "2026-11-03")

    def test_chip_has_carried_forward_marker_even_for_a_fresh_quote(self):
        for stale in (False, True):
            with self.subTest(stale=stale):
                chip = build.market_chip("Example", {"equities": {"TEST": {
                    "value": 100, "asof": "2026-11-03", "change_pct": 0, "stale": stale,
                }}}, {"Example": {"ticker": "TEST", "note": "Context note"}})
                self.assertIn('class="mktcarried"', chip)
                self.assertIn('data-mkt-note="Context note"', chip)
                self.assertEqual("previous close carried forward" in chip, stale)


if __name__ == "__main__":
    unittest.main()
