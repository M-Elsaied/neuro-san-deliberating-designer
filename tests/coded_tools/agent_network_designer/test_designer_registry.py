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
Contract tests over the designer's registry file itself.

These exist because of a specific failure. A tool was declared with an empty ``properties`` dict,
which is valid HOCON and parses cleanly, but neuro-san rejects it when it builds the tool - so the
network could not run at all, while every unit test and both linters stayed green. Parsing a config
is not the same as the runtime accepting it.

So the first test here runs neuro-san's OWN validator over every tool entry in the file. It costs
no language model and would have caught that in a second.

The rest assert the properties the deliberation design claims but which nothing enforced:

  * L1 holds no L2 - no domain noun anywhere in the method layer;
  * Phase A cannot build, and Phase B does not write its own coverage table;
  * every declared coded-tool class actually resolves.

Each is a property a plausible-looking prompt edit can silently break.
"""

import re
from pathlib import Path
from typing import Any

import pytest
from neuro_san.internals.run_context.langchain.core.langchain_openai_function_tool import LangChainOpenAIFunctionTool
from pyhocon import ConfigFactory

REGISTRY_PATH: Path = Path("registries/agent_network_designer.hocon")
CODED_TOOLS_DIR: Path = Path("coded_tools/agent_network_designer")

# Vocabulary from the three shipped packs. None of it belongs in the method layer: a domain noun in
# the designer's own prompt biases every other domain, which is the defect the L1/L2 split exists to
# prevent. Matched case-insensitively on word boundaries, so "rac" does not fire inside "practice"
# and "aks" does not fire inside "makes".
DOMAIN_NOUNS: tuple[str, ...] = (
    "oracle",
    "rman",
    "opatch",
    "datapatch",
    "exadata",
    "rac",
    "data guard",
    "kubernetes",
    "etcd",
    "poddisruptionbudget",
    "poddisruptionbudgets",
    "kubelet",
    "aks",
    "eks",
    "clinical",
    "meddra",
    "whodrug",
    "unblinding",
    "sdv",
    "servicenow",
)


def collapse(text: str) -> str:
    """
    Whitespace-collapse prompt text before matching a phrase against it.

    Prompt lines wrap, so a phrase that reads as one sentence in the file is split by a newline and
    an indent. Asserting on the raw text would make every test here brittle to re-wrapping - which
    is exactly the mistake the verifier's own fidelity check avoids.

    :param text: The raw prompt text.
    :return: The text with all runs of whitespace collapsed to single spaces.
    """
    return re.sub(r"\s+", " ", text).strip()


@pytest.fixture(name="registry")
def registry_fixture() -> Any:
    """
    :return: The parsed designer registry, with includes resolved from the repository root.
    """
    assert REGISTRY_PATH.is_file(), f"{REGISTRY_PATH} not found - run pytest from the repository root"
    # basedir="." because the file's own includes are written relative to the repository root,
    # which is how the server loads it.
    return ConfigFactory.parse_string(REGISTRY_PATH.read_text(encoding="utf-8"), basedir=".")


@pytest.fixture(name="agents")
def agents_fixture(registry) -> list[dict[str, Any]]:
    """
    :param registry: The parsed registry.
    :return: Every agent entry in the network, as dicts.
    """
    return [dict(entry) for entry in registry.get("tools")]


@pytest.fixture(name="front_man")
def front_man_fixture(agents) -> dict[str, Any]:
    """
    :param agents: Every agent entry.
    :return: The front man, which by neuro-san convention is the first entry.
    """
    return agents[0]


# --------------------------------------------------------------------------------------
# The runtime contract: neuro-san has to accept what we declared
# --------------------------------------------------------------------------------------


def test_every_tool_entry_satisfies_neuro_sans_own_function_validator(agents):
    """
    Run the framework's validator over every declared tool.

    This is the test that would have caught ``"properties": {}`` on ListDomains: HOCON-valid,
    lint-clean, and fatal at tool-construction time.
    """
    failures: list[str] = []
    for agent in agents:
        function: Any = agent.get("function")
        if function is None:
            # Toolbox entries (e.g. web_search) declare no function of their own.
            continue
        function_json: dict[str, Any] = dict(function)
        function_json.setdefault("name", agent.get("name"))
        try:
            LangChainOpenAIFunctionTool.verify_function_json(function_json)
        except ValueError as exception:
            failures.append(f"{agent.get('name')}: {str(exception).splitlines()[0]}")

    assert not failures, "neuro-san would refuse to build these tools:\n  " + "\n  ".join(failures)


def test_no_tool_declares_an_empty_properties_dict(agents):
    """
    Pin the specific shape that broke, in its own test, so the reason survives in the name.

    A tool taking no arguments must omit ``parameters`` entirely rather than declare an empty
    properties dict.
    """
    offenders: list[str] = []
    for agent in agents:
        function: Any = agent.get("function")
        if function is None:
            continue
        parameters: Any = dict(function).get("parameters")
        if parameters is None:
            continue
        properties: Any = dict(parameters).get("properties")
        if properties is not None and len(dict(properties)) == 0:
            offenders.append(str(agent.get("name")))

    assert not offenders, f"declare no 'parameters' block instead of an empty one: {offenders}"


def test_every_coded_tool_class_resolves_to_a_module_on_disk(agents):
    """
    A "class" that does not resolve fails at load, not at import, so nothing else catches it.
    """
    missing: list[str] = []
    for agent in agents:
        class_reference: Any = agent.get("class")
        if not class_reference:
            continue
        module_name: str = str(class_reference).split(".", maxsplit=1)[0]
        if not (CODED_TOOLS_DIR / f"{module_name}.py").is_file():
            missing.append(str(class_reference))

    assert not missing, f"declared classes with no module under {CODED_TOOLS_DIR}: {missing}"


def test_pack_provenance_is_allowed_upstream_so_it_survives_the_interview(front_man):
    """
    A sly_data key not listed in allow.to_upstream cannot outlive the turn that wrote it.

    The session rebuilds sly_data from the client's payload on every turn, so the provenance
    recorded by ExtractDocs during the interview is discarded before the build turn unless it is
    permitted upstream. A live run proved this: the generated artifact carried no provenance at
    all. Removing this entry would silently reintroduce that.
    """
    allow: dict[str, Any] = dict(front_man.get("allow") or {})
    upstream: list[str] = [str(key) for key in dict(allow.get("to_upstream") or {}).get("sly_data", [])]

    assert "agent_network_pack_provenance" in upstream, "provenance will not survive the interview turns without this"


def test_the_front_man_can_reach_the_curated_knowledge_tools(front_man, agents):
    """
    A tool nobody lists is a tool nobody calls - the wiring is as load-bearing as the entry.
    """
    declared: set[str] = {str(agent.get("name")) for agent in agents}
    wired: list[str] = [str(name) for name in front_man.get("tools")]

    for required in ("ListDomains", "ExtractDocs", "VerifyStandards"):
        assert required in declared, f"{required} is not declared in the network"
        assert required in wired, f"{required} is declared but the front man cannot call it"


# --------------------------------------------------------------------------------------
# The design contract: L1 holds no L2
# --------------------------------------------------------------------------------------


def test_the_method_layer_names_no_domain(front_man, agents):
    """
    The industry-agnostic claim, enforced structurally rather than by discipline.

    Covers the front man's instructions and every tool description, because a tool description is
    not documentation - it is the only way the model learns a domain exists.
    """
    surfaces: dict[str, str] = {"front man instructions": str(front_man.get("instructions") or "")}
    for agent in agents:
        function: Any = agent.get("function")
        if function is None:
            continue
        description: str = str(dict(function).get("description") or "")
        surfaces[f"{agent.get('name')} description"] = description

    found: list[str] = []
    for where, text in surfaces.items():
        lowered: str = collapse(text).lower()
        found.extend(
            f"{noun!r} in {where}"
            for noun in DOMAIN_NOUNS
            if re.search(rf"\b{re.escape(noun)}\b", lowered) is not None
        )

    assert not found, "domain vocabulary leaked into the method layer:\n  " + "\n  ".join(found)


def test_the_shared_scoping_preamble_survived_the_hocon_concatenation(front_man):
    """
    ``"instructions": ${expertise_scoping_instructions} \"\"\"...\"\"\"`` is a concatenation.

    Introduce a comma and HOCON reads it as a list instead: the preamble silently vanishes, nothing
    errors, and the agent just gets worse. Cheap to assert, invisible otherwise.
    """
    instructions: str = str(front_man.get("instructions") or "")
    assert not instructions.lstrip().startswith("You are responsible for designing"), (
        "the shared scoping preamble is missing - check for a stray comma before the triple-quoted block"
    )


def test_phase_a_forbids_building_and_allows_only_the_informing_tools(front_man):
    """
    The gate is the feature. If Phase A can build, there is no deliberation.
    """
    instructions: str = collapse(str(front_man.get("instructions") or ""))

    assert "PHASE A - DELIBERATE" in instructions
    assert "PHASE B - BUILD" in instructions
    for forbidden in ("agent_network_editor", "agent_network_instructions_editor", "agent_network_query_generator"):
        assert forbidden in instructions.split("PHASE B")[0], f"{forbidden} is not named as forbidden in Phase A"
    assert "ListDomains" in instructions.split("PHASE B")[0], "Phase A must be able to discover the catalogue"


def test_phase_b_prints_the_computed_table_and_writes_none_of_its_own(front_man):
    """
    The point of the change: the model must not author the table that certifies its own work.
    """
    instructions: str = collapse(str(front_man.get("instructions") or ""))
    phase_b: str = instructions.split("PHASE B")[-1]

    assert "VerifyStandards" in phase_b, "Phase B does not call the verifier"
    assert "| Standard | Owned by |" not in instructions, "a hand-written coverage table is back in the prompt"
    assert "Do NOT write the coverage table yourself" in phase_b


def test_the_interview_is_driven_by_the_tool_rather_than_remembered(front_man):
    """
    The prompt's half of the fix a live session argued for, and the load-bearing part of it.

    The designer offered its example answers as prose inside one sentence, the user replied with the
    words two of those examples shared, and it recorded that and moved on - so the built network's
    approval gate was chosen by the model and the user was never told a choice existed. Telling the
    model to keep a better log would have been another instruction to drift from; InterviewLog
    computes the questions, the answers and the position instead, and the prompt's job is now to
    print what it returns. So what is asserted here is the handover, not the formatting.
    """
    instructions: str = collapse(str(front_man.get("instructions") or ""))
    phase_a: str = instructions.split("PHASE B")[0]

    assert "InterviewLog" in phase_a, "Phase A cannot reach the interview state"
    assert 'print the "prompt" it returns VERBATIM' in phase_a
    assert "You do NOT keep the answer log yourself" in phase_a
    assert "never renumber the options, never re-word an option" in phase_a
    assert "InterviewLog" in front_man.get("tools", []), "the front man is not wired to the tool"


def test_an_ambiguous_answer_may_not_be_settled_by_assuming(front_man):
    """
    The interview's whole claim is that it separates what you confirmed from what it assumed.

    An answer consistent with several offered options, recorded as though it chose one, breaks that
    claim in the worst available way: it lands under "Confirmed requirements" without the user
    having confirmed it, which is the one place the brief promises never to guess. The tool decides
    whether a reply was ambiguous, so the prompt's duty is to pass the words through unedited and
    to obey the answer.
    """
    phase_a: str = collapse(str(front_man.get("instructions") or "")).split("PHASE B")[0]

    assert 'reply: "<what they said, VERBATIM>"' in phase_a
    assert "the assumption the tool exists to catch, and it cannot catch what it is not shown" in phase_a
    assert "The variable is STILL OPEN" in phase_a
    assert "do not name one of the candidates back as though it had been chosen" in phase_a


def test_the_user_can_walk_back_to_any_earlier_answer(front_man):
    """
    An interview that only moves forward makes the first wrong answer unfixable except by starting
    the session over. Going back has to be reachable from the prompt, passed to the tool in the
    user's own words - the tool resolves a count, a label or a topic, and can only notice a count
    and a topic disagreeing if it sees both - and it must never be read as a request to skip.
    """
    instructions: str = collapse(str(front_man.get("instructions") or ""))
    phase_a: str = instructions.split("PHASE B")[0]

    assert "CHANGE AN EARLIER ANSWER at any time before the build" in phase_a
    assert 'action: "back", target: "<their words, VERBATIM>"' in phase_a
    assert "There is no limit on how far back or how many times" in phase_a
    assert "Going back to an earlier answer is NOT skipping and is never refused" in instructions


def test_a_default_is_recorded_as_assumed_and_not_as_an_answer(front_man):
    """
    The one judgement the tool cannot make, and the flag that keeps it honest.

    A default is a domain fact, so the model has to choose it - but recording it through the same
    door as a real answer would make an assumption indistinguishable from a confirmation by the
    time the brief is written, which is exactly what the brief promises to keep apart.
    """
    phase_a: str = collapse(str(front_man.get("instructions") or "")).split("PHASE B")[0]

    assert "the tool cannot, because a default is a domain fact and it holds none" in phase_a
    assert 'never record a default through action "answer" instead' in phase_a


def test_the_brief_takes_its_answers_from_the_log_not_from_memory(front_man):
    """
    The gap where the computed interview met a recalled document.

    Holding the answers in a tool is worth nothing if the brief - the thing the user actually reads
    and approves - is still composed from a recollection of the conversation. The failure it lets
    through is the worst one available: an answer the user went back and corrected reaching the
    brief with its old value, so going back appears to have worked while the mistake it was meant
    to fix is what gets approved.
    """
    phase_a: str = collapse(str(front_man.get("instructions") or "")).split("PHASE B")[0]

    assert "take the brief's two answer sections from InterviewLog, not from your memory" in phase_a
    assert '"confirmed" is the list for "Confirmed requirements"' in phase_a
    assert '"assumed" is the list for "Assumptions I made"' in phase_a


def test_the_designer_is_told_to_discover_the_catalogue_before_matching(front_man):
    """
    Discovery is worthless if the prompt still assumes it knows what exists.
    """
    instructions: str = collapse(str(front_man.get("instructions") or ""))
    assert "Call ListDomains to find out which curated domains this deployment actually has" in instructions
    assert "Never assume a domain exists without listing first" in instructions
