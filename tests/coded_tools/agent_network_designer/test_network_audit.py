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
Tests for the estate audit - networks placed against the packs they were built from.

Verification is a moment-in-time check. Packs then change, and every network built before the
change quietly stops implementing the document it claims to. These tests cover the two questions
that follow: what has gone out of date, and what implements a given rule.

The case worth reading first is the reworded standard with no version bump. A version comparison
alone would call that network current; comparing the embedded text against the live pack does not.

No language model - all of this is text comparison against files on disk.
"""

from pathlib import Path

import pytest

from coded_tools.agent_network_designer.knowledge_pack import KnowledgePack
from coded_tools.agent_network_designer.network_audit import STATUS_CURRENT
from coded_tools.agent_network_designer.network_audit import STATUS_DRIFTED
from coded_tools.agent_network_designer.network_audit import STATUS_NO_STANDARDS
from coded_tools.agent_network_designer.network_audit import STATUS_STALE
from coded_tools.agent_network_designer.network_audit import STATUS_UNKNOWN_PACK
from coded_tools.agent_network_designer.network_audit import STATUS_UNSTAMPED
from coded_tools.agent_network_designer.network_audit import AuditedNetwork
from coded_tools.agent_network_designer.network_audit import audit_directory
from coded_tools.agent_network_designer.network_audit import identify_pack
from coded_tools.agent_network_designer.network_audit import main
from coded_tools.agent_network_designer.network_audit import render_audit
from coded_tools.agent_network_designer.network_audit import render_traceability
from coded_tools.agent_network_designer.pack_catalogue import load_catalogue
from coded_tools.agent_network_designer.pack_catalogue import load_pack
from coded_tools.agent_network_designer.standards_verifier import extract_embedded_standards
from tests.coded_tools.agent_network_designer.network_fixtures import reference_network

DOMAIN: str = "oracle_database_patching"


def write_network(directory: Path, name: str, pack: KnowledgePack, version: str | None = "1.0.0") -> Path:
    """
    Write a generated-looking network to disk, built from a pack.

    :param directory: Where to write it.
    :param name: The file stem.
    :param pack: The pack to build it from.
    :param version: The version to record in metadata, or None to omit the stamp entirely.
    :return: The path written.
    """
    definition: dict = reference_network(pack)
    stamp: str = ""
    if version is not None:
        stamp = f'        "knowledge_pack": "{pack.manifest.title}, v{version}, owned by nobody"\n'
    tools: list[str] = []
    for agent_name, agent in definition.items():
        instructions: str = str(agent.get("instructions", "")).replace('"""', "'''")
        tools.append(
            f'        {{\n            "name": "{agent_name}",\n'
            f'            "instructions": """{instructions}"""\n        }}'
        )
    path: Path = directory / f"{name}.hocon"
    path.write_text(
        '{\n    "metadata": {\n' + stamp + '    },\n    "tools": [\n' + ",\n".join(tools) + "\n    ]\n}\n",
        encoding="utf-8",
    )
    return path


@pytest.fixture(name="packs")
def packs_fixture() -> list[KnowledgePack]:
    """
    :return: The live packs.
    """
    return load_catalogue()


def test_a_network_built_from_the_current_pack_is_current(tmp_path, packs):
    """The baseline: nothing to report."""
    write_network(tmp_path, "oracle_net", load_pack(DOMAIN), version="1.0.0")

    results: list[AuditedNetwork] = audit_directory(tmp_path, packs)

    assert len(results) == 1
    assert results[0].status == STATUS_CURRENT
    assert results[0].domain_id == DOMAIN
    assert not results[0].needs_attention
    assert "are current" in render_audit(results)


def test_a_network_built_from_an_older_pack_version_is_stale(tmp_path, packs):
    """
    The straightforward case: the pack moved on and this network did not.
    """
    write_network(tmp_path, "oracle_net", load_pack(DOMAIN), version="0.9.0")

    results: list[AuditedNetwork] = audit_directory(tmp_path, packs)

    assert results[0].status == STATUS_STALE
    assert results[0].needs_attention
    assert "built at v0.9.0" in results[0].detail
    assert "1.0.0" in results[0].detail


def test_a_reworded_standard_is_caught_even_with_no_version_bump(tmp_path, packs):
    """
    The case a version comparison alone cannot see, and the reason drift is checked against text.

    Someone edits a standard's wording and does not bump the version - the single most likely way
    for an estate to go quietly out of date. Every network built before that edit now implements a
    rule the document no longer contains, while its recorded version still matches.
    """
    pack: KnowledgePack = load_pack(DOMAIN)
    path: Path = write_network(tmp_path, "oracle_net", pack, version=pack.manifest.version)
    target: str = pack.standards[2].standard_id
    # Simulate the pack having been edited since the build, by altering the network's copy instead.
    path.write_text(
        path.read_text(encoding="utf-8").replace("Take a full RMAN backup", "Take an RMAN backup"),
        encoding="utf-8",
    )

    results: list[AuditedNetwork] = audit_directory(tmp_path, packs)

    assert results[0].status == STATUS_DRIFTED
    assert results[0].drifted == [target]
    assert results[0].built_version == results[0].current_version, "the version alone would have looked fine"
    assert "no longer matches" in results[0].detail


