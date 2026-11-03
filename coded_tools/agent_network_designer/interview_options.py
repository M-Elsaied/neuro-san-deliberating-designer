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


class InterviewOptions:
    """
    Decides what a reply means against the options offered. The interview resolves live replies with it and the
    transcript review checks recorded ones, so both share one definition of "ambiguous". Each rule is narrow, and
    fires on one shape of reply that was seen being guessed at in a real session.
    """

    # One offered option, "  1. <text>": the number opens the line, since a digit inside a sentence is prose.
    OPTION_RE: re.Pattern = re.compile(r"^[ \t]*\d{1,2}[.)][ \t]+(?P<text>\S[^\n]*)$", re.MULTILINE)
    # How a reply names an option rather than retyping it: "2", "option 2", "#2", "2 and 3".
    OPTION_PICK_RE: re.Pattern = re.compile(r"(?:^|\b)(?:option[ \t]*|#)?(\d{1,2})\b")
    # The only words allowed beside option numbers. With any other the digits are an answer, as in "4 hours".
    PICK_FILLER: frozenset[str] = frozenset(
        "option options or and either number numbers no maybe the one please".split()
    )
    # A position said in words, as in "the second one", is read as the number it stands for.
    ORDINALS: dict[str, str] = dict(
        zip("first second third fourth fifth sixth seventh eighth ninth tenth".split(), "1 2 3 4 5 6 7 8 9 10".split())
    )
    # Offered after the pack's own examples, in this order, so a user whose answer is not listed has an honest reply.
    DESCRIBE_ESCAPE: str = "Something else - I will describe it"
    UNSURE_ESCAPE: str = "I am not sure - choose a sensible default for me"
    # The phrases that take each escape in words, as "I'm not sure" does when the reply says nothing else.
    ESCAPE_PHRASES: dict[str, tuple[str, ...]] = {
        DESCRIBE_ESCAPE: ("something else",),
        UNSURE_ESCAPE: ("not sure", "you decide", "sensible default", "don't know"),
    }
    ESCAPE_MARKERS: tuple[str, ...] = ESCAPE_PHRASES.get(DESCRIBE_ESCAPE) + ESCAPE_PHRASES.get(UNSURE_ESCAPE)
    # Words a reply may add to an escape's own and still mean only that escape.
    ESCAPE_FILLER: str = "i'm im i'll really honestly just please sorry"
    # How a reply accepts or declines the one option a "confirm" offered back, reduced as get_key() reduces it.
    YES_KEYS: frozenset[str] = frozenset("yes y yeah yep yup correct right exactly ok okay sure thatsright".split())
    NO_KEYS: frozenset[str] = frozenset("no n nope wrong incorrect notquite".split())
    # The fewest options that make a choice: one real answer and the two escapes.
    MIN_OPTIONS: int = 3

    @staticmethod
    def get_key(text: str) -> str:
        """
        Reduce text to comparable characters, so "service now CR" and "ServiceNow CR" compare equal.

        :param text: An answer or an option.
        :return: Its letters and digits, lowercased.
        """
        return re.sub(r"[^a-z0-9]+", "", text.lower())

    @staticmethod
    def is_escape(option: str) -> bool:
        """
        Check whether an option reads as "something else" or "not sure" rather than as an answer.

        :param option: One offered option.
        :return: True for an escape.
        """
        for marker in InterviewOptions.ESCAPE_MARKERS:
            if marker in option.lower():
                return True
        return False

    @staticmethod
    def get_consistent_options(reply: str, options: list[str] | tuple[str, ...]) -> list[str]:
        """
        Find the offered options a reply could mean: those it says less than, everything it says being in them.

        :param reply: What the user said.
        :param options: The options offered.
        :return: Those options in the order offered, never an escape. None means an answer in the user's own words.
        """
        key: str = InterviewOptions.get_key(reply)
        consistent: list[str] = []
        for option in options:
            option_key: str = InterviewOptions.get_key(option)
            if key and not InterviewOptions.is_escape(option) and key != option_key and key in option_key:
                consistent.append(option)
        return consistent

    @staticmethod
    def get_tied_options(reply: str, options: list[str] | tuple[str, ...]) -> list[str]:
        """
        Find the options a reply could mean but does not choose between.

        :param reply: What the user said.
        :param options: The options offered.
        :return: The tied options, or [] when the reply could mean at most one.
        """
        consistent: list[str] = InterviewOptions.get_consistent_options(reply, options)
        return consistent if len(consistent) > 1 else []

    @staticmethod
    def get_offered_options(text: str) -> list[str]:
        """
        Read the numbered options out of a rendered question.

        :param text: A rendered question.
        :return: Each option's text, in order.
        """
        offered: list[str] = []
        for match in InterviewOptions.OPTION_RE.finditer(text):
            offered.append(match.group("text").strip())
        return offered

    @staticmethod
    def names_only_numbers(text: str) -> bool:
        """
        Check whether a reply names option numbers, as "1 or 4" does, rather than answering as "4 hours" does.

        :param text: The reply.
        :return: True when it is only digits and the words allowed beside them.
        """
        has_digit: bool = False
        for word in re.findall(r"[a-z0-9]+", text.lower().replace("#", " ")):
            if word.isdigit():
                has_digit = True
            elif word not in InterviewOptions.PICK_FILLER:
                return False
        return has_digit

    @staticmethod
    def spell_ordinals(text: str) -> str:
        """
        Write each position said in words as its number, so "the second one" names option 2 as "2" does.

        :param text: The reply.
        :return: The reply, lowercased, with each ordinal word replaced by its number.
        """
        words: list[str] = []
        for word in text.lower().split():
            words.append(InterviewOptions.ORDINALS.get(word.strip(".,!?"), word))
        return " ".join(words)

    @staticmethod
    def get_escape(reply: str) -> str:
        """
        Find the escape a reply takes in words, as "I'm not sure" and "something else" do.

        :param reply: What the user said.
        :return: That escape, or "" when the reply names none or says anything the escape does not.
        """
        lowered: str = reply.lower().replace("\u2019", "'")
        words: set[str] = set(re.findall(r"[a-z']+", lowered))
        for escape, phrases in InterviewOptions.ESCAPE_PHRASES.items():
            vocabulary: str = " ".join((escape.lower(), *phrases, InterviewOptions.ESCAPE_FILLER))
            for phrase in phrases:
                if phrase in lowered and words <= set(re.findall(r"[a-z']+", vocabulary)):
                    return escape
        return ""
