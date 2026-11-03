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

from coded_tools.agent_network_designer.interview_factory import InterviewFactory
from coded_tools.agent_network_designer.interview_outcome import InterviewOutcome
from coded_tools.agent_network_designer.interview_recorder import InterviewRecorder
from coded_tools.agent_network_designer.interview_state import InterviewState


class InterviewFixtures:  # pylint: disable=too-few-public-methods
    """
    A small interview whose options include the shapes seen being guessed at, and a way to play replies through it.
    """

    QUESTIONS: list[dict[str, Any]] = [
        {
            "question": "Approval: who approves the change?",
            "options": ["ServiceNow CR approved by the CAB", "ServiceNow CR approved by the DBA lead", "Email"],
            "why": "decides the approval gate.",
        },
        {
            "question": "Window: when may it run",
            "options": ["Saturday night", "Sunday morning"],
            "why": "Sets the window.",
        },
        {"question": "Backup: which backup comes first?", "options": ["Full RMAN backup", "Snapshot"], "why": ""},
        {"question": "Scale: how many databases?", "options": ["One", "Up to ten"], "why": "Sizes the waves."},
    ]

    @staticmethod
    def play(*replies: str) -> InterviewOutcome:
        """Start the interview and record each reply in turn."""
        state: InterviewState = InterviewFactory.begin_from_questions("change", InterviewFixtures.QUESTIONS)
        outcome: InterviewOutcome = InterviewOutcome(InterviewOutcome.START, state)
        for reply in replies:
            outcome = InterviewRecorder.record(outcome.state, reply)
        return outcome
