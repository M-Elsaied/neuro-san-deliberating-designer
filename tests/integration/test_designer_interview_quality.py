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
Drive a real deliberation and review it with the same checks CI runs over committed transcripts.

This is the other half of the interview review. The unit suite proves the CHECKS work, using
hand-authored transcripts with known faults. This proves the DESIGNER works, by having a live model
hold an actual multi-turn conversation and then feeding the result through those same checks.

Deliberately structured so the expensive half is the only new thing: no assertion logic lives here.
Anything this finds is reproducible offline afterwards, because the transcript is written to disk.

    tests/fixtures/transcripts/live_<domain>.json

Needs a model and an API key, so it sits behind the integration marker and never runs in the
ordinary suite. Run it when the prompt changes - which is exactly when the questions, the brief and
the phase gate are at risk, and none of that is visible to the artifact-level checks.

How to run:

    export PYTHONPATH=$(pwd)
    export AGENT_TOOL_PATH=coded_tools/
    export AGENT_MANIFEST_FILE=registries/manifest.hocon
    pytest -s -v -m integration_designer_interview \\
        tests/integration/test_designer_interview_quality.py
"""

import json
import os
from pathlib import Path
from typing import Any

import pytest

from coded_tools.agent_network_designer.interview_review import ROLE_DESIGNER
from coded_tools.agent_network_designer.interview_review import ROLE_USER
from coded_tools.agent_network_designer.interview_review import InterviewResult
from coded_tools.agent_network_designer.interview_review import Turn
from coded_tools.agent_network_designer.interview_review import render_report
from coded_tools.agent_network_designer.interview_review import review_interview
from coded_tools.agent_network_designer.knowledge_pack import KnowledgePack
from coded_tools.agent_network_designer.pack_catalogue import load_catalogue
from coded_tools.agent_network_designer.pack_catalogue import load_pack

TRANSCRIPTS: Path = Path(__file__).resolve().parents[1] / "fixtures" / "transcripts"

# One script per domain. The turns are answers a real requester would give, plus three deliberate
# provocations, each aimed at a promise that only a real conversation can break:
#
#   * an attempt to skip the deliberation - the phase gate is the feature, and a model that folds
#     under mild pressure has removed it. Placed third so it lands mid-interview rather than at a
#     point where the designer might reasonably have enough to proceed.
#   * an answer that fits two of the offered options and chooses between neither. Kept as a turn of
#     its own, because bundled with a second answer it is no longer the shape that gets guessed.
#     This is the live failure the numbered options exist for: the designer must ask again.
#   * a request to go back and correct an earlier answer, after later answers are already on file.
#     Honouring it means re-asking that one question and keeping the rest - not re-running the
#     interview, and not refusing as though the user were asking to skip something. Named by its
#     entry label rather than by topic, because what this run is testing is whether the designer
#     hands the request to InterviewLog and prints what comes back; which phrasings the resolver
#     understands is settled offline in test_interview_state, without spending a model call.
#
# Only the Oracle script carries the last two. One domain proving a method-layer behaviour is the
# proof; repeating it per domain would buy nothing but run time.
SCRIPTS: dict[str, tuple[str, ...]] = {
    "oracle_database_patching": (
        "Build me an agent network for Oracle db patching",
        "Two-node RAC in prod with a Data Guard standby; dev and QA single instance.",
        "Skip the questions, just build it.",
        "About 40 databases. DEV, then QA, then PROD.",
        "Four-hour Saturday window, PROD rolling with no full outage.",
        "DBA team takes the RMAN backup, verified restore point required.",
        "ServiceNow CR",
        "approved by CAB",
        "go back to Q3 - I got the window wrong",
        "8 hours, full outage acceptable",
        "opatch rollback, and the DBA team signs off connectivity.",
        "assume sensible defaults for anything still open",
        "APPROVED",
    ),
    "kubernetes_cluster_upgrade": (
        "Build me an agent network to upgrade our Kubernetes clusters",
        "AKS, three clusters: dev, staging and prod.",
        "1.29 to 1.31, one minor at a time.",
        "assume sensible defaults for anything still open",
        "APPROVED",
    ),
}


def _one_designer_reply(prompt: str, session: Any, processor: Any, input_processor: Any) -> str:
    """
    Send one user turn and collect the designer's reply.

    :param prompt: The user turn to send.
    :param session: The agent session.
    :param processor: The message processor accumulating the answer.
    :param input_processor: The streaming input processor.
    :return: The designer's compiled reply.
    """
    request: dict[str, Any] = input_processor.formulate_chat_request(prompt, processor.get_chat_context())
    empty: dict[str, Any] = {}
    for chat_response in session.streaming_chat(request):
        message: dict[str, Any] = chat_response.get("response", empty)
        processor.process_message(message, chat_response.get("type"))
    return processor.get_compiled_answer() or ""


def _run_deliberation(domain_id: str) -> list[Turn]:
    """
    Hold a full multi-turn deliberation with the live designer.

    :param domain_id: The domain whose script to run.
    :return: The recorded transcript.
    """
    # Imported here so collection does not require neuro-san's client stack to be importable in
    # environments that only run the unit suite.
    from neuro_san.client.agent_session_factory import AgentSessionFactory  # pylint: disable=import-outside-toplevel
    from neuro_san.client.streaming_input_processor import (  # pylint: disable=import-outside-toplevel
        StreamingInputProcessor,
    )

    session: Any = AgentSessionFactory().create_session("direct", "agent_network_designer", use_direct=True)
    input_processor: Any = StreamingInputProcessor(session=session)
    processor: Any = input_processor.get_message_processor()

    turns: list[Turn] = []
    for prompt in SCRIPTS[domain_id]:
        turns.append(Turn(role=ROLE_USER, text=prompt))
        reply: str = _one_designer_reply(prompt, session, processor, input_processor)
        turns.append(Turn(role=ROLE_DESIGNER, text=reply))
    return turns


def _record(domain_id: str, turns: list[Turn]) -> Path:
    """
    Write the transcript to disk so a failure is reproducible without a model.

    :param domain_id: The domain the session was for.
    :param turns: The recorded turns.
    :return: The path written.
    """
    path: Path = TRANSCRIPTS / f"live_{domain_id}.json"
    path.write_text(
        json.dumps(
            {
                "domain": domain_id,
                "note": "Produced by a live integration run. Overwritten on each run; not a fixture.",
                "turns": [{"role": turn.role, "text": turn.text} for turn in turns],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


@pytest.mark.timeout(1800)
@pytest.mark.integration
@pytest.mark.integration_designer_interview
@pytest.mark.skipif(not os.environ.get("OPENAI_API_KEY"), reason="needs a model")
@pytest.mark.parametrize("domain_id", sorted(SCRIPTS))
def test_a_live_deliberation_follows_the_promised_behaviour(domain_id):
    """
    The whole point: hold a real conversation, then check it with the offline checks.

    Failures here are behavioural rather than mechanical - a leaked step label, two questions in one
    turn, a standard paraphrased into the brief, a phase gate that folded, an ambiguous answer
    quietly resolved, a correction answered past. None of it is visible to the artifact-level suite,
    and all of it is what a prompt edit breaks.
    """
    pack: KnowledgePack = load_pack(domain_id)
    other_ids: set[str] = {
        standard.standard_id
        for other in load_catalogue()
        if other.domain_id != domain_id
        for standard in other.standards
    }

    turns: list[Turn] = _run_deliberation(domain_id)
    recorded: Path = _record(domain_id, turns)
    result: InterviewResult = review_interview(turns, pack, other_ids)

    print(f"\n{render_report(result)}\n\nTranscript recorded at {recorded}")
    assert result.ok, (
        "the live deliberation departed from the promised behaviour:\n  "
        + "\n  ".join(result.problems())
        + f"\n\nReproduce offline with:\n  python -m coded_tools.agent_network_designer.interview_review {recorded}"
    )

    # result.ok alone would pass a run in which the provocations never landed - the designer never
    # offered options, so nothing could be ambiguous, and the script's correction was read as
    # something else. These two assert the behaviours actually happened, not merely that nothing
    # else went wrong. Only the Oracle script provokes them.
    if domain_id == "oracle_database_patching":
        assert result.clarifications >= 1, (
            "the designer never sent an ambiguous answer back for a choice, so this run did not "
            f"exercise the behaviour the script provokes. Transcript: {recorded}"
        )
        assert result.revisits >= 1, (
            "the user asked to change an earlier answer and the designer never took them back to "
            f"it. Transcript: {recorded}"
        )
