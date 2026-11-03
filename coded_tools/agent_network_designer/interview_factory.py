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

import json
from dataclasses import asdict
from typing import Any

from coded_tools.agent_network_designer.interview_entry import InterviewEntry
from coded_tools.agent_network_designer.interview_state import InterviewState
from coded_tools.agent_network_designer.knowledge_pack import KnowledgePack


class InterviewFactory:
    """
    Builds an interview from a pack's open variables or from questions the designer derived, and carries it
    between turns as a dictionary in sly_data.
    """

    @staticmethod
    def begin(pack: KnowledgePack) -> InterviewState:
        """
        Build the interview from a pack's open variables, one labeled entry each, in the pack's order.

        :param pack: The pack being interviewed from.
        :return: The interview at its first question.
        :raises ValueError: If the pack declares no open variables.
        """
        if not pack.open_variables:
            raise ValueError(f"pack {pack.domain_id!r} declares no open variables, so there is no interview to hold")
        entries: list[InterviewEntry] = []
        for number, variable in enumerate(pack.open_variables, start=1):
            options: list[str] = []
            for part in variable.examples.split(";"):
                if part.strip():
                    options.append(part.strip())
            label: str = f"Q{number}"
            entries.append(
                InterviewEntry(label, variable.variable_id, variable.question, tuple(options), variable.why)
            )
        return InterviewState(domain_id=pack.domain_id, entries=tuple(entries))

    @staticmethod
    def begin_from_questions(domain_id: str, questions: list[Any]) -> InterviewState:
        """
        Build the interview from questions the designer derived for a domain with no pack, marked uncurated.

        :param domain_id: What the designer calls this domain.
        :param questions: One object per question, with "question", at least two "options", and "why".
        :return: The interview at its first question.
        :raises ValueError: If a question is unusable, naming which one and why.
        """
        if not questions:
            raise ValueError("no questions were given, so there is no interview to hold")
        entries: list[InterviewEntry] = []
        for number, item in enumerate(questions, start=1):
            if not isinstance(item, dict):
                raise ValueError(f"question {number} is not an object with 'question', 'options' and 'why'")
            text: str = str(item.get("question") or "").strip()
            if not text:
                raise ValueError(f"question {number} has no question text")
            if not isinstance(item.get("options") or [], list):
                raise ValueError(f"question {number} gives its options as text; give them as a list of answers")
            options: list[str] = []
            for option in item.get("options") or []:
                if str(option).strip():
                    options.append(str(option).strip())
            if len(options) < 2:
                raise ValueError(
                    f"question {number} offers {len(options)} example answers; give at least two so the user has "
                    f"something to choose between"
                )
            why: str = str(item.get("why") or "").strip()
            entries.append(InterviewEntry(f"Q{number}", f"D{number}", text, tuple(options), why))
        return InterviewState(domain_id=domain_id, entries=tuple(entries), curated=False)

    @staticmethod
    def to_dict(state: InterviewState) -> dict[str, Any]:
        """
        Write the interview as a JSON-safe dictionary, to carry in sly_data between turns.

        :param state: The interview.
        :return: The dictionary from_dict() reads, with every tuple as a list.
        """
        return json.loads(json.dumps(asdict(state)))

    @staticmethod
    def from_dict(raw: Any) -> InterviewState:
        """
        Rebuild the interview from sly_data, strictly, since a silent restart would have the user answer it all again.

        :param raw: The dictionary to_dict() wrote.
        :return: The interview.
        :raises ValueError: If the dictionary is not a usable interview.
        """
        if not isinstance(raw, dict) or not isinstance(raw.get("entries"), list) or not raw.get("entries"):
            raise ValueError("the interview log carried no entries")
        entries: list[InterviewEntry] = []
        try:
            for item in raw.get("entries"):
                label, variable_id, question = str(item["label"]), str(item["variable_id"]), str(item["question"])
                options: list[str] = []
                for option in item.get("options", []):
                    options.append(str(option))
                why, answer, assumed = (
                    str(item.get("why", "")),
                    str(item.get("answer", "")),
                    bool(item.get("assumed", False)),
                )
                entries.append(InterviewEntry(label, variable_id, question, tuple(options), why, answer, assumed))
            cursor: int = int(raw.get("cursor", 0))
            offered: list[str] = []
            for option in raw.get("offered", ()):
                offered.append(str(option))
        except (AttributeError, KeyError, TypeError, ValueError) as exception:
            raise ValueError(f"the interview log is malformed: {exception}") from exception
        if not 0 <= cursor < len(entries):
            raise ValueError(f"the interview log points at entry {cursor} of {len(entries)}")
        # Only an absent flag reads as curated, so an uncurated interview never comes back looking verified.
        curated: bool = bool(raw.get("curated", True))
        return InterviewState(str(raw.get("domain_id", "")), tuple(entries), cursor, curated, tuple(offered))
