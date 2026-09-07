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
CodedTool wrapper around the interview state machine.

The state machine lives in interview_state, which imports nothing from neuro-san, so an interview
can be played out end to end in a unit test with no model and no agent runtime. This module is only
the adapter that lets the designer drive it mid-conversation, and the place the state is kept.

It is kept in sly_data, under one key, and that key MUST also appear in the front man's
allow.to_upstream.sly_data. Session sly_data is rebuilt from the client's payload on every turn, so
a key written on one turn is gone by the next unless it goes out to the client and comes back - and
a log that does not survive a turn is not a log. The same constraint already applies to the pack
provenance written by ExtractDocs.

The tool returns finished text in "prompt". The designer prints it rather than composing its own
version, exactly as it prints the coverage table VerifyStandards computes: what the user sees is
then the pack's own wording, in the pack's own order, at a position this module is tracking - none
of which depends on the model having remembered any of it correctly.
"""

import asyncio
import json
import logging
from typing import Any

from neuro_san.interfaces.coded_tool import CodedTool

from coded_tools.agent_network_designer.interview_matcher import Matcher
from coded_tools.agent_network_designer.interview_matcher import build_matcher
from coded_tools.agent_network_designer.interview_state import ASSUME
from coded_tools.agent_network_designer.interview_state import INTERVIEW_LOG
from coded_tools.agent_network_designer.interview_state import InterviewState
from coded_tools.agent_network_designer.interview_state import Outcome
from coded_tools.agent_network_designer.interview_state import begin
from coded_tools.agent_network_designer.interview_state import begin_from_questions
from coded_tools.agent_network_designer.interview_state import from_dict
from coded_tools.agent_network_designer.interview_state import to_dict
from coded_tools.agent_network_designer.knowledge_pack import KnowledgePack
from coded_tools.agent_network_designer.pack_catalogue import PackCatalogue
from coded_tools.agent_network_designer.pack_catalogue import discover_domains
from coded_tools.agent_network_designer.pack_catalogue import load_pack

logger = logging.getLogger(__name__)

START: str = "start"
ANSWER: str = "answer"
BACK: str = "back"
LOG: str = "log"
ACTIONS: tuple[str, ...] = (START, ANSWER, BACK, ASSUME, LOG)


class InterviewLog(CodedTool):
    """
    CodedTool that holds the interview: its questions, its answers, and where it has got to.

    Replaces an answer log the language model would otherwise keep in its context. A remembered log
    drifts - entries get relabelled, an earlier answer is quietly rewritten to agree with a later
    one, "back three" lands somewhere else - and every one of those failures is silent. Here the
    labels are assigned once, the answers are stored as written, and where a request to go back
    lands is computed rather than judged.
    """

    def __init__(self, matcher: Matcher | None = None) -> None:
        """
        :param matcher: Reads a free-text reply against the options on screen. Defaults to whatever
            this deployment is configured for - containment when no match model is named. Injected
            in tests so the offline suite never reaches a provider.
        """
        self.matcher: Matcher = matcher or build_matcher()

    def invoke(self, args: dict[str, Any], sly_data: dict[str, Any]) -> dict[str, Any] | str:
        """
        :param args: An argument dictionary with the following keys:
            - "action" (str): one of "start", "answer", "back", "assume", "log".
            - "app_name" (str): for "start" - the curated domain to interview from.
            - "questions" (list): for "start" when no pack matches - questions the designer
              derived, each with "question", "options" (at least two) and "why".
            - "reply" (str): required for "answer" - what the user said, verbatim.
            - "target" (str): optional for "back" - how the user named the entry, in their own
              words. Empty means one question back.
            - "default" (str): required for "assume" - the default the designer chose.

        :param sly_data: A dictionary whose keys are defined by the agent hierarchy, but whose
            values are meant to be kept out of the chat stream.

            Keys expected for this implementation are:
                "agent_network_interview_log": the interview so far. Written by "start" and
                updated by every other action.

        :return:
            If successful:
                A dictionary with the keys:
                - "status" (str): what to do next - "recorded", "ambiguous", "confirm",
                  "describe", "assume", "complete", "reopened", "choose" or "unknown".
                - "prompt" (str): the text to print verbatim, when there is something to ask.
                - "label" (str): the entry the status refers to.
                - "log" (list): the answer log, one line per entry asked so far.
                - "confirmed" (list): the answers the user gave, as "<subject>: <answer>", for the
                  brief's "Confirmed requirements" section.
                - "assumed" (list): the defaults the designer chose, same shape, for the brief's
                  "Assumptions I made" section.
                - "outstanding" (int): how many open variables still have no answer.
                - "curated" (bool): False when the questions were derived for a domain with no
                  pack, in which case no operating standard may be claimed as verified.
                - "candidates" (list): the options a reply was tied between, when status is
                  "ambiguous" or "choose".
                - "note" (str): one line of context, when there is any.
            Otherwise:
                A text string error message in the format:
                "Error: <error message>"
        """
        action: str = str(args.get("action") or "").strip().lower()
        if action not in ACTIONS:
            return f"Error: Unknown action {action!r}. Use one of: {', '.join(ACTIONS)}."
        if action == START:
            return self._start(args, sly_data)
        return self._advance(action, args, sly_data)

    def _advance(self, action: str, args: dict[str, Any], sly_data: dict[str, Any]) -> dict[str, Any] | str:
        """
        Apply one action to an interview already under way.

        :param action: The action, already known to be one of ACTIONS and not "start".
        :param args: See invoke().
        :param sly_data: See invoke().
        :return: See invoke().
        """
        try:
            state: InterviewState = from_dict(sly_data.get(INTERVIEW_LOG))
        except ValueError as exception:
            # Never silently restart. An interview that begins again at Q1 with every answer gone
            # would have the user answering the same questions with no idea why, and the designer
            # reporting confirmed requirements it no longer holds.
            return (
                f"Error: {exception}. The interview state was not carried between turns - say so "
                f"rather than asking everything again, and check that {INTERVIEW_LOG!r} is declared "
                f"in this agent's allow.to_upstream.sly_data."
            )

        if action == LOG:
            return self._respond(state, Outcome(status=LOG, entry=state.current))
        if action == ANSWER:
            reply: str = str(args.get("reply") or "")
            if not reply.strip():
                return "Error: No reply given to record. Pass what the user said as 'reply'."
            # The matcher is reached from HERE and nowhere else. The front man cannot route around
            # it, cannot pass its own reading of the reply, and cannot skip the policy that follows:
            # it hands over what the user said, and gets back what to print.
            state, outcome = state.record(reply, matcher=self.matcher)
        elif action == ASSUME:
            default: str = str(args.get("default") or "")
            if not default.strip():
                return "Error: No default given to assume. Pass the default you chose as 'default'."
            state, outcome = state.assume(default)
        else:
            state, outcome = state.go_back(str(args.get("target") or ""))

        sly_data[INTERVIEW_LOG] = to_dict(state)
        logger.debug("Interview %s: %s at %s", state.domain_id, outcome.status, state.current.label)
        return self._respond(state, outcome)

    def _start(self, args: dict[str, Any], sly_data: dict[str, Any]) -> dict[str, Any] | str:
        """
        Build the interview from a pack and return its first question.

        :param args: See invoke().
        :param sly_data: See invoke().
        :return: See invoke().
        """
        domain_id: str = str(args.get("app_name") or "").strip()
        derived: Any = args.get("questions")
        if derived:
            return self._start_derived(domain_id, derived, sly_data)
        if not domain_id:
            return (
                f"Error: No domain given to interview from, and no questions to ask. Pass app_name "
                f"for a curated domain, or questions for one this deployment has no pack for. "
                f"Available curated domains: {', '.join(discover_domains()) or 'none'}"
            )
        try:
            pack: KnowledgePack = load_pack(domain_id)
        except (OSError, ValueError) as exception:
            return f"Error: Could not load the knowledge pack for {domain_id!r}: {exception}"

        try:
            state: InterviewState = begin(pack)
        except ValueError as exception:
            return f"Error: {exception}"

        sly_data[INTERVIEW_LOG] = to_dict(state)
        logger.debug("Interview %s: opened with %d open variable(s)", domain_id, len(state.entries))
        return self._respond(state, Outcome(status=START, prompt=state.render(), entry=state.current))

    def _start_derived(self, domain_id: str, questions: Any, sly_data: dict[str, Any]) -> dict[str, Any] | str:
        """
        Open an interview for a domain this deployment has no pack for.

        Same machinery, same numbering, same answer log, same way back - the only thing a pack buys
        that this does not is standards that were verified by somebody. Before this existed an
        unmatched domain got a hand-composed interview with none of it, so every use case outside
        the shipped packs was back to the behaviour this work set out to fix.

        :param domain_id: What the designer is calling this domain.
        :param questions: The derived questions, as a list or as JSON text.
        :param sly_data: See invoke().
        :return: See invoke().
        """
        if isinstance(questions, str):
            # Models pass a JSON array as a string about as often as they pass a real one.
            try:
                questions = json.loads(questions)
            except json.JSONDecodeError as exception:
                return f"Error: 'questions' was text but not valid JSON: {exception}"
        if not isinstance(questions, list):
            return "Error: 'questions' must be a list of objects with 'question', 'options' and 'why'."

        try:
            state: InterviewState = begin_from_questions(domain_id or "uncurated", questions)
        except ValueError as exception:
            return f"Error: {exception}"

        sly_data[INTERVIEW_LOG] = to_dict(state)
        logger.debug("Interview %s: opened UNCURATED with %d question(s)", state.domain_id, len(state.entries))
        return self._respond(state, Outcome(status=START, prompt=state.render(), entry=state.current))

    @staticmethod
    def _respond(state: InterviewState, outcome: Outcome) -> dict[str, Any]:
        """
        :param state: The interview after the action.
        :param outcome: What the action produced.
        :return: The payload described in invoke().
        """
        prompt: str = outcome.prompt or (state.render() if outcome.status in (LOG, START) else "")
        confirmed, assumed = state.brief_lines()
        return {
            "status": outcome.status,
            "prompt": prompt,
            "label": outcome.entry.label if outcome.entry is not None else state.current.label,
            "log": state.log_lines(),
            # The brief's two most consequential sections, computed rather than recalled. Returned
            # on every action, not just "log", so the designer never has a reason to reconstruct
            # them from the conversation - which is where a corrected answer would go missing.
            "confirmed": confirmed,
            "assumed": assumed,
            "outstanding": len(state.outstanding),
            # False when the questions were derived rather than read from a pack. Returned on every
            # action so a long session cannot forget it and start describing derived questions as
            # curated standards.
            "curated": state.curated,
            "candidates": list(outcome.candidates),
            "note": outcome.note,
        }

    async def async_invoke(self, args: dict[str, Any], sly_data: dict[str, Any]) -> dict[str, Any] | str:
        """
        Drive the interview without blocking the event loop on a cold pack cache.

        Only "start" can touch the filesystem, and only on a cache miss; every other action is
        arithmetic over state already in memory and stays on the loop.

        :param args: See invoke().
        :param sly_data: See invoke().
        :return: See invoke().
        """
        if str(args.get("action") or "").strip().lower() == START and PackCatalogue.peek() is None:
            return await asyncio.to_thread(self.invoke, args, sly_data)
        return self.invoke(args, sly_data)
