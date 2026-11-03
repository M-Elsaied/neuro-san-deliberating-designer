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
import logging
import os
import re
from typing import Any

from openai import OpenAI

from coded_tools.agent_network_designer.interview_options import InterviewOptions

logger = logging.getLogger(__name__)


class ModelReplyMatcher:
    """
    Reads a reply with a language model, so "the CAB one" or "the second one" is recognized where containment finds
    nothing, then keeps only positions in the list on screen. It proposes candidates and never decides: whether a
    reply settles the question is still decided in code. A number or an exact quote never reaches it.
    """

    # Names the model. Unset means no model, so the unit suite and CI never depend on a key or a provider.
    MATCH_MODEL_ENV: str = "AGENT_NETWORK_DESIGNER_MATCH_MODEL"
    # Long enough for a considered reading, short enough that a stalled provider does not hold the interview open.
    # It is tried once, since the client's own retries would triple the wait before containment takes over.
    MATCH_TIMEOUT_SECONDS: float = 20.0
    # The model is asked which options a reply could mean, never which one the user "probably" meant.
    INSTRUCTIONS: str = """You match a person's reply against a numbered list of options they were shown.

Return every option the reply could mean. Do NOT decide between them.

Rules:
- Return an option when the reply names it, describes it, paraphrases it, or names a position in
  the list ("the second one", "the last option").
- If the reply is consistent with SEVERAL options and does not distinguish them, return ALL of
  them. This is the important case: returning one would decide something the person did not.
- If the reply says LESS than an option does but names no other, return just that option.
- If the reply matches nothing on the list, return an empty list. Answering in their own words is
  allowed and is not a failure to match.
- Never invent an option. Only ever return numbers from the list you were given.

Reply with JSON only: {"options": [<numbers>]}"""

    def __init__(self, model: str) -> None:
        """
        Constructor.

        :param model: The model to ask.
        """
        self.model: str = model

    def match(self, reply: str, options: tuple[str, ...]) -> list[str]:
        """
        Find the options a reply could mean, as the model reads it. Only numbers within the real options are kept,
        without repeats, and any failure falls back to containment.

        :param reply: What the user said, verbatim.
        :param options: The options on screen, in the order shown.
        :return: The options it could mean, in the order the model gave them, never an escape.
        """
        candidates: list[str] = []
        for option in options:
            if not InterviewOptions.is_escape(option):
                candidates.append(option)
        if not reply.strip() or not candidates:
            return []
        try:
            numbers: list[int] = self.ask(reply, candidates)
        except Exception as exception:  # pylint: disable=broad-exception-caught
            # A missing key, a timeout or a changed response must not lose the user's session.
            logger.warning("Match model %s unavailable (%s); falling back to containment", self.model, exception)
            return InterviewOptions.get_consistent_options(reply, options)
        matched: list[str] = []
        for number in numbers:
            # Dropped rather than clamped, since clamping would name an option the model did not choose.
            if 1 <= number <= len(candidates) and candidates[number - 1] not in matched:
                matched.append(candidates[number - 1])
        return matched

    def ask(self, reply: str, candidates: list[str]) -> list[int]:
        """
        Put the reply and the options to the model, and read back the option numbers it returned.

        :param reply: What the user said.
        :param candidates: The options that are not escapes, in the order shown.
        :return: The numbers it returned, not yet checked against the list.
        """
        listed: list[str] = []
        for number, candidate in enumerate(candidates, start=1):
            listed.append(f"{number}. {candidate}")
        response: Any = OpenAI(timeout=ModelReplyMatcher.MATCH_TIMEOUT_SECONDS, max_retries=0).chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": ModelReplyMatcher.INSTRUCTIONS},
                {"role": "user", "content": "Options:\n" + "\n".join(listed) + f"\n\nReply: {reply}"},
            ],
            response_format={"type": "json_object"},
        )
        parsed: Any = json.loads(response.choices[0].message.content or "{}")
        numbers: list[int] = []
        for value in parsed.get("options", []) if isinstance(parsed, dict) else []:
            if isinstance(value, (int, float, str)) and re.fullmatch(r"\d{1,2}", str(value)):
                numbers.append(int(value))
        return numbers

    @staticmethod
    def from_environment() -> "ModelReplyMatcher | None":
        """
        Build the matcher this deployment is configured for.

        :return: A matcher when AGENT_NETWORK_DESIGNER_MATCH_MODEL names a model, else None for containment.
        """
        model: str = os.environ.get(ModelReplyMatcher.MATCH_MODEL_ENV, "").strip()
        if not model or model.lower() in ("off", "none", "false"):
            return None
        logger.debug("Interview replies will be matched by %s", model)
        return ModelReplyMatcher(model)
