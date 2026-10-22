import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import coach  # noqa: E402

TODAY = date(2026, 10, 22)


def question(skill_id, answer_index=0):
    return {
        "skill_id": skill_id, "concept": f"{skill_id} 개념", "question": "?",
        "choices": ["a", "b", "c", "d"], "answer_index": answer_index, "explanation": "",
    }


class SkillMapTest(unittest.TestCase):
    def setUp(self):
        self.skills = coach.load_json(coach.SKILLS_PATH)["skills"]

    def test_ids_are_unique(self):
        ids = [s["id"] for s in self.skills]
        self.assertEqual(len(ids), len(set(ids)))

    def test_prereqs_come_earlier(self):
        seen = set()
        for skill in self.skills:
            for prereq in skill["prereqs"]:
                self.assertIn(prereq, seen, f"{skill['id']} needs {prereq} first")
            seen.add(skill["id"])


class PlanTest(unittest.TestCase):
    def setUp(self):
        self.skills = coach.load_json(coach.SKILLS_PATH)["skills"]

    def test_first_day_starts_at_first_skill(self):
        plan = coach.plan_today(self.skills, coach.new_state(), TODAY)
        self.assertEqual(plan["main"]["id"], self.skills[0]["id"])
        self.assertEqual(plan["mode"], "new")
        self.assertIsNone(plan["review"])

    def test_locked_skill_is_not_offered(self):
        state = coach.new_state()
        coach.update_skill(state, "ai-ml-dl", 0, 2, TODAY)  # failed: stays in box 1
        self.assertIsNone(coach.next_new_skill(self.skills, state))

    def test_passed_skill_unlocks_next_and_becomes_review(self):
        state = coach.new_state()
        coach.update_skill(state, "ai-ml-dl", 2, 2, TODAY)
        later = TODAY + timedelta(days=coach.REVIEW_INTERVALS[2])
        plan = coach.plan_today(self.skills, state, later)
        self.assertEqual(plan["main"]["id"], "llm-basics")
        self.assertEqual(plan["review"]["id"], "ai-ml-dl")

    def test_low_accuracy_reteaches_instead_of_new(self):
        state = coach.new_state()
        coach.update_skill(state, "ai-ml-dl", 2, 2, TODAY)
        coach.update_skill(state, "llm-basics", 0, 2, TODAY)
        state["sessions"] = [{"correct": 0, "total": 3}]
        plan = coach.plan_today(self.skills, state, TODAY + timedelta(days=1))
        self.assertEqual(plan["mode"], "reteach")
        self.assertEqual(plan["main"]["id"], "llm-basics")


class LeitnerTest(unittest.TestCase):
    def test_box_moves(self):
        state = coach.new_state()
        coach.update_skill(state, "x", 2, 2, TODAY)
        self.assertEqual(coach.skill_box(state, "x"), 2)
        coach.update_skill(state, "x", 1, 2, TODAY)  # half right: stay
        self.assertEqual(coach.skill_box(state, "x"), 2)
        coach.update_skill(state, "x", 0, 1, TODAY)  # wrong: back to box 1
        self.assertEqual(coach.skill_box(state, "x"), 1)
        self.assertEqual(state["skills"]["x"]["due"], (TODAY + timedelta(days=1)).isoformat())

    def test_box_is_capped(self):
        state = coach.new_state()
        for _ in range(10):
            coach.update_skill(state, "x", 1, 1, TODAY)
        self.assertEqual(coach.skill_box(state, "x"), coach.MAX_BOX)


class RecordResultsTest(unittest.TestCase):
    def test_records_session_and_weak_points(self):
        skills = coach.load_json(coach.SKILLS_PATH)["skills"]
        state = coach.new_state()
        plan = coach.plan_today(skills, state, TODAY)
        questions = [question("ai-ml-dl", 0), question("ai-ml-dl", 1)]
        correct = coach.record_results(state, plan, questions, [0, 0], TODAY)
        self.assertEqual(correct, 1)
        self.assertEqual(state["sessions"][-1]["total"], 2)
        self.assertEqual(state["weak_points"], [{"skill_id": "ai-ml-dl", "concept": "ai-ml-dl 개념"}])
        self.assertEqual(coach.skill_box(state, "ai-ml-dl"), 1)

    def test_weak_points_reach_the_next_lesson_prompt(self):
        skills = coach.load_json(coach.SKILLS_PATH)["skills"]
        profile = coach.load_json(coach.PROFILE_PATH)
        state = coach.new_state()
        state["weak_points"] = [{"skill_id": "ai-ml-dl", "concept": "딥러닝의 범위"}]
        plan = coach.plan_today(skills, state, TODAY)
        prompt = coach.build_lesson_prompt(profile, plan, state, TODAY)
        self.assertIn("딥러닝의 범위", prompt)


class FootnoteTest(unittest.TestCase):
    def test_reports_missing_and_unused(self):
        text = "사실 A[^1], 사실 B[^2].\n\n## 출처\n[^1]: 문서 - https://a\n[^3]: 문서 - https://c\n"
        missing, unused = coach.check_footnotes(text)
        self.assertEqual(missing, ["2"])
        self.assertEqual(unused, ["3"])


class QuizInputTest(unittest.TestCase):
    def test_retries_until_valid_number(self):
        replies = iter(["x", "9", "2"])
        self.assertEqual(coach.ask_choice(question("x"), ask=lambda _: next(replies)), 1)


class RoutineTest(unittest.TestCase):
    def setUp(self):
        self.skills = coach.load_json(coach.SKILLS_PATH)["skills"]
        self.profile = coach.load_json(coach.PROFILE_PATH)

    def quiz(self):
        return {
            "date": TODAY.isoformat(), "main": "llm-basics", "mode": "new", "review": "ai-ml-dl",
            "questions": [question("llm-basics", 0), question("llm-basics", 1), question("ai-ml-dl", 2)],
        }

    def test_plan_payload_has_writing_instructions(self):
        payload = coach.plan_payload(self.profile, self.skills, coach.new_state(), TODAY)
        self.assertEqual(payload["main"]["id"], "ai-ml-dl")
        self.assertIn(payload["main"]["title"], payload["lesson_prompt"])
        self.assertIn("ai-ml-dl", payload["quiz_instructions"])
        self.assertEqual(payload["quiz_schema"], coach.QUIZ_SCHEMA)

    def test_parse_answers(self):
        self.assertEqual(coach.parse_answers("답: 1, 3 2", 3), [0, 2, 1])
        with self.assertRaises(ValueError):
            coach.parse_answers("1 3", 3)

    def test_grade_quiz_updates_state_once(self):
        state = coach.new_state()
        coach.update_skill(state, "ai-ml-dl", 2, 2, TODAY - timedelta(days=3))
        quiz = self.quiz()
        result = coach.grade_quiz(self.skills, state, quiz, [0, 1, 0])
        self.assertEqual((result["correct"], result["total"]), (2, 3))
        self.assertFalse(result["results"][2]["ok"])
        self.assertEqual(coach.skill_box(state, "llm-basics"), 2)
        self.assertEqual(coach.skill_box(state, "ai-ml-dl"), 1)
        self.assertTrue(quiz["graded"])
        with self.assertRaises(ValueError):
            coach.grade_quiz(self.skills, state, quiz, [0, 1, 0])

    def test_grade_quiz_rejects_out_of_range_answer(self):
        with self.assertRaises(ValueError):
            coach.grade_quiz(self.skills, coach.new_state(), self.quiz(), [0, 1, 7])


if __name__ == "__main__":
    unittest.main()
