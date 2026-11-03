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

from unittest import TestCase

from coded_tools.agent_network_designer.open_variable import OpenVariable
from coded_tools.agent_network_designer.pack_parser import PackParser
from coded_tools.agent_network_designer.standard import Standard


class TestPackParser(TestCase):
    """
    Tests for PackParser.
    """

    def test_a_wrapped_standard_is_joined_into_one_rule(self) -> None:
        """
        A continuation line belongs to the standard above it, or fidelity would be checked against half a rule.
        """
        text: str = "- ODB-02: Keep OPatch at the minimum version\n  the RU README requires.\n"
        expected: Standard = Standard("ODB-02", "Keep OPatch at the minimum version the RU README requires.")
        self.assertEqual([expected], PackParser.parse_standards(text, r"ODB-\d{2}", {}))

    def test_headings_and_prose_are_not_standards(self) -> None:
        """
        A pack author can explain the pack, including with "Label: value" prose, without adding rules.
        """
        text: str = "# Standards\n\nNote: illustrative.\n\nScope: the whole estate.\n\n- ODB-01: Apply the RU.\n"
        expected: Standard = Standard("ODB-01", "Apply the RU.", "precondition")
        self.assertEqual([expected], PackParser.parse_standards(text, r"ODB-\d{2}", {"ODB-01": "precondition"}))
        self.assertEqual([], PackParser.find_unloaded_standards(text, r"ODB-\d{2}"))

    def test_dotted_ids_are_standards(self) -> None:
        """
        An organization's own numbering, such as SOP-4.2.1, works through the declared pattern.
        """
        text: str = "- SOP-4.2.1: Obtain written approval.\n- SOP-4.2.10: Record the outcome.\n"
        expected: list[Standard] = [
            Standard("SOP-4.2.1", "Obtain written approval."),
            Standard("SOP-4.2.10", "Record the outcome."),
        ]
        self.assertEqual(expected, PackParser.parse_standards(text, "SOP-[0-9.]+", {}))

    def test_a_dropped_standard_is_reported_as_unloaded(self) -> None:
        """
        A bullet outside the declared pattern, or with no text, is not loaded, and each one is recorded in order.
        """
        text: str = "- ABC-01: Fine.\n- XYZ-99: Wrongly numbered.\n- ABC-03:\n- XYZ-99: Again.\n"
        self.assertEqual([Standard("ABC-01", "Fine.")], PackParser.parse_standards(text, r"ABC-\d{2}"))
        expected: list[dict[str, str]] = [
            {"standard_id": "XYZ-99", "reason": PackParser.UNLOADED_OFF_PATTERN},
            {"standard_id": "ABC-03", "reason": PackParser.UNLOADED_NO_TEXT},
            {"standard_id": "XYZ-99", "reason": PackParser.UNLOADED_OFF_PATTERN},
        ]
        self.assertEqual(expected, PackParser.find_unloaded_standards(text, r"ABC-\d{2}"))

    def test_an_invalid_id_pattern_falls_back_to_the_default(self) -> None:
        """
        A typo in the pattern is reported by PackValidator; parsing still loads the standards.
        """
        self.assertEqual(
            [Standard("ABC-01", "A rule.")], PackParser.parse_standards("- ABC-01: A rule.\n", "A-[0", {})
        )

    def test_open_variable_fields_are_parsed(self) -> None:
        """
        Each field is parsed on its own, and a bullet with no fields is not a variable.
        """
        text: str = (
            "- V1 | Topology: single instance or RAC?\n"
            "  | examples: single instance; two-node RAC\n"
            "  | why: decides rolling versus a full outage.\n"
            "- not a variable\n"
        )
        expected: OpenVariable = OpenVariable(
            "V1",
            "Topology: single instance or RAC?",
            "single instance; two-node RAC",
            "decides rolling versus a full outage.",
        )
        self.assertEqual([expected], PackParser.parse_open_variables(text))

    def test_an_empty_field_does_not_pad_the_question(self) -> None:
        """
        An empty field between pipes is kept, but the question is trimmed at both ends.
        """
        variables: list[OpenVariable] = PackParser.parse_open_variables("- V1 | | Question\n- V2 | Q |\n")
        self.assertEqual("| Question", variables[0].question)
        self.assertEqual("Q |", variables[1].question)
