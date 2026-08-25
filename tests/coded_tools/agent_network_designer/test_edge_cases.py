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
The edge cases, gathered in one place so the handled set is reviewable rather than inferred.

Grouped by where the sharp edge is:

  A. Pack authoring - what a domain expert can write that would otherwise be lost in silence.
  B. Embedded-text extraction - what a language model does to text that a naive regex misses.
  C. Deployment - roots that do not exist, packs with no manifest, stray files.

The theme running through A and B is the same: a standard must never disappear quietly. Failing
loudly is a feature; the failure mode this whole design exists to prevent is a rule that is absent
and unremarked.
"""

from pathlib import Path
from typing import Any

import pytest

from coded_tools.agent_network_designer.knowledge_pack import UNLOADED_NO_TEXT
from coded_tools.agent_network_designer.knowledge_pack import UNLOADED_OFF_PATTERN
from coded_tools.agent_network_designer.knowledge_pack import KnowledgePack
from coded_tools.agent_network_designer.knowledge_pack import PackManifest
from coded_tools.agent_network_designer.knowledge_pack import Standard
from coded_tools.agent_network_designer.knowledge_pack import discover_domains
from coded_tools.agent_network_designer.knowledge_pack import load_pack
from coded_tools.agent_network_designer.knowledge_pack import normalise
from coded_tools.agent_network_designer.knowledge_pack import parse_standards
from coded_tools.agent_network_designer.standards_verifier import extract_embedded_standards
from coded_tools.agent_network_designer.standards_verifier import network_definition_from_hocon
from coded_tools.agent_network_designer.standards_verifier import render_report
from coded_tools.agent_network_designer.standards_verifier import verify


def write_pack(root: Path, domain_id: str, standards: str, variables: str, manifest: str | None = None) -> Path:
    """
    Write a minimal pack on disk.

    :param root: The knowdocs root to write under.
    :param domain_id: The pack directory name.
    :param standards: Contents of operating_standards.md.
    :param variables: Contents of open_variables.md.
    :param manifest: Contents of pack.hocon, or None to omit it.
    :return: The pack directory.
    """
    directory: Path = root / domain_id
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "operating_standards.md").write_text(standards, encoding="utf-8")
    (directory / "open_variables.md").write_text(variables, encoding="utf-8")
    if manifest is not None:
        (directory / "pack.hocon").write_text(manifest, encoding="utf-8")
    return directory


def one_agent(instructions: str) -> dict[str, Any]:
    """
    :param instructions: The agent's instructions.
    :return: A one-agent network definition.
    """
    return {"only_agent": {"instructions": instructions}}


# --------------------------------------------------------------------------------------
# A. Pack authoring
# --------------------------------------------------------------------------------------


def test_edge_a1_a_standard_with_no_text_is_reported_not_dropped(tmp_path):
    """
    ``- ABC-03:`` with nothing after it parses as no standard at all.

    Left unreported the rule vanishes between the document and the network, which is exactly the
    failure the verifier exists to catch - so it is an error, not a warning.
    """
    write_pack(
        tmp_path,
        "gaps",
        "- ABC-01: A real rule.\n- ABC-03: \n",
        "- V1 | q | examples: e | why: w\n",
        manifest='{ domain_id = "gaps"\n version = "1.0"\n standard_id_pattern = "ABC-\\\\d{2}" }\n',
    )
    pack: KnowledgePack = load_pack("gaps", tmp_path)

    assert [standard.standard_id for standard in pack.standards] == ["ABC-01"]
    assert ("ABC-03", UNLOADED_NO_TEXT) in pack.unloaded_standards
    assert any("ABC-03" in problem and "NOT loaded" in problem for problem in pack.validate_errors())


def test_edge_a2_an_off_pattern_id_is_reported_not_dropped(tmp_path):
    """An id the declared pattern rejects is never parsed, so it must be surfaced instead."""
    write_pack(
        tmp_path,
        "mixed",
        "- ABC-01: Fine.\n- WRONG-99: Also a rule, wrongly numbered.\n",
        "- V1 | q | examples: e | why: w\n",
        manifest='{ domain_id = "mixed"\n version = "1.0"\n standard_id_pattern = "ABC-\\\\d{2}" }\n',
    )
    pack: KnowledgePack = load_pack("mixed", tmp_path)

    assert ("WRONG-99", UNLOADED_OFF_PATTERN) in pack.unloaded_standards
    assert any("WRONG-99" in problem for problem in pack.validate_errors())


def test_edge_a3_prose_containing_a_colon_is_not_mistaken_for_a_standard(tmp_path):
    """
    A pack author must be able to write explanatory prose without half of it becoming rules.

    Only ``PREFIX-digits:`` counts, so "Note:" and "Scope: everything" stay prose.
    """
    write_pack(
        tmp_path,
        "prose",
        "# Standards\n\nNote: these are illustrative.\n\nScope: the whole estate.\n\n- ABC-01: A rule.\n",
        "- V1 | q | examples: e | why: w\n",
        manifest='{ domain_id = "prose"\n version = "1.0"\n standard_id_pattern = "ABC-\\\\d{2}" }\n',
    )
    pack: KnowledgePack = load_pack("prose", tmp_path)

    assert [standard.standard_id for standard in pack.standards] == ["ABC-01"]
    assert not pack.unloaded_standards
    assert not pack.validate_errors()


def test_edge_a4_an_unparseable_id_pattern_does_not_crash_the_load(tmp_path):
    """A typo in a regex must be a reported problem, not a stack trace at interview time."""
    write_pack(
        tmp_path,
        "badregex",
        "- ABC-01: A rule.\n",
        "- V1 | q | examples: e | why: w\n",
        manifest='{ domain_id = "badregex"\n version = "1.0"\n standard_id_pattern = "ABC-[0-9" }\n',
    )
    pack: KnowledgePack = load_pack("badregex", tmp_path)

    assert any("not a valid regular expression" in problem for problem in pack.validate_errors())


def test_edge_a5_an_organisations_own_id_scheme_works_unchanged(tmp_path):
    """
    Dotted and zero-padded schemes are common. ``SOP-4.2.1`` must be a first-class id.
    """
    write_pack(
        tmp_path,
        "house",
        "- SOP-4.2.1: Obtain written approval before proceeding.\n- SOP-4.2.10: Record the outcome.\n",
        "- V1 | q | examples: e | why: w\n",
        manifest='{ domain_id = "house"\n version = "2.0"\n standard_id_pattern = "SOP-[0-9.]+" }\n',
    )
    pack: KnowledgePack = load_pack("house", tmp_path)

    assert [standard.standard_id for standard in pack.standards] == ["SOP-4.2.1", "SOP-4.2.10"]
    assert not pack.validate_errors()
    embedded = one_agent("MUST: Obtain written approval before proceeding. [SOP-4.2.1]")
    assert verify(pack, embedded).missing == ["SOP-4.2.10"]


def test_edge_a6_a_role_pointing_at_a_deleted_standard_is_an_error(tmp_path):
    """
    Rename a standard, forget the manifest, and the structural check silently stops covering it.
    """
    write_pack(
        tmp_path,
        "stale",
        "- ABC-01: A rule.\n",
        "- V1 | q | examples: e | why: w\n",
        manifest=(
            '{ domain_id = "stale"\n version = "1.0"\n standard_id_pattern = "ABC-\\\\d{2}"\n'
            '  roles { "ABC-01" = precondition\n "ABC-77" = postcondition } }\n'
        ),
    )
    pack: KnowledgePack = load_pack("stale", tmp_path)
    assert any("ABC-77" in problem for problem in pack.validate_errors())


def test_edge_a7_a_missing_why_is_a_warning_and_does_not_block_verification(tmp_path):
    """
    An incomplete interview script degrades the questions, but the standards still reached the
    network. Blocking on it would make the manifest-less compatibility path unusable too.
    """
    write_pack(
        tmp_path,
        "nowhy",
        "- ABC-01: A rule.\n",
        "- V1 | Which environments? | examples: dev, prod\n",
        manifest='{ domain_id = "nowhy"\n version = "1.0"\n standard_id_pattern = "ABC-\\\\d{2}" }\n',
    )
    pack: KnowledgePack = load_pack("nowhy", tmp_path)

    assert any("missing its why" in problem for problem in pack.validate_warnings())
    assert not pack.validate_errors()
    assert verify(pack, one_agent("MUST: A rule. [ABC-01]")).ok


# --------------------------------------------------------------------------------------
# B. Embedded-text extraction
# --------------------------------------------------------------------------------------


def test_edge_b1_a_standard_whose_text_contains_brackets_yields_the_right_id():
    """The id is the bracket group ending the line, not the first one encountered."""
    pack = KnowledgePack(
        manifest=PackManifest(domain_id="d", version="1.0"),
        standards=[Standard("ABC-01", "Review the README [and its notes] carefully.")],
    )
    network = one_agent("MUST: Review the README [and its notes] carefully. [ABC-01]")

    embedded = extract_embedded_standards(network)
    assert [item.standard_id for item in embedded] == ["ABC-01"]
    assert verify(pack, network).ok


def test_edge_b2_trailing_whitespace_after_the_id_does_not_hide_the_line():
    """A model leaving trailing spaces must not make a present standard read as missing."""
    pack = KnowledgePack(
        manifest=PackManifest(domain_id="d", version="1.0"),
        standards=[Standard("ABC-01", "A rule.")],
    )
    assert verify(pack, one_agent("MUST: A rule. [ABC-01]   \nnext line")).ok


def test_edge_b3_a_blank_line_terminates_a_wrapped_standard():
    """
    Wrapping is tolerated, but a paragraph break is not a wrap - otherwise the extractor would
    swallow unrelated prose into the standard's text and report a false fidelity failure.
    """
    network = one_agent("MUST: The rule begins here\n\nand this is a separate paragraph. [ABC-01]")
    assert not extract_embedded_standards(network)


def test_edge_b4_the_same_standard_twice_in_one_agent_is_not_ambiguous_ownership():
    """
    Duplication inside a single agent is untidy but ownership is unambiguous, so it must not be
    reported as if two agents were fighting over the rule.
    """
    pack = KnowledgePack(
        manifest=PackManifest(domain_id="d", version="1.0"),
        standards=[Standard("ABC-01", "A rule.")],
    )
    result = verify(pack, one_agent("MUST: A rule. [ABC-01]\nMUST: A rule. [ABC-01]"))

    assert result.ok
    assert not result.ambiguous


def test_edge_b5_agents_without_instructions_are_skipped_not_crashed_on():
    """Coded tools and toolbox entries carry no instructions, and a definition may be malformed."""
    network: dict[str, Any] = {
        "coded_tool": {"class": "some.Thing"},
        "toolbox_entry": {"toolbox": "web_search"},
        "empty": {"instructions": ""},
        "malformed": "not even a dict",
        "none_instructions": {"instructions": None},
        "real": {"instructions": "MUST: A rule. [ABC-01]"},
    }
    embedded = extract_embedded_standards(network)
    assert [(item.standard_id, item.agent_name) for item in embedded] == [("ABC-01", "real")]


def test_edge_b6_an_empty_or_missing_network_extracts_nothing_without_error():
    """Verification runs before the build in the worst case; it must degrade, not explode."""
    assert not extract_embedded_standards({})
    assert not extract_embedded_standards(None)


def test_edge_b7_case_matters_in_the_marker_but_not_in_the_surrounding_prose():
    """
    ``MUST:`` is the contract. A lower-case "must:" is prose, and treating it as an embedding
    would let ordinary sentences masquerade as standards.
    """
    assert not extract_embedded_standards(one_agent("must: A rule. [ABC-01]"))
    assert len(extract_embedded_standards(one_agent("You MUST: A rule. [ABC-01]"))) == 1


def test_edge_b8_normalisation_folds_rendering_but_never_a_changed_word():
    """The line between tolerated and reported, asserted directly on normalise()."""
    assert normalise("take a\n  full   backup") == normalise("take a full backup")
    assert normalise("one off ‘quoted’ – dash") == normalise("one off 'quoted' - dash")
    assert normalise("take a full backup") != normalise("take a backup")
    assert normalise("") == ""
    assert normalise(None) == ""


def test_edge_b9_a_multi_line_standard_in_the_pack_still_matches_a_single_line_embedding():
    """
    Packs wrap their standards; networks emit them on one line. If normalisation did not bridge
    that, every standard would fail fidelity and the check would be discarded as broken.
    """
    text: str = "- ABC-01: Take a full backup before starting,\n  and confirm it is restorable.\n"
    standards = parse_standards(text, r"ABC-\d{2}")
    pack = KnowledgePack(manifest=PackManifest(domain_id="d", version="1.0"), standards=standards)

    single_line: str = "MUST: Take a full backup before starting, and confirm it is restorable. [ABC-01]"
    assert verify(pack, one_agent(single_line)).ok


# --------------------------------------------------------------------------------------
# C. Deployment
# --------------------------------------------------------------------------------------


def test_edge_c1_a_knowdocs_root_that_does_not_exist_yields_no_domains(tmp_path, monkeypatch):
    """A misconfigured path must degrade to "no curated knowledge", not raise on startup."""
    monkeypatch.setenv("AGENT_NETWORK_DESIGNER_KNOWDOCS", str(tmp_path / "nope"))
    assert not discover_domains()


def test_edge_c2_a_pack_with_no_manifest_still_loads_and_still_verifies(tmp_path):
    """
    The backwards-compatibility path. A pack written before manifests existed must keep working:
    warned about, never blocked, or the compatibility promise is empty.
    """
    write_pack(tmp_path, "legacy", "- ABC-01: A rule.\n", "- V1 | q | examples: e | why: w\n")
    pack: KnowledgePack = load_pack("legacy", tmp_path)

    assert pack.manifest.synthesised
    assert pack.manifest.title == "legacy"
    assert any("no pack.hocon found" in problem for problem in pack.validate_warnings())
    assert not pack.validate_errors()
    assert verify(pack, one_agent("MUST: A rule. [ABC-01]")).ok


def test_edge_c3_stray_documents_in_a_pack_directory_do_not_become_standards(tmp_path):
    """A README or notes file alongside the pack must not be parsed as rules."""
    directory: Path = write_pack(
        tmp_path,
        "extra",
        "- ABC-01: A rule.\n",
        "- V1 | q | examples: e | why: w\n",
        manifest='{ domain_id = "extra"\n version = "1.0"\n standard_id_pattern = "ABC-\\\\d{2}" }\n',
    )
    (directory / "README.md").write_text("- ABC-02: Not a real standard, just a note.\n", encoding="utf-8")
    pack: KnowledgePack = load_pack("extra", tmp_path)

    assert [standard.standard_id for standard in pack.standards] == ["ABC-01"]
    assert "README.md" in pack.documents


def test_edge_c4_a_directory_holding_no_documents_is_not_a_domain(tmp_path):
    """Scratch and hidden directories under the root must not appear in the catalogue."""
    (tmp_path / "scratch").mkdir()
    (tmp_path / ".hidden").mkdir()
    write_pack(tmp_path, "real", "- ABC-01: A rule.\n", "- V1 | q | examples: e | why: w\n")

    assert discover_domains(tmp_path) == ["real"]


def test_edge_c5_a_pack_error_blocks_verification_of_an_otherwise_perfect_network(tmp_path):
    """
    The gap found in review: a network can be built impeccably from a pack that lost a standard on
    load. Reporting that as verified would be the self-certification this design removes.
    """
    write_pack(
        tmp_path,
        "lossy",
        "- ABC-01: A rule.\n- WRONG-02: A rule that will not load.\n",
        "- V1 | q | examples: e | why: w\n",
        manifest='{ domain_id = "lossy"\n version = "1.0"\n standard_id_pattern = "ABC-\\\\d{2}" }\n',
    )
    pack: KnowledgePack = load_pack("lossy", tmp_path)
    result = verify(pack, one_agent("MUST: A rule. [ABC-01]"))

    # Nothing is wrong with the network itself.
    assert not result.missing
    assert not result.infidelities
    assert not result.unknown
    # But the pack lost a rule, so the whole thing must not report clean.
    assert not result.ok
    assert any("WRONG-02" in problem for problem in result.problems())
    assert "did not verify clean" in render_report(result)


def test_edge_c8_a_generated_network_whose_includes_are_root_relative_still_parses(tmp_path):
    """
    Generated networks live in registries/generated/ but write includes relative to the repo root.

    ``include "registries/aaosa.hocon"`` plus ``${aaosa_call}`` is what every real generated
    network looks like, because that is how the server loads it. Resolving includes against the
    file's own directory looks for registries/generated/registries/aaosa.hocon, misses, and then
    cannot resolve the substitution - so the offline verifier could not read a single real
    artifact. The earlier test used a synthetic file with no includes, which is why it passed.
    """
    (tmp_path / "registries").mkdir()
    (tmp_path / "registries" / "aaosa.hocon").write_text('{ aaosa_call = "shared-fragment" }\n', encoding="utf-8")
    generated: Path = tmp_path / "registries" / "generated"
    generated.mkdir()
    network: Path = generated / "net.hocon"
    network.write_text(
        '{\n    include "registries/aaosa.hocon"\n'
        '    "tools": [\n'
        '        { "name": "gate", "call": ${aaosa_call},\n'
        '          "instructions": """MUST: A rule. [ABC-01]""" }\n'
        "    ]\n}\n",
        encoding="utf-8",
    )

    # Resolved against the repository root, as the server does: readable.
    definition = network_definition_from_hocon(network, basedir=tmp_path)
    assert "MUST: A rule. [ABC-01]" in definition["gate"]["instructions"]

    # Resolved against the file's own directory: the include misses and the error says so.
    with pytest.raises(ValueError) as failure:
        network_definition_from_hocon(network, basedir=generated)
    assert "--basedir" in str(failure.value)


def test_edge_c6_the_same_pack_loaded_twice_gives_the_same_answer(tmp_path):
    """
    Determinism. The verifier's value is that two people checking the same artifact agree.
    """
    write_pack(
        tmp_path,
        "stable",
        "- ABC-01: A rule.\n- ABC-02: Another rule.\n",
        "- V1 | q | examples: e | why: w\n",
        manifest='{ domain_id = "stable"\n version = "1.0"\n standard_id_pattern = "ABC-\\\\d{2}" }\n',
    )
    network = one_agent("MUST: A rule. [ABC-01]")
    first = render_report(verify(load_pack("stable", tmp_path), network))
    second = render_report(verify(load_pack("stable", tmp_path), network))

    assert first == second


@pytest.mark.parametrize("domain_id", ["oracle_database_patching", "kubernetes_cluster_upgrade"])
def test_edge_c7_a_network_verified_against_the_wrong_pack_fails_loudly(domain_id):
    """
    Matching the wrong domain is worse than matching none - a known limit - so at least the
    artifact check must not quietly bless a network built from another domain's standards.
    """
    other: str = "clinical_trial_database_lock"
    pack: KnowledgePack = load_pack(domain_id)
    foreign: KnowledgePack = load_pack(other)
    network = one_agent(f"MUST: {foreign.standards[0].text} [{foreign.standards[0].standard_id}]")

    result = verify(pack, network)
    assert not result.ok
    assert result.unknown, "a foreign standard id was accepted as this pack's own"
    assert len(result.missing) == len(pack.standards)
