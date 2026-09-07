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
What a reply MEANS against a list of offered options.

Split out of interview_state, which owns where the interview is; this owns whether a reply settled
the question in front of it. They are separate questions and the module was getting long enough to
hide that, but the real reason to keep them apart is that both this file's callers need the same
answer: the runtime resolves a live reply with it, and interview_review checks a recorded
transcript with it. One definition of "ambiguous" rather than two that agree until someone edits
one of them.

Every rule here is deliberately narrow. A check that fires on ordinary answers is one a reader
learns to wave through, so each of these fires on one shape, and each shape is one that was
observed being guessed at in a real session.
"""

import re

# One offered option as rendered and as parsed: "  1. <text>". The number opens the line, because
# an option the user can answer by number is the whole point - a digit buried in a sentence is
# prose again. Shared with interview_review so what is rendered here is what is recognised there.
OPTION_RE: re.Pattern = re.compile(r"^[ \t]*\d{1,2}[.)][ \t]+(?P<text>\S[^\n]*)$", re.MULTILINE)

# How the user names an option instead of retyping it: "2", "option 2", "#2", "2 and 3".
OPTION_PICK_RE: re.Pattern = re.compile(r"(?:^|\b)(?:option[ \t]*|#)?(\d{1,2})\b")

# Words allowed to keep a reply company and still count as naming option numbers. Anything else
# and the digits are part of an ANSWER, not a choice of option: "4 hours" was read as option 4,
# and "1.29 to 1.31" or "40 databases" would go the same way. A real answer mentioning a number is
# far commoner than a numbered pick dressed up in prose, so the digits only win when almost
# nothing else is there.
PICK_FILLER: frozenset[str] = frozenset(
    {"option", "options", "or", "and", "either", "number", "numbers", "no", "maybe"}
)

# The two escapes appended to every question, in this order, after the pack's own examples.
# Without them a numbered list narrows the answer to whatever got enumerated, and a user whose
# situation is not listed has no honest reply - the numbering would have made guessing tidier
# rather than rarer.
DESCRIBE_ESCAPE: str = "Something else - I will describe it"
UNSURE_ESCAPE: str = "I am not sure - choose a sensible default for me"

# Recognising an escape in text that has already been rendered, for the checker and for a reply
# that quotes one back instead of naming its number.
ESCAPE_MARKERS: tuple[str, ...] = ("not sure", "something else", "you decide", "sensible default", "don't know")

# The fewest options that make a choice: at least one real answer plus the two escapes.
MIN_OPTIONS: int = 3


def option_key(text: str) -> str:
    """
    Reduce an answer or an option to comparable characters only.

    Letters and digits, lowercased, everything else dropped - so "service now CR" and "ServiceNow
    CR" are one key. That matters here specifically: the shortenings a user actually types differ
    from the curated wording in spacing and punctuation far more often than in words, and a
    comparison that missed those would miss the case this exists for.

    :param text: Any fragment.
    :return: The comparison key.
    """
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def is_escape(option: str) -> bool:
    """
    :param option: One offered option.
    :return: True when the option is an escape rather than a candidate answer.
    """
    lowered: str = option.lower()
    return any(marker in lowered for marker in ESCAPE_MARKERS)


def consistent_options(reply: str, options: list[str] | tuple[str, ...]) -> list[str]:
    """
    The offered options a reply is consistent with. One question, asked once.

    The whole of matching reduces to this count, and the two callers that used to own it were the
    same computation with different length branches: "more than one" meant settle nothing, "exactly
    one" meant it had chosen in fewer words than the pack uses. Keeping them apart meant the
    containment rule was written twice, and a change to one would not reach the other.

    The rule is deliberately narrow: the reply's key must be a PROPER substring of the option's key,
    so the reply says less than the option and everything it does say the option also says. An
    answer matching nothing on offer is the user describing something else in their own words, which
    is a complete answer and not this function's business.

    Narrow on purpose. A broader notion needs judgement, and a check that fires on ordinary answers
    is one a reader learns to wave through. Where judgement IS wanted, a matcher supplies it - see
    interview_matcher - and this stays the fallback that needs no model.

    :param reply: What the user said.
    :param options: The options that were offered.
    :return: The options it could have meant, in the order offered.
    """
    key: str = option_key(reply)
    if not key:
        return []
    return [
        option
        for option in options
        if not is_escape(option) and key != option_key(option) and key in option_key(option)
    ]


def tied_options(reply: str, options: list[str] | tuple[str, ...]) -> list[str]:
    """
    The options a reply is consistent with but does not choose between.

    :param reply: What the user said.
    :param options: The options that were offered.
    :return: The tied options, or an empty list when the reply settles the question.
    """
    consistent: list[str] = consistent_options(reply, options)
    return consistent if len(consistent) > 1 else []


def sole_match(reply: str, options: list[str] | tuple[str, ...]) -> str | None:
    """
    The one option a reply identifies, when it identifies exactly one.

    :param reply: What the user said.
    :param options: The options that were offered.
    :return: That option's curated text, or None when it identifies none or several.
    """
    consistent: list[str] = consistent_options(reply, options)
    return consistent[0] if len(consistent) == 1 else None


def offered_options(text: str) -> list[str]:
    """
    :param text: Rendered question text.
    :return: The text of each numbered option it offers, in order.
    """
    return [match.group("text").strip() for match in OPTION_RE.finditer(text)]


def names_only_numbers(text: str) -> bool:
    """
    Whether a reply is naming option numbers rather than answering in words that contain a number.

    "1", "1 or 4", "option 2" and "#3" choose options. "4 hours", "40 databases" and "1.29 to 1.31"
    are answers - and the first of those was read as option 4 in a live interview, which silently
    took the describe escape on the user's behalf.

    :param text: The reply.
    :return: True when the reply is digits and connectives and nothing else.
    """
    words: list[str] = re.findall(r"[a-z0-9]+", text.lower().replace("#", " "))
    if not any(word.isdigit() for word in words):
        return False
    return all(word.isdigit() or word in PICK_FILLER for word in words)
