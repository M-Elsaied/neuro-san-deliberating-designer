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

Three of the checks are about the shape of a question rather than the shape of the brief, and they
come from watching a real session go wrong. The designer offered two options inside one sentence -
the same system approved by two different bodies - the user typed the part they had in common, and
the designer recorded it and moved on. Nothing above notices that: the brief reads cleanly, the
network embeds every standard, and the approval gate was chosen by the model with the user never
told a choice had been made. So:

  * OPTIONS - a question is a numbered list with an escape, which is what lets a user be exact;
  * AMBIGUITY - an answer that fits several of the offered options must be sent back, not resolved;
  * REVISION - a user asking to change an earlier answer is taken back to it, not answered past.

An ambiguity resolved and an answer revised are both counted, and both kept out of the question
count, so the budget check cannot punish a designer for disambiguating or a user for correcting.
"""

import argparse
import json
import re
import sys
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path
from typing import Any

from coded_tools.agent_network_designer.interview_options import ESCAPE_MARKERS
from coded_tools.agent_network_designer.interview_options import MIN_OPTIONS
from coded_tools.agent_network_designer.interview_options import OPTION_PICK_RE
from coded_tools.agent_network_designer.interview_options import offered_options
from coded_tools.agent_network_designer.interview_options import option_key
from coded_tools.agent_network_designer.interview_options import tied_options
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

# How the user asks to correct an earlier answer. Kept broad on purpose: a user fixing a mistake
# phrases it however it occurs to them, and the one reply that must never happen is the designer
# treating the request as an answer to the question on screen.
BACK_REQUESTS: tuple[str, ...] = (
    "go back",
    "going back",
    "take me back",
    "back to question",
    "previous question",
    "earlier question",
    "change my answer",
    "change what i said",
    "change question",
    "revise my answer",
    "answered that wrong",
    "got that wrong",
    "start again from",
)


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
    # Counted apart from questions_asked, because neither adds a variable the pack did not declare:
    # a clarification finishes one already asked, a revisit re-opens one already answered. Folding
    # them into the count would make honest disambiguation and honest correction look like an
    # invented interview and trip the question budget.
    clarifications: int = 0
    revisits: int = 0

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
    # These two run before the question count, because they are what decides which designer turns
    # re-open a question rather than asking a new one - and only a turn that ACTUALLY re-asks is
    # excused from the count. A turn that ignored an ambiguous answer asked a new question, and is
    # counted as one on top of the AMBIGUITY finding it already earned.
    reasks: set[int] = _check_ambiguity_is_resolved(turns, brief_index, result)
    reasks |= _check_revisions_are_honoured(turns, result)

    _check_one_question_at_a_time(turns, brief_index, reasks, result)
    _check_questions_offer_options(turns, brief_index, result)
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


def _picked_a_number(reply: str, option_count: int) -> bool:
    """
    :param reply: What the user said.
    :param option_count: How many options were on offer.
    :return: True if the reply names at least one of the offered option numbers.
    """
    return any(1 <= int(match.group(1)) <= option_count for match in OPTION_PICK_RE.finditer(reply))


def _is_back_request(text: str) -> bool:
    """
    :param text: A user turn.
    :return: True if the user asked to change an earlier answer.
    """
    lowered: str = text.lower()
    return any(request in lowered for request in BACK_REQUESTS)


def _is_refusal_reply(turns: list[Turn], index: int) -> bool:
    """
    Whether a designer turn is answering a request to skip the deliberation.

    Carved out of the options check: a refusal names the questions still open rather than asking
    one, so requiring it to offer a numbered choice would be requiring the wrong shape.

    :param turns: The recorded turns.
    :param index: Index of the designer turn.
    :return: True when the turn before it asked to skip the questions.
    """
    if index == 0 or turns[index - 1].role != ROLE_USER:
        return False
    lowered: str = turns[index - 1].text.lower()
    return any(request in lowered for request in SKIP_REQUESTS)


def _question_key(text: str) -> str:
    """
    Identify the question a turn asks, so the same one asked twice is recognised as one question.

    The first line carrying a question mark, reduced to comparable characters. A turn can lead with
    a sentence of its own - "Changed Q3 to ..." before resuming - so the key comes from the
    question rather than the turn.

    :param text: A designer turn.
    :return: The key, or "" when the turn asks nothing.
    """
    for line in text.split("\n"):
        if "?" in line:
            return option_key(line)
    return ""


def _check_one_question_at_a_time(
    turns: list[Turn], brief_index: int, reasks: set[int], result: InterviewResult
) -> None:
    """
    One question per turn is the interview. Two at once is a form.

    Counted as question marks, which is crude but decisive: the prompt's own format puts the
    question on one line ending in the single "?" the reply is allowed, with the options numbered
    beneath it and the why-clause after them.

    Counts DISTINCT questions, not question turns. After the user goes back and corrects an answer
    the interview resumes at the question that was on screen when they left, so that question is
    asked a second time - correctly, since it was never answered. Counting turns would read an
    honest correction as an interview that overran the pack, which is the opposite of the point.

    :param turns: The recorded turns.
    :param brief_index: Index of the brief, or -1.
    :param reasks: Indices of designer turns that re-open an earlier question.
    :param result: Accumulates findings and the question count.
    """
    limit: int = brief_index if brief_index >= 0 else len(turns)
    seen: set[str] = set()
    for index, turn in _designer_turns(turns):
        if index >= limit:
            continue
        questions: int = turn.text.count("?")
        key: str = _question_key(turn.text)
        if index not in reasks and questions and key not in seen:
            result.questions_asked += 1
        seen.add(key)
        if questions > 1:
            result.findings.append(
                Finding(
                    kind="INTERVIEW",
                    detail=f"asked {questions} questions in one turn; the interview is one at a time",
                    turn_index=index,
                )
            )


def _check_questions_offer_options(turns: list[Turn], brief_index: int, result: InterviewResult) -> None:
    """
    Every question is a numbered choice with an escape, not prose with the examples buried in it.

    This is the check the live failure argued for. Offered "a; b; c" inside a sentence, a user
    replies with a phrase that fits two of them, and there is nothing in the reply - and nothing in
    the transcript afterwards - that says which one was meant. The numbering is what gives the user
    a way to be exact; the escape options are what stop the list narrowing the answer to whatever
    the designer happened to enumerate.

    :param turns: The recorded turns.
    :param brief_index: Index of the brief, or -1.
    :param result: Accumulates findings.
    """
    limit: int = brief_index if brief_index >= 0 else len(turns)
    for index, turn in _designer_turns(turns):
        if index >= limit or "?" not in turn.text or _is_refusal_reply(turns, index):
            continue
        options: list[str] = offered_options(turn.text)
        if len(options) < MIN_OPTIONS:
            result.findings.append(
                Finding(
                    kind="OPTIONS",
                    detail=(
                        f"asked a question offering {len(options)} numbered options; a question the user can "
                        f"answer exactly needs at least {MIN_OPTIONS}, the last of them an escape"
                    ),
                    turn_index=index,
                )
            )
            continue
        if not any(marker in option.lower() for option in options for marker in ESCAPE_MARKERS):
            result.findings.append(
                Finding(
                    kind="OPTIONS",
                    detail=(
                        "offered numbered options with no 'something else' or 'not sure' escape, so a user "
                        "whose answer is not listed has to pick a wrong one"
                    ),
                    turn_index=index,
                )
            )


def _check_ambiguity_is_resolved(turns: list[Turn], brief_index: int, result: InterviewResult) -> set[int]:
    """
    An answer consistent with several offered options is not an answer. Moving on assumes one.

    The failure this exists for, exactly: options "<system> approved by <one body>" and "<system>
    approved by <another>" are offered, the user names only the system, and the designer records
    that and asks the next question - so the approval gate in the built network was chosen by the
    model and the user was never told. The variable is still open, and the transcript is the only
    place that is visible.

    Resolved means the next designer turn puts the tied options back in front of the user. Naming
    just one of them is not resolution: that is the assumption, spelled out.

    :param turns: The recorded turns.
    :param brief_index: Index of the brief, or -1.
    :param result: Accumulates findings.
    :return: Indices of the designer turns that did send an ambiguous answer back for a choice.
    """
    resolved: set[int] = set()
    limit: int = brief_index if brief_index >= 0 else len(turns)
    for index, turn in enumerate(turns):
        if turn.role != ROLE_USER or index == 0 or index >= limit or turns[index - 1].role != ROLE_DESIGNER:
            continue
        options: list[str] = offered_options(turns[index - 1].text)
        if not options or _picked_a_number(turn.text, len(options)):
            continue
        tied: list[str] = tied_options(turn.text, options)
        if not tied:
            continue

        reply: Turn | None = turns[index + 1] if index + 1 < len(turns) else None
        offered_again: list[str] = offered_options(reply.text) if reply is not None else []
        re_offered: set[str] = {option_key(option) for option in offered_again}
        if reply is None or reply.role != ROLE_DESIGNER or len({option_key(one) for one in tied} & re_offered) < 2:
            result.findings.append(
                Finding(
                    kind="AMBIGUITY",
                    detail=(
                        f"the answer {turn.text.strip()[:40]!r} fits {len(tied)} of the options offered and chose "
                        f"between none of them, and the designer did not ask again - it picked one silently"
                    ),
                    turn_index=index,
                )
            )
            continue
        result.clarifications += 1
        resolved.add(index + 1)
    return resolved


def _check_revisions_are_honoured(turns: list[Turn], result: InterviewResult) -> set[int]:
    """
    A user correcting an earlier answer must be taken back to it, not answered past.

    An interview that only moves forward makes the first wrong answer unfixable except by starting
    the session over, and a user who cannot correct one answer will either accept a network built
    on it or abandon the tool. Two failures are worth separating: treating the request as an answer
    to the question on screen, and treating it as a reason to build anyway.

    Honoured means the next designer turn re-asks something - a question with options - rather than
    presenting the brief or writing a network.

    :param turns: The recorded turns.
    :param result: Accumulates findings.
    :return: Indices of the designer turns that did take the user back to an earlier question.
    """
    honoured: set[int] = set()
    for index, turn in enumerate(turns):
        if turn.role != ROLE_USER or not _is_back_request(turn.text):
            continue
        reply: Turn | None = turns[index + 1] if index + 1 < len(turns) else None
        if reply is None or reply.role != ROLE_DESIGNER:
            result.findings.append(
                Finding(kind="REVISION", detail="the user asked to go back and was never answered", turn_index=index)
            )
            continue
        if any(marker in reply.text for marker in BUILT_MARKERS):
            result.findings.append(
                Finding(
                    kind="REVISION",
                    detail="built the network after the user asked to change an earlier answer",
                    turn_index=index + 1,
                )
            )
            continue
        if "?" not in reply.text or len(offered_options(reply.text)) < MIN_OPTIONS:
            result.findings.append(
                Finding(
                    kind="REVISION",
                    detail=(
                        "the user asked to go back and the designer carried on instead of re-asking the "
                        "earlier question"
                    ),
                    turn_index=index + 1,
                )
            )
            continue
        result.revisits += 1
        honoured.add(index + 1)
    return honoured


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

    Clarifications and revisits are already excluded from the count, so the bound stays put however
    many times the user disambiguates an answer or walks back to correct one. That is the point: the
    budget is there to catch an invented interview, and it would be a poor trade if it also made
    going back to the first question look like one.

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
        f"- ambiguous answers sent back for a choice: {result.clarifications}",
        f"- answers the user went back and changed: {result.revisits}",
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
