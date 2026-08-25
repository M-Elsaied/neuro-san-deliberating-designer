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
CodedTool wrapper around the standards verifier.

The checks themselves live in standards_verifier, which imports nothing from neuro-san so the
same verification can run in CI, in a pre-commit hook, or over a directory of already-generated
networks. This module is only the adapter that lets the designer call it mid-build.
"""

import logging
from typing import Any

from neuro_san.interfaces.coded_tool import CodedTool

from coded_tools.agent_network_designer.knowledge_pack import PACK_PROVENANCE
from coded_tools.agent_network_designer.knowledge_pack import KnowledgePack
from coded_tools.agent_network_designer.knowledge_pack import discover_domains
from coded_tools.agent_network_designer.knowledge_pack import load_pack
from coded_tools.agent_network_designer.standards_verifier import VerificationResult
from coded_tools.agent_network_designer.standards_verifier import render_report
from coded_tools.agent_network_designer.standards_verifier import verify

logger = logging.getLogger(__name__)

# sly_data key holding the network under construction.
AGENT_NETWORK_DEFINITION: str = "agent_network_definition"


class VerifyStandards(CodedTool):
    """
    CodedTool that verifies a generated agent network against its domain's knowledge pack.

    Reads the network from sly_data, loads the pack, and returns a COMPUTED coverage report -
    replacing a table the language model would otherwise write about its own work.

    Advisory by default: a network covering five of six standards with one flagged is more useful
    than an exception, and an honest partial report is the point. Pass strict=true to turn a
    failed verification into an error the designer is obliged to surface.
    """

    def invoke(self, args: dict[str, Any], sly_data: dict[str, Any]) -> dict[str, Any] | str:
        """
        :param args: An argument dictionary with the following keys:
            - "app_name" (str): the curated domain the network was designed for.
            - "strict" (bool, optional): when true, a failed verification is returned as an
              error string rather than a report. Defaults to false.

        :param sly_data: A dictionary whose keys are defined by the agent hierarchy, but whose
            values are meant to be kept out of the chat stream.

            Keys expected for this implementation are:
                "agent_network_definition": the network under construction.

        :return:
            If successful:
                A dictionary containing the verification outcome with the keys:
                - "ok" (bool): whether every check passed.
                - "domain" (str): the domain verified against.
                - "provenance" (str): the pack's identity, version and owner.
                - "report" (str): a markdown coverage table, ready to print verbatim.
                - "problems" (list): every failure, as human-readable lines.
                - "pack_errors" (list): pack faults that block verification.
                - "pack_warnings" (list): pack faults that do not block verification.
            Otherwise:
                A text string error message in the format:
                "Error: <error message>"
        """
        available: str = ", ".join(discover_domains()) or "none"

        domain_id: str | None = args.get("app_name")
        if not domain_id:
            return f"Error: No domain provided to verify against. Available curated domains: {available}"

        # The network under audit is read ONLY from sly_data, which the middleware maintains.
        # It is deliberately not accepted from args: args is what the model sends, and letting the
        # audited party hand the auditor the artifact to audit would reinstate exactly the
        # self-certification this tool exists to remove.
        network_definition: Any = (sly_data or {}).get(AGENT_NETWORK_DEFINITION)
        if not isinstance(network_definition, dict) or not network_definition:
            return (
                "Error: No agent network definition is available to verify. "
                "Verification runs after the network has been built."
            )

        try:
            pack: KnowledgePack = load_pack(domain_id)
        except (FileNotFoundError, OSError) as exception:
            return f"Error: {exception}. Available curated domains: {available}"

        result: VerificationResult = verify(pack, network_definition)
        report: str = render_report(result)
        logger.debug("Standards verification for %s: ok=%s", domain_id, result.ok)

        # Record the provenance here as well as in ExtractDocs, and the reason is the sly_data
        # lifecycle rather than belt-and-braces. The session dict is rebuilt from the client's
        # payload on every turn (DataDrivenChatSession), so a key written during the interview
        # survives to the build turn only if allow.to_upstream lets it out and the client sends it
        # back. This tool runs in the SAME turn as persistence, so writing it here guarantees the
        # generated artifact can state what it was built from even if the round trip is lossy.
        if sly_data is not None:
            sly_data[PACK_PROVENANCE] = pack.manifest.provenance()

        if args.get("strict") and not result.ok:
            return "Error: Standards verification failed.\n\n" + report

        return {
            "ok": result.ok,
            "domain": result.domain_id,
            "provenance": result.provenance,
            "report": report,
            "problems": result.problems(),
            "pack_errors": result.pack_errors,
            "pack_warnings": result.pack_warnings,
        }

    async def async_invoke(self, args: dict[str, Any], sly_data: dict[str, Any]) -> dict[str, Any] | str:
        """
        Delegates to the synchronous implementation: verification is CPU-bound string work.

        :param args: See invoke().
        :param sly_data: See invoke().
        :return: See invoke().
        """
        return self.invoke(args, sly_data)
