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
The interview as state, not as something the model remembers.

WHY THIS EXISTS
---------------
The prompt can tell the designer to keep an answer log, ask one question at a time and let the user
walk back to any earlier answer. It cannot make any of that true. A log held in a language model's
context drifts: entries get relabelled, an answer is silently rewritten to fit a later one, "back
three" lands two questions away, and the answers a correction should have left alone come back
subtly changed. None of it errors, and all of it is invisible until someone reads the transcript
against what they actually said.

So position and history are computed here instead. This module owns:

  * the entry list, one per open variable, labelled once at the start and never relabelled;
  * which entry is on screen;
  * what each answer was, and whether it came from the user or was assumed;
  * where "back three", "Q2" or a topic actually lands;
  * whether an answer settled the question or is consistent with several offered options.

It is the same move VerifyStandards made for the coverage table: the model stops reporting on its
own bookkeeping and starts printing a computed result. render() returns the exact text of the next
question, so the designer's job is to print it rather than to reconstruct it.

WHERE THE LINE IS
-----------------
Bookkeeping is computed here; domain judgement is not, and must not be. This module has no idea
what any answer MEANS. It cannot pick a sensible default, because a default is a domain fact and
the method layer holds none - so an "I am not sure" reply comes back as ASSUME, for the model to
answer with a default of its own. It cannot tell that a corrected answer contradicts a later one,
because that too is domain knowledge - it reports what changed and leaves the reading to the model.

What it can do is refuse to lose track, which is the part the model was never going to get right.

