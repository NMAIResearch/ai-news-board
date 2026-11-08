"""Regression tests for the audio and video release section of fetch_releases.py.

Every name in here was read off a maker's own Hugging Face organisation list on 2026-11-08,
so these tests pin what the section did rather than what it was hoped to do. Two faults found
by reading the rows of a print-only run have a test each: 16 of 34 rows were LTX control
adapters, and one Stable Audio 3 launch arrived as 7 repositories over three days.

No network and no file write: av_kind_of, av_base_of, av_rows_from_hf, av_fold, av_counts_of
and payload_of take data and return data.
"""

import os
import unittest
from datetime import datetime, timezone

import fetch_releases as fr

# 180 days before 2026-11-08, the window the section ran with when these rows were measured.
CUTOFF = datetime(2026, 5, 12, tzinfo=timezone.utc)


def hf(mid, created):
    """One entry shaped like the Hugging Face models API returns it."""
    return {"id": mid, "createdAt": f"{created}T00:00:00.000Z"}


class AvKindTests(unittest.TestCase):
    def test_video_names_measured_on_the_makers_own_lists(self):
        for name in ("LTX-2-Marking", "LTX-2.5-Pre-Trained", "Wan2.2-Animate-2-14B",
                     "Wan-Dancer-14B", "mochi-1-preview", "Wan2.2-I2V-A14B",
                     # Joined to the next word with no separator, which the boundary rule
                     # alone cannot see:
                     "HunyuanVideo-Avatar", "CogVideoX-5b", "LTXVideo-13b"):
            self.assertEqual(fr.av_kind_of(name), "video", name)

    def test_audio_names_measured_on_the_makers_own_lists(self):
        for name in ("MiniMax-Music3", "stable-audio-3-optimized", "stable-audio-3-medium",
                     "acestep-v15-xl-base-diffusers", "riffusion-model-v1", "bark-small"):
            self.assertEqual(fr.av_kind_of(name), "audio", name)

    def test_text_and_vision_releases_from_the_same_makers_are_neither(self):
        for name in ("MiniMax-M3.1-Flash", "WeVisOne-VL-4B", "sdxl-base-amdnpu-medusa",
                     "Qwen3.8-27B-DSpine-b16", "granite-switch-4.1-8b-GGUF"):
            self.assertIsNone(fr.av_kind_of(name), name)

    def test_a_word_inside_another_word_does_not_match(self):
        # The boundary each side is the whole point. In a comparable check on 2026-11-08 a
        # plain substring test counted "elo" 2,376 times inside words such as "below".
        for name in ("swan-lake", "barking-dog", "sorabella", "unvoiced"):
            self.assertIsNone(fr.av_kind_of(name), name)

    def test_video_wins_when_a_name_carries_both(self):
        self.assertEqual(fr.av_kind_of("LTX-2.5-audio-ref"), "video")


class AvBaseTests(unittest.TestCase):
    def test_a_packaging_copy_shares_its_releases_base(self):
        self.assertEqual(fr.av_base_of("LTX-2.5-Diffusers"), fr.av_base_of("LTX-2.5"))
        self.assertEqual(fr.av_base_of("Wan2.2-Animate-2-14B-Distilled-Diffusers"),
                         fr.av_base_of("Wan2.2-Animate-2-14B"))

    def test_a_pretrained_base_twin_shares_its_releases_base(self):
        self.assertEqual(fr.av_base_of("stable-audio-3-medium-base"),
                         fr.av_base_of("stable-audio-3-medium"))

    def test_a_size_or_purpose_variant_keeps_its_own_base(self):
        self.assertNotEqual(fr.av_base_of("stable-audio-3-small-music"),
                            fr.av_base_of("stable-audio-3-small-sfx"))
        self.assertNotEqual(fr.av_base_of("stable-audio-3-medium"),
                            fr.av_base_of("stable-audio-3-small-sfx"))

    def test_a_name_of_nothing_but_fold_words_keeps_its_name(self):
        self.assertEqual(fr.av_base_of("Diffusers"), "diffusers")
        self.assertEqual(fr.av_base_of(""), "")


