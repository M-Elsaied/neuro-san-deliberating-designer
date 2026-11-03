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
from dataclasses import replace

from coded_tools.agent_network_designer.interview_outcome import InterviewOutcome
from coded_tools.agent_network_designer.interview_renderer import InterviewRenderer
from coded_tools.agent_network_designer.interview_state import InterviewState


class InterviewNavigator:
    """
    Takes the interview back to an earlier entry so its answer can be replaced: by a count, a label, a number or a
    topic. A request that could mean more than one entry is asked about, since picking one turns a correction into a
    different wrong answer. There is no limit, and the answers in between keep their values.
    """

    BACK_DISTANCE_RE: re.Pattern = re.compile(
        r"\bback\s+(\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten)\b", re.IGNORECASE
    )
    WORD_NUMBERS: dict[str, int] = dict(zip("one two three four five six seven eight nine ten".split(), range(1, 11)))
    # Words that say how to get somewhere rather than where, and the fillers a correction arrives in. They decide
    # only whether a request names a subject; any other word that matches no entry is reported, not guessed at.
    NAVIGATION_WORDS: frozenset[str] = frozenset(
        "about above actually again answer answered back before change correct earlier first from going have hold "
        "ignore instead just last made make mean meant need nope okay oops option options please previous prior "
        "question questions recent redo revise said scratch sorry step take that then there this undo wait want "
        "wanted well what with wrong".split()
    )
    # Naming the start rather than counting to it, where every word is a navigation word.
    FIRST_RE: re.Pattern = re.compile(
        r"\b(?:very\s+first|first\s+question|first\s+one|the\s+first|the\s+beginning|the\s+start|"
        r"all\s+the\s+way\s+back|right\s+back)\b",
        re.IGNORECASE,
    )
    LABEL_RE: re.Pattern = re.compile(r"\bq\s*(\d{1,2})\b", re.IGNORECASE)
    BARE_NUMBER_RE: re.Pattern = re.compile(r"^\D*(\d{1,2})\D*$")

    @staticmethod
    def go_back(state: InterviewState, target: str = "") -> InterviewOutcome:
        """
        Move to the entry a request names, and show the log with its question asked again.

        :param state: The interview.
        :param target: How the user named the entry. Empty means one back.
        :return: The outcome, carrying the state after it.
        """
        resolved: int | InterviewOutcome = InterviewNavigator.resolve(state, target)
        if isinstance(resolved, InterviewOutcome):
            return replace(resolved, state=state)
        moved: InterviewState = replace(state, cursor=resolved, offered=())
        distance: int | None = InterviewNavigator.get_distance(target)
        note: str = ""
        if resolved == 0 and distance is not None and distance > state.cursor:
            note = "That is further back than the first question, so this is the first one."
        log: str = "\n".join(["Here is what I have on file:", "", *InterviewRenderer.get_log_lines(moved), ""])
        lead: str = f"Back to {moved.current.label}."
        prompt: str = f"{log}\n{InterviewRenderer.render(moved, lead=lead)}"
        return InterviewOutcome(InterviewOutcome.REOPENED, moved, prompt, moved.current, note=note)

    @staticmethod
    def resolve(state: InterviewState, target: str) -> int | InterviewOutcome:
        """
        Work out which entry a request names: by a label, a count, a number or a topic, else the one before.

        :param state: The interview.
        :param target: How the user named the entry.
        :return: The entry's index, or the outcome to return when the request names no single entry.
        """
        text: str = target.strip()
        label: re.Match | None = InterviewNavigator.LABEL_RE.search(text)
        distance: int | None = InterviewNavigator.get_distance(text)
        bare: re.Match | None = InterviewNavigator.BARE_NUMBER_RE.match(text)
        if not text:
            return max(state.cursor - 1, 0)
        if label is not None:
            return InterviewNavigator.resolve_number(state, int(label.group(1)))
        if distance is not None:
            return InterviewNavigator.resolve_count(state, text, distance)
        if bare is not None:
            return InterviewNavigator.resolve_number(state, int(bare.group(1)))
        # Naming no count, label or subject, as "wait, go back" does, is a bare "go back".
        if not InterviewNavigator.get_subject_words(text) and InterviewNavigator.FIRST_RE.search(text) is None:
            return max(state.cursor - 1, 0)
        return InterviewNavigator.resolve_topic(state, text)

    @staticmethod
    def resolve_count(state: InterviewState, text: str, distance: int) -> int | InterviewOutcome:
        """
        Resolve a count back, clamped to the first entry, asking when a subject in it names another entry.

        :param state: The interview.
        :param text: The request.
        :param distance: How many entries back it counts.
        :return: The entry's index, or a "choose" outcome when the subject names another entry.
        """
        counted: int = max(state.cursor - distance, 0)
        named: int | InterviewOutcome = InterviewNavigator.resolve_topic(state, text)
        if not isinstance(named, int) or named == counted:
            return counted
        lines: list[str] = InterviewRenderer.get_log_lines(state)
        candidates: tuple[str, ...] = (lines[counted], lines[named])
        question: str = "That counts back to one answer and names another - which did you mean?"
        prompt: str = "\n".join([question, "", *candidates, ""]) + "\nName it by its label."
        return InterviewOutcome(
            InterviewOutcome.CHOOSE, None, prompt, None, candidates, "the count and the subject disagree"
        )

    @staticmethod
    def resolve_number(state: InterviewState, number: int) -> int | InterviewOutcome:
        """
        Resolve an entry named by its number.

        :param state: The interview.
        :param number: The entry number, from 1.
        :return: The entry's index, or an "unknown" outcome showing the log when no visible entry has it.
        """
        if 1 <= number <= len(state.visible):
            return number - 1
        heading: str = "I have no entry with that number. Here is what I have on file:"
        prompt: str = "\n".join([heading, "", *InterviewRenderer.get_log_lines(state)])
        return InterviewOutcome(
            InterviewOutcome.UNKNOWN, prompt=prompt, note=f"asked for entry {number} of {len(state.visible)}"
        )

    @staticmethod
    def resolve_topic(state: InterviewState, text: str) -> int | InterviewOutcome:
        """
        Resolve an entry by matching the request's subject words against each visible entry's question and answer.

        :param state: The interview.
        :param text: The request, in the user's words.
        :return: The entry's index when exactly one matches, else an outcome to show the log or the matches.
        """
        if InterviewNavigator.FIRST_RE.search(text) is not None:
            return 0
        lines: list[str] = InterviewRenderer.get_log_lines(state)
        hits: list[str] = []
        index_of: int = -1
        for index, entry in enumerate(state.visible):
            haystack: str = f"{entry.question} {entry.answer}".lower()
            for word in InterviewNavigator.get_subject_words(text):
                if word in haystack:
                    hits.append(lines[index])
                    index_of = index
                    break
        if len(hits) == 1:
            return index_of
        if not hits:
            heading: str = "I could not tell which answer you mean. Here is what I have on file:"
            prompt: str = "\n".join([heading, "", *lines, ""]) + "\nWhich one would you like to change?"
            return InterviewOutcome(InterviewOutcome.UNKNOWN, prompt=prompt, note="no entry matched")
        heading = "More than one of these could be what you mean - which one?"
        prompt = "\n".join([heading, "", *hits, ""]) + "\nName it by its label."
        return InterviewOutcome(
            InterviewOutcome.CHOOSE, None, prompt, None, tuple(hits), f"{len(hits)} entries matched"
        )

    @staticmethod
    def get_subject_words(text: str) -> list[str]:
        """
        Find the words in a request that name what it is about rather than how to get there.

        :param text: How the user named the entry.
        :return: The subject words, which may be none.
        """
        words: list[str] = []
        for word in re.findall(r"[a-z0-9]+", text.lower()):
            if (
                len(word) > 3
                and word not in InterviewNavigator.NAVIGATION_WORDS | InterviewNavigator.WORD_NUMBERS.keys()
            ):
                words.append(word)
        return words

    @staticmethod
    def get_distance(text: str) -> int | None:
        """
        Read how many entries back a request asks for.

        :param text: How the user named the entry.
        :return: The count, or None when it gives none.
        """
        match: re.Match | None = InterviewNavigator.BACK_DISTANCE_RE.search(text)
        if match is None:
            return None
        found: str = match.group(1).lower()
        return int(found) if found.isdigit() else InterviewNavigator.WORD_NUMBERS.get(found)
