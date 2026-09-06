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
Tests for the interview state machine - the part the model used to have to remember.

The prompt can ask for an answer log, one question at a time and a way back to any earlier answer.
It cannot make any of that true, and every way it fails is silent: a relabelled entry, an answer
quietly rewritten to agree with a later one, "back three" landing two questions away. So the whole
point of these tests is that the bookkeeping is now arithmetic, and arithmetic can be asserted.

No model and no agent runtime here - an interview is played out by calling record() and go_back(),
which is exactly how the CodedTool drives it.
"""

import pytest

from coded_tools.agent_network_designer.interview_state import AMBIGUOUS
from coded_tools.agent_network_designer.interview_state import ASSUME
from coded_tools.agent_network_designer.interview_state import CHOOSE
from coded_tools.agent_network_designer.interview_state import COMPLETE
from coded_tools.agent_network_designer.interview_state import DESCRIBE
from coded_tools.agent_network_designer.interview_state import RECORDED
from coded_tools.agent_network_designer.interview_state import REOPENED
from coded_tools.agent_network_designer.interview_state import UNKNOWN
from coded_tools.agent_network_designer.interview_state import Entry
from coded_tools.agent_network_designer.interview_state import InterviewState
from coded_tools.agent_network_designer.interview_state import begin
from coded_tools.agent_network_designer.interview_state import from_dict
from coded_tools.agent_network_designer.interview_state import offered_options
from coded_tools.agent_network_designer.interview_state import to_dict
from coded_tools.agent_network_designer.knowledge_pack import KnowledgePack
from coded_tools.agent_network_designer.knowledge_pack import OpenVariable
from coded_tools.agent_network_designer.knowledge_pack import PackManifest
from coded_tools.agent_network_designer.pack_catalogue import load_pack

DOMAIN: str = "oracle_database_patching"


@pytest.fixture(name="pack")
def pack_fixture() -> KnowledgePack:
    """
    :return: The Oracle reference pack.
    """
    return load_pack(DOMAIN)


def synthetic(count: int = 3) -> KnowledgePack:
    """
    A pack with no domain in it, for the cases that are about the machinery rather than a domain.

    :param count: How many open variables to declare.
    :return: The pack.
    """
    return KnowledgePack(
        manifest=PackManifest(domain_id="synthetic"),
        open_variables=[
            OpenVariable(
                variable_id=f"V{number}",
                question=f"Subject {number}: which one?",
                examples=f"first {number}; second {number}",
                why=f"it changes thing {number}.",
            )
            for number in range(1, count + 1)
        ],
    )


def play(state: InterviewState, *replies: str) -> InterviewState:
    """
    :param state: The interview.
    :param replies: Replies to record in order.
    :return: The interview after them.
    """
    for reply in replies:
        state, _ = state.record(reply)
    return state


# --------------------------------------------------------------------------------------
# The questions themselves
# --------------------------------------------------------------------------------------


def test_the_options_are_the_packs_own_examples_verbatim_and_in_order(pack):
    """
    The reason rendering moved out of the prompt: "never invent an option" stops being an
    instruction the model may drift from and becomes a property of the code that draws the list.
    """
    state: InterviewState = begin(pack)
    rendered: str = state.render()
    offered: list[str] = offered_options(rendered)
    expected: list[str] = [part.strip() for part in pack.open_variables[0].examples.split(";")]

    assert offered[: len(expected)] == expected
    assert offered[-2:] == ["Something else - I will describe it", "I am not sure - choose a sensible default for me"]
    assert rendered.count("?") == 1, "a question must carry exactly one question mark"


def test_every_question_carries_both_escapes(pack):
    """
    Without them a numbered list narrows the answer to whatever got enumerated, and a user whose
    situation is not listed has to pick a wrong one - guessing made tidier rather than rarer.
    """
    state: InterviewState = begin(pack)
    for _ in pack.open_variables:
        offered: list[str] = offered_options(state.render())
        assert "Something else - I will describe it" in offered
        assert "I am not sure - choose a sensible default for me" in offered
        state, _ = state.record("1")


def test_a_pack_with_no_open_variables_is_refused(pack):  # pylint: disable=unused-argument
    """
    An interview with nothing to ask is a bug in the pack, not an empty interview to hold.
    """
    with pytest.raises(ValueError, match="no open variables"):
        begin(synthetic(count=0))


# --------------------------------------------------------------------------------------
# Recording an answer
# --------------------------------------------------------------------------------------


def test_answering_by_number_records_the_packs_wording_not_the_number(pack):
    """
    What lands in the log is the curated text, so the brief quotes the pack rather than "2".
    """
    state: InterviewState = begin(pack)
    expected: str = pack.open_variables[0].examples.split(";")[1].strip()
    state, outcome = state.record("2")

    assert outcome.status == RECORDED
    assert state.entries[0].answer == expected
    assert not state.entries[0].assumed


def test_an_answer_fitting_two_options_leaves_the_variable_open(pack):
    """
    The live failure, at the level that can actually prevent it.

    "service now CR" is consistent with two of the offered options and chooses between neither.
    Recording it would put a requirement the user never confirmed under "Confirmed requirements",
    so the cursor must not move and no answer may be stored.
    """
    state: InterviewState = play(begin(pack), "2", "1", "1", "1")
    before: str = state.current.label
    after, outcome = state.record("service now CR")

    assert outcome.status == AMBIGUOUS
    assert len(outcome.candidates) == 2
    assert after.current.label == before, "the cursor moved past a question that is still open"
    assert not after.current.answered, "an ambiguous reply was recorded as an answer"
    assert offered_options(outcome.prompt)[:2] == list(outcome.candidates)


def test_the_narrowed_re_ask_asks_once(pack):
    """
    The re-ask leads with its own question, so printing the original underneath would ask twice -
    which is the shape the one-question-at-a-time check reads as two questions in one turn.
    """
    state: InterviewState = play(begin(pack), "2", "1", "1", "1")
    _, outcome = state.record("service now CR")

    assert outcome.prompt.count("?") == 1, outcome.prompt


def test_an_answer_in_the_users_own_words_is_recorded_as_given(pack):
    """
    The "something else" route. An answer matching nothing on offer is a complete answer, and must
    not be bent towards the nearest option.
    """
    state: InterviewState = begin(pack)
    state, outcome = state.record("a four-node RAC we inherited, no standby")

    assert outcome.status == RECORDED
    assert state.entries[0].answer == "a four-node RAC we inherited, no standby"


def test_taking_the_describe_escape_keeps_the_question_open(pack):
    """
    "Something else" is a promise to answer, not an answer.
    """
    state: InterviewState = begin(pack)
    after, outcome = state.record("5")

    assert outcome.status == DESCRIBE
    assert not after.current.answered
    assert after.current.label == "Q1"


def test_not_sure_comes_back_for_the_model_to_default_and_is_flagged(pack):
    """
    The line between what is computed and what is judged.

    A default is a domain fact, and this module holds none - so "not sure" returns ASSUME rather
    than inventing one. Recording it as assumed rather than confirmed is the part it can do, and
    the part the brief's honesty depends on.
    """
    state: InterviewState = begin(pack)
    after, outcome = state.record("6")

    assert outcome.status == ASSUME
    assert not after.current.answered, "the tool must not invent a domain default"

    assumed, outcome = after.assume("single instance, no standby")
    assert outcome.status == RECORDED
    assert assumed.entries[0].assumed is True
    assert "(assumed)" in assumed.log_lines()[0]


def test_the_last_answer_completes_the_interview(pack):
    """
    COMPLETE is how the designer learns to stop asking and present the brief.
    """
    state: InterviewState = begin(pack)
    for _ in range(len(pack.open_variables) - 1):
        state, outcome = state.record("1")
        assert outcome.status == RECORDED
    state, outcome = state.record("1")

    assert outcome.status == COMPLETE
    assert not state.outstanding


# --------------------------------------------------------------------------------------
# Going back - the behaviour this module exists to make real
# --------------------------------------------------------------------------------------


def test_a_bare_go_back_reopens_the_previous_entry(pack):
    """
    The commonest case: the answer just given was the wrong one.
    """
    state: InterviewState = play(begin(pack), "1", "1", "1")
    after, outcome = state.go_back()

    assert outcome.status == REOPENED
    assert after.current.label == "Q3"
    assert after.current.answered, "the entry reopened should still hold the answer being replaced"
    assert "(currently on file)" in outcome.prompt


def test_back_n_counts_entries_and_clamps_at_the_first(pack):
    """
    "As far back as the first question" is the promise, so a distance past the start is satisfied
    approximately and said out loud - refusing a request whose intent is unmistakable is worse.
    """
    state: InterviewState = play(begin(pack), "1", "1", "1", "1", "1")

    after, outcome = state.go_back("back two")
    assert (after.current.label, outcome.status) == ("Q4", REOPENED)

    after, outcome = state.go_back("back 20 please")
    assert after.current.label == "Q1"
    assert "further back than the first question" in outcome.note


def test_an_entry_can_be_named_by_its_stable_label(pack):
    """
    Labels are assigned once and never reassigned, which is the only reason "Q2" means anything.
    Re-answering an entry must not renumber it, or the next request lands somewhere else.
    """
    state: InterviewState = play(begin(pack), "1", "1", "1", "1")
    after, _ = state.go_back("change question 2")
    assert after.current.label == "Q2"

    after, _ = after.record("2")
    assert [entry.label for entry in after.entries] == [f"Q{number}" for number in range(1, 8)]
    assert after.entries[1].answer == pack.open_variables[1].examples.split(";")[1].strip()


def test_an_entry_can_be_named_by_its_topic(pack):
    """
    Users say what they got wrong, not which number it was.
    """
    state: InterviewState = play(begin(pack), "1", "1", "1", "1", "1")
    after, outcome = state.go_back("change what I said about the rollback")

    assert outcome.status == REOPENED
    assert "Rollback" in after.current.question


@pytest.mark.parametrize(
    ("target", "expected"),
    [
        # Every phrasing the prompt promises to honour, verbatim from it.
        ("", "Q6"),
        ("go back", "Q6"),
        ("back three", "Q4"),
        ("change question 3", "Q3"),
        ("change what I said about the rollback", "Q6"),
        ("take me back to the first question", "Q1"),
        ("start again from the first question", "Q1"),
        # And the fillers a correction actually arrives wrapped in. These are not politeness: a
        # user fixing a mistake types "wait" or "sorry" first, and the request has to survive it.
        ("wait, go back", "Q6"),
        ("sorry - go back", "Q6"),
        ("hold on, go back", "Q6"),
        ("scratch that, go back", "Q6"),
        ("oops, go back please", "Q6"),
        # Positional, and a distance past the start.
        ("start again from the beginning", "Q1"),
        ("back 20", "Q1"),
    ],
)
def test_every_phrasing_the_prompt_promises_is_honoured(target, expected, pack):
    """
    The prompt tells the designer to pass the user's words through verbatim, so these are the exact
    strings this resolver receives. A phrasing the prompt advertises and the resolver does not
    understand is a promise the product does not keep - and it fails as "I could not tell which
    answer you mean", which reads like the user's fault.
    """
    state: InterviewState = play(begin(pack), "1", "1", "1", "1", "1", "1")
    after, outcome = state.go_back(target)

    assert outcome.status == REOPENED, f"{target!r} was not understood: {outcome.status}"
    assert after.current.label == expected


def test_a_count_and_a_topic_that_disagree_are_put_back_to_the_user(pack):
    """
    The same fault as an ambiguous answer, one level up.

    "back two - change the topology answer" counts to one entry and names another. Taking the user
    to the wrong question is worse than asking, because they may not notice and would then correct
    an answer that was right.
    """
    state: InterviewState = play(begin(pack), "1", "1", "1", "1", "1", "1")
    after, outcome = state.go_back("back two - change the topology answer")

    assert outcome.status == CHOOSE
    assert len(outcome.candidates) == 2
    assert after.current.label == state.current.label, "the cursor moved on an unresolved request"


def test_a_topic_matching_nothing_shows_the_log_rather_than_guessing(pack):
    """
    A request naming an entry that does not exist gets the log back, so the user can name one that
    does. Anything else is the machinery choosing which answer to change.
    """
    state: InterviewState = play(begin(pack), "1", "1")
    after, outcome = state.go_back("change what I said about the catering")

    assert outcome.status == UNKNOWN
    assert after.current.label == state.current.label
    assert "Q1." in outcome.prompt


def test_a_label_out_of_range_is_refused_with_the_log(pack):
    """
    Numbers the user cannot have meant, including entries not yet asked.
    """
    state: InterviewState = play(begin(pack), "1", "1")
    _, outcome = state.go_back("Q9")

    assert outcome.status == UNKNOWN
    assert "entry 9 of 3" in outcome.note


def test_correcting_one_answer_keeps_every_other_and_resumes_where_it_was(pack):
    """
    The property that makes going back cheap rather than a re-run, asserted as a whole journey.

    Five answers on file, walk back to the second, change it: the other four are untouched, the
    label is unchanged, and the interview resumes at the first entry still unanswered rather than
    re-asking everything it passed on the way back.
    """
    state: InterviewState = play(begin(pack), "1", "1", "1", "1", "1")
    before: list[str] = [entry.answer for entry in state.entries]
    resumed_at: str = state.current.label

    state, _ = state.go_back("Q2")
    state, outcome = state.record("2")

    assert outcome.status == RECORDED
    assert state.entries[1].answer != before[1], "the corrected answer was not replaced"
    assert [entry.answer for entry in state.entries][2:] == before[2:], "an untouched answer changed"
    assert state.entries[0].answer == before[0]
    assert state.current.label == resumed_at, "the interview did not resume where it had got to"


def test_there_is_no_limit_on_how_far_back_or_how_often(pack):
    """
    "N questions back, as many times as needed" is the promise. A cap would be a cap on it.

    Walks the whole interview backwards one entry at a time from the last answer to the first, then
    forward again, and asserts nothing was lost on either leg.
    """
    state: InterviewState = play(begin(pack), *["1"] * len(pack.open_variables))
    answers: list[str] = [entry.answer for entry in state.entries]

    state = InterviewState(domain_id=state.domain_id, entries=state.entries, cursor=len(state.entries) - 1)
    for expected in range(len(pack.open_variables) - 2, -1, -1):
        state, outcome = state.go_back()
        assert outcome.status == REOPENED
        assert state.current.label == f"Q{expected + 1}"

    assert [entry.answer for entry in state.entries] == answers, "walking back lost an answer"
    assert state.current.label == "Q1"


def test_the_log_is_labelled_so_it_cannot_be_read_as_an_option_list(pack):
    """
    Two numbered lists in one reply and the user answers the wrong one.

    The log is navigated by label and the options are answered by number, so a log rendered as
    "1." would be indistinguishable from an offered option - to the user, and to anything reading
    the transcript afterwards.
    """
    state: InterviewState = play(begin(pack), "1", "1")
    _, outcome = state.go_back("Q1")

    log_part: str = outcome.prompt.split("Back to", maxsplit=1)[0]
    assert not offered_options(log_part), "the answer log rendered as a numbered option list"
    assert all(line.startswith("Q") for line in state.log_lines())


def test_the_log_shows_only_what_has_been_asked(pack):
    """
    Every entry exists from the start so labels can be stable, but a log listing questions the user
    has not seen would be reporting answers nobody was asked for.
    """
    state: InterviewState = play(begin(pack), "1", "1")

    assert len(state.log_lines()) == 3, state.log_lines()
    assert "not yet answered" in state.log_lines()[-1]


def test_a_corrected_answer_is_the_one_that_reaches_the_brief(pack):
    """
    What going back is FOR, at the only point where it finally matters.

    An answer corrected mid-interview but recalled at brief-writing time with its old value would
    make going back appear to work while the user approves the mistake it was meant to fix. So the
    brief's two sections are derived from the entries, where a correction has already replaced the
    value in place, rather than assembled from a reading of the conversation.
    """
    state: InterviewState = play(begin(pack), "1", "1", "1")
    original: str = state.entries[2].answer

    state, _ = state.go_back("Q3")
    state, _ = state.record("2")
    confirmed, assumed = state.brief_lines()

    assert not assumed
    assert not any(original in line for line in confirmed), "the superseded answer reached the brief"
    assert any(state.entries[2].answer in line for line in confirmed)
    assert len(confirmed) == 3, "the brief listed an answer nobody gave"


def test_the_brief_separates_what_was_given_from_what_was_defaulted(pack):
    """
    The brief's whole claim, held as data rather than as a judgement made while writing it.
    """
    state: InterviewState = begin(pack)
    state, _ = state.record("1")
    state, _ = state.assume("a default nobody was asked for")
    confirmed, assumed = state.brief_lines()

    assert len(confirmed) == 1 and len(assumed) == 1
    assert "a default nobody was asked for" in assumed[0]
    assert not any("a default nobody was asked for" in line for line in confirmed)


def test_an_unanswered_question_is_in_neither_brief_section(pack):
    """
    Every entry exists from the start so labels stay stable, so the brief has to filter.
    """
    state: InterviewState = play(begin(pack), "1")
    confirmed, assumed = state.brief_lines()

    assert len(confirmed) + len(assumed) == 1, "the brief reported an answer that was never given"


# --------------------------------------------------------------------------------------
# Carrying the state between turns
# --------------------------------------------------------------------------------------


def test_the_interview_survives_a_round_trip_through_sly_data(pack):
    """
    The state crosses a turn boundary as JSON, via the client and back. If a round trip lost
    anything, the designer would re-ask questions the user had already answered.
    """
    state: InterviewState = play(begin(pack), "2", "1", "1")
    state, _ = state.go_back("Q1")

    assert from_dict(to_dict(state)) == state


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ({}, "carried no entries"),
        ({"entries": []}, "carried no entries"),
        ("not a dict", "carried no entries"),
        ({"entries": [{"label": "Q1"}]}, "malformed"),
    ],
)
def test_a_broken_payload_is_an_error_rather_than_a_silent_restart(raw, expected):
    """
    The failure that would be worst if it were quiet.

    An interview restarting at Q1 with every answer gone would have the user answering the same
    questions with no idea why, and the designer reporting confirmed requirements it no longer
    holds. Better to say the state was lost.
    """
    with pytest.raises(ValueError, match=expected):
        from_dict(raw)


def test_a_cursor_outside_the_entries_is_refused(pack):
    """
    A payload that parses but points nowhere. current would raise on the next read, somewhere less
    obvious than here.
    """
    raw: dict = to_dict(begin(pack))
    raw["cursor"] = 99

    with pytest.raises(ValueError, match="points at entry 99"):
        from_dict(raw)


def test_the_subject_falls_back_to_the_whole_question(pack):  # pylint: disable=unused-argument
    """
    Open variables are written "<subject>: <question>", but a pack need not use that shape, and a
    log line is more useful long than absent.
    """
    entry: Entry = Entry(label="Q1", variable_id="V1", question="Which one is it?", options=(), why="")

    assert entry.subject == "Which one is it"
