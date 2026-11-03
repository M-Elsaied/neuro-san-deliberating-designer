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

from dataclasses import replace

from coded_tools.agent_network_designer.interview_entry import InterviewEntry
from coded_tools.agent_network_designer.interview_options import InterviewOptions
from coded_tools.agent_network_designer.interview_outcome import InterviewOutcome
from coded_tools.agent_network_designer.interview_renderer import InterviewRenderer
from coded_tools.agent_network_designer.interview_state import InterviewState


class InterviewRecorder:
    """
    Records answers. A reply that does not settle the question on screen is asked about again rather than guessed
    at, and choosing a default is left to the designer, since a default is a domain fact and this holds none.
    """

    @staticmethod
    def record(state: InterviewState, reply: str) -> InterviewOutcome:
        """
        Resolve a reply against the entry on screen, and record it if it settles the question.

        :param state: The interview.
        :param reply: What the user said.
        :return: The outcome, carrying the state after it.
        """
        entry: InterviewEntry = state.current
        text: str = reply.strip()
        picked: list[str] = InterviewRecorder.get_picked(state, text)
        held: InterviewOutcome | None = InterviewRecorder.get_refused(state, text, picked)
        if held is None:
            held = InterviewRecorder.get_unsettled(state, text, picked)
        if held is not None:
            # A narrowed re-ask is numbered from 1, so the next state keeps the narrowed list on screen.
            return replace(held, state=replace(state, offered=held.shown))
        if picked and picked[0] == InterviewOptions.DESCRIBE_ESCAPE:
            # Phrased as a question, so the original question is not printed under it as well.
            prompt: str = InterviewRenderer.render(state, lead="Go ahead - what is it, in your own words?")
            return InterviewOutcome(InterviewOutcome.DESCRIBE, state, prompt, entry)
        if picked and picked[0] == InterviewOptions.UNSURE_ESCAPE:
            return InterviewOutcome(InterviewOutcome.ASSUME, state, entry=entry, note=entry.why)
        return InterviewRecorder.store(state, picked[0] if picked else text, assumed=False)

    @staticmethod
    def assume(state: InterviewState, default: str) -> InterviewOutcome:
        """
        Record a default the designer chose, flagged as assumed so the brief keeps it apart from confirmed answers.

        :param state: The interview.
        :param default: The default to record.
        :return: The outcome, carrying the state after it.
        """
        return InterviewRecorder.store(state, default.strip(), assumed=True)

    @staticmethod
    def get_picked(state: InterviewState, text: str) -> list[str]:
        """
        Find the options a reply names by number or position, read against those on screen, or else the one it
        quotes, the escape it says in words, or the option a confirm offered back that it says yes to.

        :param state: The interview.
        :param text: The reply, stripped.
        :return: The options picked, without repeats, which may be none.
        """
        shown: list[str] = [*state.on_screen, InterviewOptions.DESCRIBE_ESCAPE, InterviewOptions.UNSURE_ESCAPE]
        picked: list[str] = []
        numbered: str = InterviewOptions.spell_ordinals(text)
        if InterviewOptions.names_only_numbers(numbered):
            for match in InterviewOptions.OPTION_PICK_RE.finditer(numbered):
                number: int = int(match.group(1))
                if 1 <= number <= len(shown) and shown[number - 1] not in picked:
                    picked.append(shown[number - 1])
        key: str = InterviewOptions.get_key(text)
        for option in shown:
            if not picked and key and key == InterviewOptions.get_key(option):
                picked.append(option)
        if not picked and InterviewOptions.get_escape(text):
            picked.append(InterviewOptions.get_escape(text))
        if not picked and len(state.offered) == 1 and key in InterviewOptions.YES_KEYS:
            picked.append(state.offered[0])
        return picked

    @staticmethod
    def get_refused(state: InterviewState, text: str, picked: list[str]) -> InterviewOutcome | None:
        """
        Hold a reply open when it names only numbers that are not on the list and fit no option, as "8" fits
        "8 hours", or says no to the one option a confirm offered back.

        :param state: The interview.
        :param text: The reply, stripped.
        :param picked: The options the reply picked.
        :return: The outcome to return instead of recording, or None.
        """
        if picked:
            return None
        consistent: list[str] = InterviewOptions.get_consistent_options(text, state.on_screen)
        if InterviewOptions.names_only_numbers(InterviewOptions.spell_ordinals(text)) and not consistent:
            prompt: str = InterviewRenderer.render(state, lead="That number is not on the list - which one is it?")
            return InterviewOutcome(
                InterviewOutcome.AMBIGUOUS, prompt=prompt, entry=state.current, shown=state.offered
            )
        if len(state.offered) == 1 and InterviewOptions.get_key(text) in InterviewOptions.NO_KEYS:
            # Every option is offered again, since the one offered back was the wrong one.
            prompt = InterviewRenderer.render(replace(state, offered=()), lead="Then which is it?")
            return InterviewOutcome(InterviewOutcome.AMBIGUOUS, prompt=prompt, entry=state.current)
        return None

    @staticmethod
    def get_unsettled(state: InterviewState, text: str, picked: list[str]) -> InterviewOutcome | None:
        """
        Hold a reply open when it says nothing, picks or fits several options, or fits one while saying less than it.

        :param state: The interview.
        :param text: The reply, stripped.
        :param picked: The options the reply picked by number or quote.
        :return: The outcome to return instead of recording, or None when the reply is an answer.
        """
        entry: InterviewEntry = state.current
        if not text:
            prompt: str = InterviewRenderer.render(state)
            return InterviewOutcome(
                InterviewOutcome.AMBIGUOUS, prompt=prompt, entry=entry, note="nothing was said", shown=state.offered
            )
        if len(picked) > 1:
            prompt = InterviewRenderer.render(state, lead="You named more than one of those - which one is it?")
            return InterviewOutcome(
                InterviewOutcome.AMBIGUOUS, None, prompt, entry, tuple(picked), entry.why, state.offered
            )
        if picked:
            return None
        consistent: tuple[str, ...] = tuple(InterviewOptions.get_consistent_options(text, state.on_screen))
        if len(consistent) > 1:
            lead: str = "Both of those match what you said, and they build different networks - which is it?"
            prompt = InterviewRenderer.render(state, options=consistent, lead=lead)
            return InterviewOutcome(InterviewOutcome.AMBIGUOUS, None, prompt, entry, consistent, entry.why, consistent)
        if consistent:
            lead = "That matches one option, and it says a little more than you did - is this right?"
            prompt = InterviewRenderer.render(state, options=consistent, lead=lead)
            return InterviewOutcome(InterviewOutcome.CONFIRM, None, prompt, entry, consistent, entry.why, consistent)
        return None

    @staticmethod
    def store(state: InterviewState, answer: str, assumed: bool) -> InterviewOutcome:
        """
        Write an answer to the entry on screen and move to the first entry still unanswered.

        :param state: The interview.
        :param answer: The answer to record.
        :param assumed: Whether the designer chose it rather than the user.
        :return: The outcome, carrying the state after it.
        """
        entries: list[InterviewEntry] = list(state.entries)
        entries[state.cursor] = replace(entries[state.cursor], answer=answer, assumed=assumed)
        moved: InterviewState = replace(state, entries=tuple(entries), offered=())
        for index, entry in enumerate(moved.entries):
            if not entry.answered:
                moved = replace(moved, cursor=index)
                return InterviewOutcome(
                    InterviewOutcome.RECORDED, moved, InterviewRenderer.render(moved), entries[state.cursor]
                )
        return InterviewOutcome(InterviewOutcome.COMPLETE, moved, entry=entries[state.cursor])
