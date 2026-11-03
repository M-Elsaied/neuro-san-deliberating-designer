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

import json
from typing import Any
from unittest import IsolatedAsyncioTestCase

from coded_tools.agent_network_designer.interview_log import InterviewLog
from coded_tools.agent_network_designer.interview_state import InterviewState
from coded_tools.agent_network_designer.pack_reader import PackReader
from tests.coded_tools.agent_network_designer.interview_fixtures import InterviewFixtures
from tests.coded_tools.agent_network_designer.pack_fixtures import PackFixtures


class TestInterviewLog(IsolatedAsyncioTestCase):
    """
    Tests for InterviewLog.
    """

    def setUp(self) -> None:
        """Read the shipped packs, and give each test one session's sly_data."""
        PackFixtures.use_knowdocs_root(self, None)
        self.sly_data: dict[str, Any] = {}

    async def call(self, **args: Any) -> dict[str, Any] | str:
        """Call the tool as the designer does, against this test's session."""
        return await InterviewLog().async_invoke(args, self.sly_data)

    async def test_an_interview_is_held_across_calls(self) -> None:
        """Each call reads the state the last one wrote, which is the whole mechanism."""
        started: Any = await self.call(action="start", app_name="oracle_database_patching")
        self.assertEqual(
            ("start", "Q1", 7, True),
            (started.get("status"), started.get("label"), started.get("outstanding"), started.get("curated")),
        )
        self.assertTrue(started.get("prompt").startswith("Topology: single instance, RAC, Data Guard standby"))
        self.assertIn(InterviewState.SLY_DATA_KEY, self.sly_data)
        self.assertEqual(["Topology: two-node RAC"], (await self.call(action="answer", reply="2")).get("confirmed"))
        assumed: Any = await self.call(action="assume", default="All non-production first")
        self.assertEqual(["Estate and order: All non-production first"], assumed.get("assumed"))
        back: Any = await self.call(action="back", target="Q1")
        self.assertTrue(back.get("prompt").startswith("Here is what I have on file:"))
        logged: Any = await self.call(action="log")
        self.assertEqual(("log", back.get("log")), (logged.get("status"), logged.get("log")))
        self.assertEqual("ambiguous", (await self.call(action="answer", reply="RAC")).get("status"))

    async def test_every_domain_can_be_interviewed_and_one_with_no_pack_is_uncurated(self) -> None:
        """A domain-shaped assumption hides when every test names one domain, and derived questions are not curated."""
        for domain_id in PackReader.discover_domains():
            with self.subTest(domain_id=domain_id):
                self.sly_data = {}
                result: Any = await self.call(action="start", app_name=domain_id)
                while result.get("status") != "complete":
                    self.assertIn(result.get("status"), ("start", "recorded"))
                    result = await self.call(action="answer", reply="1")
                self.assertEqual(
                    (0, len(result.get("log"))), (result.get("outstanding"), len(result.get("confirmed")))
                )
        for questions in (InterviewFixtures.QUESTIONS, json.dumps(InterviewFixtures.QUESTIONS)):
            self.sly_data = {}
            self.assertFalse((await self.call(action="start", app_name="pizza", questions=questions)).get("curated"))
            self.assertFalse((await self.call(action="answer", reply="3")).get("curated"))

    async def test_misuse_comes_back_as_a_readable_error(self) -> None:
        """The model drives the tool by name, so each mistake names what to do instead."""
        cases: dict[str, dict[str, Any]] = {
            "Error: Unknown action 'skip'. Use one of: start, answer, back, assume, log.": {"action": "skip"},
            "Error: No domain given to interview from, and no questions to ask.": {"action": "start"},
            "Error: Could not load the knowledge pack for 'nowhere': No knowledge pack": {
                "action": "start",
                "app_name": "nowhere",
            },
            "Error: 'questions' was text but not valid JSON": {"action": "start", "questions": "[not json"},
            "Error: 'questions' must be a list of objects": {"action": "start", "questions": {"question": "q"}},
            "Error: question 1 has no question text": {"action": "start", "questions": [{"options": ["a", "b"]}]},
            "Error: the interview log carried no entries. The interview state was not carried": {
                "action": "answer",
                "reply": "1",
            },
        }
        for expected, args in cases.items():
            with self.subTest(expected=expected):
                self.assertTrue(str(await self.call(**args)).startswith(expected))
        await self.call(action="start", app_name="oracle_database_patching")
        self.assertTrue(
            str(await self.call(action="answer", reply="  ")).startswith("Error: No reply given to record.")
        )
        self.assertTrue(str(await self.call(action="assume")).startswith("Error: No default given to assume."))
