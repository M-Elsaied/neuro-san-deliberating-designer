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

import asyncio
import logging
from typing import Any

from neuro_san.interfaces.coded_tool import CodedTool

from coded_tools.agent_network_designer.knowledge_pack import KnowledgePack
from coded_tools.agent_network_designer.pack_catalog import PackCatalog
from coded_tools.agent_network_designer.pack_reader import PackReader
from coded_tools.agent_network_designer.standards_verifier import StandardsVerifier
from coded_tools.agent_network_designer.verification_report import VerificationReport
from coded_tools.agent_network_designer.verification_result import VerificationResult
from coded_tools.agent_network_editor.constants import AGENT_NETWORK_DEFINITION

logger = logging.getLogger(__name__)


class VerifyStandards(CodedTool):
    """
    CodedTool that verifies the network under construction against its domain's knowledge pack and returns the
    computed coverage report. A failed verification is reported, not raised, so the designer can state it.
    """

    def invoke(self, args: dict[str, Any], sly_data: dict[str, Any]) -> dict[str, Any] | str:
        """
        Verify the network under construction and return the computed coverage report.

        :param args: "app_name", the domain the network was designed for, and optionally "strict", which turns a
            failed verification into an error string.
        :param sly_data: "agent_network_definition", the network to verify. It is never taken from args, since
            the model being audited must not supply the artifact under audit. The pack's provenance is written
            under KnowledgePack.PROVENANCE_KEY, because this runs in the same turn as persistence.
        :return: "ok", "domain", "provenance", "report" (markdown to print verbatim), "problems",
            "pack_errors" and "pack_warnings". Otherwise an "Error: ..." string, which in strict mode carries
            the report.
        """
        domain_id: str | None = args.get("app_name")
        if not domain_id:
            return (
                f"Error: No domain provided to verify against. "
                f"Available curated domains: {PackReader.describe_domains()}"
            )

        network_definition: Any = (sly_data or {}).get(AGENT_NETWORK_DEFINITION)
        if not isinstance(network_definition, dict) or not network_definition:
            return (
                "Error: No agent network definition is available to verify. "
                "Verification runs after the network has been built."
            )
        try:
            pack: KnowledgePack = PackCatalog.load_pack(domain_id)
        except FileNotFoundError as exception:
            return f"Error: {exception}. Available curated domains: {PackReader.describe_domains()}"
        except (OSError, ValueError) as exception:
            logger.warning("Could not read knowledge pack %s: %s", domain_id, exception)
            return f"""Error: The knowledge pack for domain "{domain_id}" could not be read: {exception}"""

        result: VerificationResult = StandardsVerifier.verify(pack, network_definition)
        report: str = VerificationReport.render(result)
        logger.debug("Standards verification for %s: ok=%s", domain_id, result.ok)
        if sly_data is not None:
            sly_data[KnowledgePack.PROVENANCE_KEY] = result.provenance
        if args.get("strict") and not result.ok:
            return "Error: Standards verification failed.\n\n" + report
        return {
            "ok": result.ok,
            "domain": result.domain_id,
            "provenance": result.provenance,
            "report": report,
            "problems": VerificationReport.get_problems(result),
            "pack_errors": result.pack_errors,
            "pack_warnings": result.pack_warnings,
        }

    async def async_invoke(self, args: dict[str, Any], sly_data: dict[str, Any]) -> dict[str, Any] | str:
        """
        Runs invoke() in a worker thread, since it reads the pack from disk.

        :param args: See invoke().
        :param sly_data: See invoke().
        :return: See invoke().
        """
        return await asyncio.to_thread(self.invoke, args, sly_data)
