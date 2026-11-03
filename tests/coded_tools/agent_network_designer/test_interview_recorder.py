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

from typing import Any
from unittest import TestCase
from unittest import mock

from coded_tools.agent_network_designer.interview_entry import InterviewEntry
from coded_tools.agent_network_designer.interview_factory import InterviewFactory
from coded_tools.agent_network_designer.interview_options import InterviewOptions
from coded_tools.agent_network_designer.interview_outcome import InterviewOutcome
from coded_tools.agent_network_designer.interview_recorder import InterviewRecorder
from coded_tools.agent_network_designer.interview_renderer import InterviewRenderer
from coded_tools.agent_network_designer.interview_state import InterviewState
from coded_tools.agent_network_designer.model_reply_matcher import ModelReplyMatcher
from tests.coded_tools.agent_network_designer.interview_fixtures import InterviewFixtures


class TestInterviewRecorder(TestCase):
    """
    Tests for InterviewRecorder.
    """

    CAB: str = "ServiceNow CR approved by the CAB"
    DBA: str = "ServiceNow CR approved by the DBA lead"

    def test_a_number_a_quote_or_own_words_settle_the_question(self) -> None:
        """A number or quote records the option's own text; words matching nothing, including "4 hours", as given."""
        for reply, answer in {
            "2": self.DBA,
            "#2": self.DBA,
            self.DBA.lower(): self.DBA,
            " 4 hours ": "4 hours",
        }.items():
            with self.subTest(reply=reply):
                outcome: InterviewOutcome = InterviewFixtures.play(reply)
                self.assertEqual(
                    (InterviewOutcome.RECORDED, answer, "Q2"),
                    (outcome.status, outcome.state.entries[0].answer, outcome.state.current.label),
                )
                self.assertEqual(InterviewRenderer.render(outcome.state), outcome.prompt)

    def test_a_reply_fitting_several_options_is_asked_again_with_only_those(self) -> None:
        """The live failure: the narrowed list is numbered from 1, and stays on screen after "1 or 2"."""
        outcome: InterviewOutcome = InterviewFixtures.play("service now CR")
        self.assertEqual((InterviewOutcome.AMBIGUOUS, (self.CAB, self.DBA)), (outcome.status, outcome.candidates))
        expected: str = (
            "Both of those match what you said, and they build different networks - which is it?\n"
            f"  1. {self.CAB}\n  2. {self.DBA}\n"
            f"  3. {InterviewOptions.DESCRIBE_ESCAPE}\n  4. {InterviewOptions.UNSURE_ESCAPE}"
            f"\n\nDecides the approval gate.\n{InterviewRenderer.CLOSING_LINE}"
        )
        self.assertEqual(expected, outcome.prompt)
        both: InterviewOutcome = InterviewRecorder.record(outcome.state, "1 or 2")
        self.assertEqual((InterviewOutcome.AMBIGUOUS, (self.CAB, self.DBA)), (both.status, both.state.offered))
        self.assertEqual(self.DBA, InterviewRecorder.record(both.state, "2").state.entries[0].answer)

    def test_a_reply_saying_less_than_its_one_option_is_confirmed_first(self) -> None:
        """Recording the option would put the rest of it in the user's mouth, so it is offered back for a yes."""
        outcome: InterviewOutcome = InterviewFixtures.play("the DBA lead")
        self.assertEqual((InterviewOutcome.CONFIRM, (self.DBA,)), (outcome.status, outcome.state.offered))
        self.assertEqual(self.DBA, InterviewRecorder.record(outcome.state, "1").state.entries[0].answer)

    def test_the_escapes_ask_for_a_description_or_a_default_recorded_as_assumed(self) -> None:
        """Describing asks for words, and "not sure" leaves the default to the designer, flagged as assumed."""
        describe: InterviewOutcome = InterviewFixtures.play("4")
        self.assertEqual(InterviewOutcome.DESCRIBE, describe.status)
        self.assertTrue(describe.prompt.startswith("Go ahead - what is it, in your own words?\n  1. "))
        unsure: InterviewOutcome = InterviewFixtures.play("5")
        self.assertEqual((InterviewOutcome.ASSUME, "decides the approval gate."), (unsure.status, unsure.note))
        assumed: InterviewOutcome = InterviewRecorder.assume(unsure.state, " Email ")
        self.assertEqual(("Email", True), (assumed.state.entries[0].answer, assumed.state.entries[0].assumed))

    def test_a_yes_a_no_a_position_or_an_escape_in_words_is_read_as_meant(self) -> None:
        """Each was recorded word for word as a confirmed requirement: "yes", "7", "the second one", "not sure"."""
        confirm: InterviewState = InterviewFixtures.play("the DBA lead").state
        self.assertEqual(self.DBA, InterviewRecorder.record(confirm, "Yes").state.entries[0].answer)
        declined: InterviewOutcome = InterviewRecorder.record(confirm, "no")
        self.assertEqual((InterviewOutcome.AMBIGUOUS, ()), (declined.status, declined.state.offered))
        self.assertTrue(declined.prompt.startswith(f"Then which is it?\n  1. {self.CAB}\n"))
        for reply, expected in {
            "7": (InterviewOutcome.AMBIGUOUS, ""),
            "the second one": (InterviewOutcome.RECORDED, self.DBA),
            "I'm not sure": (InterviewOutcome.ASSUME, ""),
            "something else": (InterviewOutcome.DESCRIBE, ""),
        }.items():
            with self.subTest(reply=reply):
                outcome: InterviewOutcome = InterviewFixtures.play(reply)
                self.assertEqual(expected, (outcome.status, outcome.state.entries[0].answer))
        questions: list[dict[str, Any]] = [{"question": "Window?", "options": ["4 hours", "8 hours"], "why": ""}]
        state: InterviewState = InterviewFactory.begin_from_questions("change", questions)
        self.assertEqual(InterviewOutcome.CONFIRM, InterviewRecorder.record(state, "8").status)

    def test_the_log_and_brief_come_from_what_is_on_file(self) -> None:
        """The log reads "Q1." so it is not mistaken for options, and the brief separates what was assumed."""
        state: InterviewState = InterviewRecorder.assume(InterviewFixtures.play("1", "2").state, "Snapshot").state
        self.assertEqual(
            ["Q3. Backup - Snapshot (assumed)", "Q4. Scale - not yet answered"],
            InterviewRenderer.get_log_lines(state)[2:],
        )
        self.assertEqual(["Window: Sunday morning"], InterviewRenderer.get_brief_lines(state, False)[1:])
        self.assertEqual(["Backup: Snapshot"], InterviewRenderer.get_brief_lines(state, assumed=True))
        for question, subject in {
            "Topology: which one?": "Topology",
            "Which window?": "Which window",
            ": odd?": ": odd",
        }.items():
            self.assertEqual(subject, InterviewRenderer.get_subject(InterviewEntry("Q1", "V1", question, (), "")))

    def test_the_last_answer_completes_the_interview(self) -> None:
        """Once every entry is answered there is no next question, only the brief."""
        outcome: InterviewOutcome = InterviewFixtures.play("3", "1", "1", "2")
        self.assertEqual(
            (InterviewOutcome.COMPLETE, "", "Q4", ()),
            (outcome.status, outcome.prompt, outcome.entry.label, outcome.state.outstanding),
        )

    def test_a_matcher_proposes_candidates_but_the_policy_decides(self) -> None:
        """Two candidates are asked about, one is confirmed, none is an answer, and a number never reaches it."""
        for candidates, status in {(self.CAB, self.DBA): "ambiguous", (self.CAB,): "confirm", (): "recorded"}.items():
            with self.subTest(candidates=candidates):
                matcher: Any = mock.Mock(spec=ModelReplyMatcher)
                matcher.match.return_value = list(candidates)
                outcome: InterviewOutcome = InterviewRecorder.record(
                    InterviewFixtures.play().state, "the CAB one", matcher
                )
                self.assertEqual(status, outcome.status)
        InterviewRecorder.record(InterviewFixtures.play().state, "2", matcher)
        matcher.match.assert_called_once()
