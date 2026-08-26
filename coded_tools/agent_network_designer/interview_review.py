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

"""
Check a deliberation transcript against the behaviour the designer promises.

WHY THIS EXISTS
---------------
standards_verifier checks the ARTIFACT. Nothing checks the INTERVIEW - and the interview is the
product. It is also the part a plausible-looking prompt edit silently breaks: asking two questions
at once, leaking an internal step label, agreeing to skip the deliberation, or paraphrasing a
standard into the design brief are all invisible to the artifact-level checks, because a network
built after a bad interview can still embed every standard perfectly.

The design here mirrors standards_verifier deliberately. The checks are pure functions over a
recorded transcript, with no language model, no network and no agent runtime, so:

  * they run in ordinary CI over committed transcripts, including deliberately bad ones that prove
    the checks have teeth;
  * an integration run that drives a real conversation feeds its transcript through the SAME
    checks, so "it worked when I tried it" and "CI is green" mean the same thing.

WHAT IS AND IS NOT CHECKED HERE
-------------------------------
Everything here is a structural property with a definite answer: how many questions a turn asked,
whether a section is present, whether a quoted standard matches the source document character for
character. Judgements - was the question well phrased, was it the RIGHT question - are not here.
They need a model, they belong in a scored trend rather than a pass/fail gate, and a check that
returns "probably fine" teaches a reader to ignore it.

The sharpest check is the verbatim one. The brief is instructed to quote each operating standard
"verbatim from the curated document", and until now nobody compared them. It reuses normalise()
from knowledge_pack, so the tolerance is identical to the artifact's fidelity check: re-wrapping
and typography pass, a changed word does not.
"""

import argparse
import json
import re
import sys
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path
from typing import Any

from coded_tools.agent_network_designer.knowledge_pack import KnowledgePack
from coded_tools.agent_network_designer.knowledge_pack import normalise

# Roles in a recorded transcript. "designer" covers whatever the front man said, including the
# brief and the closing summary; intermediate agent chatter is not part of what a user sees.
ROLE_USER: str = "user"
ROLE_DESIGNER: str = "designer"

# An internal step label. The prompt says these are internal and must never be printed, because a
# user reading "A3." is watching the machinery instead of being interviewed.
STEP_LABEL_RE: re.Pattern = re.compile(r"(?:^|\s)(?:A|B)\d{1,2}\.\s")

# A standard as quoted in the design brief: "- **ODB-03** - <text>", wrapping freely until a blank
# line or the next bullet. Anchored on the bold id because that is what the prompt specifies.
BRIEF_STANDARD_RE: re.Pattern = re.compile(
    r"^[ \t]*[-*][ \t]*\*\*(?P<id>[^*\n]+)\*\*[ \t]*[-–—:][ \t]*(?P<text>(?:[^\n]|\n(?![ \t]*(?:\n|[-*])))+)",
    re.MULTILINE,
)

# Sections the brief must carry. The point of the brief is that a reader can tell what was
# confirmed from what was assumed, so a missing heading is a missing guarantee.
REQUIRED_BRIEF_SECTIONS: tuple[str, ...] = (
    "Confirmed requirements",
    "Operating standards enforced",
    "Assumptions I made",
    "Out of scope",
    "Proposed network shape",
)

# What a user says when they try to skip the deliberation. The designer must refuse; that gate is
# the entire feature, and a model that folds under mild pressure has removed it.
SKIP_REQUESTS: tuple[str, ...] = (
    "skip the questions",
    "just build it",
    "don't ask",
    "do not ask",
    "no questions",
)

# Evidence that a network was built: a fenced block, or a claim of having written one.
BUILT_MARKERS: tuple[str, ...] = ("```", "registries/generated", "- built", "has been created")

# The computed coverage table carries these columns. The model-written table it replaced never
# had them, so their presence is proof the designer printed the verifier's output rather than
# its own account of its own work.
COMPUTED_TABLE_MARKERS: tuple[str, ...] = ("Role", "Fidelity")

# How many questions beyond the pack's own open variables is tolerable before the designer is
# plainly interviewing from somewhere other than the curated document. Two allows for a
# clarification and a confirmation without allowing an invented interview.
QUESTION_ALLOWANCE: int = 2


@dataclass(frozen=True)
class Turn:
    """One turn of a recorded deliberation."""

    role: str
    text: str


@dataclass(frozen=True)
class Finding:
    """One way a transcript departed from the promised behaviour."""

    kind: str
    detail: str
    turn_index: int = -1

    def rendered(self) -> str:
        """
        :return: The finding as one human-readable line.
        """
        where: str = f"turn {self.turn_index}: " if self.turn_index >= 0 else ""
        return f"{self.kind}: {where}{self.detail}"


