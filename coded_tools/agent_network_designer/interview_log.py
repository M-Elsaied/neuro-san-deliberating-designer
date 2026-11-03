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

import asyncio
import json
import logging
from typing import Any

from neuro_san.interfaces.coded_tool import CodedTool

from coded_tools.agent_network_designer.interview_factory import InterviewFactory
from coded_tools.agent_network_designer.interview_navigator import InterviewNavigator
from coded_tools.agent_network_designer.interview_outcome import InterviewOutcome
from coded_tools.agent_network_designer.interview_recorder import InterviewRecorder
from coded_tools.agent_network_designer.interview_renderer import InterviewRenderer
from coded_tools.agent_network_designer.interview_state import InterviewState
from coded_tools.agent_network_designer.knowledge_pack import KnowledgePack
from coded_tools.agent_network_designer.pack_catalog import PackCatalog
from coded_tools.agent_network_designer.pack_reader import PackReader

logger = logging.getLogger(__name__)


class InterviewLog(CodedTool):
    """
    CodedTool that holds the interview in sly_data and returns finished text for the designer to print, so the user
    sees the pack's own wording at a computed position rather than an answer log the model keeps and lets drift.
    """

    START: str = "start"
    ANSWER: str = "answer"
    BACK: str = "back"
    ASSUME: str = "assume"
    LOG: str = "log"
    ACTIONS: tuple[str, ...] = (START, ANSWER, BACK, ASSUME, LOG)

    def invoke(self, args: dict[str, Any], sly_data: dict[str, Any]) -> dict[str, Any] | str:
        """
        Apply one action to the interview.

        :param args: "action", one of "start", "answer", "back", "assume" or "log". For "start", "app_name", the
            curated domain to interview from, or "questions", derived for a domain with no pack, each with
            "question", at least two "options" and "why". For "answer", "reply", what the user said verbatim. For
            "back", "target", how the user named the entry, or nothing for one back. For "assume", "default".
        :param sly_data: The interview is kept under InterviewState.SLY_DATA_KEY, written by "start" and updated by
            every other action.
        :return: "status", what to do next; "prompt", the text to print verbatim; "label", the entry the status is
            about; "log", the answer log; "confirmed" and "assumed", the brief's two answer sections; "outstanding",
            how many entries have no answer; "curated", False when the questions were derived; "candidates", the
            options or entries a reply was tied between; and "note". Otherwise an "Error: ..." string.
        """
        action: str = str(args.get("action") or "").strip().lower()
        if action not in InterviewLog.ACTIONS:
            return f"Error: Unknown action {action!r}. Use one of: {', '.join(InterviewLog.ACTIONS)}."
        if action == InterviewLog.START:
            return InterviewLog.start(args, sly_data)
        return InterviewLog.advance(action, args, sly_data)

    @staticmethod
    def start(args: dict[str, Any], sly_data: dict[str, Any]) -> dict[str, Any] | str:
        """
        Open the interview, from a pack or from derived questions, and return its first question.

        :param args: See invoke().
        :param sly_data: See invoke().
        :return: See invoke().
        """
        domain_id: str = str(args.get("app_name") or "").strip()
        questions: Any = args.get("questions")
        if questions:
            return InterviewLog.start_derived(domain_id, questions, sly_data)
        if not domain_id:
            return (
                f"Error: No domain given to interview from, and no questions to ask. Pass app_name for a curated "
                f"domain, or questions for one this deployment has no pack for. "
                f"Available curated domains: {PackReader.describe_domains()}"
            )
        try:
            pack: KnowledgePack = PackCatalog.load_pack(domain_id)
        except (OSError, ValueError) as exception:
            return f"Error: Could not load the knowledge pack for {domain_id!r}: {exception}"
        try:
            state: InterviewState = InterviewFactory.begin(pack)
        except ValueError as exception:
            return f"Error: {exception}"
        logger.debug("Interview %s: opened with %d open variable(s)", domain_id, len(state.entries))
        return InterviewLog.open(state, sly_data)

    @staticmethod
    def start_derived(domain_id: str, questions: Any, sly_data: dict[str, Any]) -> dict[str, Any] | str:
        """
        Open the interview for a domain with no pack, which works the same way but is not curated.

        :param domain_id: What the designer calls this domain.
        :param questions: The derived questions, as a list or as JSON text, since models pass both.
        :param sly_data: See invoke().
        :return: See invoke().
        """
        if isinstance(questions, str):
            try:
                questions = json.loads(questions)
            except json.JSONDecodeError as exception:
                return f"Error: 'questions' was text but not valid JSON: {exception}"
        if not isinstance(questions, list):
            return "Error: 'questions' must be a list of objects with 'question', 'options' and 'why'."
        try:
            state: InterviewState = InterviewFactory.begin_from_questions(domain_id or "uncurated", questions)
        except ValueError as exception:
            return f"Error: {exception}"
        logger.debug("Interview %s: opened UNCURATED with %d question(s)", state.domain_id, len(state.entries))
        return InterviewLog.open(state, sly_data)

    @staticmethod
    def open(state: InterviewState, sly_data: dict[str, Any]) -> dict[str, Any]:
        """
        Store a new interview and return its first question.

        :param state: The interview at its first question.
        :param sly_data: See invoke().
        :return: See invoke().
        """
        sly_data[InterviewState.SLY_DATA_KEY] = InterviewFactory.to_dict(state)
        outcome: InterviewOutcome = InterviewOutcome(
            InterviewOutcome.START, state, InterviewRenderer.render(state), state.current
        )
        return InterviewLog.respond(outcome)

    @staticmethod
    def advance(action: str, args: dict[str, Any], sly_data: dict[str, Any]) -> dict[str, Any] | str:
        """
        Apply an action to an interview already under way.

        :param action: The action, which is not "start".
        :param args: See invoke().
        :param sly_data: See invoke().
        :return: See invoke().
        """
        try:
            state: InterviewState = InterviewFactory.from_dict(sly_data.get(InterviewState.SLY_DATA_KEY))
        except ValueError as exception:
            return (
                f"Error: {exception}. The interview state was not carried between turns - say so rather than asking "
                f"everything again, and check that {InterviewState.SLY_DATA_KEY!r} is declared in this agent's "
                f"allow.to_upstream.sly_data."
            )
        if action == InterviewLog.LOG:
            return InterviewLog.respond(InterviewOutcome(InterviewOutcome.LOG, state, entry=state.current))
        if action == InterviewLog.ANSWER:
            reply: str = str(args.get("reply") or "")
            if not reply.strip():
                return "Error: No reply given to record. Pass what the user said as 'reply'."
            outcome: InterviewOutcome = InterviewRecorder.record(state, reply)
        elif action == InterviewLog.ASSUME:
            default: str = str(args.get("default") or "")
            if not default.strip():
                return "Error: No default given to assume. Pass the default you chose as 'default'."
            outcome = InterviewRecorder.assume(state, default)
        else:
            outcome = InterviewNavigator.go_back(state, str(args.get("target") or ""))
        sly_data[InterviewState.SLY_DATA_KEY] = InterviewFactory.to_dict(outcome.state)
        logger.debug("Interview %s: %s at %s", state.domain_id, outcome.status, outcome.state.current.label)
        return InterviewLog.respond(outcome)

    @staticmethod
    def respond(outcome: InterviewOutcome) -> dict[str, Any]:
        """
        Build the payload invoke() returns, with the brief's sections and the curated flag on every action.

        :param outcome: What the action produced.
        :return: See invoke().
        """
        state: InterviewState = outcome.state
        prompt: str = outcome.prompt
        if not prompt and outcome.status in (InterviewOutcome.LOG, InterviewOutcome.START):
            prompt = InterviewRenderer.render(state)
        return {
            "status": outcome.status,
            "prompt": prompt,
            "label": outcome.entry.label if outcome.entry is not None else state.current.label,
            "log": InterviewRenderer.get_log_lines(state),
            "confirmed": InterviewRenderer.get_brief_lines(state, assumed=False),
            "assumed": InterviewRenderer.get_brief_lines(state, assumed=True),
            "outstanding": len(state.outstanding),
            "curated": state.curated,
            "candidates": list(outcome.candidates),
            "note": outcome.note,
        }

    async def async_invoke(self, args: dict[str, Any], sly_data: dict[str, Any]) -> dict[str, Any] | str:
        """
        Runs invoke() in a worker thread, since "start" may read the pack from disk.

        :param args: See invoke().
        :param sly_data: See invoke().
        :return: See invoke().
        """
        return await asyncio.to_thread(self.invoke, args, sly_data)
