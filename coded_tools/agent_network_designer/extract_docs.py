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
from coded_tools.agent_network_designer.pack_validator import PackValidator

logger = logging.getLogger(__name__)


class ExtractDocs(CodedTool):
    """
    CodedTool that returns one domain's knowledge documents whole and verbatim, so its standards can be quoted
    word for word. An unknown domain is an explicit miss naming the domains that exist, never a fallback to
    another domain's documents.
    """

    def invoke(self, args: dict[str, Any], sly_data: dict[str, Any]) -> dict[str, Any] | str:
        """
        Return one domain's knowledge documents and record the pack's provenance.

        :param args: "app_name", the domain to read, as ListDomains reported it.
        :param sly_data: The pack's provenance is written under KnowledgePack.PROVENANCE_KEY for persistence.
        :return: "files", document name to full text; "pack", the pack's "id", "title", "version" and
            "provenance"; and "standard_ids". Otherwise an "Error: ..." string, or "ERROR: ..." when the pack
            directory holds no documents.
        """
        domain_id: str | None = args.get("app_name")
        logger.debug("############### Curated knowledge reader ###############")
        logger.debug("Domain: %s", domain_id)
        if not domain_id:
            return f"Error: No domain provided. Available curated domains: {PackReader.describe_domains()}"
        try:
            pack: KnowledgePack = PackCatalog.load_pack(domain_id)
        except FileNotFoundError:
            return (
                f"""Error: No curated knowledge for domain "{domain_id}". """
                f"Available curated domains: {PackReader.describe_domains()}"
            )
        except (OSError, ValueError) as exception:
            logger.warning("Could not read knowledge pack %s: %s", domain_id, exception)
            return f"""Error: The knowledge pack for domain "{domain_id}" could not be read: {exception}"""
        if not pack.documents:
            root: str = str(PackReader.get_knowdocs_root())
            return f"""ERROR: No knowledge documents found for domain "{domain_id}" under {root}."""

        for problem in PackValidator.get_problems(pack):
            logger.warning("Knowledge pack problem: %s", problem)

        provenance: str = pack.manifest.get_provenance()
        if sly_data is not None:
            sly_data[KnowledgePack.PROVENANCE_KEY] = provenance
        standard_ids: list[str] = []
        for standard in pack.standards:
            standard_ids.append(standard.standard_id)
        logger.debug("############### Documents extraction done ###############")
        return {
            "files": pack.documents,
            "pack": {
                "id": pack.domain_id,
                "title": pack.manifest.title,
                "version": pack.manifest.version,
                "provenance": provenance,
            },
            "standard_ids": standard_ids,
        }

    async def async_invoke(self, args: dict[str, Any], sly_data: dict[str, Any]) -> dict[str, Any] | str:
        """
        Runs invoke() in a worker thread, since it reads the pack from disk.

        :param args: See invoke().
        :param sly_data: See invoke().
        :return: See invoke().
        """
        return await asyncio.to_thread(self.invoke, args, sly_data)
