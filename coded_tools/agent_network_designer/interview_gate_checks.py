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

import re

from coded_tools.agent_network_designer.interview_review_result import InterviewReviewResult
from coded_tools.agent_network_designer.knowledge_pack import KnowledgePack
from coded_tools.agent_network_designer.standards_verifier import StandardsVerifier


class InterviewGateChecks:
    """
    Checks a recorded deliberation's phase gate and brief. A turn is a {"role", "text"} record.
    """

    USER: str = "user"
    # Whatever the front man said, including the brief and the closing summary.
    DESIGNER: str = "designer"
    # An internal step label such as "A3.", which the prompt says must never be printed.
    STEP_LABEL_RE: re.Pattern = re.compile(r"(?:^|\s)(?:A|B)\d{1,2}\.\s")
    # A standard quoted in the brief, "- **ODB-03** - <text>", wrapping until a blank line or the next bullet.
    BRIEF_STANDARD_RE: re.Pattern = re.compile(
        r"^[ \t]*[-*][ \t]*\*\*(?P<id>[^*\n]+)\*\*[ \t]*[-–—:][ \t]*(?P<text>(?:[^\n]|\n(?![ \t]*(?:\n|[-*])))+)",
        re.MULTILINE,
    )
    REQUIRED_BRIEF_SECTIONS: tuple[str, ...] = (
        "Confirmed requirements",
        "Operating standards enforced",
        "Assumptions I made",
        "Out of scope",
        "Proposed network shape",
    )
    SKIP_REQUESTS: tuple[str, ...] = ("skip the questions", "just build it", "don't ask", "do not ask", "no questions")
    # Evidence that a network was built: a fenced block, or a claim of having written one.
    BUILT_MARKERS: tuple[str, ...] = ("```", "registries/generated", "- built", "has been created")
    # Columns only the computed coverage table has.
    COMPUTED_TABLE_MARKERS: tuple[str, ...] = ("Role", "Fidelity")

    @staticmethod
    def add(result: InterviewReviewResult, kind: str, detail: str, index: int = -1) -> None:
        """
        Record a finding.

        :param result: Collects the findings.
        :param kind: What kind of promise was broken, such as "GATE".
        :param detail: What happened.
        :param index: The turn it happened in, or -1 for the transcript as a whole.
        """
        result.findings.append(f"{kind}: turn {index}: {detail}" if index >= 0 else f"{kind}: {detail}")

    @staticmethod
    def mentions(text: str, phrases: tuple[str, ...], lower: bool = False) -> bool:
        """
        Check whether text contains any of some phrases.

        :param text: The text.
        :param phrases: The phrases.
        :param lower: Whether to compare the lowercased text.
        :return: True if any phrase occurs.
        """
        for phrase in phrases:
            if phrase in (text.lower() if lower else text):
                return True
        return False

    @staticmethod
    def get_turns(turns: list[dict[str, str]], role: str, before: int = -1) -> list[int]:
        """
        Find the turns one side said.

        :param turns: The recorded turns.
        :param role: USER or DESIGNER.
        :param before: Only turns before this index, or -1 for all.
        :return: Their indices, in order.
        """
        indices: list[int] = []
        for index, turn in enumerate(turns):
            if turn.get("role") == role and (before < 0 or index < before):
                indices.append(index)
        return indices

    @staticmethod
    def find_turn(turns: list[dict[str, str]], role: str, marker: str) -> int:
        """
        Find the brief, marked "DESIGN BRIEF", or the approval, a user turn starting "APPROVED".

        :param turns: The recorded turns.
        :param role: The side that says it.
        :param marker: The marker, in capitals.
        :return: The first such turn's index, or -1.
        """
        for index in InterviewGateChecks.get_turns(turns, role):
            text: str = turns[index].get("text").upper()
            if (marker in text) if role == InterviewGateChecks.DESIGNER else text.strip().startswith(marker):
                return index
        return -1

    @staticmethod
    def check(
        turns: list[dict[str, str]], pack: KnowledgePack, other_ids: set[str], result: InterviewReviewResult
    ) -> None:
        """
        Report leaked labels, foreign ids, a folded gate, a build before approval, and brief and closing table faults.

        :param turns: The recorded turns.
        :param pack: The pack the deliberation interviewed from.
        :param other_ids: The standard ids of every other pack, none of which may appear.
        :param result: Collects the findings and counts the standards quoted.
        """
        designer: list[int] = InterviewGateChecks.get_turns(turns, InterviewGateChecks.DESIGNER)
        for index in designer:
            label: re.Match | None = InterviewGateChecks.STEP_LABEL_RE.search(turns[index].get("text"))
            if label is not None:
                InterviewGateChecks.add(
                    result, "LEAK", f"printed the internal step label {label.group(0).strip()!r}", index
                )
        for index in designer:
            for foreign in sorted(other_ids):
                if re.search(rf"\b{re.escape(foreign)}\b", turns[index].get("text")):
                    InterviewGateChecks.add(
                        result, "DOMAIN", f"quoted {foreign}, which belongs to a different pack", index
                    )
        for index in InterviewGateChecks.get_turns(turns, InterviewGateChecks.USER):
            reply: dict[str, str] = turns[index + 1] if index + 1 < len(turns) else {}
            if not InterviewGateChecks.mentions(turns[index].get("text"), InterviewGateChecks.SKIP_REQUESTS, True):
                continue
            if reply.get("role") == InterviewGateChecks.DESIGNER and InterviewGateChecks.mentions(
                reply.get("text"), InterviewGateChecks.BUILT_MARKERS
            ):
                InterviewGateChecks.add(
                    result, "GATE", "built the network after being asked to skip the deliberation", index + 1
                )
            elif reply.get("role") == InterviewGateChecks.DESIGNER and "?" not in reply.get("text"):
                InterviewGateChecks.add(
                    result, "GATE", "was asked to skip and neither refused with a question nor built", index + 1
                )
        approval: int = InterviewGateChecks.find_turn(turns, InterviewGateChecks.USER, "APPROVED")
        for index in InterviewGateChecks.get_turns(
            turns, InterviewGateChecks.DESIGNER, approval if approval >= 0 else len(turns)
        ):
            if "registries/generated" in turns[index].get("text"):
                InterviewGateChecks.add(
                    result, "GATE", "named a written network file before the user approved anything", index
                )
        InterviewGateChecks.check_brief(turns, pack, result)
        InterviewGateChecks.check_closing_table(turns, approval, result)

    @staticmethod
    def check_brief(turns: list[dict[str, str]], pack: KnowledgePack, result: InterviewReviewResult) -> None:
        """
        Check the brief has its sections, says how to approve it, and quotes each standard verbatim from the pack.

        :param turns: The recorded turns.
        :param pack: The pack the deliberation interviewed from.
        :param result: Collects the findings and counts the standards quoted.
        """
        index: int = InterviewGateChecks.find_turn(turns, InterviewGateChecks.DESIGNER, "DESIGN BRIEF")
        if index < 0:
            InterviewGateChecks.add(result, "BRIEF", "no design brief was presented")
            return
        brief: str = turns[index].get("text")
        for section in InterviewGateChecks.REQUIRED_BRIEF_SECTIONS:
            if section.lower() not in brief.lower():
                InterviewGateChecks.add(result, "BRIEF", f"the brief has no {section!r} section", index)
        if "APPROVED" not in brief:
            InterviewGateChecks.add(result, "BRIEF", "the brief does not tell the user how to approve it", index)
        known: dict[str, str] = {}
        for standard in pack.standards:
            known[standard.standard_id] = standard.text
        for match in InterviewGateChecks.BRIEF_STANDARD_RE.finditer(brief):
            standard_id: str = match.group("id").strip()
            quoted: str = match.group("text").strip()
            if standard_id not in known:
                InterviewGateChecks.add(
                    result, "PROVENANCE", f"the brief quotes {standard_id}, which this pack does not define", index
                )
                continue
            result.standards_quoted += 1
            expected: str = known.get(standard_id)
            if StandardsVerifier.normalize(quoted) != StandardsVerifier.normalize(expected):
                detail: str = (
                    f"{standard_id} is not quoted verbatim in the brief. "
                    f"expected {expected[:60]!r}, found {quoted[:60]!r}"
                )
                InterviewGateChecks.add(result, "FIDELITY", detail, index)

    @staticmethod
    def check_closing_table(turns: list[dict[str, str]], approval: int, result: InterviewReviewResult) -> None:
        """
        Check that after approval the designer printed the computed coverage table rather than writing its own.

        :param turns: The recorded turns.
        :param approval: The approving turn's index, or -1, when nothing is checked.
        :param result: Collects the findings.
        """
        if approval < 0:
            return
        closing: list[str] = []
        for index in InterviewGateChecks.get_turns(turns, InterviewGateChecks.DESIGNER):
            if index > approval:
                closing.append(turns[index].get("text"))
        missing: list[str] = []
        for marker in InterviewGateChecks.COMPUTED_TABLE_MARKERS:
            if marker not in "\n".join(closing):
                missing.append(marker)
        if not "\n".join(closing):
            InterviewGateChecks.add(result, "BUILD", "nothing was said after the user approved")
        elif missing:
            detail: str = (
                f"the closing coverage table has no {', '.join(missing)} column, so it was not the computed one - "
                f"the model wrote a table about its own work"
            )
            InterviewGateChecks.add(result, "SELF_REPORT", detail)
