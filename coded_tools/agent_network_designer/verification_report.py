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

from coded_tools.agent_network_designer.verification_result import VerificationResult


class VerificationReport:
    """
    Renders a VerificationResult as the markdown coverage table the designer prints verbatim.
    """

    @staticmethod
    def get_problems(result: VerificationResult) -> list[str]:
        """
        List a verification's failures.

        :param result: The verification result.
        :return: Every failure as one line, prefixed with the check that found it.
        """
        problems: list[str] = []
        for error in result.pack_errors:
            problems.append(f"PACK: {error}")
        for standard_id in result.missing:
            problems.append(f"COVERAGE: {standard_id} is not embedded in any agent.")
        for standard_id in result.ambiguous:
            owners: str = ", ".join(sorted(set(result.owners.get(standard_id, []))))
            problems.append(
                f"COVERAGE: {standard_id} is embedded in more than one agent ({owners}); ownership is ambiguous."
            )
        for embedded in result.unknown:
            problems.append(
                f"PROVENANCE: agent '{embedded.agent_name}' carries id {embedded.standard_id}, "
                f"which is not a standard in this pack."
            )
        for infidelity in result.infidelities:
            problems.append(
                f"FIDELITY: {infidelity.get('standard_id')} in agent '{infidelity.get('agent_name')}' "
                f"does not match the pack text. {infidelity.get('detail')}"
            )
        for structural in result.structural:
            problems.append(f"STRUCTURE: {structural}")
        return problems

    @staticmethod
    def render(result: VerificationResult) -> str:
        """
        Render a verification as the markdown coverage report.

        :param result: The verification result.
        :return: A markdown table of every standard's role, owner and fidelity, followed by any problems.
        """
        lines: list[str] = ["## Standards coverage (verified)", ""]
        if result.provenance:
            lines.extend([f"_Pack: {result.provenance}_", ""])
        lines.extend(["| Standard | Role | Owned by | Fidelity |", "|---|---|---|---|"])

        altered: set[str] = set()
        for infidelity in result.infidelities:
            altered.add(infidelity.get("standard_id", ""))
        for standard_id in sorted(set(result.roles) | set(result.owners)):
            owners: list[str] = sorted(set(result.owners.get(standard_id, [])))
            owner_cell: str = "**not embedded**"
            fidelity_cell: str = "-"
            if owners:
                owner_cell = "`" + "`, `".join(owners) + "`"
                if len(owners) > 1:
                    owner_cell += " **(ambiguous)**"
                fidelity_cell = "**altered**" if standard_id in altered else "verbatim"
            role: str = result.roles.get(standard_id, "-")
            lines.append(f"| **{standard_id}** | {role} | {owner_cell} | {fidelity_cell} |")

        lines.append("")
        if result.ok:
            lines.append("Every standard is embedded exactly once, verbatim, with a valid id.")
        else:
            lines.extend(["**This network did not verify clean:**", ""])
            for problem in VerificationReport.get_problems(result):
                lines.append(f"- {problem}")
        if result.pack_warnings:
            lines.extend(["", "**Pack warnings** (under-specified, but the standards are intact):", ""])
            for warning in result.pack_warnings:
                lines.append(f"- {warning}")
        return "\n".join(lines)
