"""Regression tests for upcoming and announced models register."""

import json
import os
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UPCOMING_PATH = os.path.join(HERE, "upcoming_models.json")


class UpcomingModelsTests(unittest.TestCase):
    def test_upcoming_models_file_exists(self):
        self.assertTrue(os.path.isfile(UPCOMING_PATH), "upcoming_models.json must exist")

    def test_upcoming_models_schema(self):
        with open(UPCOMING_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)

        self.assertIn("updated_at", data)
        self.assertIn("disclosure", data)
        self.assertIn("upcoming", data)
        self.assertIsInstance(data["upcoming"], list)
        self.assertGreater(len(data["upcoming"]), 0)

        valid_statuses = {"announced_unshipped", "access_restricted", "target_delayed", "in_training", "announced"}

        for item in data["upcoming"]:
            self.assertIn("lab", item)
            self.assertIn("model", item)
            self.assertIn("announced_date", item)
            self.assertIn("target_window", item)
            self.assertIn("status", item)
            self.assertIn(item["status"], valid_statuses, f"Invalid status: {item['status']}")
            self.assertIn("url", item)
            self.assertTrue(item["url"].startswith("http"), f"Invalid URL: {item['url']}")