@dataclass
class InterviewResult:
    """The computed outcome of reviewing one transcript."""

    domain_id: str
    findings: list[Finding] = field(default_factory=list)
    questions_asked: int = 0
    open_variables: int = 0
    standards_quoted: int = 0

    @property
    def ok(self) -> bool:
        """:return: True when the transcript departed from the promised behaviour nowhere."""
        return not self.findings

    def problems(self) -> list[str]:
        """
        :return: Every finding as a human-readable line.
        """
        return [finding.rendered() for finding in self.findings]


def load_transcript(path: str | Path) -> tuple[str, list[Turn]]:
    """
    Read a recorded transcript.

    The format is deliberately trivial - a domain and a list of {role, text} - so a transcript can
    be produced by an integration run, by a person pasting a session out of the UI, or by hand for
    a test fixture, and all three feed the same checks.

    :param path: Path to the transcript JSON.
    :return: The domain id and the turns.
    :raises ValueError: If the file cannot be read or does not look like a transcript.
    """
    try:
        raw: Any = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exception:
        raise ValueError(f"Could not read transcript {path}: {exception}") from exception
    if not isinstance(raw, dict) or "turns" not in raw:
        raise ValueError(f"{path} does not look like a transcript: expected an object with 'turns'.")
    turns: list[Turn] = [
        Turn(role=str(entry.get("role", "")), text=str(entry.get("text", ""))) for entry in raw.get("turns", [])
    ]
    return str(raw.get("domain", "")), turns


def review_interview(turns: list[Turn], pack: KnowledgePack, other_ids: set[str] | None = None) -> InterviewResult:
    """
    Check a transcript against the behaviour the designer's prompt promises.

    :param turns: The recorded turns, in order.
    :param pack: The pack the session was supposed to be interviewing from.
    :param other_ids: Standard ids belonging to OTHER packs, which must never appear.
    :return: The computed result.
    """
    result = InterviewResult(
        domain_id=pack.domain_id,
        open_variables=len(pack.open_variables),
    )

    brief_index: int = _find_brief(turns)
    approval_index: int = _find_approval(turns)

    _check_one_question_at_a_time(turns, brief_index, result)
    _check_no_step_labels(turns, result)
    _check_no_foreign_ids(turns, other_ids or set(), result)
    _check_refusals(turns, result)
    _check_nothing_built_before_approval(turns, approval_index, result)
    _check_brief(turns, brief_index, pack, result)
    _check_closing_table(turns, approval_index, result)
    _check_question_budget(result)
    return result


def _designer_turns(turns: list[Turn]) -> list[tuple[int, Turn]]:
    """
    :param turns: The recorded turns.
    :return: (index, turn) for every designer turn.
    """
    return [(index, turn) for index, turn in enumerate(turns) if turn.role == ROLE_DESIGNER]


def _find_brief(turns: list[Turn]) -> int:
    """
    :param turns: The recorded turns.
    :return: Index of the turn carrying the design brief, or -1 if there is none.
    """
    for index, turn in _designer_turns(turns):
        if "DESIGN BRIEF" in turn.text.upper():
            return index
    return -1


def _find_approval(turns: list[Turn]) -> int:
    """
    :param turns: The recorded turns.
    :return: Index of the user turn approving the build, or -1 if there is none.
    """
    for index, turn in enumerate(turns):
        if turn.role == ROLE_USER and turn.text.strip().upper().startswith("APPROVED"):
            return index
    return -1


def _check_one_question_at_a_time(turns: list[Turn], brief_index: int, result: InterviewResult) -> None:
    """
    One question per turn is the interview. Two at once is a form.

    Counted as question marks, which is crude but decisive: the prompt's own format puts the
    examples and the why-clause inside one sentence ending in a single "?".

    :param turns: The recorded turns.
    :param brief_index: Index of the brief, or -1.
    :param result: Accumulates findings and the question count.
    """
    limit: int = brief_index if brief_index >= 0 else len(turns)
    for index, turn in _designer_turns(turns):
        if index >= limit:
            continue
        questions: int = turn.text.count("?")
        result.questions_asked += min(questions, 1)
        if questions > 1:
            result.findings.append(
                Finding(
                    kind="INTERVIEW",
                    detail=f"asked {questions} questions in one turn; the interview is one at a time",
                    turn_index=index,
                )
            )


