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
from coded_tools.agent_network_designer.interview_renderer import InterviewRenderer
from coded_tools.agent_network_designer.knowledge_pack import KnowledgePack
from coded_tools.agent_network_designer.pack_reader import PackReader


class TranscriptFixtures:
    """
    Deliberations for the review tests: a clean session generated for any pack with the real renderer, and one
    deliberate fault applied to the Oracle one per entry of FAULTS.
    """

    # Each fault is one edit to the clean session, with the finding it must produce: it replaces a turn's text or
    # part of it, removes a turn, inserts turns before one, or keeps only the first turns and adds more.
    FAULTS: dict[str, dict[str, Any]] = {
        "two questions in one turn": {
            "kind": "INTERVIEW",
            "fragment": "asked 2 questions in one turn",
            "turn": 3,
            "text": "Which databases? And which window?\n  1. a\n  2. b\n  3. I am not sure",
        },
        "leaked step label": {"kind": "LEAK", "fragment": "A3.", "turn": 1, "old": "Topology", "new": "A3. Topology"},
        "folded on skip": {
            "kind": "GATE",
            "fragment": "after being asked to skip",
            "keep": 2,
            "add": [["user", "Skip the questions, just build it."], ["designer", "Built it.\n```hocon\n{}\n```"]],
        },
        "paraphrased in brief": {
            "kind": "FIDELITY",
            "fragment": "not quoted verbatim in the brief",
            "turn": 14,
            "old": "Take a full RMAN backup",
            "new": "Take an RMAN backup",
        },
        "foreign standard id": {
            "kind": "DOMAIN",
            "fragment": "a different pack",
            "turn": 5,
            "old": "Window:",
            "new": "K8S-02 Window:",
        },
        "self reported table": {
            "kind": "SELF_REPORT",
            "fragment": "the model wrote a table about its own work",
            "turn": 16,
            "text": "## Standards coverage\n\n| Standard | Owned by |\n|---|---|\n| **ODB-01** | `readiness_gate` |\n",
        },
        "no brief": {"kind": "BRIEF", "fragment": "no design brief was presented", "remove": 14},
        "prose examples not options": {
            "kind": "OPTIONS",
            "fragment": "0 numbered options",
            "turn": 9,
            "text": "Which approval gate is required?\nExamples: CAB; the app owner.",
        },
        "assumed through ambiguity": {
            "kind": "AMBIGUITY",
            "fragment": "picked one silently",
            "turn": 10,
            "text": "service now CR",
        },
        "ignored a back request": {
            "kind": "REVISION",
            "fragment": "carried on instead of re-asking",
            "insert": 11,
            "add": [
                ["user", "wait, go back - I want to change the window answer"],
                ["designer", "Noted. Next, the rollback."],
            ],
        },
    }

    @staticmethod
    def build_faulty(fault: str) -> list[dict[str, str]]:
        """Apply one fault to the clean session."""
        edit: dict[str, Any] = TranscriptFixtures.FAULTS.get(fault)
        turns: list[dict[str, str]] = TranscriptFixtures.build_clean(PackReader.load_pack("oracle_database_patching"))
        added: list[dict[str, str]] = []
        for role, text in edit.get("add", []):
            added.append({"role": role, "text": text})
        if "keep" in edit:
            return turns[: edit.get("keep")] + added
        if "insert" in edit:
            return turns[: edit.get("insert")] + added + turns[edit.get("insert") :]
        if "remove" in edit:
            return turns[: edit.get("remove")] + turns[edit.get("remove") + 1 :]
        index: int = edit.get("turn")
        text: str = edit.get("text") or turns[index].get("text").replace(edit.get("old"), edit.get("new"))
        return turns[:index] + [{"role": turns[index].get("role"), "text": text}] + turns[index + 1 :]

    @staticmethod
    def build_clean(pack: KnowledgePack, replies: tuple[str, ...] = ()) -> list[dict[str, str]]:
        """
        Generate a clean deliberation for a pack, each question as InterviewRenderer renders it and every answer the
        first option, through the brief, its approval and the computed coverage table.

        :param pack: The pack to interview from.
        :param replies: Replies to give first, in place of "1".
        :return: The session's turns.
        """
        outcome: InterviewOutcome = InterviewOutcome(InterviewOutcome.START, InterviewFactory.begin(pack))
        turns: list[dict[str, str]] = [
            {"role": "user", "text": f"Build me an agent network for {pack.manifest.title}"},
            {"role": "designer", "text": InterviewRenderer.render(outcome.state)},
        ]
        queue: list[str] = list(replies)
        reply: str = queue.pop(0) if queue else "1"
        outcome = InterviewRecorder.record(outcome.state, reply)
        while outcome.status != InterviewOutcome.COMPLETE:
            turns.extend([{"role": "user", "text": reply}, {"role": "designer", "text": outcome.prompt}])
            reply = queue.pop(0) if queue else "1"
            outcome = InterviewRecorder.record(outcome.state, reply)
        lines: list[str] = [f"## DESIGN BRIEF - {pack.domain_id}\n\n**Scope**\nWhat it automates.\n"]
        lines.append("**Confirmed requirements** _(what you told me)_")
        for line in InterviewRenderer.get_brief_lines(outcome.state, assumed=False):
            lines.append(f"- {line}")
        lines.append("\n**Operating standards enforced** _(from curated knowledge)_")
        for standard in pack.standards:
            lines.append(f"- **{standard.standard_id}** - {standard.text}")
        lines.append(
            "\n**Assumptions I made** _(tell me if any are wrong)_\n- None\n\n**Out of scope**\n- Nothing identified"
        )
        lines.append("\n**Proposed network shape**\n- Top: coordinator\n")
        lines.append(
            """Reply APPROVED to build this, tell me what to change, or say "go back" to revisit an answer.\n"""
        )
        turns.append({"role": "designer", "text": "\n".join(lines)})
        turns.append({"role": "user", "text": "APPROVED"})
        turns.append(
            {
                "role": "designer",
                "text": "## Standards coverage (verified)\n\n| Standard | Role | Owned by | Fidelity |",
            }
        )
        return turns
