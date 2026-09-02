import json
import unittest

from services.auto_apply_submission.application_answer_memory_service import (
    answer_is_compatible,
    normalize_memory_match_text,
)
from services.auto_apply_submission.application_question_service import (
    load_question_state,
)


class ApplicationQuestionTests(unittest.TestCase):
    @staticmethod
    def choice_list(count):
        return [
            {
                "value": str(index),
                "label": str(index),
            }
            for index in range(count)
        ]

    def test_large_legacy_checkbox_list_becomes_multiselect(self):
        state = load_question_state(
            json.dumps({
                "questions": [
                    {
                        "key": "nationality",
                        "type": "checkbox",
                        "choices": self.choice_list(25),
                    }
                ],
                "answers": {},
            })
        )

        self.assertEqual(
            state["questions"][0]["type"],
            "multiselect",
        )

    def test_small_checkbox_group_remains_checkbox(self):
        state = load_question_state(
            json.dumps({
                "questions": [
                    {
                        "key": "availability",
                        "type": "checkbox",
                        "choices": self.choice_list(3),
                    }
                ],
                "answers": {},
            })
        )

        self.assertEqual(
            state["questions"][0]["type"],
            "checkbox",
        )

    def test_multiselect_memory_accepts_multiple_valid_answers(self):
        question = {
            "type": "multiselect",
            "choices": self.choice_list(4),
        }

        self.assertTrue(
            answer_is_compatible(
                question,
                ["1", "3"],
            )
        )
        self.assertFalse(
            answer_is_compatible(
                question,
                ["1", "missing"],
            )
        )

    def test_remembered_question_matching_ignores_form_punctuation(self):
        self.assertEqual(
            normalize_memory_match_text(
                "Preferred First Name: *"
            ),
            normalize_memory_match_text(
                "Preferred First Name"
            ),
        )


if __name__ == "__main__":
    unittest.main()
