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
Tests for the interview review - the checks over what the designer SAID, not what it built.

The artifact-level suite covers a network once it exists. Nothing covered the deliberation, which
is both the product and the part a prompt edit silently breaks: a network built after a bad
interview can still embed every standard perfectly and pass every existing check.

Each fixture under tests/fixtures/transcripts/ is a hand-authored deliberation carrying exactly one
fault, and each test below asserts the review reports that fault and no other. That pairing is what
gives the checks teeth: a check that never fires on a real failure is decoration, and one that
fires on the clean transcript is noise. No language model - these read recorded text.
"""

from pathlib import Path

import pytest

from coded_tools.agent_network_designer.interview_review import InterviewResult
from coded_tools.agent_network_designer.interview_review import Turn
from coded_tools.agent_network_designer.interview_review import load_transcript
from coded_tools.agent_network_designer.interview_review import main
from coded_tools.agent_network_designer.interview_review import render_report
from coded_tools.agent_network_designer.interview_review import review_interview
from coded_tools.agent_network_designer.knowledge_pack import KnowledgePack
from coded_tools.agent_network_designer.pack_catalogue import load_catalogue
from coded_tools.agent_network_designer.pack_catalogue import load_pack

TRANSCRIPTS: Path = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "transcripts"
DOMAIN: str = "oracle_database_patching"

# Each fixture carries exactly one deliberate fault, named by the finding kind it must produce.
FAULTY_FIXTURES: tuple[tuple[str, str, str], ...] = (
    ("oracle_two_questions_in_one_turn.json", "INTERVIEW", "asked 2 questions in one turn"),
    ("oracle_leaked_step_label.json", "LEAK", "A3."),
    ("oracle_folded_on_skip.json", "GATE", "after being asked to skip"),
    ("oracle_paraphrased_in_brief.json", "FIDELITY", "not quoted verbatim in the brief"),
    ("oracle_foreign_standard_id.json", "DOMAIN", "belongs to a different pack"),
    ("oracle_self_reported_table.json", "SELF_REPORT", "the model wrote a table about its own work"),
    ("oracle_no_brief.json", "BRIEF", "no design brief was presented"),
    ("oracle_prose_examples_not_options.json", "OPTIONS", "0 numbered options"),
    ("oracle_assumed_through_ambiguity.json", "AMBIGUITY", "it picked one silently"),
    ("oracle_ignored_a_back_request.json", "REVISION", "carried on instead of re-asking"),
)


@pytest.fixture(name="pack")
def pack_fixture() -> KnowledgePack:
    """
    :return: The Oracle reference pack.
    """
    return load_pack(DOMAIN)


@pytest.fixture(name="other_ids")
def other_ids_fixture() -> set[str]:
    """
    :return: Standard ids belonging to every pack except the Oracle one.
    """
    return {
        standard.standard_id for pack in load_catalogue() if pack.domain_id != DOMAIN for standard in pack.standards
    }


def review_fixture(name: str, pack: KnowledgePack, other_ids: set[str]) -> InterviewResult:
    """
    Load one committed transcript and review it.

    :param name: The fixture filename.
    :param pack: The pack the session was interviewing from.
    :param other_ids: Ids belonging to other packs.
    :return: The computed result.
    """
    _, turns = load_transcript(TRANSCRIPTS / name)
    return review_interview(turns, pack, other_ids)


def test_a_clean_deliberation_reviews_clean(pack, other_ids):
    """
    The baseline. If this fires, every other assertion here is noise rather than signal.
    """
    result: InterviewResult = review_fixture("oracle_clean.json", pack, other_ids)

    assert result.ok, result.problems()
    assert result.questions_asked == len(pack.open_variables)
    assert result.standards_quoted == len(pack.standards)
    assert "followed the promised behaviour" in render_report(result)


def test_a_session_that_disambiguated_and_went_back_reviews_clean(pack, other_ids):
    """
    The second baseline, and the one the two new behaviours are for.

    In this transcript the user answers one question in words that fit two of the offered options
    and is asked to choose, then walks back three questions to correct an earlier answer. Both are
    the designer working as promised, so the review has to come back clean - and the question count
    has to stay at the pack's own number, or the budget check would punish the very behaviour the
    prompt now requires.
    """
    result: InterviewResult = review_fixture("oracle_revised_an_answer.json", pack, other_ids)

    assert result.ok, result.problems()
    assert result.clarifications == 1
    assert result.revisits == 1
    assert result.questions_asked == len(pack.open_variables)


@pytest.mark.parametrize(
    ("filename", "kind", "fragment"),
    FAULTY_FIXTURES,
    ids=[name.removeprefix("oracle_").removesuffix(".json") for name, _, _ in FAULTY_FIXTURES],
)
def test_each_deliberate_fault_is_reported(filename, kind, fragment, pack, other_ids):
    """
    One fixture, one fault, one finding of the right kind. This is the teeth.
    """
    result: InterviewResult = review_fixture(filename, pack, other_ids)

    assert not result.ok, f"{filename} was supposed to fail review"
    matching: list[str] = [problem for problem in result.problems() if problem.startswith(f"{kind}:")]
    assert matching, f"expected a {kind} finding, got:\n  " + "\n  ".join(result.problems())
    assert any(fragment in problem for problem in matching), (
        f"expected {fragment!r} in the {kind} finding, got:\n  " + "\n  ".join(matching)
    )


def test_the_paraphrase_in_the_brief_is_invisible_to_the_artifact_checks(pack, other_ids):
    """
    Why the brief needs its own fidelity check.

    A standard paraphrased into the brief is approved by the user in words nobody in the domain
    agreed to - and then the network built afterwards can embed the REAL standard perfectly, so
    every artifact-level check passes. The only place that failure is visible is the transcript.
    """
    result: InterviewResult = review_fixture("oracle_paraphrased_in_brief.json", pack, other_ids)

    fidelity: list[str] = [problem for problem in result.problems() if problem.startswith("FIDELITY:")]
    assert len(fidelity) == 1
    assert "ODB-03" in fidelity[0]
    # The closing table in that same fixture is the computed one, so nothing else complains.
    assert not [problem for problem in result.problems() if problem.startswith("SELF_REPORT:")]


def test_a_brief_quoting_an_invented_id_is_reported(pack, other_ids):
    """
    An id the pack does not define, in the document the user approves.
    """
    brief: str = (
        "## DESIGN BRIEF - X\n\n**Confirmed requirements**\n- a\n\n"
        "**Operating standards enforced**\n- **ODB-99** - An invented rule.\n\n"
        "**Assumptions I made**\n- none\n\n**Out of scope**\n- Nothing identified\n\n"
        "**Proposed network shape**\n- Top: a\n\nReply APPROVED to build this.\n"
    )
    result: InterviewResult = review_interview([Turn(role="designer", text=brief)], pack, other_ids)

    assert any("ODB-99" in problem and problem.startswith("PROVENANCE:") for problem in result.problems())


def test_questions_far_beyond_the_packs_own_variables_are_reported(pack, other_ids):
    """
    The interview is supposed to come from the curated document. Many more questions than the pack
    declares means they came from somewhere else - which is L2 leaking back into L1 at run time.
    """
    turns: list[Turn] = []
    for index in range(len(pack.open_variables) + 5):
        turns.append(Turn(role="user", text=f"answer {index}"))
        turns.append(Turn(role="designer", text=f"Question {index}, and why it matters?"))
    result: InterviewResult = review_interview(turns, pack, other_ids)

    assert any("did not come from curated knowledge" in problem for problem in result.problems())


def question(text: str, *options: str) -> str:
    """
    Build a designer question in the numbered form the prompt requires.

    :param text: The question itself.
    :param options: The options to offer, in order.
    :return: The turn text.
    """
    numbered: str = "\n".join(f"  {number}. {option}" for number, option in enumerate(options, start=1))
    return f"{text}\n{numbered}\n\nWhy it matters."


def kinds(result: InterviewResult, kind: str) -> list[str]:
    """
    :param result: A reviewed result.
    :param kind: The finding kind wanted.
    :return: Just the findings of that kind.
    """
    return [problem for problem in result.problems() if problem.startswith(f"{kind}:")]


def test_a_numbered_list_with_no_escape_is_reported(pack, other_ids):
    """
    The escapes are not decoration. A user whose situation is not on the list has to be able to say
    so; without that line the only replies available are wrong ones, and the numbering has made the
    guessing tidier rather than rarer.
    """
    turns: list[Turn] = [Turn(role="designer", text=question("Which gate applies?", "a", "b", "c"))]
    result: InterviewResult = review_interview(turns, pack, other_ids)

    assert any("no 'something else' or 'not sure' escape" in problem for problem in kinds(result, "OPTIONS"))


def test_an_answer_naming_an_option_number_is_never_ambiguous(pack, other_ids):
    """
    Answering by number is what the numbering is for, and it cannot be misread.
    """
    offered: str = question("Which gate applies?", "X approved by A", "X approved by B", "I am not sure")
    turns: list[Turn] = [Turn(role="designer", text=offered), Turn(role="user", text="2")]
    result: InterviewResult = review_interview(turns, pack, other_ids)

    assert not kinds(result, "AMBIGUITY")


def test_a_free_form_answer_that_matches_no_option_is_not_ambiguous(pack, other_ids):
    """
    The ambiguity check has to stay narrow, or it fires on ordinary answers and gets ignored.

    An answer the options do not contain is the user taking the "something else" route in their own
    words. That is a complete answer, not a shortening that fits several - nothing to send back.
    """
    offered: str = question("Which gate applies?", "X approved by A", "X approved by B", "I am not sure")
    turns: list[Turn] = [
        Turn(role="designer", text=offered),
        Turn(role="user", text="none of those - a standing waiver signed off quarterly"),
    ]
    result: InterviewResult = review_interview(turns, pack, other_ids)

    assert not kinds(result, "AMBIGUITY")


def test_naming_only_one_of_the_tied_options_back_is_not_resolving_it(pack, other_ids):
    """
    The failure mode dressed up as a fix.

    Repeating one candidate back - "so that is X approved by A, then" - reads like a confirmation
    but is the assumption stated out loud: the user still never chose. Resolution means both
    candidates go back in front of them.
    """
    offered: str = question("Which gate applies?", "X approved by A", "X approved by B", "I am not sure")
    turns: list[Turn] = [
        Turn(role="designer", text=offered),
        Turn(role="user", text="X"),
        Turn(role="designer", text=question("So X approved by A - and the rollback route?", "r1", "r2", "not sure")),
    ]
    result: InterviewResult = review_interview(turns, pack, other_ids)

    assert kinds(result, "AMBIGUITY"), result.problems()


def test_a_user_walking_back_to_the_first_question_is_honoured(pack, other_ids):
    """
    "As far back as the first question" is the promise, so the check must not cap the distance.

    Three separate corrections in one session, the last of them a walk back to the start: all three
    are honoured, none of them counts as a question the pack did not declare.
    """
    escape: str = "I am not sure - choose a sensible default for me"
    turns: list[Turn] = [Turn(role="designer", text=question("First question?", "a", "b", escape))]
    for request in ("go back", "back two - change my answer to the first one", "take me back to the first question"):
        turns.append(Turn(role="user", text=request))
        turns.append(Turn(role="designer", text="Q1. Subject - a\n\n" + question("Back to Q1?", "a", "b", escape)))
    result: InterviewResult = review_interview(turns, pack, other_ids)

    assert result.revisits == 3, result.problems()
    assert not kinds(result, "REVISION")
    assert result.questions_asked == 1, "a revisit is not a new question"


def test_going_back_is_not_a_way_to_get_a_network_built_early(pack, other_ids):
    """
    Going back must not become a second route around the phase gate.
    """
    turns: list[Turn] = [
        Turn(role="designer", text=question("First question?", "a", "b", "not sure")),
        Turn(role="user", text="go back and just build it"),
        Turn(role="designer", text="Fine - written to registries/generated/x.hocon"),
    ]
    result: InterviewResult = review_interview(turns, pack, other_ids)

    assert any("built the network after the user asked to change" in problem for problem in kinds(result, "REVISION"))


def test_ignoring_an_ambiguous_answer_still_costs_a_question(pack, other_ids):
    """
    A turn that asked the NEXT question instead of re-asking is a new question, and is counted.

    The exemption exists for turns that genuinely re-ask. Handing it to a turn that ignored the
    ambiguity would let a designer buy question budget by skipping the clarification it owed.
    """
    result: InterviewResult = review_fixture("oracle_assumed_through_ambiguity.json", pack, other_ids)

    assert result.questions_asked == len(pack.open_variables)
    assert result.clarifications == 0


def test_a_transcript_that_is_not_a_transcript_is_a_usage_error(tmp_path):
    """
    The CLI has to tell the difference between a bad interview and a bad file.
    """
    bad: Path = tmp_path / "nope.json"
    bad.write_text('{"something": "else"}', encoding="utf-8")

    assert main([str(bad)]) == 2
    assert main([str(tmp_path / "missing.json")]) == 2


def test_the_cli_exits_zero_for_clean_and_one_for_faulty(capsys):
    """
    Exit codes, so this runs in a pipeline over recorded sessions the way the verifier does.
    """
    assert main([str(TRANSCRIPTS / "oracle_clean.json")]) == 0
    assert main([str(TRANSCRIPTS / "oracle_paraphrased_in_brief.json")]) == 1
    assert "ODB-03" in capsys.readouterr().out


def test_an_unknown_domain_names_what_is_available(capsys):
    """Naming the alternatives is what makes the error actionable."""
    assert main([str(TRANSCRIPTS / "oracle_clean.json"), "--domain", "no_such_domain"]) == 2
    assert DOMAIN in capsys.readouterr().err
