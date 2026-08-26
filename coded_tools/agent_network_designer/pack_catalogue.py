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
Loading and caching the knowledge-pack catalogue.

knowledge_pack.py models a pack and reads one from disk. This module is the entry point every
caller should use instead, because it adds the thing a server needs: the packs are read once per
process rather than once per tool call.

The public functions here mirror the disk-reading ones exactly - discover_domains, load_pack,
load_catalogue - so a caller does not choose between "cached" and "correct". They are the same
answer, and the cache invalidates itself against the filesystem on every read.
"""

import os
from pathlib import Path

from coded_tools.agent_network_designer.knowledge_pack import _FINGERPRINTED_SUFFIXES
from coded_tools.agent_network_designer.knowledge_pack import KnowledgePack
from coded_tools.agent_network_designer.knowledge_pack import knowdocs_root
from coded_tools.agent_network_designer.knowledge_pack import read_domains
from coded_tools.agent_network_designer.knowledge_pack import read_pack
from coded_tools.agent_network_editor.shared_process_cache import SharedProcessCache


def discover_domains(root: str | os.PathLike | None = None) -> list[str]:
    """
    List the domains available under the knowdocs root.

    A domain is any immediate subdirectory holding at least one readable document. Nothing is
    registered in Python, so adding a domain is a filesystem operation: no code change, no fork.

    Served from the process-wide cache when it is warm; a miss walks the root without forcing a
    full pack load, since a caller who only wants the names should not pay to parse every pack.

    :param root: The knowdocs root, or None to resolve it.
    :return: Sorted domain identifiers.
    """
    cached: dict[str, KnowledgePack] | None = PackCatalogue.peek(root)
    if cached is not None:
        return sorted(cached)
    return read_domains(root)


def load_pack(domain_id: str, root: str | os.PathLike | None = None) -> KnowledgePack:
    """
    Load one pack by domain identifier, from the process-wide cache when it is warm.

    A warm catalogue is served from memory. A cold one is NOT loaded in full here: reading one
    pack must not become an O(all packs) operation just because the cache happens to be empty.
    In the live designer this costs nothing, because ListDomains runs before ExtractDocs and so
    the catalogue is already warm by the time a single pack is asked for.

    :param domain_id: The domain identifier - the pack's directory name.
    :param root: The knowdocs root, or None to resolve it.
    :return: The loaded pack.
    :raises FileNotFoundError: If no pack directory exists for this domain.
    """
    cached: dict[str, KnowledgePack] | None = PackCatalogue.peek(root)
    if cached is not None and domain_id in cached:
        return cached[domain_id]
    return read_pack(domain_id, root)


def load_catalogue(root: str | os.PathLike | None = None) -> list[KnowledgePack]:
    """
    Load every discoverable pack, from the process-wide cache when it is warm.

    :param root: The knowdocs root, or None to resolve it.
    :return: The loaded packs, ordered by domain id.
    """
    return list(PackCatalogue.get(root).values())


def _load_catalogue_uncached(root: str | os.PathLike | None = None) -> dict[str, KnowledgePack]:
    """
    Read every discoverable pack from disk, in domain order.

    :param root: The knowdocs root, or None to resolve it.
    :return: Domain id to loaded pack.
    """
    packs: dict[str, KnowledgePack] = {}
    for domain_id in read_domains(root):
        try:
            packs[domain_id] = read_pack(domain_id, root)
        except (FileNotFoundError, OSError):
            continue
    return packs


def catalogue_fingerprint(root: str | os.PathLike | None = None) -> tuple[str, tuple[tuple[str, int], ...]]:
    """
    Probe the version of every document under the knowdocs root.

    Must never raise, per the SharedProcessCache contract: a root that vanishes mid-probe is
    reported as an empty document set, which is a legitimate version of the source rather than an
    error, and the loader reports the same emptiness.

    :param root: The knowdocs root, or None to resolve it.
    :return: The resolved root and a sorted (relative path, modification time) tuple.
    """
    resolved: Path = knowdocs_root(root)
    documents: list[tuple[str, int]] = []
    try:
        for path in sorted(resolved.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in _FINGERPRINTED_SUFFIXES:
                continue
            modified: int | None = SharedProcessCache.stat_modification_time_ns(str(path))
            documents.append((str(path.relative_to(resolved)), modified if modified is not None else -1))
    except OSError:
        return str(resolved), ()
    return str(resolved), tuple(documents)


class PackCatalogue:
    """
    The process-wide knowledge-pack cache.

    Every pack was previously re-read from disk on every tool call - directories re-walked,
    pack.hocon re-parsed, documents re-read and PDFs re-extracted through pypdf - which
    load_catalogue then did N+1 times over. Measured at 21 ms for the three shipped packs, on the
    event loop, per ListDomains call, and linear in the number of packs: a deployment serving
    fifty would block for roughly 300 ms every time the designer asked what domains exist.

    The cache is process-wide rather than per-conversation because the catalogue is a property of
    the deployment: N concurrent conversations should read one copy. Locking, publish ordering and
    the async once-gate all live in SharedProcessCache, which four other coded tools here already
    use - so this adds a call site, not machinery.

    Freshness is a full walk of the root. That is the most expensive probe available and still
    only 0.4 ms, about 2% of a cold load, and it buys exact correctness: an edited pack is picked
    up with no restart, no TTL to tune and no staleness window to document. Serving a stale pack
    would be worse than not caching at all, because the designer and the verifier read the same
    copy and would agree with each other about a document that had already changed.

    The resolved root is part of the fingerprint, so a changed AGENT_NETWORK_DESIGNER_KNOWDOCS is
    a miss rather than a wrong hit. An explicit root= bypasses the cache entirely.
    """

    _shared_catalogue_cache: SharedProcessCache[dict[str, KnowledgePack]] = SharedProcessCache(
        loader=_load_catalogue_uncached,
        fingerprint=catalogue_fingerprint,
    )

    @staticmethod
    def get(root: str | os.PathLike | None = None) -> dict[str, KnowledgePack]:
        """
        Read the whole catalogue, loading it on a miss.

        :param root: The knowdocs root, or None to resolve it.
        :return: Domain id to loaded pack. Treat as read-only: it is the shared value.
        """
        if root is not None:
            # An explicit root is a caller reading somewhere other than the deployment's own
            # store, which the single-slot cache cannot represent without evicting the value
            # every other caller is using. Read it directly instead.
            return _load_catalogue_uncached(root)
        return PackCatalogue._shared_catalogue_cache.get()

    @staticmethod
    def peek(root: str | os.PathLike | None = None) -> dict[str, KnowledgePack] | None:
        """
        Read the catalogue only if it is already cached and still fresh.

        Lets load_pack serve a single domain from a warm catalogue without forcing a cold load of
        every pack, which would turn a one-pack read into an O(all packs) one.

        :param root: The knowdocs root, or None to resolve it.
        :return: The cached catalogue, or None on a miss.
        """
        if root is not None:
            return None
        return PackCatalogue._shared_catalogue_cache.peek()

    @classmethod
    def clear_shared_catalogue_for_testing(cls):
        """
        Reset the process-wide catalogue cache. For test isolation only.

        Production code must never call this. Tests call it via tests/conftest.py so packs loaded
        under one test's knowdocs root cannot leak into the next. Living here rather than in
        conftest keeps the singleton policy in one place.
        """
        PackCatalogue._shared_catalogue_cache.clear_for_testing()
