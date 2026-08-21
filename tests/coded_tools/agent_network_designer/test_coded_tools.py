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
Tests for the three coded tools themselves - the adapter layer between neuro-san and the checks.

This layer had no tests, and both of the runtime faults found in review lived here rather than in
the logic underneath: a tool declared so it could not be built, and a verifier willing to accept the
artifact under audit from the party being audited. Neither would have been caught by testing
``verify()`` alone, which is what the original suite did.

No language model: the tools are invoked directly with the args and sly_data they would receive.
"""

import asyncio
from typing import Any

import pytest

from coded_tools.agent_network_designer.extract_docs import ExtractDocs
from coded_tools.agent_network_designer.knowledge_pack import PACK_PROVENANCE
from coded_tools.agent_network_designer.knowledge_pack import KnowledgePack
from coded_tools.agent_network_designer.knowledge_pack import load_pack
from coded_tools.agent_network_designer.list_domains import ListDomains
from coded_tools.agent_network_designer.verify_standards import VerifyStandards
from tests.coded_tools.agent_network_designer.network_fixtures import reference_network

DOMAIN: str = "oracle_database_patching"


@pytest.fixture(name="pack")
def pack_fixture() -> KnowledgePack:
    """
    :return: The Oracle reference pack.
    """
    return load_pack(DOMAIN)


@pytest.fixture(name="built")
def built_fixture(pack) -> dict[str, Any]:
    """
    :param pack: The loaded pack.
    :return: sly_data as it stands once a correct network has been built.
    """
    return {"agent_network_definition": reference_network(pack)}


# --------------------------------------------------------------------------------------
# ListDomains
# --------------------------------------------------------------------------------------


def test_list_domains_reports_the_catalogue_with_versions_and_ids():
    """
    The designer decides which domain a request belongs to from this, so it has to be complete.
    """
    result: Any = ListDomains().invoke({}, {})

    assert isinstance(result, dict), result
    assert result["count"] == len(result["domains"])
    entry: dict[str, Any] = next(item for item in result["domains"] if item["id"] == DOMAIN)
    assert entry["version"]
    assert entry["standard_ids"]
    assert entry["title"]


def test_list_domains_takes_no_arguments():
    """
    It is declared with no parameters block, so it must not depend on receiving any.
    """
    assert ListDomains().invoke({}, {}) == ListDomains().invoke({"unexpected": "value"}, {})


def test_list_domains_reports_an_error_rather_than_an_empty_catalogue(tmp_path, monkeypatch):
    """
    An empty deployment must be an explicit, actionable miss - "" would read as "no domains match".
    """
    monkeypatch.setenv("AGENT_NETWORK_DESIGNER_KNOWDOCS", str(tmp_path))
    result: Any = ListDomains().invoke({}, {})

    assert isinstance(result, str)
    assert result.startswith("Error:")
    assert "general knowledge" in result


# --------------------------------------------------------------------------------------
# ExtractDocs
# --------------------------------------------------------------------------------------


def test_extract_docs_returns_documents_whole_and_records_provenance():
    """
    Documents must arrive verbatim, and the pack's identity must be recorded for the artifact.
    """
    sly_data: dict[str, Any] = {}
    result: Any = ExtractDocs().invoke({"app_name": DOMAIN}, sly_data)

    assert isinstance(result, dict), result
    assert "operating_standards.md" in result["files"]
    assert result["standard_ids"]
    assert result["pack"]["version"]
    # The provenance is what lets the generated network state its own ancestry.
    assert sly_data[PACK_PROVENANCE].startswith(result["pack"]["title"])
    assert result["pack"]["version"] in sly_data[PACK_PROVENANCE]


def test_extract_docs_names_the_alternatives_on_a_miss():
    """
    The control case. A miss must be explicit and must not fall back to another domain's standards.
    """
    result: Any = ExtractDocs().invoke({"app_name": "pizza_delivery"}, {})

    assert isinstance(result, str)
    assert result.startswith("Error:")
    assert DOMAIN in result


def test_extract_docs_survives_being_given_no_sly_data():
    """
    The provenance write must not become a new way for the tool to fail.
    """
    result: Any = ExtractDocs().invoke({"app_name": DOMAIN}, None)
    assert isinstance(result, dict), result


# --------------------------------------------------------------------------------------
# VerifyStandards - the audit boundary
# --------------------------------------------------------------------------------------


def test_verify_standards_reports_clean_for_a_correct_build(built):
    """
    Baseline for the tool wrapper, as opposed to the function underneath it.
    """
    result: Any = VerifyStandards().invoke({"app_name": DOMAIN}, built)

    assert isinstance(result, dict), result
    assert result["ok"] is True
    assert result["problems"] == []
    assert "Standards coverage (verified)" in result["report"]
    assert result["provenance"]


def test_verify_standards_ignores_a_network_supplied_by_the_model(pack, built):
    """
    The audited party must not be able to hand the auditor the artifact to audit.

    A model that passed its own definition in args - a doctored one, with every standard present -
    would otherwise be verifying a network that is not the one being built. sly_data is the only
    accepted source, so the doctored copy has no effect and the real fault is still reported.
    """
    broken: dict[str, Any] = {name: dict(value) for name, value in built["agent_network_definition"].items()}
    dropped: str = pack.standards[-1].standard_id
    for definition in broken.values():
        lines: list[str] = [
            line for line in str(definition.get("instructions", "")).splitlines() if f"[{dropped}]" not in line
        ]
        definition["instructions"] = "\n".join(lines)
    sly_data: dict[str, Any] = {"agent_network_definition": broken}

    # The model offers a pristine network in args. It must be disregarded entirely.
    result: Any = VerifyStandards().invoke(
        {"app_name": DOMAIN, "agent_network_definition": built["agent_network_definition"]}, sly_data
    )

    assert isinstance(result, dict), result
    assert result["ok"] is False, "a model-supplied definition was accepted"
    assert any(dropped in problem for problem in result["problems"])


def test_verify_standards_refuses_before_anything_is_built():
    """
    Called too early, it must say so rather than report an empty network as clean.
    """
    result: Any = VerifyStandards().invoke({"app_name": DOMAIN}, {})

    assert isinstance(result, str)
    assert result.startswith("Error:")
    assert "after the network has been built" in result


def test_verify_standards_requires_a_domain(built):
    """
    Without a domain there is nothing to verify against, which is an error not an empty pass.
    """
    result: Any = VerifyStandards().invoke({}, built)
    assert isinstance(result, str)
    assert result.startswith("Error:")


def test_verify_standards_rejects_an_unknown_domain(built):
    """
    A typo in app_name must not silently verify against nothing.
    """
    result: Any = VerifyStandards().invoke({"app_name": "not_a_domain"}, built)
    assert isinstance(result, str)
    assert result.startswith("Error:")
    assert DOMAIN in result


def test_strict_mode_turns_a_failed_verification_into_an_error(built):
    """
    Advisory is the default; strict is what a caller uses when it wants the build to stop.
    """
    broken: dict[str, Any] = {name: dict(value) for name, value in built["agent_network_definition"].items()}
    broken["coordinator"]["instructions"] += "\nMUST: Invented rule [ODB-99]"
    sly_data: dict[str, Any] = {"agent_network_definition": broken}

    advisory: Any = VerifyStandards().invoke({"app_name": DOMAIN}, sly_data)
    assert isinstance(advisory, dict)
    assert advisory["ok"] is False

    strict: Any = VerifyStandards().invoke({"app_name": DOMAIN, "strict": True}, sly_data)
    assert isinstance(strict, str)
    assert strict.startswith("Error: Standards verification failed")
    # The report still travels with the error, so the failure is actionable rather than opaque.
    assert "ODB-99" in strict


def test_strict_mode_does_not_fire_on_a_clean_build(built):
    """
    Strict must mean "fail on failure", not "fail".
    """
    result: Any = VerifyStandards().invoke({"app_name": DOMAIN, "strict": True}, built)
    assert isinstance(result, dict), result
    assert result["ok"] is True


def test_the_async_entry_points_match_the_sync_ones(built):
    """
    Every tool ships async_invoke; a divergence there would only show up in the live server.
    """
    assert asyncio.run(ListDomains().async_invoke({}, {})) == ListDomains().invoke({}, {})
    assert asyncio.run(ExtractDocs().async_invoke({"app_name": DOMAIN}, {})) == ExtractDocs().invoke(
        {"app_name": DOMAIN}, {}
    )
    assert asyncio.run(VerifyStandards().async_invoke({"app_name": DOMAIN}, built)) == VerifyStandards().invoke(
        {"app_name": DOMAIN}, built
    )
