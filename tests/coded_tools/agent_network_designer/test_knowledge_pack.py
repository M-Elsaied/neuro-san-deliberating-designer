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
Unit tests for knowledge pack discovery, parsing and validation.

No language model, no network, no agent runtime: these run in ordinary CI.
"""

from pathlib import Path

import pytest

from coded_tools.agent_network_designer.knowledge_pack import KNOWDOCS_ENV_VAR
from coded_tools.agent_network_designer.knowledge_pack import UNLOADED_OFF_PATTERN
from coded_tools.agent_network_designer.knowledge_pack import KnowledgePack
from coded_tools.agent_network_designer.knowledge_pack import discover_domains
from coded_tools.agent_network_designer.knowledge_pack import knowdocs_root
from coded_tools.agent_network_designer.knowledge_pack import load_catalogue
from coded_tools.agent_network_designer.knowledge_pack import load_pack
from coded_tools.agent_network_designer.knowledge_pack import normalise
from coded_tools.agent_network_designer.knowledge_pack import parse_open_variables
from coded_tools.agent_network_designer.knowledge_pack import parse_standards

SHIPPED_DOMAINS: tuple[str, ...] = (
    "clinical_trial_database_lock",
    "kubernetes_cluster_upgrade",
    "oracle_database_patching",
)


def write_pack(
    root: Path,
    domain_id: str,
    standards: str,
    variables: str,
    manifest: str | None = None,
) -> Path:
    """
    Write a minimal pack on disk for a test.

    :param root: The knowdocs root to write under.
    :param domain_id: The pack directory name.
    :param standards: Contents of operating_standards.md.
    :param variables: Contents of open_variables.md.
    :param manifest: Contents of pack.hocon, or None to omit the manifest entirely.
    :return: The pack directory.
    """
    directory: Path = root / domain_id
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "operating_standards.md").write_text(standards, encoding="utf-8")
    (directory / "open_variables.md").write_text(variables, encoding="utf-8")
    if manifest is not None:
        (directory / "pack.hocon").write_text(manifest, encoding="utf-8")
    return directory


# --------------------------------------------------------------------------------------
# Discovery and path resolution
# --------------------------------------------------------------------------------------


def test_shipped_domains_are_discovered_without_being_registered_in_python():
    """Adding a domain must be a filesystem operation, not a code change."""
    assert set(SHIPPED_DOMAINS).issubset(set(discover_domains()))


def test_default_root_is_relative_to_the_module_not_the_working_directory(tmp_path, monkeypatch):
    """
    The original implementation resolved knowdocs against the process working directory, so the
    designer only worked when the server happened to start from the repository root. Changing
    directory must not break domain discovery.
    """
    monkeypatch.delenv(KNOWDOCS_ENV_VAR, raising=False)
    monkeypatch.chdir(tmp_path)
    assert set(SHIPPED_DOMAINS).issubset(set(discover_domains()))


def test_environment_variable_overrides_the_root(tmp_path, monkeypatch):
    """A deployment must be able to serve packs from its own knowledge store."""
    write_pack(tmp_path, "house_style", "- HS-01: Never ship on a Friday.", "- V1 | Why? | examples: a | why: b")
    monkeypatch.setenv(KNOWDOCS_ENV_VAR, str(tmp_path))
    assert discover_domains() == ["house_style"]
    assert knowdocs_root() == tmp_path.resolve()


def test_directories_without_documents_are_not_domains(tmp_path):
    """An empty or non-document directory is not a pack."""
    (tmp_path / "not_a_pack").mkdir()
    (tmp_path / ".hidden").mkdir()
    assert not discover_domains(tmp_path)


def test_unknown_domain_raises_rather_than_falling_back(tmp_path):
    """
    An unknown domain must be an explicit miss. Silently returning some default document would
    let the designer interview a user from the wrong domain's standards.
    """
    with pytest.raises(FileNotFoundError):
        load_pack("no_such_domain", tmp_path)


# --------------------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("domain_id", SHIPPED_DOMAINS)
def test_every_shipped_pack_parses_and_validates_clean(domain_id):
    """The packs that ship must satisfy the contract they define."""
    pack: KnowledgePack = load_pack(domain_id)
    assert pack.standards, f"{domain_id} parsed no standards"
    assert pack.open_variables, f"{domain_id} parsed no open variables"
    assert not pack.validate(), f"{domain_id} did not validate clean"


def test_oracle_pack_parses_its_standards_and_variables():
    """Spot-check the reference pack against known content."""
    pack: KnowledgePack = load_pack("oracle_database_patching")
    assert [standard.standard_id for standard in pack.standards] == [f"ODB-0{index}" for index in range(1, 7)]
    assert len(pack.open_variables) == 7
    assert pack.manifest.version == "1.0.0"


def test_wrapped_standards_are_rejoined_into_one_logical_rule():
    """
    Standards wrap across lines in markdown. If continuations were dropped, the fidelity check
    downstream would compare against a truncated rule and pass things it should fail.
    """
    text: str = (
        "- ODB-02: Keep OPatch updated: verify and upgrade OPatch to the minimum version\n"
        "  the RU README requires, before applying the patch.\n"
    )
    standards = parse_standards(text, r"ODB-\d{2}")
    assert len(standards) == 1
    assert standards[0].text.endswith("before applying the patch.")
    assert "\n" not in standards[0].text


def test_preamble_prose_and_headings_are_not_parsed_as_standards():
    """A pack author must be able to explain the pack without corrupting it."""
    text: str = (
        "# Operating standards\n\n"
        "These represent a TYPICAL SOP. Confirm against your own before relying on them.\n\n"
        "- ODB-01: Apply the latest Release Update.\n"
    )
    assert [standard.standard_id for standard in parse_standards(text, r"ODB-\d{2}")] == ["ODB-01"]


def test_open_variables_carry_the_why_clause():
    """
    The 'why' is what lets the designer justify a question it does not itself understand, so it
    is parsed as a first-class field rather than left inside the question text.
    """
    text: str = (
        "- V1 | Topology: single instance or RAC?\n"
        "  | examples: single instance; two-node RAC\n"
        "  | why: decides rolling versus a full outage.\n"
    )
    variables = parse_open_variables(text)
    assert len(variables) == 1
    assert variables[0].variable_id == "V1"
    assert variables[0].question.startswith("Topology:")
    assert variables[0].examples == "single instance; two-node RAC"
    assert variables[0].why.startswith("decides rolling")


def test_roles_come_from_the_manifest_not_from_the_markdown():
    """
    Declaring temporal role in the manifest keeps the markdown a pure statement of the rule, and
    takes the topology decision away from the language model.
    """
    pack: KnowledgePack = load_pack("kubernetes_cluster_upgrade")
    roles = {standard.standard_id: standard.role for standard in pack.standards}
    assert roles["K8S-02"] == "precondition"
    assert roles["K8S-05"] == "work"
    assert roles["K8S-06"] == "postcondition"


# --------------------------------------------------------------------------------------
# Genericity
# --------------------------------------------------------------------------------------


def test_a_pack_declares_its_own_id_pattern(tmp_path):
    """
    Ids are not assumed to look like ours. A deployment numbering its standards std-001 must work
    without changing any code - this is the difference between an example and an extension point.
    """
    write_pack(
        tmp_path,
        "house_rules",
        "- std-001: Never ship on a Friday.\n- std-002: Two approvals for production.\n",
        "- V1 | Which environment? | examples: dev; prod | why: sets the approval path.\n",
        manifest=(
            '{ domain_id = "house_rules"\n'
            '  title = "House rules"\n'
            '  version = "2.4"\n'
            '  owner = "Platform"\n'
            '  standard_id_pattern = "std-\\\\d{3}"\n'
            '  roles { "std-001" = precondition, "std-002" = precondition }\n'
            "}\n"
        ),
    )
    pack: KnowledgePack = load_pack("house_rules", tmp_path)
    assert [standard.standard_id for standard in pack.standards] == ["std-001", "std-002"]
    assert not pack.validate()
    assert "v2.4" in pack.manifest.provenance()
    assert "owned by Platform" in pack.manifest.provenance()


def test_a_pack_without_a_manifest_still_loads(tmp_path):
    """
    Packs written before manifests existed must keep working. The missing manifest is reported as
    a warning, not an error, so an upgrade does not break an existing deployment.
    """
    write_pack(
        tmp_path,
        "legacy",
        "- LEG-01: Something invariant.\n",
        "- V1 | A question? | examples: a; b | why: it matters.\n",
        manifest=None,
    )
    pack: KnowledgePack = load_pack("legacy", tmp_path)
    assert pack.manifest.synthesised is True
    assert [standard.standard_id for standard in pack.standards] == ["LEG-01"]
    assert any("no pack.hocon found" in problem for problem in pack.validate())


def test_load_catalogue_returns_every_discoverable_pack(tmp_path):
    """The catalogue is what replaces a hardcoded domain list in the designer's prompt."""
    write_pack(tmp_path, "alpha", "- A-01: One.\n", "- V1 | q | examples: e | why: w\n")
    write_pack(tmp_path, "beta", "- B-01: Two.\n", "- V1 | q | examples: e | why: w\n")
    assert [pack.domain_id for pack in load_catalogue(tmp_path)] == ["alpha", "beta"]