class AvRowsTests(unittest.TestCase):
    def test_a_row_carries_the_keys_the_payload_and_the_page_need(self):
        rows = fr.av_rows_from_hf([hf("Lightricks/LTX-2.5", "2026-07-23")],
                                  "Lightricks", "Lightricks")
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["kind"], "video")
        self.assertEqual(row["lab"], "Lightricks")
        self.assertEqual(row["model"], "LTX-2.5")
        self.assertEqual(row["date"], "2026-07-23")
        self.assertEqual(row["hf_id"], "Lightricks/LTX-2.5")
        self.assertEqual(row["url"], "https://huggingface.co/Lightricks/LTX-2.5")
        self.assertEqual(row["evidence"], "open-weights")
        self.assertIn("repo creation", row["source"])
        # The fold adds `folded`; the row builder must not, or a count of copies would be
        # carried by rows that were never folded.
        self.assertNotIn("folded", row)

    def test_the_row_builder_does_not_apply_the_window(self):
        # genmo/mochi-1-preview is real and outside 180 days: 2024-10-22. The row is built
        # here and dropped by av_in_window after the fold, never before it.
        rows = fr.av_rows_from_hf([hf("genmo/mochi-1-preview", "2024-10-22")],
                                  "genmo", "Genmo")
        self.assertEqual([r["date"] for r in rows], ["2024-10-22"])
        self.assertEqual(fr.av_in_window(rows, CUTOFF), [])

    def test_a_control_adapter_is_dropped_and_the_engine_is_kept(self):
        data = [hf("Lightricks/LTX-2.5-22b-IC-LoRA-Deblur", "2026-10-01"),
                hf("Lightricks/LTX-2.5-22b-IC-LoRA-Colorization", "2026-10-01"),
                hf("Lightricks/LTX-2.5", "2026-07-23")]
        rows = fr.av_rows_from_hf(data, "Lightricks", "Lightricks")
        self.assertEqual([r["model"] for r in rows], ["LTX-2.5"])

    def test_a_text_model_from_a_watched_maker_is_dropped(self):
        rows = fr.av_rows_from_hf([hf("MiniMaxAI/MiniMax-M3.1-Flash", "2026-10-19")],
                                  "MiniMaxAI", "MiniMax")
        self.assertEqual(rows, [])

    def test_an_empty_organisation_list_gives_no_rows(self):
        # Mureka's and ElevenLabs' lists each answered 200 with a 2-byte body on 2026-11-08.
        self.assertEqual(fr.av_rows_from_hf([], "mureka", "Mureka"), [])

    def test_a_payload_that_is_not_a_list_gives_no_rows(self):
        self.assertEqual(fr.av_rows_from_hf({"error": "nope"}, "suno", "Suno"), [])

    def test_an_entry_with_no_usable_date_is_dropped(self):
        self.assertEqual(fr.av_rows_from_hf([{"id": "suno/bark"}], "suno", "Suno"), [])
        self.assertEqual(fr.av_rows_from_hf(["suno/bark"], "suno", "Suno"), [])


