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
Reading a free-text reply against the options on screen - and only reading it.

WHY THIS EXISTS
---------------
Every interpretation bug this interview has had was the same failure: matching a reply to options
by substring containment. It cannot see that "the CAB one" names an option, that "the second one"
is a position, or that "the DBA guys" is the DBA team. A language model reads all of that without
effort, which is the argument for putting one here.

It is also, exactly, the argument AGAINST putting one here - because a model deciding what an
under-specified reply meant is the original failure this whole feature was built to remove. A
session offered two options differing only in who approves, the user named the part they shared,
and the model resolved it silently. Handing that decision to a better-briefed model would produce
the same class of error in a nicer wrapper.

So the split is deliberate and the boundary is the point:

    RECOGNITION - which of these options is the reply consistent with?   <- a model is good at this
    POLICY      - is that settled enough to record as a requirement?     <- arithmetic, in code

A matcher returns a SET. It never returns a decision. Zero matches is a free-text answer, one is
confirmed with the user because the option may say more than they did, two or more is asked again -
and that policy lives in interview_state, where it is a pure function over the count and stays
covered by tests that need no model at all.

THE GUARDS
----------
A model's output is untrusted input. Every returned index is checked against the list actually
offered, escapes are stripped, duplicates dropped, and anything malformed falls back to the
deterministic matcher rather than failing the turn. A hallucinated option cannot enter the
interview, because the only thing that crosses this boundary is positions in a list the caller
already has.

Deterministic first, always. A reply naming a number or quoting an option exactly is resolved in
interview_state before anything here is consulted, so the common case costs no call, and an
interview runs end to end with no model when none is configured.
"""

import json
import logging
import os
import re
from typing import Any
from typing import Protocol

from coded_tools.agent_network_designer.interview_options import consistent_options
from coded_tools.agent_network_designer.interview_options import is_escape

# Each matcher is a one-method strategy, which is the whole shape of the seam: a single question
# with interchangeable answers. Splitting them further would be inventing structure.
# pylint: disable=too-few-public-methods

logger = logging.getLogger(__name__)

# Names the model matcher. Unset means deterministic only, which is the default on purpose: the
# offline suite and any CI run must never depend on a key, a network or a provider being reachable.
MATCH_MODEL_ENV: str = "AGENT_NETWORK_DESIGNER_MATCH_MODEL"

# Long enough for a considered reading, short enough that a stalled provider does not hold an
# interview open. On timeout the deterministic matcher answers instead.
MATCH_TIMEOUT_SECONDS: float = 20.0

# What the model is asked. It is given the options and the reply and asked which options the reply
# could mean - never which one the user "probably" meant, because that word is the whole failure.
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


class Matcher(Protocol):
    """Reads a reply against the options on screen. Returns candidates, never a decision."""

    def match(self, reply: str, options: tuple[str, ...]) -> list[str]:
        """
        :param reply: What the user said, verbatim.
        :param options: The options on screen, in the order shown.
        :return: The options the reply could mean, in the order offered.
        """


class DeterministicMatcher:
    """
    The matcher that needs no model: proper-substring containment.

    Crude, and the reason this seam exists. It is also the reason the seam is safe to add - it stays
    the default, the fallback for every model failure, and the implementation the whole offline
    suite runs against.
    """

    def match(self, reply: str, options: tuple[str, ...]) -> list[str]:
        """
        :param reply: See Matcher.match.
        :param options: See Matcher.match.
        :return: See Matcher.match.
        """
        return consistent_options(reply, options)


class ModelMatcher:
    """
    Reads the reply with a language model, then throws away everything but the positions.

    The model never sees an answer being recorded and never learns what the interview does with its
    reading. It is asked one question about two pieces of text, and its answer is validated against
    the list the caller already holds before it is allowed to mean anything.
    """

    def __init__(self, model: str, fallback: Matcher | None = None) -> None:
        """
        :param model: The model to ask.
        :param fallback: Matcher to use when the call fails or answers unusably.
        """
        self.model: str = model
        self.fallback: Matcher = fallback or DeterministicMatcher()

    def match(self, reply: str, options: tuple[str, ...]) -> list[str]:
        """
        :param reply: See Matcher.match.
        :param options: See Matcher.match.
        :return: See Matcher.match.
        """
        candidates: list[str] = [option for option in options if not is_escape(option)]
        if not reply.strip() or not candidates:
            return []
        try:
            numbers: list[int] = self._ask(reply, candidates)
        except Exception as exception:  # pylint: disable=broad-exception-caught
            # Any provider fault - no key, rate limit, timeout, changed response shape - must
            # degrade to the deterministic reading rather than break the interview. A user mid-way
            # through eight questions should never lose the session to a matcher being unavailable.
            logger.warning("Match model %s unavailable (%s); falling back to containment", self.model, exception)
            return self.fallback.match(reply, options)

        # Untrusted input from here down: keep only positions that exist, in the order offered,
        # without duplicates. A number outside the list is dropped rather than clamped, because
        # clamping would silently name an option the model did not choose.
        seen: list[str] = []
        for number in numbers:
            if 1 <= number <= len(candidates) and candidates[number - 1] not in seen:
                seen.append(candidates[number - 1])
        return seen

    def _ask(self, reply: str, candidates: list[str]) -> list[int]:
        """
        Put the question to the model and read the numbers back out.

        :param reply: What the user said.
        :param candidates: The non-escape options, in the order shown.
        :return: The option numbers it returned, unvalidated.
        :raises Exception: Any provider or parsing failure, handled by the caller.
        """
        # Imported here so this module can be imported, and the deterministic path used, in an
        # environment with no provider SDK installed at all.
        from openai import OpenAI  # pylint: disable=import-outside-toplevel

        listed: str = "\n".join(f"{number}. {option}" for number, option in enumerate(candidates, start=1))
        response: Any = OpenAI(timeout=MATCH_TIMEOUT_SECONDS).chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": INSTRUCTIONS},
                {"role": "user", "content": f"Options:\n{listed}\n\nReply: {reply}"},
            ],
            response_format={"type": "json_object"},
        )
        content: str = response.choices[0].message.content or "{}"
        parsed: Any = json.loads(content)
        raw: Any = parsed.get("options", []) if isinstance(parsed, dict) else []
        return [int(one) for one in raw if isinstance(one, (int, float, str)) and re.fullmatch(r"\d{1,2}", str(one))]


def build_matcher() -> Matcher:
    """
    The matcher this deployment is configured for.

    Deterministic unless a model is named, so nothing that runs without configuration acquires a
    dependency on a provider - the offline suite, a CI run and a deployment with no key all keep
    working, with worse recognition and identical policy.

    :return: The matcher to use.
    """
    model: str = os.environ.get(MATCH_MODEL_ENV, "").strip()
    if not model or model.lower() in ("off", "none", "false"):
        return DeterministicMatcher()
    logger.debug("Interview replies will be matched by %s", model)
    return ModelMatcher(model=model)
