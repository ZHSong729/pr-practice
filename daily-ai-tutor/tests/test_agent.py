import json
import sys
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import agent  # noqa: E402


class PickLessonTest(unittest.TestCase):
    def setUp(self):
        self.curriculum = agent.load_json(agent.CURRICULUM_PATH)
        self.lessons = self.curriculum["lessons"]

    def test_first_day_starts_at_first_lesson(self):
        lesson, previous = agent.pick_lesson(self.curriculum, {"history": []})
        self.assertEqual(lesson["id"], self.lessons[0]["id"])
        self.assertIsNone(previous)

    def test_next_day_moves_on_and_reviews_previous(self):
        progress = {"history": [{"date": "2026-10-20", "lesson_id": self.lessons[0]["id"]}]}
        lesson, previous = agent.pick_lesson(self.curriculum, progress)
        self.assertEqual(lesson["id"], self.lessons[1]["id"])
        self.assertEqual(previous["id"], self.lessons[0]["id"])

    def test_restarts_after_curriculum_is_finished(self):
        history = [{"date": f"d{i}", "lesson_id": l["id"]} for i, l in enumerate(self.lessons)]
        lesson, _ = agent.pick_lesson(self.curriculum, {"history": history})
        self.assertEqual(lesson["id"], self.lessons[0]["id"])

    def test_lesson_ids_are_unique(self):
        ids = [l["id"] for l in self.lessons]
        self.assertEqual(len(ids), len(set(ids)))


class BuildPromptTest(unittest.TestCase):
    def test_prompt_contains_lesson_and_sections(self):
        config = agent.load_json(agent.CONFIG_PATH)
        lesson = {"id": "x", "track": "ML 기초 이론", "title": "테스트 주제"}
        prompt = agent.build_prompt(config, lesson, None, datetime(2026, 10, 20, tzinfo=agent.KST))
        self.assertIn("테스트 주제", prompt)
        self.assertIn("2026-10-20", prompt)
        for section in ("오늘의 개념", "이번 주 AI 소식", "확인 퀴즈", "검증 메모", "출처"):
            self.assertIn(section, prompt)


class ConfigTest(unittest.TestCase):
    def test_config_is_valid_json_with_required_keys(self):
        config = json.loads(agent.CONFIG_PATH.read_text(encoding="utf-8"))
        for key in ("learner", "model", "effort", "news_items", "news_window_days", "max_web_searches"):
            self.assertIn(key, config)


if __name__ == "__main__":
    unittest.main()