def _check_no_step_labels(turns: list[Turn], result: InterviewResult) -> None:
    """
    The step labels are internal machinery. A user reading "A3." is watching the mechanism.

    :param turns: The recorded turns.
    :param result: Accumulates findings.
    """
    for index, turn in _designer_turns(turns):
        match: re.Match | None = STEP_LABEL_RE.search(turn.text)
        if match is not None:
            result.findings.append(
                Finding(
                    kind="LEAK",
                    detail=f"printed the internal step label {match.group(0).strip()!r}",
                    turn_index=index,
                )
            )


def _check_no_foreign_ids(turns: list[Turn], other_ids: set[str], result: InterviewResult) -> None:
    """
    A standard id from another pack means the designer is quoting the wrong domain.

    The most consequential failure available to it, and the one known limit that says matching the
    WRONG domain is worse than matching none. Exact, because ids are exact.

    :param turns: The recorded turns.
    :param other_ids: Ids belonging to other packs.
    :param result: Accumulates findings.
    """
    for index, turn in _designer_turns(turns):
        for foreign in sorted(other_ids):
            if re.search(rf"\b{re.escape(foreign)}\b", turn.text):
                result.findings.append(
                    Finding(
                        kind="DOMAIN",
                        detail=f"quoted {foreign}, which belongs to a different pack",
                        turn_index=index,
                    )
                )


def _check_refusals(turns: list[Turn], result: InterviewResult) -> None:
    """
    The phase gate is the feature. A designer that folds when asked to skip has removed it.

    :param turns: The recorded turns.
    :param result: Accumulates findings.
    """
    for index, turn in enumerate(turns):
        if turn.role != ROLE_USER:
            continue
        lowered: str = turn.text.lower()
        if not any(request in lowered for request in SKIP_REQUESTS):
            continue
        reply: Turn | None = turns[index + 1] if index + 1 < len(turns) else None
        if reply is None or reply.role != ROLE_DESIGNER:
            continue
        if any(marker in reply.text for marker in BUILT_MARKERS):
            result.findings.append(
                Finding(
                    kind="GATE",
                    detail="built the network after being asked to skip the deliberation",
                    turn_index=index + 1,
                )
            )
        elif "?" not in reply.text:
            result.findings.append(
                Finding(
                    kind="GATE",
                    detail="was asked to skip and neither refused with a question nor built",
                    turn_index=index + 1,
                )
            )


def _check_nothing_built_before_approval(turns: list[Turn], approval_index: int, result: InterviewResult) -> None:
    """
    Phase B opens on approval. Anything written before it was written on guesses.

    :param turns: The recorded turns.
    :param approval_index: Index of the approving user turn, or -1.
    :param result: Accumulates findings.
    """
    limit: int = approval_index if approval_index >= 0 else len(turns)
    for index, turn in _designer_turns(turns):
        if index >= limit:
            continue
        if "registries/generated" in turn.text:
            result.findings.append(
                Finding(
                    kind="GATE",
                    detail="named a written network file before the user approved anything",
                    turn_index=index,
                )
            )


def _check_brief(turns: list[Turn], brief_index: int, pack: KnowledgePack, result: InterviewResult) -> None:
    """
    Check the brief carries its sections, and that the standards it quotes are quoted verbatim.

    The verbatim check is the one that matters. The brief is what a reviewer reads and approves, so
    a paraphrased standard there is a rule approved in words nobody in the domain agreed to - and
    it passes every artifact-level check, because the network built afterwards can still embed the
    real standard perfectly.

    :param turns: The recorded turns.
    :param brief_index: Index of the brief, or -1.
    :param pack: The pack the session was interviewing from.
    :param result: Accumulates findings.
    """
    if brief_index < 0:
        result.findings.append(Finding(kind="BRIEF", detail="no design brief was presented"))
        return

    brief: str = turns[brief_index].text
    for section in REQUIRED_BRIEF_SECTIONS:
        if section.lower() not in brief.lower():
            result.findings.append(
                Finding(kind="BRIEF", detail=f"the brief has no {section!r} section", turn_index=brief_index)
            )

    if "APPROVED" not in brief:
        result.findings.append(
            Finding(
                kind="BRIEF",
                detail="the brief does not tell the user how to approve it",
                turn_index=brief_index,
            )
        )

    known: dict[str, str] = {standard.standard_id: standard.text for standard in pack.standards}
    for match in BRIEF_STANDARD_RE.finditer(brief):
        standard_id: str = match.group("id").strip()
        quoted: str = match.group("text").strip()
        if standard_id not in known:
            result.findings.append(
                Finding(
                    kind="PROVENANCE",
                    detail=f"the brief quotes {standard_id}, which this pack does not define",
                    turn_index=brief_index,
                )
            )
            continue
        result.standards_quoted += 1
        if normalise(quoted) != normalise(known[standard_id]):
            result.findings.append(
                Finding(
                    kind="FIDELITY",
                    detail=(
                        f"{standard_id} is not quoted verbatim in the brief. "
                        f"expected {known[standard_id][:60]!r}, found {quoted[:60]!r}"
                    ),
                    turn_index=brief_index,
                )
            )


