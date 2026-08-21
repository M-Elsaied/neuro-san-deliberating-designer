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


def test_the_designer_is_told_to_discover_the_catalogue_before_matching(front_man):
    """
    Discovery is worthless if the prompt still assumes it knows what exists.
    """
    instructions: str = collapse(str(front_man.get("instructions") or ""))
    assert "Call ListDomains to find out which curated domains this deployment actually has" in instructions
    assert "Never assume a domain exists without listing first" in instructions