def test_a_network_with_no_recorded_version_is_reported_but_not_flagged(tmp_path, packs):
    """
    Networks built before provenance stamping existed are unstamped, not wrong.

    Their standards may be perfectly current, and text drift is checked independently of the
    version - so flagging them for attention would be noise, and noise gets switched off.
    """
    write_network(tmp_path, "old_net", load_pack(DOMAIN), version=None)

    results: list[AuditedNetwork] = audit_directory(tmp_path, packs)

    assert results[0].status == STATUS_UNSTAMPED
    assert not results[0].needs_attention
    assert results[0].domain_id == DOMAIN, "identity must still be recoverable from the embedded ids"


def test_the_pack_is_identified_from_embedded_ids_not_from_metadata(packs):
    """
    Why identity comes from the ids: it cannot be fooled by metadata that disagrees with the
    instructions, which is exactly the discrepancy an audit exists to find.
    """
    pack: KnowledgePack = load_pack(DOMAIN)
    embedded = extract_embedded_standards(reference_network(pack))

    assert identify_pack(embedded, packs) is not None
    assert identify_pack(embedded, packs).domain_id == DOMAIN
    assert identify_pack([], packs) is None


def test_a_network_carrying_no_standards_is_reported_as_such(tmp_path, packs):
    """
    A network with no MUST: lines carries nothing traceable. That is a finding in itself, and it
    must not be silently counted as current.
    """
    (tmp_path / "plain.hocon").write_text(
        '{\n    "tools": [\n        { "name": "a", "instructions": "Do something." }\n    ]\n}\n', encoding="utf-8"
    )

    results: list[AuditedNetwork] = audit_directory(tmp_path, packs)

    assert results[0].status == STATUS_NO_STANDARDS
    assert "no traceable standards" in results[0].detail


def test_standards_from_no_known_pack_are_reported(tmp_path, packs):
    """
    A network built against a pack this deployment no longer serves.
    """
    (tmp_path / "orphan.hocon").write_text(
        '{\n    "tools": [\n        { "name": "a", "instructions": """MUST: Some rule. [ZZZ-01]""" }\n    ]\n}\n',
        encoding="utf-8",
    )

    results: list[AuditedNetwork] = audit_directory(tmp_path, packs)

    assert results[0].status == STATUS_UNKNOWN_PACK
    assert results[0].needs_attention
    assert "ZZZ-01" in results[0].detail


def test_the_manifest_is_not_audited_as_a_network(tmp_path, packs):
    """
    registries/generated/ holds a manifest alongside the networks; it is not one.
    """
    write_network(tmp_path, "oracle_net", load_pack(DOMAIN))
    (tmp_path / "manifest.hocon").write_text('{\n    "oracle_net.hocon": true\n}\n', encoding="utf-8")

    results: list[AuditedNetwork] = audit_directory(tmp_path, packs)

    assert [audited.path.name for audited in results] == ["oracle_net.hocon"]


def test_traceability_answers_which_networks_implement_a_standard(tmp_path, packs):
    """
    The question an auditor asks: show me everything that implements this rule.
    """
    pack: KnowledgePack = load_pack(DOMAIN)
    write_network(tmp_path, "first", pack)
    write_network(tmp_path, "second", pack)
    results: list[AuditedNetwork] = audit_directory(tmp_path, packs)

    report: str = render_traceability(results, None, pack.standards[0].standard_id)
    assert "first.hocon" in report
    assert "second.hocon" in report

    assert "No generated network implements" in render_traceability(results, None, "ODB-99")


def test_traceability_answers_which_networks_come_from_a_pack(tmp_path, packs):
    """
    The other half: everything built from a given pack, for when a pack is revised.
    """
    write_network(tmp_path, "oracle_net", load_pack(DOMAIN))
    results: list[AuditedNetwork] = audit_directory(tmp_path, packs)

    assert "oracle_net.hocon" in render_traceability(results, DOMAIN, None)
    assert "No generated network implements" in render_traceability(results, "kubernetes_cluster_upgrade", None)


def test_the_cli_exits_one_when_something_needs_attention(tmp_path, capsys):
    """
    Exit codes, so this can run as a scheduled check over an estate rather than by eye.
    """
    write_network(tmp_path, "current_net", load_pack(DOMAIN), version="1.0.0")
    assert main([str(tmp_path)]) == 0

    write_network(tmp_path, "stale_net", load_pack(DOMAIN), version="0.1.0")
    assert main([str(tmp_path)]) == 1
    assert "stale" in capsys.readouterr().out


def test_a_missing_directory_is_a_usage_error(tmp_path):
    """A mistyped path must not read as a clean estate."""
    assert main([str(tmp_path / "nope")]) == 2


def test_an_empty_directory_reports_nothing_found(tmp_path, capsys):
    """Zero networks is not the same as zero problems, and must not print an empty table."""
    assert main([str(tmp_path)]) == 0
    assert "No generated networks found" in capsys.readouterr().out
