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

import re

from coded_tools.agent_network_designer.knowledge_pack import KnowledgePack
from coded_tools.agent_network_designer.pack_manifest import PackManifest
from coded_tools.agent_network_designer.pack_reader import PackReader


class PackValidator:
    """
    Checks a loaded knowledge pack. An error means a standard may not reach the network, so it fails verification.
    A warning means the pack is under-specified but its standards are intact.
    """

    VALID_ROLES: tuple[str, ...] = ("precondition", "work", "postcondition")

    @staticmethod
    def get_problems(pack: KnowledgePack) -> list[str]:
        """
        List every problem with a pack, errors and warnings together.

        :param pack: The pack to check.
        :return: Manifest warnings, a missing standards or open variables file, then each standard's and each open
            variable's problems.
        """
        return (
            PackValidator.get_manifest_warnings(pack)
            + PackValidator.get_missing_standards_errors(pack)
            + PackValidator.get_missing_variables_warnings(pack)
            + PackValidator.get_standard_errors(pack)
            + PackValidator.get_variable_warnings(pack)
        )

    @staticmethod
    def get_errors(pack: KnowledgePack) -> list[str]:
        """
        List the problems that stop a pack's standards reaching a network, and so fail verification.

        :param pack: The pack to check.
        :return: The errors, in the order get_problems() lists them.
        """
        return PackValidator.get_missing_standards_errors(pack) + PackValidator.get_standard_errors(pack)

    @staticmethod
    def get_warnings(pack: KnowledgePack) -> list[str]:
        """
        List the problems that leave a pack under-specified but its standards intact.

        :param pack: The pack to check.
        :return: The warnings, in the order get_problems() lists them.
        """
        return (
            PackValidator.get_manifest_warnings(pack)
            + PackValidator.get_missing_variables_warnings(pack)
            + PackValidator.get_variable_warnings(pack)
        )

    @staticmethod
    def get_manifest_warnings(pack: KnowledgePack) -> list[str]:
        """
        Check that the pack has a pack.hocon, and that it declares a version.

        :param pack: The pack to check.
        :return: At most one warning.
        """
        if pack.manifest.synthesized:
            return [
                f"{pack.domain_id}: no {PackReader.MANIFEST_FILENAME} found - identity and provenance were inferred "
                f"from the directory name. Add one to record version, owner and approval."
            ]
        if not pack.manifest.version:
            return [f"{pack.domain_id}: {PackReader.MANIFEST_FILENAME} declares no version."]
        return []

    @staticmethod
    def get_missing_standards_errors(pack: KnowledgePack) -> list[str]:
        """
        Check that the pack's standards file yielded at least one standard.

        :param pack: The pack to check.
        :return: At most one error.
        """
        if pack.standards:
            return []
        return [f"{pack.domain_id}: no operating standards found in {PackReader.STANDARDS_FILENAME}."]

    @staticmethod
    def get_missing_variables_warnings(pack: KnowledgePack) -> list[str]:
        """
        Check that the pack's open variables file yielded at least one question.

        :param pack: The pack to check.
        :return: At most one warning.
        """
        if pack.open_variables:
            return []
        return [f"{pack.domain_id}: no open variables found in {PackReader.VARIABLES_FILENAME}."]

    @staticmethod
    def get_standard_errors(pack: KnowledgePack) -> list[str]:
        """
        Check the id pattern and each standard's id, text and role, then the bullets that never loaded and the
        roles the manifest assigns to ids the pack does not define.

        :param pack: The pack to check.
        :return: The errors, in that order.
        """
        domain: str = pack.domain_id
        id_pattern: str = pack.manifest.standard_id_pattern
        errors: list[str] = []
        try:
            id_re: re.Pattern = re.compile(f"^(?:{id_pattern})$")
        except re.error as exception:
            errors.append(f"{domain}: standard_id_pattern is not a valid regular expression: {exception}")
            id_re = re.compile(f"^(?:{PackManifest.DEFAULT_STANDARD_ID_PATTERN})$")

        seen: set[str] = set()
        for standard in pack.standards:
            if standard.standard_id in seen:
                errors.append(f"{domain}: duplicate standard id {standard.standard_id}.")
            seen.add(standard.standard_id)
            if not id_re.match(standard.standard_id):
                errors.append(
                    f"{domain}: standard id {standard.standard_id} does not match the pack's declared pattern "
                    f"{id_pattern!r}."
                )
            if not standard.text.strip():
                errors.append(f"{domain}: standard {standard.standard_id} has no text.")
            if standard.role is not None and standard.role not in PackValidator.VALID_ROLES:
                errors.append(
                    f"{domain}: standard {standard.standard_id} declares role {standard.role!r}; "
                    f"expected one of {', '.join(PackValidator.VALID_ROLES)}."
                )
        for unloaded in pack.unloaded_standards:
            errors.append(
                f"{domain}: {unloaded.get('standard_id')} reads as a standard but {unloaded.get('reason')}, "
                f"so it was NOT loaded."
            )
        # A role for an id the pack no longer defines usually means a renamed standard and a stale manifest.
        for standard_id in pack.manifest.roles:
            if standard_id not in seen:
                errors.append(
                    f"{domain}: {PackReader.MANIFEST_FILENAME} assigns a role to {standard_id}, "
                    f"which is not a standard in this pack."
                )
        return errors

    @staticmethod
    def get_variable_warnings(pack: KnowledgePack) -> list[str]:
        """
        Check that each open variable has a unique id, a question, examples and a why.

        :param pack: The pack to check.
        :return: The warnings, in document order.
        """
        warnings: list[str] = []
        seen: set[str] = set()
        for variable in pack.open_variables:
            if variable.variable_id in seen:
                warnings.append(f"{pack.domain_id}: duplicate open variable id {variable.variable_id}.")
            seen.add(variable.variable_id)
            fields: dict[str, str] = {
                "question": variable.question,
                "examples": variable.examples,
                "why": variable.why,
            }
            for label, value in fields.items():
                if not value.strip():
                    warnings.append(f"{pack.domain_id}: open variable {variable.variable_id} is missing its {label}.")
        return warnings