# --------------------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------------------


def test_duplicate_standard_ids_are_reported(tmp_path):
    """Two rules under one id makes ownership meaningless."""
    write_pack(
        tmp_path,
        "dupes",
        "- DUP-01: First rule.\n- DUP-01: Second rule.\n",
        "- V1 | q | examples: e | why: w\n",
        manifest='{ domain_id = "dupes"\n version = "1.0"\n standard_id_pattern = "DUP-\\\\d{2}" }\n',
    )
    problems = load_pack("dupes", tmp_path).validate()
    assert any("duplicate standard id DUP-01" in problem for problem in problems)


def test_an_id_outside_the_declared_pattern_is_reported(tmp_path):
    """A pack that declares a pattern is held to it."""
    write_pack(
        tmp_path,
        "mixed",
        "- ABC-01: Fine.\n- XYZ-99: Not fine.\n",
        "- V1 | q | examples: e | why: w\n",
        manifest='{ domain_id = "mixed"\n version = "1.0"\n standard_id_pattern = "ABC-\\\\d{2}" }\n',
    )
    pack = load_pack("mixed", tmp_path)
    # XYZ-99 does not match the declared pattern, so it is not parsed as a standard at all - which is
    # exactly why it has to be REPORTED. A rule that silently disappears between the document and the
    # network is the failure this whole check exists to prevent.
    assert [standard.standard_id for standard in pack.standards] == ["ABC-01"]
    assert pack.unloaded_standards == [("XYZ-99", UNLOADED_OFF_PATTERN)]
    # An unloaded standard blocks verification: it cannot have reached the network.
    assert any("XYZ-99" in problem and "NOT loaded" in problem for problem in pack.validate_errors())


