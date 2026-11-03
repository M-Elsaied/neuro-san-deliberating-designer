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
import sys
from argparse import ArgumentParser
from argparse import Namespace
from pathlib import Path
from typing import Any

from coded_tools.agent_network_designer.interview_gate_checks import InterviewGateChecks
from coded_tools.agent_network_designer.interview_options import InterviewOptions
from coded_tools.agent_network_designer.interview_renderer import InterviewRenderer
from coded_tools.agent_network_designer.interview_review_result import InterviewReviewResult
from coded_tools.agent_network_designer.knowledge_pack import KnowledgePack
from coded_tools.agent_network_designer.pack_reader import PackReader


class InterviewReview:
    """
    Checks a recorded deliberation against the behavior the designer promises, with no model, for committed and live
    transcripts alike. Only structural properties are checked, never the judgment behind a question.
    """

    # Questions beyond the pack's open variables tolerated before the interview plainly comes from elsewhere.
    QUESTION_ALLOWANCE: int = 2
    # How a user asks to change an earlier answer. Broad, since the reply that must never happen is the designer
    # treating the request as an answer to the question on screen.
    BACK_REQUESTS: tuple[str, ...] = tuple(
        "go back|going back|take me back|back to question|previous question|earlier question|change my answer|change "
        "what i said|change question|revise my answer|answered that wrong|got that wrong|start again from".split("|")
    )

    @staticmethod
    def review(
        turns: list[dict[str, str]], pack: KnowledgePack, other_ids: set[str] | None = None
    ) -> InterviewReviewResult:
        """
        Check a recorded deliberation.

        :param turns: The recorded {"role", "text"} turns, in order.
        :param pack: The pack the deliberation interviewed from.
        :param other_ids: The standard ids of every other pack, none of which may appear.
        :return: The findings and counts.
        """
        result: InterviewReviewResult = InterviewReviewResult(pack.domain_id, open_variables=len(pack.open_variables))
        brief: int = InterviewGateChecks.find_turn(turns, InterviewGateChecks.DESIGNER, "DESIGN BRIEF")
        limit: int = brief if brief >= 0 else len(turns)
        # First, since a designer turn that genuinely asks again is not counted as a new question.
        reasks: set[int] = InterviewReview.check_ambiguity(turns, limit, result) | InterviewReview.check_revisions(
            turns, result
        )
        seen: set[str] = set()
        for index in InterviewGateChecks.get_turns(turns, InterviewGateChecks.DESIGNER, limit):
            text: str = turns[index].get("text")
            key: str = InterviewReview.get_question_key(text)
            # Distinct questions, since after a correction the interview asks the open question again.
            if index not in reasks and text.count("?") and key not in seen:
                result.questions_asked += 1
            seen.add(key)
            if text.count("?") > 1:
                detail: str = f"asked {text.count('?')} questions in one turn; the interview is one at a time"
                InterviewGateChecks.add(result, "INTERVIEW", detail, index)
        InterviewReview.check_options(turns, limit, result)
        InterviewGateChecks.check(turns, pack, other_ids or set(), result)
        if (
            result.open_variables
            and result.questions_asked > result.open_variables + InterviewReview.QUESTION_ALLOWANCE
        ):
            detail = (
                f"asked {result.questions_asked} questions where the pack declares {result.open_variables} open "
                f"variables; the extras did not come from curated knowledge"
            )
            InterviewGateChecks.add(result, "INTERVIEW", detail)
        return result

    @staticmethod
    def check_options(turns: list[dict[str, str]], limit: int, result: InterviewReviewResult) -> None:
        """
        Report a question that is not a numbered choice with an escape, except a refusal to skip.

        :param turns: The recorded turns.
        :param limit: The index of the brief, after which nothing is checked.
        :param result: Collects the findings.
        """
        for index in InterviewGateChecks.get_turns(turns, InterviewGateChecks.DESIGNER, limit):
            text: str = turns[index].get("text")
            previous: dict[str, str] = turns[index - 1] if index else {}
            refusal: bool = previous.get("role") == InterviewGateChecks.USER and InterviewGateChecks.mentions(
                previous.get("text"), InterviewGateChecks.SKIP_REQUESTS, True
            )
            if "?" not in text or refusal:
                continue
            options: list[str] = InterviewOptions.get_offered_options(text)
            if len(options) < InterviewOptions.MIN_OPTIONS:
                detail: str = (
                    f"asked a question offering {len(options)} numbered options; a question the user can answer "
                    f"exactly needs at least {InterviewOptions.MIN_OPTIONS}, the last of them an escape"
                )
                InterviewGateChecks.add(result, "OPTIONS", detail, index)
            elif not InterviewGateChecks.mentions("\n".join(options), InterviewOptions.ESCAPE_MARKERS, True):
                detail = (
                    "offered numbered options with no 'something else' or 'not sure' escape, so a user whose answer "
                    "is not listed has to pick a wrong one"
                )
                InterviewGateChecks.add(result, "OPTIONS", detail, index)

    @staticmethod
    def check_ambiguity(turns: list[dict[str, str]], limit: int, result: InterviewReviewResult) -> set[int]:
        """
        Report an answer fitting several options that the designer moved past rather than offering them again.

        :param turns: The recorded turns.
        :param limit: The index of the brief, after which nothing is checked.
        :param result: Collects the findings and counts the clarifications.
        :return: The designer turns that did send an ambiguous answer back for a choice.
        """
        resolved: set[int] = set()
        for index in InterviewGateChecks.get_turns(turns, InterviewGateChecks.USER, limit):
            if not index or turns[index - 1].get("role") != InterviewGateChecks.DESIGNER:
                continue
            text: str = turns[index].get("text")
            options: list[str] = InterviewOptions.get_offered_options(turns[index - 1].get("text"))
            tied: list[str] = InterviewOptions.get_tied_options(text, options)
            if not options or InterviewReview.picks_a_number(text, len(options)) or not tied:
                continue
            reply: dict[str, str] = turns[index + 1] if index + 1 < len(turns) else {}
            again: set[str] = set()
            for option in InterviewOptions.get_offered_options(reply.get("text", "")):
                again.add(InterviewOptions.get_key(option))
            tied_keys: set[str] = set()
            for option in tied:
                tied_keys.add(InterviewOptions.get_key(option))
            if reply.get("role") != InterviewGateChecks.DESIGNER or len(tied_keys & again) < 2:
                detail: str = (
                    f"the answer {text.strip()[:40]!r} fits {len(tied)} of the options offered and chose between none "
                    f"of them, and the designer did not ask again - it picked one silently"
                )
                InterviewGateChecks.add(result, "AMBIGUITY", detail, index)
            else:
                result.clarifications += 1
                resolved.add(index + 1)
        return resolved

    @staticmethod
    def check_revisions(turns: list[dict[str, str]], result: InterviewReviewResult) -> set[int]:
        """
        Report a request to change an earlier answer that was answered past or built on rather than asked again.

        :param turns: The recorded turns.
        :param result: Collects the findings and counts the revisits.
        :return: The designer turns that took the user back to an earlier question.
        """
        honored: set[int] = set()
        for index in InterviewGateChecks.get_turns(turns, InterviewGateChecks.USER):
            if not InterviewGateChecks.mentions(turns[index].get("text"), InterviewReview.BACK_REQUESTS, True):
                continue
            reply: dict[str, str] = turns[index + 1] if index + 1 < len(turns) else {}
            text: str = reply.get("text", "")
            if reply.get("role") != InterviewGateChecks.DESIGNER:
                InterviewGateChecks.add(result, "REVISION", "the user asked to go back and was never answered", index)
            elif InterviewGateChecks.mentions(text, InterviewGateChecks.BUILT_MARKERS):
                detail: str = "built the network after the user asked to change an earlier answer"
                InterviewGateChecks.add(result, "REVISION", detail, index + 1)
            elif "?" not in text or len(InterviewOptions.get_offered_options(text)) < InterviewOptions.MIN_OPTIONS:
                detail = (
                    "the user asked to go back and the designer carried on instead of re-asking the earlier question"
                )
                InterviewGateChecks.add(result, "REVISION", detail, index + 1)
            else:
                result.revisits += 1
                honored.add(index + 1)
        return honored

    @staticmethod
    def get_question_key(text: str) -> str:
        """
        Identify the question a turn asks, so asking it again counts once. InterviewLog prints the reason for the
        question above its closing line, and a re-ask keeps it under a first line of its own, so that reason is the
        key when there is one, and otherwise the first line with a question mark is.

        :param text: A designer turn.
        :return: That line reduced to comparable characters, or "" when the turn asks nothing.
        """
        lines: list[str] = text.split("\n")
        for index, line in enumerate(lines):
            if index and line.strip() == InterviewRenderer.CLOSING_LINE and lines[index - 1].strip():
                return InterviewOptions.get_key(lines[index - 1])
        for line in lines:
            if "?" in line:
                return InterviewOptions.get_key(line)
        return ""

    @staticmethod
    def picks_a_number(reply: str, option_count: int) -> bool:
        """
        Check whether a reply names one of the offered option numbers.

        :param reply: What the user said.
        :param option_count: How many options were offered.
        :return: True if it names at least one of them.
        """
        for match in InterviewOptions.OPTION_PICK_RE.finditer(reply):
            if 1 <= int(match.group(1)) <= option_count:
                return True
        return False

    @staticmethod
    def read_transcript(path: str | Path) -> dict[str, Any]:
        """
        Read a recorded transcript: a JSON object with a "domain" and "turns", each with a "role" and "text".

        :param path: The transcript file.
        :return: The transcript, its turns normalized to {"role", "text"} strings.
        :raises ValueError: If the file cannot be read or is not a transcript.
        """
        try:
            raw: Any = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exception:
            raise ValueError(f"Could not read transcript {path}: {exception}") from exception
        if not isinstance(raw, dict) or "turns" not in raw:
            raise ValueError(f"{path} does not look like a transcript: expected an object with 'turns'.")
        if not isinstance(raw.get("turns"), list):
            raise ValueError(f"{path} does not look like a transcript: 'turns' must be a list.")
        turns: list[dict[str, str]] = []
        for entry in raw.get("turns"):
            if not isinstance(entry, dict):
                raise ValueError(f"{path} does not look like a transcript: each turn needs a 'role' and 'text'.")
            turns.append({"role": str(entry.get("role", "")), "text": str(entry.get("text", ""))})
        return {"domain": str(raw.get("domain", "")), "turns": turns}

    @staticmethod
    def render(result: InterviewReviewResult) -> str:
        """
        Render a review as markdown.

        :param result: The review.
        :return: The counts, then every finding, or a line saying there were none.
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
            return "\n".join([*lines, "The deliberation followed the promised behavior in every checked respect."])
        lines.extend([f"**{len(result.findings)} departures from the promised behavior:**", ""])
        for finding in result.findings:
            lines.append(f"- {finding}")
        return "\n".join(lines)

    @staticmethod
    def main(argv: list[str] | None = None) -> int:
        """
        Review a recorded transcript from the command line.

        :param argv: The arguments, or None to read sys.argv.
        :return: 0 when the deliberation kept every promise checked, 1 when it did not, 2 on a usage error.
        """
        parser: ArgumentParser = ArgumentParser(
            description="Check a recorded deliberation transcript against the designer's promised behavior."
        )
        parser.add_argument("transcript", help="path to a transcript JSON file")
        parser.add_argument("--domain", default=None, help="override the domain recorded in the transcript")
        parser.add_argument("--knowdocs", default=None, help="override the knowdocs root")
        arguments: Namespace = parser.parse_args(argv)
        try:
            transcript: dict[str, Any] = InterviewReview.read_transcript(arguments.transcript)
        except ValueError as exception:
            print(f"Error: {exception}", file=sys.stderr)
            return 2
        domain_id: str = arguments.domain or transcript.get("domain")
        pack: KnowledgePack | None = None
        other_ids: set[str] = set()
        available: list[str] = []
        for candidate in PackReader.load_catalog(arguments.knowdocs):
            available.append(candidate.domain_id)
            if candidate.domain_id == domain_id:
                pack = candidate
                continue
            for standard in candidate.standards:
                other_ids.add(standard.standard_id)
        if pack is None:
            print(
                f"Error: no pack for domain {domain_id!r}. Available: {', '.join(available) or 'none'}",
                file=sys.stderr,
            )
            return 2
        result: InterviewReviewResult = InterviewReview.review(transcript.get("turns"), pack, other_ids)
        print(InterviewReview.render(result))
        return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(InterviewReview.main())
