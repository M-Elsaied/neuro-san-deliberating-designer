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
Unit tests for the standards verifier.

Each test pins one way a generated network can silently fail to carry the standards it claims.
No language model, no network, no agent runtime.
"""

from typing import Any

import pytest

from coded_tools.agent_network_designer.knowledge_pack import KnowledgePack
from coded_tools.agent_network_designer.knowledge_pack import load_pack
from coded_tools.agent_network_designer.standards_verifier import extract_embedded_standards
from coded_tools.agent_network_designer.standards_verifier import network_definition_from_hocon
from coded_tools.agent_network_designer.standards_verifier import render_report
from coded_tools.agent_network_designer.standards_verifier import verify


@pytest.fixture(name="pack")
def pack_fixture() -> KnowledgePack:
    """:return: The Oracle reference pack."""
    return load_pack("oracle_database_patching")


def clean_network(pack: KnowledgePack) -> dict[str, Any]:
    """
    Build a network that embeds every standard exactly once, verbatim, in its own agent.

    This is what a correct build looks like; every other fixture in this module is a mutation
    of it.

    :param pack: The pack to satisfy.
    :return: An agent network definition.
    """
    network: dict[str, Any] = {
        "front_man": {"instructions": "You coordinate the patching run.", "tools": []},
    }
    for index, standard in enumerate(pack.standards, start=1):
        network[f"agent_{index}"] = {
            "instructions": f"You own one step.\nMUST: {standard.text} [{standard.standard_id}]\n",
            "tools": [],
        }
    network["front_man"]["tools"] = [name for name in network if name != "front_man"]
    return network


# --------------------------------------------------------------------------------------
# Extraction
# --------------------------------------------------------------------------------------


def test_embedded_standards_are_found_with_their_owning_agent():
    """The owning agent is the whole point of the coverage check."""
    network = {
        "backup_gate": {"instructions": "MUST: Take a backup. [ODB-03]"},
        "validator": {"instructions": "Preamble.\nMUST: Check connectivity. [ODB-06]\nEpilogue."},
        "a_coded_tool": {"description": "no instructions here"},
    }
    embedded = extract_embedded_standards(network)
    assert {(item.standard_id, item.agent_name) for item in embedded} == {
        ("ODB-03", "backup_gate"),
        ("ODB-06", "validator"),
    }


def test_a_standard_whose_text_contains_brackets_still_yields_the_right_id():
    """The id is the trailing bracket group, not the first one."""
    network = {"agent": {"instructions": "MUST: Review the README [and its notes] carefully. [ODB-05]"}}
    embedded = extract_embedded_standards(network)
    assert embedded[0].standard_id == "ODB-05"
    assert embedded[0].text == "Review the README [and its notes] carefully."


def test_a_wrapped_must_line_is_still_found():
    """
    The agent writing instructions is a language model and wraps long lines. If a wrapped
    standard were missed, it would be reported as never embedded - sending a reviewer hunting
    for a rule that is present and correct, which is worse than not checking at all.
    """
    network = {
        "backup_gate": {
            "instructions": (
                "You own the backup gate.\n"
                "MUST: Take a full RMAN backup before applying any patch, and confirm\n"
                "the backup is restorable. [ODB-03]\n"
            )
        }
    }
    embedded = extract_embedded_standards(network)
    assert len(embedded) == 1
    assert embedded[0].standard_id == "ODB-03"
    assert "confirm" in embedded[0].text and "restorable" in embedded[0].text


def test_a_wrapped_standard_verifies_as_faithful(pack):
    """Wrapping is a rendering artefact, not a change to the rule."""
    standard = pack.standards[2]
    wrapped: str = standard.text.replace(", and", ",\nand")
    network = {"gate": {"instructions": f"MUST: {wrapped} [{standard.standard_id}]\n"}}
    result = verify(pack, network)
    assert not result.infidelities, result.infidelities
    assert result.owners[standard.standard_id] == ["gate"]


def test_a_blank_line_ends_a_must_paragraph():
    """
    A newline is treated as a wrap only within a paragraph. Without this bound, an unterminated
    MUST line would swallow the rest of an agent's instructions looking for a bracket.
    """
    network = {
        "agent": {
            "instructions": "MUST: A rule with no id\n\nSome later prose. [ODB-01]\n",
        }
    }
    assert not extract_embedded_standards(network)


def test_an_empty_network_extracts_nothing():
    """Guards the verifier against being called before anything was built."""
    assert not extract_embedded_standards({})


# --------------------------------------------------------------------------------------
# The three properties
# --------------------------------------------------------------------------------------


def test_a_correctly_built_network_verifies_clean(pack):
    """The happy path must be reachable, or every other assertion is meaningless."""
    result = verify(pack, clean_network(pack))
    assert result.ok, result.problems()
    assert not result.missing
    assert len(result.owners) == len(pack.standards)


def test_coverage_catches_a_standard_that_reached_no_agent(pack):
    """The failure the self-reported table is least likely to admit to."""
    network = clean_network(pack)
    del network["agent_3"]
    result = verify(pack, network)
    assert not result.ok
    assert "ODB-03" in result.missing
    assert any("ODB-03 is not embedded" in problem for problem in result.problems())


def test_coverage_catches_a_standard_owned_by_two_agents(pack):
    """Two owners means neither is accountable."""
    network = clean_network(pack)
    network["duplicate_owner"] = {"instructions": f"MUST: {pack.standards[0].text} [ODB-01]"}
    result = verify(pack, network)
    assert not result.ok
    assert "ODB-01" in result.ambiguous
    assert any("more than one agent" in problem for problem in result.problems())


def test_provenance_catches_an_invented_standard(pack):
    """
    The build-time version of the pizza failure: a confident-looking rule with an id that does
    not exist. Nothing in the current design would notice this.
    """
    network = clean_network(pack)
    network["over_eager"] = {"instructions": "MUST: Always take two backups. [ODB-07]"}
    result = verify(pack, network)
    assert not result.ok
    assert [item.standard_id for item in result.unknown] == ["ODB-07"]
    assert any("not a standard in this pack" in problem for problem in result.problems())


def test_fidelity_catches_a_paraphrased_standard(pack):
    """
    The failure mode the whole verbatim-embedding design exists to prevent, and the one a human
    skimming the generated file would not spot.
    """
    network = clean_network(pack)
    network["agent_3"]["instructions"] = "MUST: Take a backup before patching. [ODB-03]"
    result = verify(pack, network)
    assert not result.ok
    assert [mismatch["standard_id"] for mismatch in result.infidelities] == ["ODB-03"]
    assert "first differs at character" in result.infidelities[0]["detail"]


def test_fidelity_catches_a_dropped_trailing_clause(pack):
    """Truncation is the most plausible real-world infidelity."""
    network = clean_network(pack)
    network["agent_3"]["instructions"] = "MUST: Take a full RMAN backup before applying any patch. [ODB-03]"
    result = verify(pack, network)
    assert not result.ok
    assert result.infidelities


def test_fidelity_tolerates_rewrapping_and_smart_punctuation(pack):
    """
    A model that re-wraps a line or swaps a hyphen for an en dash has not altered the rule. If
    these were reported, every build would fail and the check would be ignored.
    """
    network = clean_network(pack)
    standard = pack.standards[2]
    rewrapped: str = standard.text.replace(" ", "\n   ", 1).replace("-", "–")
    network["agent_3"]["instructions"] = f"MUST: {rewrapped} [{standard.standard_id}]"
    result = verify(pack, network)
    assert not result.infidelities, result.infidelities


# --------------------------------------------------------------------------------------
# Structure
# --------------------------------------------------------------------------------------


def test_structure_catches_a_gate_that_is_also_the_work():
    """
    Temporal role is what turns knowledge into topology. An agent owning both a precondition and
    the work it guards has collapsed the gate, which the text checks alone cannot see.
    """
    pack: KnowledgePack = load_pack("kubernetes_cluster_upgrade")
    network: dict[str, Any] = {}
    for standard in pack.standards:
        # K8S-02 is a precondition, K8S-05 is work: put both in one agent.
        agent_name: str = "everything_agent" if standard.standard_id in ("K8S-02", "K8S-05") else standard.standard_id
        existing: str = network.get(agent_name, {}).get("instructions", "")
        network[agent_name] = {
            "instructions": f"{existing}\nMUST: {standard.text} [{standard.standard_id}]",
        }
    result = verify(pack, network)
    assert not result.ok
    assert any("does not gate anything" in problem for problem in result.problems())


def test_structure_is_skipped_for_packs_that_declare_no_roles(tmp_path):
    """The structural check is opt-in, so packs without roles are unaffected."""
    directory = tmp_path / "roleless"
    directory.mkdir()
    (directory / "operating_standards.md").write_text("- RL-01: One.\n- RL-02: Two.\n", encoding="utf-8")
    (directory / "open_variables.md").write_text("- V1 | q | examples: e | why: w\n", encoding="utf-8")
    (directory / "pack.hocon").write_text(
        '{ domain_id = "roleless"\n version = "1.0"\n standard_id_pattern = "RL-\\\\d{2}" }\n', encoding="utf-8"
    )
    pack = load_pack("roleless", tmp_path)
    network = {"one_agent": {"instructions": "MUST: One. [RL-01]\nMUST: Two. [RL-02]"}}
    result = verify(pack, network)
    assert not result.structural


# --------------------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------------------


def test_report_renders_a_table_for_a_clean_network(pack):
    """The report replaces a table the model would otherwise write about its own work."""
    report: str = render_report(verify(pack, clean_network(pack)))
    assert "| Standard | Role | Owned by | Fidelity |" in report
    assert "**ODB-03**" in report
    assert "verbatim" in report
    assert "Every standard is embedded exactly once" in report


def test_report_names_every_failure(pack):
    """A partial, honest report is more useful than an exception."""
    network = clean_network(pack)
    del network["agent_1"]
    network["agent_3"]["instructions"] = "MUST: Take a backup. [ODB-03]"
    network["invented"] = {"instructions": "MUST: Do something extra. [ODB-99]"}
    report: str = render_report(verify(pack, network))
    assert "did not verify clean" in report
    assert "ODB-01 is not embedded" in report
    assert "FIDELITY: ODB-03" in report
    assert "ODB-99" in report
    assert "**not embedded**" in report


def test_report_carries_pack_provenance(pack):
    """A generated network of unknown ancestry is hard to defend in an audit."""
    report: str = render_report(verify(pack, clean_network(pack)))
    assert "Oracle database patching" in report
    assert "v1.0.0" in report


# --------------------------------------------------------------------------------------
# Offline use
# --------------------------------------------------------------------------------------


def test_a_generated_hocon_file_can_be_verified_offline(tmp_path, pack):
    """
    The same checks must run in CI over files already on disk, with no agent runtime and no
    API key.
    """
    standard = pack.standards[2]
    generated = tmp_path / "generated.hocon"
    generated.write_text(
        "{\n"
        '    "tools": [\n'
        '        { "name": "front_man", "instructions": "Coordinate.", "tools": ["backup_gate"] },\n'
        f'        {{ "name": "backup_gate", "instructions": "MUST: {standard.text} [{standard.standard_id}]" }}\n'
        "    ]\n"
        "}\n",
        encoding="utf-8",
    )
    definition = network_definition_from_hocon(generated)
    assert set(definition) == {"front_man", "backup_gate"}
    result = verify(pack, definition)
    assert "ODB-03" in result.owners
    assert result.owners["ODB-03"] == ["backup_gate"]


def test_a_file_that_is_not_an_agent_network_is_rejected(tmp_path):
    """Fail with a clear message rather than reporting zero coverage on a wrong file."""
    not_a_network = tmp_path / "notes.hocon"
    not_a_network.write_text('{ "something": "else" }\n', encoding="utf-8")
    with pytest.raises(ValueError, match="does not look like an agent network"):
        network_definition_from_hocon(not_a_network)