class AvWindowTests(unittest.TestCase):
    """The window runs after the fold, which is what keeps a copy's date out of the section."""

    def test_a_release_inside_the_window_is_kept_and_one_outside_is_dropped(self):
        rows = [{"date": "2026-07-23", "model": "LTX-2.5"},
                {"date": "2024-10-22", "model": "mochi-1-preview"}]
        self.assertEqual([r["model"] for r in fr.av_in_window(rows, CUTOFF)], ["LTX-2.5"])

    def test_a_row_with_an_unreadable_date_is_dropped(self):
        self.assertEqual(fr.av_in_window([{"date": "soon"}, {}], CUTOFF), [])

    def test_a_copy_inside_the_window_does_not_publish_a_release_outside_it(self):
        # ACE Studio, measured 2026-11-08: the Diffusers copies are of 2026-06-01, inside the
        # window, and the releases they package are of 2026-04-02, outside it. Folding first
        # means the release's own date decides, so neither is published.
        data = [hf("ACE-Step/acestep-v15-xl-base-diffusers", "2026-06-01"),
                hf("ACE-Step/acestep-v15-xl-base", "2026-04-02")]
        rows = fr.av_rows_from_hf(data, "ACE-Step", "ACE Studio")
        folded = fr.av_fold(rows)
        self.assertEqual([r["model"] for r in folded], ["acestep-v15-xl-base"])
        self.assertEqual(folded[0]["folded"], 1)
        self.assertEqual(fr.av_in_window(folded, CUTOFF), [])

    def test_windowing_before_folding_would_have_published_the_copy(self):
        # The fault this order fixes, stated as a test so the order cannot be swapped back.
        data = [hf("ACE-Step/acestep-v15-xl-base-diffusers", "2026-06-01"),
                hf("ACE-Step/acestep-v15-xl-base", "2026-04-02")]
        rows = fr.av_rows_from_hf(data, "ACE-Step", "ACE Studio")
        wrong_order = fr.av_fold(fr.av_in_window(rows, CUTOFF))
        self.assertEqual([r["model"] for r in wrong_order],
                         ["acestep-v15-xl-base-diffusers"])
        self.assertEqual(fr.av_in_window(fr.av_fold(rows), CUTOFF), [])


class AvFoldTests(unittest.TestCase):
    @staticmethod
    def rows(*quads):
        return [{"lab": lab, "model": model, "date": date, "kind": kind}
                for lab, model, date, kind in quads]

    def test_a_diffusers_copy_folds_into_the_earliest_row(self):
        out = fr.av_fold(self.rows(("Lightricks", "LTX-2.5-Diffusers", "2026-07-26", "video"),
                                   ("Lightricks", "LTX-2.5", "2026-07-23", "video")))
        self.assertEqual([r["model"] for r in out], ["LTX-2.5"])
        self.assertEqual(out[0]["date"], "2026-07-23")
        self.assertEqual(out[0]["folded"], 1)

    def test_two_copies_fold_into_one_row_and_are_counted(self):
        out = fr.av_fold(self.rows(
            ("Alibaba (Wan)", "Wan2.2-Animate-2-14B-Distilled-Diffusers", "2026-08-06",
             "video"),
            ("Alibaba (Wan)", "Wan2.2-Animate-2-14B-Diffusers", "2026-08-06", "video"),
            ("Alibaba (Wan)", "Wan2.2-Animate-2-14B", "2026-07-14", "video")))
        self.assertEqual([r["model"] for r in out], ["Wan2.2-Animate-2-14B"])
        self.assertEqual(out[0]["folded"], 2)

    def test_a_size_or_purpose_variant_keeps_its_own_row(self):
        out = fr.av_fold(self.rows(
            ("Stability AI", "stable-audio-3-medium", "2026-05-17", "audio"),
            ("Stability AI", "stable-audio-3-small-sfx", "2026-05-17", "audio")))
        self.assertEqual(len(out), 2)
        self.assertEqual([r["folded"] for r in out], [0, 0])

    def test_a_same_day_tie_keeps_the_plainer_name(self):
        out = fr.av_fold(self.rows(
            ("Stability AI", "stable-audio-3-medium-base", "2026-05-17", "audio"),
            ("Stability AI", "stable-audio-3-medium", "2026-05-17", "audio")))
        self.assertEqual([r["model"] for r in out], ["stable-audio-3-medium"])
        self.assertEqual(out[0]["folded"], 1)

    def test_the_same_name_from_two_labs_does_not_fold(self):
        out = fr.av_fold(self.rows(("Stability AI", "stable-audio-3", "2026-05-17", "audio"),
                                   ("MiniMax", "stable-audio-3", "2026-05-17", "audio")))
        self.assertEqual(len(out), 2)

    def test_rows_come_back_newest_first(self):
        out = fr.av_fold(self.rows(("MiniMax", "MiniMax-Music3", "2026-08-07", "audio"),
                                   ("Lightricks", "LTX-2-Marking", "2026-10-28", "video")))
        self.assertEqual([r["date"] for r in out], ["2026-10-28", "2026-08-07"])

    def test_no_rows_fold_to_no_rows(self):
        self.assertEqual(fr.av_fold([]), [])


