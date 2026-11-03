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

from coded_tools.agent_network_designer.interview_factory import InterviewFactory
from coded_tools.agent_network_designer.interview_recorder import InterviewRecorder
from coded_tools.agent_network_designer.interview_state import InterviewState
from tests.coded_tools.agent_network_designer.interview_fixtures import InterviewFixtures
from tests.coded_tools.agent_network_designer.pack_fixtures import PackFixtures


class TestInterviewFactory(TestCase):
    """
    Tests for InterviewFactory.
    """

    def test_a_pack_or_derived_questions_become_labeled_entries(self) -> None:
        """Entries exist from the start with the pack's examples as options; derived ones are never curated."""
        state: InterviewState = InterviewFactory.begin(
            PackFixtures.load_shipped_pack(self, "oracle_database_patching")
        )
        self.assertEqual(
            (7, "Q1", "V1", True), (len(state.entries), state.current.label, state.current.variable_id, state.curated)
        )
        self.assertEqual("two-node RAC", state.current.options[1])
        derived: InterviewState = InterviewFixtures.play().state
        self.assertEqual(
            ("D4", ("One", "Up to ten"), False),
            (derived.entries[3].variable_id, derived.entries[3].options, derived.curated),
        )
        bad: dict[str, list[Any]] = {
            "no questions were given, so there is no interview to hold": [],
            "question 1 is not an object with 'question', 'options' and 'why'": ["Which window?"],
            "question 1 has no question text": [{"options": ["a", "b"]}],
            "question 1 offers 1 example answers; give at least two so the user has something to choose between": [
                {"question": "Q?", "options": ["a", " "]}
            ],
            "question 1 gives its options as text; give them as a list of answers": [
                {"question": "Q?", "options": "a, b"}
            ],
        }
        for message, questions in bad.items():
            with self.subTest(message=message), self.assertRaises(ValueError) as raised:
                InterviewFactory.begin_from_questions("pizza", questions)
            self.assertEqual(message, str(raised.exception))

    def test_the_interview_round_trips_through_sly_data_and_rejects_a_malformed_one(self) -> None:
        """The state comes back through the client, so a bad payload is an error rather than a silent restart."""
        state: InterviewState = InterviewRecorder.assume(InterviewFixtures.play().state, "Email").state
        state = InterviewRecorder.record(InterviewRecorder.record(state, "Sunday").state, "1 or 2").state
        self.assertEqual(state, InterviewFactory.from_dict(InterviewFactory.to_dict(state)))
        entry: dict[str, Any] = {"label": "Q1", "variable_id": "V1", "question": "Q?"}
        bad: dict[str, Any] = {
            "the interview log carried no entries": {"entries": []},
            "the interview log is malformed: 'variable_id'": {"entries": [{"label": "Q1"}]},
            "the interview log points at entry 5 of 1": {"entries": [entry], "cursor": 5},
            "the interview log is malformed: 'int' object is not iterable": {"entries": [entry], "offered": 5},
        }
        for message, raw in bad.items():
            with self.subTest(message=message), self.assertRaises(ValueError) as raised:
                InterviewFactory.from_dict(raw)
            self.assertEqual(message, str(raised.exception))
        self.assertTrue(InterviewFactory.from_dict({"entries": [entry]}).curated)
