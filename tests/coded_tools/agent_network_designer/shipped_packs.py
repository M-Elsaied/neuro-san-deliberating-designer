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
The packs this repository ships, and the packs actually present on disk.

Note on the filename: deliberately not test_*, so pytest does not collect it as a test module.

Two different lists, used for two different purposes, and conflating them was a real gap:

  SHIPPED_DOMAINS   what this repository intends to ship. Adding a pack means adding a line here,
                    so a new pack is a deliberate act rather than an invisible one.
  present_domains() what is actually on disk right now, including a deployment's own packs.

Validation is parametrised over present_domains(), not SHIPPED_DOMAINS. Before that, the check
that packs are well formed ran against a hardcoded tuple while the discovery assertions were
one-directional subset checks - so a malformed pack dropped into the knowdocs root passed CI in
silence. Every malformed-pack test used synthetic fixtures, which proved the checks worked without
ever pointing them at the content that ships.
"""

from coded_tools.agent_network_designer.pack_catalogue import discover_domains

SHIPPED_DOMAINS: tuple[str, ...] = (
    "clinical_trial_database_lock",
    "kubernetes_cluster_upgrade",
    "oracle_database_patching",
)


def present_domains() -> list[str]:
    """
    Every pack currently under the default knowdocs root.

    Called at collection time by the parametrised validation tests, so any pack present - ours or
    a deployment's - is checked. That is what makes a malformed pack a red build.

    :return: Sorted domain identifiers.
    """
    return discover_domains()
