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
Read the curated knowledge documents for one domain.

Documents are returned WHOLE and verbatim - never chunked or summarised - because the operating
standards they carry have to reach the designed agents word for word, with their ids intact.
Anything less and the fidelity check in verify_standards has nothing to compare against.

Domain resolution is delegated to knowledge_pack, so:

  * domains are discovered by scanning the knowdocs root rather than listed here in Python;
  * the root honours AGENT_NETWORK_DESIGNER_KNOWDOCS, and otherwise resolves relative to this
    module rather than the process working directory;
  * an unknown domain is an explicit MISS listing what does exist, not a silent fallback to
    some default document. The designer has to KNOW it missed so it can say so and fall back
    to general knowledge, rather than interviewing the user from the wrong domain's standards.
"""

import logging
from typing import Any

from neuro_san.interfaces.coded_tool import CodedTool

from coded_tools.agent_network_designer.knowledge_pack import PACK_PROVENANCE
from coded_tools.agent_network_designer.knowledge_pack import KnowledgePack
from coded_tools.agent_network_designer.knowledge_pack import discover_domains
from coded_tools.agent_network_designer.knowledge_pack import knowdocs_root
from coded_tools.agent_network_designer.knowledge_pack import load_pack

logger = logging.getLogger(__name__)


class ExtractDocs(CodedTool):
    """
    CodedTool implementation that extracts the curated knowledge documents for a domain.

    Returns a dictionary mapping each document file name to its text, plus the pack's identity
    and provenance so the designer can state what it built from.
    """

    def invoke(self, args: dict[str, Any], sly_data: dict[str, Any]) -> dict[str, Any] | str:
        """
        :param args: An argument dictionary with the following keys:
            - "app_name" (str): the curated domain to read, as reported by ListDomains.

        :param sly_data: A dictionary whose keys are defined by the agent hierarchy, but whose
            values are meant to be kept out of the chat stream.

            Keys expected for this implementation are:
                None

        :return:
            If successful:
                A dictionary with the keys:
                - "files" (dict): document file name to full verbatim text.
                - "pack" (dict): the domain's id, title, version and provenance line.
                - "standard_ids" (list): the ids this pack defines, for the designer to quote.
            Otherwise:
                A text string error message in the format:
                "Error: <error message>"
        """
        domain_id: str | None = args.get("app_name")
        available: str = ", ".join(discover_domains()) or "none"

        logger.debug("############### Curated knowledge reader ###############")
        logger.debug("Domain: %s", domain_id)

        if not domain_id:
            return f"Error: No domain provided. Available curated domains: {available}"

        try:
            pack: KnowledgePack = load_pack(domain_id)
        except (FileNotFoundError, OSError):
            # An explicit miss, not a fallback: see the module docstring.
            return f'Error: No curated knowledge for domain "{domain_id}". Available curated domains: {available}'

        if not pack.documents:
            return f'ERROR: No knowledge documents found for domain "{domain_id}" under {knowdocs_root()}.'

        for problem in pack.validate():
            logger.warning("Knowledge pack problem: %s", problem)

        # Record what this network is being built from, so the persistence layer can stamp it into
        # the generated artifact. Without this the provenance lives only in a chat transcript, and
        # the file on disk is of unknown ancestry - which is the thing a manifest exists to fix.
        if sly_data is not None:
            sly_data[PACK_PROVENANCE] = pack.manifest.provenance()

        logger.debug("############### Documents extraction done ###############")
        return {
            "files": pack.documents,
            "pack": {
                "id": pack.domain_id,
                "title": pack.manifest.title,
                "version": pack.manifest.version,
                "provenance": pack.manifest.provenance(),
            },
            "standard_ids": [standard.standard_id for standard in pack.standards],
        }

    async def async_invoke(self, args: dict[str, Any], sly_data: dict[str, Any]) -> dict[str, Any] | str:
        """
        Delegates to the synchronous implementation.

        :param args: See invoke().
        :param sly_data: See invoke().
        :return: See invoke().
        """
        return self.invoke(args, sly_data)
