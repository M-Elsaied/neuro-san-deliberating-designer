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

from coded_tools.agent_network_designer.open_variable import OpenVariable
from coded_tools.agent_network_designer.pack_manifest import PackManifest
from coded_tools.agent_network_designer.standard import Standard


class PackParser:
    """
    Parses the markdown documents of a knowledge pack. Only bullets are parsed, so headings and prose between
    them stay commentary for the reader.
    """

    # Reasons a bullet that reads as a standard was not loaded. Each completes "<id> reads as a standard but ...".
    UNLOADED_OFF_PATTERN: str = "its id falls outside the pack's declared standard_id_pattern"
    UNLOADED_NO_TEXT: str = "it has no text after the id"

    BULLET_RE: re.Pattern = re.compile(r"^\s*[-*]\s+")

    @staticmethod
    def parse_standards(text: str, id_pattern: str, roles: dict[str, str] | None = None) -> list[Standard]:
        """
        Parse "- <id>: <text>" bullets into standards.

        :param text: The operating_standards.md text.
        :param id_pattern: The pack's declared standard id pattern.
        :param roles: Standard id to temporal role, from the manifest, or None when no standard has a role.
        :return: The standards, in document order.
        """
        roles = roles or {}
        # Named groups, so that groups inside the pack's own pattern do not shift which group holds the text.
        matcher: re.Pattern = PackParser.compile_with_fallback(
            r"^(?P<standard_id>{})\s*[:.]\s*(?P<standard_text>.+)$", id_pattern
        )
        standards: list[Standard] = []
        for bullet in PackParser.get_bullets(text):
            match: re.Match | None = matcher.match(bullet.strip())
            if match is not None:
                standard_id: str = match.group("standard_id").strip()
                standard_text: str = match.group("standard_text").strip()
                standards.append(Standard(standard_id, standard_text, roles.get(standard_id)))
        return standards

    @staticmethod
    def find_unloaded_standards(text: str, id_pattern: str) -> list[dict[str, str]]:
        """
        Find bullets that read as a standard but that parse_standards() drops, so a rule cannot vanish silently.
        Only ids shaped like PREFIX-number count, so prose such as "Note: ..." is not mistaken for a standard.

        :param text: The operating_standards.md text.
        :param id_pattern: The pack's declared standard id pattern.
        :return: One entry per dropped bullet, in document order, with "standard_id" and "reason" keys.
        """
        candidate_re: re.Pattern = re.compile(
            rf"^({PackManifest.DEFAULT_STANDARD_ID_PATTERN})\s*[:.]\s*(.*)$", re.DOTALL
        )
        declared_re: re.Pattern = PackParser.compile_with_fallback("^(?:{})$", id_pattern)
        unloaded: list[dict[str, str]] = []
        for bullet in PackParser.get_bullets(text):
            match: re.Match | None = candidate_re.match(bullet.strip())
            if match is None:
                continue
            candidate_id: str = match.group(1).strip()
            if not declared_re.match(candidate_id):
                unloaded.append({"standard_id": candidate_id, "reason": PackParser.UNLOADED_OFF_PATTERN})
            elif not match.group(2).strip():
                unloaded.append({"standard_id": candidate_id, "reason": PackParser.UNLOADED_NO_TEXT})
        return unloaded

    @staticmethod
    def parse_open_variables(text: str) -> list[OpenVariable]:
        """
        Parse "- <id> | <question> | examples: <examples> | why: <why>" bullets into open variables.

        :param text: The open_variables.md text.
        :return: The open variables, in document order.
        """
        variables: list[OpenVariable] = []
        for bullet in PackParser.get_bullets(text):
            parts: list[str] = bullet.split("|")
            variable_id: str = parts[0].strip()
            if len(parts) < 2 or not variable_id:
                continue
            question_parts: list[str] = []
            examples: str = ""
            why: str = ""
            # Fields other than examples and why belong to the question, which may itself contain a pipe.
            for raw_part in parts[1:]:
                part: str = raw_part.strip()
                lowered: str = part.lower()
                if lowered.startswith("examples:"):
                    examples = part.partition(":")[2].strip()
                elif lowered.startswith("why:"):
                    why = part.partition(":")[2].strip()
                else:
                    question_parts.append(part)
            variables.append(OpenVariable(variable_id, " | ".join(question_parts).strip(), examples, why))
        return variables

    @staticmethod
    def get_bullets(text: str) -> list[str]:
        """
        Collect each markdown bullet as one line, joining wrapped continuation lines onto it.

        :param text: The markdown text.
        :return: The bullets, in document order.
        """
        bullets: list[str] = []
        current: str | None = None
        for line in text.splitlines():
            stripped: str = line.strip()
            starts_bullet: bool = PackParser.BULLET_RE.match(line) is not None
            # A blank line, heading or quote ends the current bullet, and so does the start of the next one.
            if current is not None and (starts_bullet or not stripped or stripped.startswith(("#", ">"))):
                bullets.append(current)
                current = None
            if starts_bullet:
                current = PackParser.BULLET_RE.sub("", line).strip()
            elif current is not None:
                current = f"{current} {stripped}"
        if current is not None:
            bullets.append(current)
        return bullets

    @staticmethod
    def compile_with_fallback(template: str, id_pattern: str) -> re.Pattern:
        """
        Compile a regular expression around a pack's id pattern. PackValidator reports an invalid pattern, so
        parsing carries on with the default one rather than failing the load.

        :param template: The expression, with {} where the id pattern goes.
        :param id_pattern: The pack's declared standard id pattern.
        :return: The compiled expression.
        """
        try:
            return re.compile(template.format(id_pattern), re.DOTALL)
        except re.error:
            return re.compile(template.format(PackManifest.DEFAULT_STANDARD_ID_PATTERN), re.DOTALL)
