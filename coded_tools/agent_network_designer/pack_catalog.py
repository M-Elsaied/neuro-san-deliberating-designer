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

import os
from pathlib import Path

from coded_tools.agent_network_designer.knowledge_pack import KnowledgePack
from coded_tools.agent_network_designer.pack_reader import PackReader
from coded_tools.agent_network_editor.shared_process_cache import SharedProcessCache


class PackCatalog:
    """
    Serves the knowledge packs from a process-wide cache, so they are read once per process rather than once per
    tool call. Each method answers as the PackReader method of the same name does.
    """

    # Every file a pack is built from, so a change to any of them invalidates the cache.
    FINGERPRINTED_SUFFIXES: tuple[str, ...] = PackReader.DOCUMENT_SUFFIXES + (".hocon",)

    @staticmethod
    def load_pack(domain_id: str, root: str | os.PathLike | None = None) -> KnowledgePack:
        """
        Load one pack, from the cache when it is warm. A cold cache is not filled, so one pack never reads them all.

        :param domain_id: The domain id, which is the pack's directory name.
        :param root: The knowdocs root, or None for the one PackReader resolves.
        :return: The pack.
        :raises FileNotFoundError: As PackReader.load_pack() does.
        :raises ValueError: As PackReader.load_pack() does.
        """
        cached: dict[str, KnowledgePack] | None = PackCatalog.peek(root)
        if cached is not None and domain_id in cached:
            return cached.get(domain_id)
        return PackReader.load_pack(domain_id, root)

    @staticmethod
    def load_catalog(root: str | os.PathLike | None = None) -> list[KnowledgePack]:
        """
        Load every pack, filling the cache on a miss. An explicit root is read directly, since the cache holds one.

        :param root: The knowdocs root, or None for the one PackReader resolves.
        :return: Every readable pack, in domain id order.
        """
        if root is not None:
            return PackReader.load_catalog(root)
        return list(PackCatalog._shared_catalog_cache.get().values())

    @staticmethod
    def peek(root: str | os.PathLike | None = None) -> dict[str, KnowledgePack] | None:
        """
        Read the catalog only if the cache already holds a fresh copy.

        :param root: The knowdocs root, or None for the one PackReader resolves.
        :return: Domain id to pack, or None on a miss or for an explicit root.
        """
        return None if root is not None else PackCatalog._shared_catalog_cache.peek()

    @staticmethod
    def read_catalog() -> dict[str, KnowledgePack]:
        """
        Read every pack from disk, to fill the cache.

        :return: Domain id to pack, in domain id order.
        """
        catalog: dict[str, KnowledgePack] = {}
        for pack in PackReader.load_catalog():
            catalog[pack.domain_id] = pack
        return catalog

    @staticmethod
    def get_fingerprint() -> str:
        """
        Identify the version of every file the catalog is built from, including the resolved root, so a changed
        AGENT_NETWORK_DESIGNER_KNOWDOCS is a miss. Must not raise, per the SharedProcessCache contract.

        :return: The resolved root, then one line per pack file with its modification time.
        """
        resolved: Path = PackReader.get_knowdocs_root()
        lines: list[str] = [str(resolved)]
        try:
            for path in sorted(resolved.rglob("*")):
                if path.is_file() and path.suffix.lower() in PackCatalog.FINGERPRINTED_SUFFIXES:
                    modified: int | None = SharedProcessCache.stat_modification_time_ns(str(path))
                    lines.append(f"{path.relative_to(resolved)} {modified if modified is not None else -1}")
        except OSError:
            # A root that vanishes mid-walk is an empty catalog, which is what the loader reads too.
            return str(resolved)
        return "\n".join(lines)

    # One copy per deployment, shared by every conversation. The fingerprint walks the whole root, so an edited pack
    # is picked up with no restart: a stale pack would be worse than none, since the designer and the verifier
    # would agree with each other about a document that had already changed.
    _shared_catalog_cache: SharedProcessCache[dict[str, KnowledgePack]] = SharedProcessCache(
        loader=read_catalog, fingerprint=get_fingerprint
    )

    @classmethod
    def clear_shared_catalog_for_testing(cls):
        """
        Reset the process-wide catalog cache, for test isolation only. tests/conftest.py calls it around every test.
        """
        PackCatalog._shared_catalog_cache.clear_for_testing()
