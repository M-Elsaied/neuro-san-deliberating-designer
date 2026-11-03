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
from typing import Any
from unittest import TestCase
from unittest import mock

from coded_tools.agent_network_designer.interview_log import InterviewLog
from coded_tools.agent_network_designer.interview_options import InterviewOptions
from coded_tools.agent_network_designer.model_reply_matcher import ModelReplyMatcher


class TestModelReplyMatcher(TestCase):
    """
    Tests for ModelReplyMatcher.
    """

    OPTIONS: tuple[str, ...] = (
        "DBA team",
        "Platform team",
        InterviewOptions.DESCRIBE_ESCAPE,
        InterviewOptions.UNSURE_ESCAPE,
    )

    def test_only_real_options_cross_the_boundary_and_a_failure_falls_back(self) -> None:
        """An invented, out-of-range or repeated number names nothing, and a failing model degrades to containment."""
        cases: dict[str, tuple[list[int], list[str]]] = {
            "out of range": ([1, 99, -3, 0], ["DBA team"]),
            "repeated": ([2, 2, 2], ["Platform team"]),
            "several": ([2, 1], ["Platform team", "DBA team"]),
            "an escape": ([3], []),
        }
        for case, (answer, expected) in cases.items():
            with self.subTest(case=case), mock.patch.object(ModelReplyMatcher, "ask", return_value=answer):
                self.assertEqual(expected, ModelReplyMatcher("a-model").match("the second one", self.OPTIONS))
        with mock.patch.object(ModelReplyMatcher, "ask", side_effect=RuntimeError("down")), self.assertLogs() as logs:
            self.assertEqual(["DBA team"], ModelReplyMatcher("a-model").match("DBA", self.OPTIONS))
        self.assertIn("Match model a-model unavailable (down); falling back to containment", logs.output[0])
        self.assertEqual([], ModelReplyMatcher("a-model").match("  ", self.OPTIONS))

    def test_the_model_is_asked_which_options_the_reply_could_mean(self) -> None:
        """The request lists only the real options, and the numbers are read back whatever their type."""
        response: Any = mock.MagicMock()
        response.choices[0].message.content = """{"options": [1, "2", 2.5, "x", 123]}"""
        with mock.patch("coded_tools.agent_network_designer.model_reply_matcher.OpenAI") as client:
            client.return_value.chat.completions.create.return_value = response
            self.assertEqual([1, 2], ModelReplyMatcher("a-model").ask("either", ["DBA team", "Platform team"]))
        request: dict[str, Any] = client.return_value.chat.completions.create.call_args.kwargs
        self.assertEqual("a-model", request.get("model"))
        self.assertEqual(0, client.call_args.kwargs.get("max_retries"))
        self.assertEqual(
            "Options:\n1. DBA team\n2. Platform team\n\nReply: either", request.get("messages")[1]["content"]
        )

    def test_no_model_is_used_unless_one_is_named(self) -> None:
        """The default needs no key, provider or network, so the unit suite and CI never depend on one."""
        for value in ("", "off", "None", "false"):
            with self.subTest(value=value), mock.patch.dict(os.environ, {ModelReplyMatcher.MATCH_MODEL_ENV: value}):
                self.assertIsNone(InterviewLog().matcher)
        with mock.patch.dict(os.environ, {ModelReplyMatcher.MATCH_MODEL_ENV: "some-model"}):
            self.assertEqual("some-model", ModelReplyMatcher.from_environment().model)
