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
Tests for the reply matcher, and for the boundary that keeps it a recogniser.

A model reads free text far better than substring containment does, which is why the seam exists.
It is also how the original failure happened - a model deciding what an under-specified reply meant
and recording it - which is why a matcher may only ever propose CANDIDATES. Most of what is
asserted here is therefore not "the matcher is right" but "the matcher cannot decide, cannot
introduce an option that was not offered, and cannot break the interview by failing".

No model is called. A matcher is an interface, so a fake one is the whole point: it lets the
policy be tested against readings a real model might plausibly return, including malicious ones.
"""

import os
from typing import Any

import pytest

from coded_tools.agent_network_designer.interview_log import InterviewLog
from coded_tools.agent_network_designer.interview_matcher import MATCH_MODEL_ENV
from coded_tools.agent_network_designer.interview_matcher import DeterministicMatcher
from coded_tools.agent_network_designer.interview_matcher import ModelMatcher
from coded_tools.agent_network_designer.interview_matcher import build_matcher
from coded_tools.agent_network_designer.interview_options import consistent_options
from coded_tools.agent_network_designer.interview_state import AMBIGUOUS
from coded_tools.agent_network_designer.interview_state import CONFIRM
from coded_tools.agent_network_designer.interview_state import RECORDED
from coded_tools.agent_network_designer.interview_state import InterviewState
from coded_tools.agent_network_designer.interview_state import begin
from coded_tools.agent_network_designer.pack_catalogue import load_pack

DOMAIN: str = "oracle_database_patching"

# The fakes below are one-method strategies, matching the interface they stand in for.
# pylint: disable=too-few-public-methods,unused-argument


class FakeMatcher:
    """A matcher that returns whatever a test tells it to, including nonsense."""

    def __init__(self, *returns: str) -> None:
        self.returns: list[str] = list(returns)
        self.seen: list[str] = []

    def match(self, reply: str, options: tuple[str, ...]) -> list[str]:  # noqa: ARG002
        """
        Ignores the options on purpose: the point is to hand the policy a reading it did not
        derive, including one no honest matcher would produce.

        :param reply: See Matcher.match.
        :param options: See Matcher.match. Unused.
        :return: Whatever the test asked for.
        """
        self.seen.append(reply)
        return list(self.returns)


class ExplodingMatcher:
    """A matcher that fails, which is what a provider outage looks like from here."""

    def match(self, reply: str, options: tuple[str, ...]) -> list[str]:
        """
        :param reply: See Matcher.match.
        :param options: See Matcher.match.
        :raises RuntimeError: Always.
        """
        raise RuntimeError("provider unavailable")


@pytest.fixture(name="approval")
def approval_fixture() -> InterviewState:
    """
    :return: An interview sitting on the approval question, whose options are the ones that started
        all of this - the same change record approved by two different bodies.
    """
    state: InterviewState = begin(load_pack(DOMAIN))
    for _ in range(4):
        state, _ = state.record("1")
    return state


# --------------------------------------------------------------------------------------
# The boundary: a matcher proposes, the policy decides
# --------------------------------------------------------------------------------------


def test_two_candidates_are_asked_about_however_confident_the_matcher_is(approval):
    """
    The whole reason a model is allowed nowhere near the decision.

    A matcher returning two options has said the reply does not distinguish them. Recording either
    would put a requirement in the brief the user never chose - which is the failure this feature
    exists to prevent, and would be reintroduced the moment a confident-sounding reading was
    allowed to settle anything.
    """
    both: tuple[str, ...] = approval.current.options[:2]
    after, outcome = approval.record("whatever the model made of this", matcher=FakeMatcher(*both))

    assert outcome.status == AMBIGUOUS
    assert outcome.candidates == both
    assert not after.current.answered


def test_one_candidate_is_confirmed_rather_than_recorded(approval):
    """
    A model naming one option has identified WHICH option, not agreed to everything it says.

    Same reasoning as the deterministic path: the option may say more than the user did, so it goes
    back for a yes. A better reader does not earn the right to skip that.
    """
    after, outcome = approval.record("the CAB one", matcher=FakeMatcher(approval.current.options[0]))

    assert outcome.status == CONFIRM
    assert not after.current.answered


def test_no_candidates_is_a_free_text_answer(approval):
    """
    A reply matching nothing on the list is the user answering in their own words, which is allowed
    and must not be bent towards the nearest option.
    """
    after, outcome = approval.record("a standing waiver signed quarterly", matcher=FakeMatcher())

    assert outcome.status == RECORDED
    assert after.entries[4].answer == "a standing waiver signed quarterly"


# --------------------------------------------------------------------------------------
# The guards: a matcher's output is untrusted input
# --------------------------------------------------------------------------------------


def test_an_option_that_was_never_offered_cannot_enter_the_interview(approval):
    """
    The failure a model makes that a substring never could: inventing an option.

    Left unchecked, an invented standard or approval route would reach the brief and be approved.
    Only positions in the list the caller already holds may cross the boundary.
    """
    matcher = ModelMatcher(model="unused", fallback=DeterministicMatcher())
    matcher._ask = lambda reply, candidates: [1, 99, -3, 0]  # pylint: disable=protected-access
    matched: list[str] = matcher.match("something", approval.current.options)

    assert matched == [approval.current.options[0]], "an out-of-range index was not dropped"


def test_a_matcher_cannot_return_an_escape_as_an_answer(approval):
    """
    "I am not sure" is a route out of the question, not an answer to it. A matcher that returned it
    would have the interview record uncertainty as a requirement.
    """
    matcher = ModelMatcher(model="unused")
    matcher._ask = lambda reply, candidates: [1]  # pylint: disable=protected-access
    with_escapes: tuple[str, ...] = approval.current.options + ("I am not sure - choose a default",)

    assert matcher.match("dunno", with_escapes) == [approval.current.options[0]]


def test_duplicate_candidates_do_not_look_like_ambiguity(approval):
    """
    The same option twice is one option. Counted twice it would read as two candidates and send a
    settled answer back to the user for no reason.
    """
    matcher = ModelMatcher(model="unused")
    matcher._ask = lambda reply, candidates: [2, 2, 2]  # pylint: disable=protected-access

    assert matcher.match("the second", approval.current.options) == [approval.current.options[1]]


def test_a_failing_matcher_falls_back_instead_of_losing_the_session(approval):
    """
    A provider outage mid-interview must not cost the user seven answered questions.

    Recognition degrades to containment; the policy is untouched. Worse readings, same guarantees.
    """
    matcher = ModelMatcher(model="unused", fallback=DeterministicMatcher())
    matcher._ask = lambda reply, candidates: (_ for _ in ()).throw(RuntimeError("down"))  # pylint: disable=protected-access

    assert matcher.match("service now CR", approval.current.options) == consistent_options(
        "service now CR", approval.current.options
    )


def test_the_policy_survives_a_matcher_that_throws(approval):
    """
    And a matcher that raises where no fallback can catch it must not corrupt the interview.
    """
    with pytest.raises(RuntimeError):
        approval.record("anything", matcher=ExplodingMatcher())

    assert not approval.current.answered, "state was mutated by a failed match"


# --------------------------------------------------------------------------------------
# Configuration, and the deterministic fast path
# --------------------------------------------------------------------------------------


def test_no_model_is_reached_when_none_is_configured(monkeypatch):
    """
    The default has to need no key, no network and no provider, or the offline suite and every
    deployment without a key acquire a dependency they never asked for.
    """
    monkeypatch.delenv(MATCH_MODEL_ENV, raising=False)
    assert isinstance(build_matcher(), DeterministicMatcher)


@pytest.mark.parametrize("value", ["off", "none", "false", "", "   "])
def test_the_match_model_can_be_turned_off(value, monkeypatch):
    """
    An operator has to be able to switch it off without editing code.
    """
    monkeypatch.setenv(MATCH_MODEL_ENV, value)
    assert isinstance(build_matcher(), DeterministicMatcher)


def test_a_named_model_is_used(monkeypatch):
    """
    :param monkeypatch: Fixture.
    """
    monkeypatch.setenv(MATCH_MODEL_ENV, "some-model")
    matcher: Any = build_matcher()

    assert isinstance(matcher, ModelMatcher)
    assert matcher.model == "some-model"


@pytest.mark.parametrize("reply", ["1", "2", "option 3", "#1", "1 or 2"])
def test_a_numbered_reply_never_reaches_the_matcher(reply, approval):
    """
    The fast path, asserted rather than assumed.

    A number is unambiguous by construction, so consulting a model about it would spend a call and
    a round trip to be told what the list already said - and would put a model in the way of the
    one input that cannot be misread.
    """
    matcher = FakeMatcher()
    approval.record(reply, matcher=matcher)

    assert not matcher.seen, f"{reply!r} was sent to the matcher"


def test_an_exact_quote_never_reaches_the_matcher(approval):
    """
    Same for a reply that quotes an option word for word.
    """
    matcher = FakeMatcher()
    approval.record(approval.current.options[0], matcher=matcher)

    assert not matcher.seen


def test_the_tool_owns_the_matcher_so_the_front_man_cannot_bypass_it():
    """
    Placement, asserted. The model that conducts the interview is the one that got this wrong
    before, so the matcher is reached from inside the tool rather than by the front man choosing
    to call it - and the policy runs whether or not the front man cooperates.
    """
    both: tuple[str, ...] = load_pack(DOMAIN).open_variables[4].examples.split(";")[:2]
    matcher = FakeMatcher(*(one.strip() for one in both))
    tool, sly_data = InterviewLog(matcher=matcher), {}

    tool.invoke({"action": "start", "app_name": DOMAIN}, sly_data)
    for _ in range(4):
        tool.invoke({"action": "answer", "reply": "1"}, sly_data)
    result: Any = tool.invoke({"action": "answer", "reply": "the servicenow one"}, sly_data)

    assert result["status"] == AMBIGUOUS
    assert matcher.seen == ["the servicenow one"], "the tool did not consult its own matcher"
    assert result["outstanding"] == 3, "an unsettled reply was recorded"


def test_the_default_tool_needs_no_configuration(monkeypatch):
    """
    Constructing the tool with nothing set must not reach for a provider.
    """
    monkeypatch.delenv(MATCH_MODEL_ENV, raising=False)
    assert isinstance(InterviewLog().matcher, DeterministicMatcher)
    assert os.environ.get(MATCH_MODEL_ENV) is None
