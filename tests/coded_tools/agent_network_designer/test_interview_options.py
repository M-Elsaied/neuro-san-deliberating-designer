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

from coded_tools.agent_network_designer.interview_options import InterviewOptions


class TestInterviewOptions(TestCase):
    """
    Tests for InterviewOptions.
    """

    CAB: str = "ServiceNow CR approved by the CAB"
    DBA: str = "ServiceNow CR approved by the DBA lead"
    OPTIONS: tuple[str, ...] = (
        CAB,
        DBA,
        "Email approval",
        InterviewOptions.DESCRIBE_ESCAPE,
        InterviewOptions.UNSURE_ESCAPE,
    )

    def test_a_reply_means_the_options_it_says_less_than(self) -> None:
        """The live failure: naming what two options share chooses neither, whatever the spacing or case."""
        self.assertEqual([self.CAB, self.DBA], InterviewOptions.get_tied_options("servicenow cr", self.OPTIONS))
        self.assertEqual(["Email approval"], InterviewOptions.get_consistent_options("email", self.OPTIONS))
        self.assertEqual([], InterviewOptions.get_tied_options("email", self.OPTIONS))
        for reply in ("Email approval", "not sure", "", "  -  ", "a change freeze"):
            with self.subTest(reply=reply):
                self.assertEqual([], InterviewOptions.get_consistent_options(reply, self.OPTIONS))

    def test_escapes_and_numbered_options_are_recognized(self) -> None:
        """An escape quoted back is not an answer, and only a number opening a line offers an option."""
        for option in (InterviewOptions.DESCRIBE_ESCAPE, InterviewOptions.UNSURE_ESCAPE, "You decide", "I don't know"):
            with self.subTest(option=option):
                self.assertTrue(InterviewOptions.is_escape(option))
        self.assertFalse(InterviewOptions.is_escape("Email approval"))
        text: str = "Which window?\n  1. Saturday night\n2) Sunday\nWe patch 3 times a year.\n 10. Any\n"
        self.assertEqual(["Saturday night", "Sunday", "Any"], InterviewOptions.get_offered_options(text))

    def test_a_reply_names_option_numbers_only_when_little_else_is_there(self) -> None:
        """ "4 hours" was read as option 4 in a live interview, which chose the describe escape for the user."""
        for reply, expected in {
            "1": True,
            "1 or 4": True,
            "option 2": True,
            "#3": True,
            "maybe 3": True,
            "4 hours": False,
            "1.29 to 1.31": False,
            "no": False,
            "": False,
        }.items():
            with self.subTest(reply=reply):
                self.assertEqual(expected, InterviewOptions.names_only_numbers(reply))

    def test_a_position_or_an_escape_said_in_words_reads_as_its_number_would(self) -> None:
        """Each was recorded word for word as a requirement; an escape with anything more said is an answer."""
        self.assertEqual("the 2 one", InterviewOptions.spell_ordinals("The second one"))
        self.assertTrue(InterviewOptions.names_only_numbers(InterviewOptions.spell_ordinals("the first, please")))
        for reply, escape in {
            "I'm not sure": InterviewOptions.UNSURE_ESCAPE,
            "I don\u2019t know, you decide": InterviewOptions.UNSURE_ESCAPE,
            "Something else.": InterviewOptions.DESCRIBE_ESCAPE,
            "something else: our Ansible pipeline": "",
            "not sure, probably the DBA team": "",
            "sure": "",
        }.items():
            with self.subTest(reply=reply):
                self.assertEqual(escape, InterviewOptions.get_escape(reply))