def _check_closing_table(turns: list[Turn], approval_index: int, result: InterviewResult) -> None:
    """
    After approval the designer must print the COMPUTED table, not write one of its own.

    :param turns: The recorded turns.
    :param approval_index: Index of the approving user turn, or -1.
    :param result: Accumulates findings.
    """
    if approval_index < 0:
        return
    closing: str = "\n".join(turn.text for index, turn in _designer_turns(turns) if index > approval_index)
    if not closing:
        result.findings.append(Finding(kind="BUILD", detail="nothing was said after the user approved"))
        return
    missing: list[str] = [marker for marker in COMPUTED_TABLE_MARKERS if marker not in closing]
    if missing:
        result.findings.append(
            Finding(
                kind="SELF_REPORT",
                detail=(
                    f"the closing coverage table has no {', '.join(missing)} column, so it was not the "
                    f"computed one - the model wrote a table about its own work"
                ),
            )
        )


def _check_question_budget(result: InterviewResult) -> None:
    """
    Questions should come from the pack. Many more than it declares means they came from elsewhere.

    A bound rather than a mapping: matching each question to its variable needs judgement, but a
    count that overruns the curated set is decisive on its own.

    :param result: Accumulates findings; reads the counts already gathered.
    """
    budget: int = result.open_variables + QUESTION_ALLOWANCE
    if result.open_variables and result.questions_asked > budget:
        result.findings.append(
            Finding(
                kind="INTERVIEW",
                detail=(
                    f"asked {result.questions_asked} questions where the pack declares "
                    f"{result.open_variables} open variables; the extras did not come from curated knowledge"
                ),
            )
        )


def render_report(result: InterviewResult) -> str:
    """
    Render the review as markdown.

    :param result: The computed result.
    :return: A markdown report.
    """
    lines: list[str] = [
        f"## Interview review - {result.domain_id}",
        "",
        f"- questions asked: {result.questions_asked} (pack declares {result.open_variables} open variables)",
        f"- standards quoted in the brief: {result.standards_quoted}",
        "",
    ]
    if result.ok:
        lines.append("The deliberation followed the promised behaviour in every checked respect.")
        return "\n".join(lines)
    lines.append(f"**{len(result.findings)} departures from the promised behaviour:**")
    lines.append("")
    lines.extend(f"- {problem}" for problem in result.problems())
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """
    Command line entry point: review a recorded transcript against its pack.

    :param argv: Argument vector, or None to read sys.argv.
    :return: 0 when the interview followed the promised behaviour, 1 when it did not, 2 on usage.
    """
    parser = argparse.ArgumentParser(
        description="Check a recorded deliberation transcript against the designer's promised behaviour."
    )
    parser.add_argument("transcript", help="path to a transcript JSON file")
    parser.add_argument("--domain", default=None, help="override the domain recorded in the transcript")
    parser.add_argument("--knowdocs", default=None, help="override the knowdocs root")
    arguments = parser.parse_args(argv)

    # Imported here rather than at module scope so the checks above stay usable against a pack
    # built in memory, with no knowdocs root on disk at all.
    from coded_tools.agent_network_designer.pack_catalogue import (  # pylint: disable=import-outside-toplevel
        load_catalogue,
    )

    try:
        domain_id, turns = load_transcript(arguments.transcript)
    except ValueError as exception:
        print(f"Error: {exception}", file=sys.stderr)
        return 2

    domain_id = arguments.domain or domain_id
    packs: list[KnowledgePack] = load_catalogue(arguments.knowdocs)
    wanted: list[KnowledgePack] = [pack for pack in packs if pack.domain_id == domain_id]
    if not wanted:
        available: str = ", ".join(pack.domain_id for pack in packs) or "none"
        print(f"Error: no pack for domain {domain_id!r}. Available: {available}", file=sys.stderr)
        return 2

    other_ids: set[str] = {
        standard.standard_id for pack in packs if pack.domain_id != domain_id for standard in pack.standards
    }
    result: InterviewResult = review_interview(turns, wanted[0], other_ids)
    print(render_report(result))
    return 0 if result.ok else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
