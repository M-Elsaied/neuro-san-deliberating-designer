# Copyright © 2025-2026 Cognizant Technology Solutions Corp, www.cognizant.com.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# END COPYRIGHT

from unittest import TestCase

from coded_tools.agent_network_designer.interview_navigator import InterviewNavigator
from coded_tools.agent_network_designer.interview_outcome import InterviewOutcome
from coded_tools.agent_network_designer.interview_recorder import InterviewRecorder
from coded_tools.agent_network_designer.interview_renderer import InterviewRenderer
from coded_tools.agent_network_designer.interview_state import InterviewState
from tests.coded_tools.agent_network_designer.interview_fixtures import InterviewFixtures


class TestInterviewNavigator(TestCase):
    """
    Tests for InterviewNavigator.
    """

    FURTHER: str = "That is further back than the first question, so this is the first one."

    def setUp(self) -> None:
        """Answer the first three questions, so the fourth is on screen."""
        self.state: InterviewState = InterviewFixtures.play("3", "1", "1").state

    def test_each_way_of_naming_an_entry_lands_on_it(self) -> None:
        """A bare request, a count clamped to the first, a label, a number, a topic, or the start by name."""
        cases: dict[str, tuple[str, str]] = {
            "": ("Q3", ""),
            "wait, go back": ("Q3", ""),
            "back two": ("Q2", ""),
            "back 3": ("Q1", ""),
            "back ten": ("Q1", self.FURTHER),
            "Q2": ("Q2", ""),
            "question 1": ("Q1", ""),
            "change the window": ("Q2", ""),
            "the rman one": ("Q3", ""),
            "take me back to the first question": ("Q1", ""),
        }
        for target, (label, note) in cases.items():
            with self.subTest(target=target):
                outcome: InterviewOutcome = InterviewNavigator.go_back(self.state, target)
                self.assertEqual(
                    (InterviewOutcome.REOPENED, label, note),
                    (outcome.status, outcome.state.current.label, outcome.note),
                )
        reopened: str = InterviewNavigator.go_back(self.state, "Q1").prompt
        self.assertTrue(reopened.startswith("Here is what I have on file:\n\nQ1. Approval - Email\nQ2. Window"))
        self.assertIn("\n\nBack to Q1.\nApproval: who approves the change?\n", reopened)
        self.assertIn("  3. Email (currently on file)\n", reopened)

    def test_a_request_naming_no_single_entry_is_asked_about_not_guessed(self) -> None:
        """Picking for the user turns a correction into a different wrong answer."""
        cases: dict[str, tuple[str, str]] = {
            "Q9": (InterviewOutcome.UNKNOWN, "asked for entry 9 of 4"),
            "the weather": (InterviewOutcome.UNKNOWN, "no entry matched"),
            "change the backup or the window": (InterviewOutcome.CHOOSE, "2 entries matched"),
            "back three - I got the window wrong": (InterviewOutcome.CHOOSE, "the count and the subject disagree"),
        }
        for target, (status, note) in cases.items():
            with self.subTest(target=target):
                outcome: InterviewOutcome = InterviewNavigator.go_back(self.state, target)
                self.assertEqual((status, note, self.state), (outcome.status, outcome.note, outcome.state))

    def test_a_correction_keeps_every_other_answer_and_reaches_the_brief(self) -> None:
        """A mistyped answer costs one turn: nothing in between is asked again, and the brief has the new value."""
        corrected: InterviewOutcome = InterviewRecorder.record(InterviewNavigator.go_back(self.state, "Q1").state, "1")
        self.assertEqual("Q4", corrected.state.current.label)
        self.assertEqual(
            "Approval: ServiceNow CR approved by the CAB", InterviewRenderer.get_brief_lines(corrected.state, False)[0]
        )
        self.assertEqual("Window: Saturday night", InterviewRenderer.get_brief_lines(corrected.state, False)[1])