No neuro-san import: the state machine runs in a unit test with no agent runtime, and the CodedTool
in interview_log is only the adapter. interview_review imports the option and ambiguity primitives
from here too, so the runtime's notion of "ambiguous" and the checker's are the same one rather
than two definitions that agree until someone edits one.
"""

import re
from dataclasses import dataclass
from dataclasses import replace
from typing import Any

from coded_tools.agent_network_designer.interview_matcher import DeterministicMatcher
from coded_tools.agent_network_designer.interview_matcher import Matcher
from coded_tools.agent_network_designer.interview_options import DESCRIBE_ESCAPE
from coded_tools.agent_network_designer.interview_options import OPTION_PICK_RE
from coded_tools.agent_network_designer.interview_options import UNSURE_ESCAPE
from coded_tools.agent_network_designer.interview_options import names_only_numbers
from coded_tools.agent_network_designer.interview_options import option_key
from coded_tools.agent_network_designer.knowledge_pack import KnowledgePack

# sly_data key holding the interview. Must also be declared in the front man's
# allow.to_upstream.sly_data, or it does not survive a turn: session sly_data is rebuilt from the
# client's payload each time, so a key written on one turn is discarded unless it goes out to the
# client and comes back. The whole point of this module is state that outlives a turn, so that
# declaration is not optional bookkeeping - without it there is no log at all.
INTERVIEW_LOG: str = "agent_network_interview_log"
# "back two", "back 2". Words as well as digits, because users type both.
BACK_DISTANCE_RE: re.Pattern = re.compile(
    r"\bback\s+(\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten)\b", re.IGNORECASE
)
WORD_NUMBERS: dict[str, int] = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}

# Words that describe the NAVIGATION rather than the subject being navigated to, plus the fillers a
# correction actually arrives wrapped in. Two jobs, both needed:
#
#   * a request like "back three - I got the window wrong" matches on "back", which appears in an
#     unrelated question, so the one word that identified the entry is outvoted by the ones that
#     only said how to get there;
#   * "wait, go back" names no entry, and must be read as a bare go-back rather than as a subject
#     nothing matches. Users type "wait", "sorry", "hold on", "scratch that" constantly, and
#     without them here every one of those turns a working request into "I could not tell which
#     answer you mean".
#
# The list only decides whether a subject was NAMED. A word that survives it and still matches no
# entry is a real subject the user got wrong, and is reported as such rather than guessed at.
NAVIGATION_WORDS: frozenset[str] = frozenset(
    {
        "about",
        "actually",
        "again",
        "answer",
        "answered",
        "back",
        "change",
        "correct",
        "earlier",
        "first",
        "from",
        "going",
        "have",
        "hold",
        "ignore",
        "instead",
        "just",
        "last",
        "made",
        "make",
        "mean",
        "meant",
        "need",
        "nope",
        "okay",
        "oops",
        "option",
        "options",
        "prior",
        "before",
        "above",
        "step",
        "recent",
        "please",
        "previous",
        "question",
        "questions",
        "redo",
        "revise",
        "said",
        "scratch",
        "sorry",
        "take",
        "that",
        "then",
        "there",
        "this",
        "undo",
        "wait",
        "want",
        "wanted",
        "well",
        "what",
        "with",
        "wrong",
    }
)

# Naming the start rather than counting to it: "take me back to the first question", "start again
# from the beginning". Needed because every word in those phrases is a navigation word, so topic
# matching sees nothing left to match on and the request looks unintelligible - and this is one of
# the phrasings the prompt promises to honour.
FIRST_RE: re.Pattern = re.compile(
    r"\b(?:very\s+first|first\s+question|first\s+one|the\s+first|the\s+beginning|the\s+start|"
    r"all\s+the\s+way\s+back|right\s+back)\b",
    re.IGNORECASE,
)

# An entry label as the user names it: "Q3", "q3", or a bare "3".
LABEL_RE: re.Pattern = re.compile(r"\bq\s*(\d{1,2})\b", re.IGNORECASE)
BARE_NUMBER_RE: re.Pattern = re.compile(r"^\D*(\d{1,2})\D*$")

# Outcome statuses. The model branches on these, so they are named for what it must do next.
RECORDED: str = "recorded"
AMBIGUOUS: str = "ambiguous"
CONFIRM: str = "confirm"
DESCRIBE: str = "describe"
ASSUME: str = "assume"
COMPLETE: str = "complete"
REOPENED: str = "reopened"
CHOOSE: str = "choose"
UNKNOWN: str = "unknown"


@dataclass(frozen=True)
class Entry:
    """
    One open variable, and whatever is known about it.

    Frozen because an entry is only ever replaced, never mutated in place: a correction that edits
    an entry under the caller's feet is precisely the drift this module exists to stop.
    """

    label: str
    variable_id: str
    question: str
    options: tuple[str, ...]
    why: str
    answer: str = ""
    assumed: bool = False

    @property
    def answered(self) -> bool:
        """:return: True when this entry has an answer on file."""
        return bool(self.answer)

    @property
    def subject(self) -> str:
        """
        The question's own subject, for the log line.

        Open variables are written "<subject>: <the question>", so the part before the first colon
        is the pack author's own name for the variable. Falls back to the whole question when a
        pack does not use that shape, because a log line is more useful truncated than absent.

        :return: A short label for the log.
        """
        head: str = self.question.split(":", 1)[0].strip()
        return head if head and len(head) < len(self.question) else self.question.rstrip("?").strip()


@dataclass(frozen=True)
class Outcome:
    """What the caller must do next, and the text to print in order to do it."""

    status: str
    prompt: str = ""
    entry: Entry | None = None
    candidates: tuple[str, ...] = ()
    note: str = ""
    # The option list the prompt DISPLAYED, when it is not the entry's own. A narrowed re-ask
    # renumbers from 1, so the next reply's "1" means the first thing on screen and not the first
    # option in the pack. Carrying it here is what lets the state remember that. Empty means the
    # entry's own options were shown.
    shown: tuple[str, ...] = ()


@dataclass(frozen=True)
class InterviewState:
    """
    The interview so far: every entry, and which one is on screen.

    Labels are assigned once, when the state is built from the pack, and never reassigned -
    re-answering Q3 leaves it Q3. That stability is what makes "back to Q3" mean something
    definite, and it is the reason entries for questions not yet reached exist from the start
    rather than being appended as the interview goes.
    """

    domain_id: str
    entries: tuple[Entry, ...]
    cursor: int = 0
    # Whether the questions came from a curated pack. False means the designer derived them for a
    # domain this deployment has no pack for. The machinery is identical either way - what differs
    # is what may be CLAIMED about the result, and the brief has to keep saying "standards are not
    # verified" for the whole session, not only in the sentence that opened it.
    curated: bool = True
    # What is on screen right now, when a re-ask narrowed the list. A number in the next reply is
    # resolved against THIS, not against the entry's options: a live run offered a single narrowed
    # option, the user typed "1", and it recorded the pack's first option instead. The ambiguity
    # re-ask had the same fault and was right only by coincidence - its two candidates happened to
    # be the pack's first two, in order. Empty means the entry's own options are on screen.
    offered: tuple[str, ...] = ()

    # ----------------------------------------------------------------------------------
    # Reading the state
    # ----------------------------------------------------------------------------------

    @property
    def current(self) -> Entry:
        """:return: The entry on screen."""
        return self.entries[self.cursor]

    @property
    def on_screen(self) -> tuple[str, ...]:
        """
        :return: The options the user is looking at - the narrowed list if a re-ask narrowed it,
            otherwise the entry's own.
        """
        return self.offered or self.current.options

    @property
    def visible(self) -> tuple[Entry, ...]:
        """
        The entries the user has actually seen: everything answered, plus the one on screen.

        Derived rather than tracked. The cursor only ever moves to the first unanswered entry or
        back to an answered one, so "answered, plus current" is exactly the set that has been
        asked - and a derived answer cannot fall out of step with the thing it describes.

        :return: The visible entries, in order.
        """
        return tuple(entry for entry in self.entries if entry.answered or entry.label == self.current.label)

    def brief_lines(self) -> tuple[list[str], list[str]]:
        """
        The two sections of the design brief that must not be written from memory.

        The brief is the document the user reads and approves, and its whole claim is that a reader
        can tell what they confirmed from what the designer assumed. Both halves of that were still
        being composed from a recollection of the conversation - so an answer the user had gone back
        and CORRECTED could reach the brief with its old value, which would make going back look
        like it worked while approving the mistake it was meant to fix. Everything needed is already
        on file here, exactly once, with the assumed flag set where a default was taken.

        Only answered entries appear: an unanswered one belongs in neither section.

        :return: The confirmed lines and the assumed lines, each "<subject>: <answer>".
        """
        confirmed: list[str] = []
        assumed: list[str] = []
        for entry in self.entries:
            if not entry.answered:
                continue
            (assumed if entry.assumed else confirmed).append(f"{entry.subject}: {entry.answer}")
        return confirmed, assumed

    @property
    def outstanding(self) -> tuple[Entry, ...]:
        """:return: Entries with no answer on file, in order."""
        return tuple(entry for entry in self.entries if not entry.answered)

    def log_lines(self) -> list[str]:
        """
        Render the answer log.

        Labelled "Q1." and never a bare "1." - a bare number opening a line is how an option is
        offered, so a log in that shape invites the user to answer the log instead of the question,
        and makes the two indistinguishable to anything parsing the transcript afterwards.

        :return: One line per visible entry.
        """
        lines: list[str] = []
        for entry in self.visible:
            answer: str = entry.answer or "not yet answered"
            suffix: str = " (assumed)" if entry.assumed else ""
            lines.append(f"{entry.label}. {entry.subject} - {answer}{suffix}")
        return lines

    # ----------------------------------------------------------------------------------
    # Rendering: the designer prints this rather than composing it
    # ----------------------------------------------------------------------------------

    def render(self, options: tuple[str, ...] | None = None, lead: str = "") -> str:
        """
        Render the entry on screen as a numbered question.

        The options come from the pack, verbatim and in its own order, with the two escapes after
        them. Because the text is built here, "never invent an option the document does not offer"
        stops being an instruction the model may or may not follow and becomes a property of the
        rendering - which is the whole reason this returns finished text instead of a data
        structure for the model to lay out.

        :param options: Override the candidate options, for narrowing an ambiguous answer down to
            the ones it could have meant. The escapes are appended either way.
        :param lead: An optional first line, for a re-ask that needs to say why it is re-asking.
        :return: The question, ready to print verbatim.
        """
        entry: Entry = self.current
        candidates: tuple[str, ...] = options if options is not None else self.on_screen
        lines: list[str] = [lead] if lead else []
        # A lead that already asks something IS the question - printing the original underneath it
        # asks twice in one reply, which is the shape the one-question-at-a-time check reads as two.
        if not lead.rstrip().endswith("?"):
            lines.append(entry.question if entry.question.rstrip().endswith("?") else f"{entry.question}?")

        shown: list[str] = list(candidates) + [DESCRIBE_ESCAPE, UNSURE_ESCAPE]
        for number, option in enumerate(shown, start=1):
            on_file: str = " (currently on file)" if entry.answered and option == entry.answer else ""
            lines.append(f"  {number}. {option}{on_file}")

        lines.append("")
        if entry.why:
            lines.append(entry.why if entry.why[0].isupper() else entry.why[0].upper() + entry.why[1:])
        lines.append('Reply with a number, or in your own words. Say "go back" to change an earlier answer.')
        return "\n".join(lines)

    # ----------------------------------------------------------------------------------
    # Recording an answer
    # ----------------------------------------------------------------------------------

    def record(self, reply: str, matcher: Matcher | None = None) -> tuple["InterviewState", Outcome]:
        """
        Resolve a reply against the entry on screen and record it if it settles the question.

        Four things a reply can be, and only one of them is an answer:

          * a number naming one of the pack's own options - recorded as that option's exact text,
            so what lands in the log is the curated wording rather than the model's memory of it;
          * the "something else" escape with nothing else - the entry stays open and the user is
            asked to describe it, because the escape is a promise to answer, not an answer;
          * the "not sure" escape - the entry stays open and comes back as ASSUME. A default is a
            domain fact and this module holds none, so choosing one is the model's job; recording
            it as assumed rather than confirmed is this module's job;
          * anything else - consistent with several offered options, and therefore still open, or
            a settled answer in the user's own words.

        :param reply: What the user said.
        :return: The new state, and what the caller must do next.
        """
        entry: Entry = self.current
        text: str = reply.strip()
        # Deterministic first: a number or an exact quote is unambiguous and costs no matcher call.
        numbered: list[str] = self._picked_numbers(text)
        picked: str | None = numbered[0] if numbered else self._pick(text)

        held: Outcome | None = self._unsettled(text, entry, numbered, picked, matcher or DeterministicMatcher())
        if held is not None:
            # A narrowed re-ask renumbers from 1, so the state has to carry the narrowed list into
            # the next turn or the reply's "1" is read against the pack's list instead.
            return replace(self, offered=held.shown), held
        if picked == DESCRIBE_ESCAPE:
            return self, Outcome(
                status=DESCRIBE,
                # Phrased as a question so render() does not print the original underneath it. The
                # live run showed the pair, and a restated question above its own option list reads
                # as though the list were still the thing to answer.
                prompt=self.render(lead="Go ahead - what is it, in your own words?"),
                entry=entry,
            )
        if picked == UNSURE_ESCAPE:
            return self, Outcome(status=ASSUME, entry=entry, note=entry.why)
        return self._store(picked or text, assumed=False)

    def _unsettled(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self, text: str, entry: Entry, numbered: list[str], picked: str | None, matcher: Matcher
    ) -> Outcome | None:
        """
        Decide whether a reply has actually settled the question, and hold it open if not.

        Three ways a reply can fail to settle one, all of them found in a real session and all of
        them previously resolved by taking the likeliest reading:

          * it names more than one option - "1 or 4" is the user weighing two aloud, and the reply
            says outright that the choice is still open;
          * it is consistent with several options and chooses between none, which is the failure
            this whole feature was built for;
          * it identifies exactly one option and says LESS than that option does. Recording the
            option puts the difference in the user's mouth - "DBA team" against an option reading
            "DBA team, verified restore required" put a verified restore under "what you told me" -
            and recording their words instead drops the part of the option nobody disputed, so an
            option naming a change record becomes an approval with no record in it. Neither is
            honest, so the option goes back for one confirmation.

        :param text: The reply, stripped.
        :param entry: The entry on screen.
        :param numbered: The options the reply named by number.
        :param picked: The single option it resolved to, if any.
        :param matcher: Supplies the candidates for a free-text reply. It proposes; this decides.
        :return: The outcome to return instead of recording, or None when the reply is an answer.
        """
        if not text:
            return Outcome(status=AMBIGUOUS, prompt=self.render(), entry=entry, note="nothing was said")
        if len(numbered) > 1:
            return Outcome(
                status=AMBIGUOUS,
                prompt=self.render(lead="You named more than one of those - which one is it?"),
                entry=entry,
                candidates=tuple(numbered),
                note=entry.why,
            )
        if picked is not None:
            return None

        # One question - how many of the options on screen is this reply consistent with? - and
        # the answer decides everything downstream. Two or more and nothing is settled; exactly one
        # and the option may still say more than the user did; none and they answered in their own
        # words. The matcher supplies the count; this decides what it means.
        consistent: list[str] = matcher.match(text, self.on_screen)
        tied: list[str] = consistent if len(consistent) > 1 else []
        if tied:
            return Outcome(
                status=AMBIGUOUS,
                prompt=self.render(
                    options=tuple(tied),
                    lead="Both of those match what you said, and they build different networks - which is it?",
                ),
                entry=entry,
                candidates=tuple(tied),
                note=entry.why,
                shown=tuple(tied),
            )
        sole: str | None = consistent[0] if len(consistent) == 1 else None
        if sole is not None:
            return Outcome(
                status=CONFIRM,
                prompt=self.render(
                    options=(sole,),
                    lead="That matches one option, and it says a little more than you did - is this right?",
                ),
                entry=entry,
                candidates=(sole,),
                note=entry.why,
                shown=(sole,),
            )
        return None

    def assume(self, default: str) -> tuple["InterviewState", Outcome]:
        """
        Record a default the model chose, flagged as assumed rather than confirmed.

        Separate from record() on purpose. The brief promises that a reader can tell what the user
        confirmed from what the designer assumed, and that promise is only as good as the flag: if
        an assumed default could enter through the same door as an answer, the two would be
        indistinguishable by the time the brief is written.

        :param default: The default to record.
        :return: The new state, and what the caller must do next.
        """
        return self._store(default.strip(), assumed=True)

    def _picked_numbers(self, text: str) -> list[str]:
        """
        Every option the reply names by number, de-duplicated and in the order offered.

        Resolved against what is ON SCREEN rather than the entry's own list, because a narrowed
        re-ask renumbers from 1 and the user is reading that.

        :param text: The reply.
        :return: The options named, which may be none, one, or several.
        """
        if not names_only_numbers(text):
            return []
        shown: list[str] = list(self.on_screen) + [DESCRIBE_ESCAPE, UNSURE_ESCAPE]
        seen: list[str] = []
        for match in OPTION_PICK_RE.finditer(text):
            number: int = int(match.group(1))
            if 1 <= number <= len(shown) and shown[number - 1] not in seen:
                seen.append(shown[number - 1])
        return seen

    def _pick(self, text: str) -> str | None:
        """
        Resolve a reply that quotes an option back word for word.

        Numbers are not handled here - _picked_numbers owns them, and a second resolver would be
        one more place for the screen-versus-pack confusion to come back.

        :param text: The reply.
        :return: The option's exact text, or None when the reply names no option.
        """
        shown: list[str] = list(self.on_screen) + [DESCRIBE_ESCAPE, UNSURE_ESCAPE]
        key: str = option_key(text)
        for option in shown:
            if key and key == option_key(option):
                return option
        return None

    def _store(self, answer: str, assumed: bool) -> tuple["InterviewState", Outcome]:
        """
        Write an answer to the entry on screen and move to the first entry still unanswered.

        "First still unanswered" is what makes a correction cheap: after re-answering an earlier
        entry the interview resumes wherever it had got to, because everything in between still
        has its answer and is skipped. Nothing is re-asked for having been passed on the way back.

        :param answer: The answer to record.
        :param assumed: Whether the designer chose it rather than the user.
        :return: The new state, and what the caller must do next.
        """
        entries: list[Entry] = list(self.entries)
        entries[self.cursor] = replace(entries[self.cursor], answer=answer, assumed=assumed)
        moved: InterviewState = replace(self, entries=tuple(entries), offered=())

        outstanding: tuple[Entry, ...] = moved.outstanding
        if not outstanding:
            return moved, Outcome(status=COMPLETE, entry=entries[self.cursor])
        next_cursor: int = next(index for index, entry in enumerate(moved.entries) if not entry.answered)
        moved = replace(moved, cursor=next_cursor)
        return moved, Outcome(status=RECORDED, prompt=moved.render(), entry=entries[self.cursor])

    # ----------------------------------------------------------------------------------
    # Going back
    # ----------------------------------------------------------------------------------

    def go_back(self, target: str = "") -> tuple["InterviewState", Outcome]:
        """
        Move the cursor to an earlier entry so its answer can be replaced.

        Everything the request can mean, resolved here rather than guessed by the model:

          * nothing at all, or a bare "go back" - the entry before the one on screen;
          * "back three" - three entries back, clamped to the first. Asking to go further back
            than the first question lands on the first and says so, because refusing a request
            whose intent is unmistakable is worse than satisfying it approximately;
          * "Q2", "question 2", or a bare "2" - that entry, by its stable label;
          * a topic - the visible entry whose question or answer it names. Exactly one match moves
            the cursor; several come back as CHOOSE with just those entries, because picking one
            for the user is how a correction turns into a different wrong answer; none comes back
            as UNKNOWN with the log, so the user can name an entry that exists.

        No floor on how many times this can happen and no cap on the distance: the promise is that
        a mistyped answer costs one turn rather than the session, and a limit would be a limit on
        that. Nothing is discarded either - the answers between here and where the interview had
        got to keep their values, and _store resumes at the first entry still unanswered.

        :param target: How the user named the entry, in their own words. Empty means one back.
        :return: The new state, and what the caller must do next.
        """
        index, outcome = self._resolve(target)
        if outcome is not None:
            return self, outcome

        moved: InterviewState = replace(self, cursor=index, offered=())
        note: str = ""
        if index == 0 and self.cursor > 1 and _distance(target) is not None:
            note = "That is further back than the first question, so this is the first one."
        return moved, Outcome(
            status=REOPENED,
            prompt="\n".join(["Here is what I have on file:", "", *moved.log_lines(), ""])
            + "\n"
            + moved.render(lead=f"Back to {moved.current.label}."),
            entry=moved.current,
            note=note,
        )

    def _resolve(self, target: str) -> tuple[int, Outcome | None]:
        """
        Work out which entry a request names.

        :param target: How the user named the entry.
        :return: The entry index and None, or an unusable index and the outcome to return instead.
        """
        text: str = target.strip()
        if not text:
            return max(self.cursor - 1, 0), None

        label: re.Match | None = LABEL_RE.search(text)
        if label is not None:
            return self._by_number(int(label.group(1)))

        distance: int | None = _distance(text)
        if distance is not None:
            counted: int = max(self.cursor - distance, 0)
            # A request can say both how far back and what about: "back three - I got the window
            # wrong". When the count and the subject point at different entries one of them is a
            # miscount, and taking the user to the wrong question is worse than asking - they may
            # not notice, and would then "correct" an answer that was right. Same reasoning as an
            # ambiguous answer: two readings, so neither is chosen here.
            named, _ = self._by_topic(text)
            if named >= 0 and named != counted:
                lines: list[str] = self.log_lines()
                return -1, Outcome(
                    status=CHOOSE,
                    prompt="\n".join(
                        [
                            "That counts back to one answer and names another - which did you mean?",
                            "",
                            lines[counted],
                            lines[named],
                            "",
                        ]
                    )
                    + "\nName it by its label.",
                    candidates=(lines[counted], lines[named]),
                    note="the count and the subject disagree",
                )
            return counted, None

        bare: re.Match | None = BARE_NUMBER_RE.match(text)
        if bare is not None:
            return self._by_number(int(bare.group(1)))
        return self._by_subject(text)

    def _by_subject(self, text: str) -> tuple[int, Outcome | None]:
        """
        Resolve a request that named no count and no label.

        Nothing recognisable in it at all - no position, no subject, only navigation words and
        filler - is a bare "go back", which the prompt passes through verbatim as the user typed
        it, and means the entry before this one. Handled here rather than inside _by_topic because
        the count-versus-subject check needs that one strict: a "back three" whose remaining words
        name nothing must not look like a subject pointing one entry back.

        :param text: How the user named the entry.
        :return: The entry index and None, or an unusable index and an outcome.
        """
        if not _subject_words(text) and FIRST_RE.search(text) is None:
            return max(self.cursor - 1, 0), None
        return self._by_topic(text)

    def _by_number(self, number: int) -> tuple[int, Outcome | None]:
        """
        :param number: The entry number the user named, 1-based.
        :return: The entry index and None, or an unusable index and an outcome.
        """
        if 1 <= number <= len(self.visible):
            return number - 1, None
        return -1, Outcome(
            status=UNKNOWN,
            prompt="\n".join(
                ["I have no entry with that number. Here is what I have on file:", "", *self.log_lines()]
            ),
            note=f"asked for entry {number} of {len(self.visible)}",
        )

    def _by_topic(self, text: str) -> tuple[int, Outcome | None]:
        """
        Work out which entry a request names, by position or by subject.

        Matched on the words the user typed rather than on the whole phrase, because a request
        names a subject in passing - the words that matter are in there with several that do not.

        :param text: The topic, in the user's words.
        :return: The entry index and None, or an unusable index and an outcome.
        """
        if FIRST_RE.search(text) is not None:
            return 0, None
        words: list[str] = _subject_words(text)
        hits: list[int] = []
        for index, entry in enumerate(self.visible):
            haystack: str = f"{entry.question} {entry.answer}".lower()
            if any(word in haystack for word in words):
                hits.append(index)
        if len(hits) == 1:
            return hits[0], None
        if not hits:
            return -1, Outcome(
                status=UNKNOWN,
                prompt="\n".join(
                    ["I could not tell which answer you mean. Here is what I have on file:", "", *self.log_lines(), ""]
                )
                + "\nWhich one would you like to change?",
                note="no entry matched",
            )
        candidates: list[str] = [self.log_lines()[index] for index in hits]
        return -1, Outcome(
            status=CHOOSE,
            prompt="\n".join(["More than one of these could be what you mean - which one?", "", *candidates, ""])
            + "\nName it by its label.",
            candidates=tuple(candidates),
            note=f"{len(hits)} entries matched",
        )


def _subject_words(text: str) -> list[str]:
    """
    The words in a request that name what it is about, rather than how to get there.

    :param text: How the user named the entry.
    :return: The subject words, which may be empty.
    """
    return [
        word
        for word in re.findall(r"[a-z0-9]+", text.lower())
        if len(word) > 3 and word not in NAVIGATION_WORDS and word not in WORD_NUMBERS
    ]


def _distance(text: str) -> int | None:
    """
    :param text: How the user named the entry.
    :return: How many entries back they asked for, or None if they did not say.
    """
    match: re.Match | None = BACK_DISTANCE_RE.search(text)
    if match is None:
        return None
    found: str = match.group(1).lower()
    return int(found) if found.isdigit() else WORD_NUMBERS.get(found)


# --------------------------------------------------------------------------------------
# Building and carrying the state
# --------------------------------------------------------------------------------------


def begin(pack: KnowledgePack) -> InterviewState:
    """
    Build the interview from a pack's open variables.

    Every entry exists from the start, labelled in the pack's own order, rather than being appended
    as the interview reaches it. That is what makes a label stable: Q5 is Q5 before it is asked,
    while it is being answered, and after the user has gone back and changed it.

    :param pack: The pack being interviewed from.
    :return: The interview at its first question.
    :raises ValueError: If the pack declares no open variables to ask.
    """
    if not pack.open_variables:
        raise ValueError(f"pack {pack.domain_id!r} declares no open variables, so there is no interview to hold")
    entries: tuple[Entry, ...] = tuple(
        Entry(
            label=f"Q{number}",
            variable_id=variable.variable_id,
            question=variable.question,
            options=tuple(part.strip() for part in variable.examples.split(";") if part.strip()),
            why=variable.why,
        )
        for number, variable in enumerate(pack.open_variables, start=1)
    )
    return InterviewState(domain_id=pack.domain_id, entries=entries)


def begin_from_questions(domain_id: str, questions: list[dict[str, Any]]) -> InterviewState:
    """
    Build the interview from questions the designer derived, for a domain with no pack.

    The whole point of a method layer holding no domain facts is that it works for a domain nobody
    has written a pack for yet - and until this existed, it did not. An unmatched domain fell back
    to the model composing its own questions in prose, which is where both the numbering and the
    answer log were lost: exactly the failure mode that started this work, reappearing for every
    use case outside the three shipped packs. A pack buys VERIFIED standards. It should not also be
    the price of being able to go back and fix a typo.

    So the entries are built the same way and behave identically. curated=False is the only
    difference, and it exists to stop a derived interview being described as a curated one.

    :param domain_id: What the designer is calling this domain.
    :param questions: One entry per question: "question" (required), "options" (the example answers
        to offer, at least two) and "why" (one clause on what the answer changes).
    :return: The interview at its first question.
    :raises ValueError: If the questions are unusable, naming which one and why.
    """
    if not questions:
        raise ValueError("no questions were given, so there is no interview to hold")
    entries: list[Entry] = []
    for number, item in enumerate(questions, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"question {number} is not an object with 'question', 'options' and 'why'")
        text: str = str(item.get("question") or "").strip()
        options: tuple[str, ...] = tuple(str(one).strip() for one in item.get("options") or () if str(one).strip())
        if not text:
            raise ValueError(f"question {number} has no question text")
        if len(options) < 2:
            # Fewer than two and there is nothing to choose between, so the reply comes back as
            # prose and nothing can tell whether it settled anything - which is the failure the
            # numbering exists to prevent, reintroduced through the back door.
            raise ValueError(
                f"question {number} offers {len(options)} example answers; give at least two so the "
                f"user has something to choose between"
            )
        entries.append(
            Entry(
                label=f"Q{number}",
                variable_id=f"D{number}",
                question=text,
                options=options,
                why=str(item.get("why") or "").strip(),
            )
        )
    return InterviewState(domain_id=domain_id, entries=tuple(entries), curated=False)


def to_dict(state: InterviewState) -> dict[str, Any]:
    """
    :param state: The interview.
    :return: A JSON-safe dictionary, for carrying in sly_data between turns.
    """
    return {
        "domain_id": state.domain_id,
        "cursor": state.cursor,
        "curated": state.curated,
        "offered": list(state.offered),
        "entries": [
            {
                "label": entry.label,
                "variable_id": entry.variable_id,
                "question": entry.question,
                "options": list(entry.options),
                "why": entry.why,
                "answer": entry.answer,
                "assumed": entry.assumed,
            }
            for entry in state.entries
        ],
    }


def from_dict(raw: Any) -> InterviewState:
    """
    Rebuild the interview from what sly_data carried.

    Strict about shape. This crosses a turn boundary via the client, so a malformed payload is a
    real possibility, and an interview silently restarting at Q1 with every answer lost is far
    worse than an error - the user would answer the same questions again with no idea why.

    :param raw: The dictionary written by to_dict.
    :return: The interview.
    :raises ValueError: If the payload is not a usable interview.
    """
    if not isinstance(raw, dict) or not isinstance(raw.get("entries"), list) or not raw["entries"]:
        raise ValueError("the interview log carried no entries")
    try:
        entries: tuple[Entry, ...] = tuple(
            Entry(
                label=str(item["label"]),
                variable_id=str(item["variable_id"]),
                question=str(item["question"]),
                options=tuple(str(option) for option in item.get("options", [])),
                why=str(item.get("why", "")),
                answer=str(item.get("answer", "")),
                assumed=bool(item.get("assumed", False)),
            )
            for item in raw["entries"]
        )
    except (KeyError, TypeError) as exception:
        raise ValueError(f"the interview log is malformed: {exception}") from exception
    cursor: int = int(raw.get("cursor", 0))
    if not 0 <= cursor < len(entries):
        raise ValueError(f"the interview log points at entry {cursor} of {len(entries)}")
    return InterviewState(
        domain_id=str(raw.get("domain_id", "")),
        entries=entries,
        cursor=cursor,
        # Defaults to True only when absent entirely; an uncurated interview must never come back
        # from a round trip looking curated, because that is a claim about verification.
        curated=bool(raw.get("curated", True)),
        offered=tuple(str(one) for one in raw.get("offered", ())),
    )