def test_an_open_variable_missing_its_why_is_reported(tmp_path):
    """Without the why-clause the designer cannot justify the question it is asking."""
    write_pack(
        tmp_path,
        "thin",
        "- THN-01: A rule.\n",
        "- V1 | A question? | examples: a; b\n",
        manifest='{ domain_id = "thin"\n version = "1.0"\n standard_id_pattern = "THN-\\\\d{2}" }\n',
    )
    problems = load_pack("thin", tmp_path).validate()
    assert any("missing its why" in problem for problem in problems)


def test_a_role_assigned_to_an_unknown_standard_is_reported(tmp_path):
    """Catches a manifest left behind after a standard was renamed or removed."""
    write_pack(
        tmp_path,
        "stale",
        "- STL-01: A rule.\n",
        "- V1 | q | examples: e | why: w\n",
        manifest=(
            '{ domain_id = "stale"\n version = "1.0"\n standard_id_pattern = "STL-\\\\d{2}"\n'
            '  roles { "STL-01" = precondition, "STL-99" = work } }\n'
        ),
    )
    problems = load_pack("stale", tmp_path).validate()
    assert any("STL-99" in problem for problem in problems)


def test_an_invalid_role_name_is_reported(tmp_path):
    """Roles drive topology, so a typo must not silently become 'no role'."""
    write_pack(
        tmp_path,
        "badrole",
        "- BAD-01: A rule.\n",
        "- V1 | q | examples: e | why: w\n",
        manifest=(
            '{ domain_id = "badrole"\n version = "1.0"\n standard_id_pattern = "BAD-\\\\d{2}"\n'
            '  roles { "BAD-01" = preconditon } }\n'
        ),
    )
    problems = load_pack("badrole", tmp_path).validate()
    assert any("preconditon" in problem for problem in problems)


# --------------------------------------------------------------------------------------
# Normalisation
# --------------------------------------------------------------------------------------


def test_normalise_collapses_wrapping_and_typography():
    """
    Line wrapping and smart punctuation are not fidelity failures; a changed word is. Getting
    this wrong in either direction makes the fidelity check useless.
    """
    assert normalise("Take a full\n  RMAN backup") == "Take a full RMAN backup"
    assert normalise("don’t — stop") == normalise("don't - stop")
    assert normalise("a  b") != normalise("a c")


def test_normalise_handles_empty_input():
    """Guards the fidelity comparison against an agent with no instructions."""
    assert normalise("") == ""