class AvCountsTests(unittest.TestCase):
    def test_counts_separate_audio_video_labs_and_folded(self):
        rows = [{"kind": "audio", "lab": "Stability AI", "folded": 2},
                {"kind": "audio", "lab": "MiniMax", "folded": 0},
                {"kind": "video", "lab": "Lightricks", "folded": 1}]
        counts = fr.av_counts_of(rows)
        self.assertEqual(counts["total"], 3)
        self.assertEqual(counts["audio"], 2)
        self.assertEqual(counts["video"], 1)
        self.assertEqual(counts["folded"], 3)
        self.assertEqual(counts["labs"], 3)
        self.assertEqual(counts["orgs_watched"], len(fr.AV_ORGS))

    def test_the_makers_with_a_row_are_not_the_makers_watched(self):
        # The page must not say "from 11 makers" above rows from one.
        counts = fr.av_counts_of([{"kind": "audio", "lab": "Stability AI", "folded": 0}])
        self.assertEqual(counts["labs"], 1)
        self.assertGreater(counts["orgs_watched"], counts["labs"])


class AvPayloadTests(unittest.TestCase):
    @staticmethod
    def payload():
        releases = [{"lab": "OpenAI", "model": "GPT-6.1 Terra", "date": "2026-10-26",
                     "evidence": "closed"}]
        av = [{"kind": "audio", "lab": "MiniMax", "model": "MiniMax-Music3",
               "date": "2026-08-07", "folded": 0}]
        return fr.payload_of(releases, av, [], generated="2026-11-08 14:00 UTC")

    def test_the_two_sides_stay_separate_keys_with_separate_windows(self):
        payload = self.payload()
        self.assertEqual(payload["counts"]["total"], 1)
        self.assertEqual(payload["av_counts"]["total"], 1)
        self.assertEqual(payload["window_days"], fr.MAX_AGE_DAYS)
        self.assertEqual(payload["av_window_days"], fr.AV_WINDOW_DAYS)
        self.assertNotEqual(payload["window_days"], payload["av_window_days"])
        self.assertEqual(payload["av_releases"][0]["model"], "MiniMax-Music3")

    def test_the_section_carries_its_own_dated_limit_statement(self):
        payload = self.payload()
        self.assertEqual(len(payload["av_no_route"]), 4)
        for entry in payload["av_no_route"]:
            self.assertIn("maker", entry)
            self.assertIn("note", entry)
            self.assertIn("checked", entry)
        self.assertIn("180 days", payload["av_disclosure"])
        self.assertIn("Suno", payload["av_disclosure"])

    def test_no_row_key_names_a_score(self):
        # The board's own rule for this file: no benchmark scores, ever.
        for row in self.payload()["av_releases"]:
            for key in row:
                for word in ("score", "elo", "rating", "rank"):
                    self.assertNotIn(word, key.lower())

    def test_the_generated_stamp_is_passed_through(self):
        self.assertEqual(self.payload()["generated"], "2026-11-08 14:00 UTC")


class AvDesignTests(unittest.TestCase):
    def test_the_window_the_cap_and_the_maker_list_are_the_measured_ones(self):
        if os.environ.get("AV_RELEASE_MAX_AGE_DAYS"):
            self.skipTest("window overridden by AV_RELEASE_MAX_AGE_DAYS")
        self.assertEqual(fr.AV_WINDOW_DAYS, 180)
        self.assertEqual(fr.AV_LIMIT, 20)
        self.assertEqual(len(fr.AV_ORGS), 11)
        self.assertEqual(len({org for org, _ in fr.AV_ORGS}), 11)


if __name__ == "__main__":
    unittest.main()
