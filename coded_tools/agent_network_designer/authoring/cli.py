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
The pack author's command line.

Authoring a pack was documented as a content task - "no Python required" - while the only way to
check one was a Python snippet in the docs, and the only shipped command needed an already-built
agent network, so it could not check a pack at all. That left "copy an existing pack for the shape"
as the entire quality gate for the extension point this design exists to provide.

    validate    does this pack load, and if not, what exactly is wrong with it

Nothing here needs a language model, an API key or a running server.
"""

import argparse
import sys

from coded_tools.agent_network_designer.authoring.report import render_pack_report
from coded_tools.agent_network_designer.authoring.report import render_summary
from coded_tools.agent_network_designer.knowledge_pack import KnowledgePack
from coded_tools.agent_network_designer.knowledge_pack import knowdocs_root
from coded_tools.agent_network_designer.pack_catalogue import discover_domains
from coded_tools.agent_network_designer.pack_catalogue import load_catalogue
from coded_tools.agent_network_designer.pack_catalogue import load_pack

EXIT_OK: int = 0
EXIT_PROBLEM: int = 1
EXIT_USAGE: int = 2


def build_parser() -> argparse.ArgumentParser:
    """
    :return: The argument parser for the authoring commands.
    """
    parser = argparse.ArgumentParser(
        prog="python -m coded_tools.agent_network_designer.authoring",
        description="Author and check curated knowledge packs.",
    )
    subcommands = parser.add_subparsers(dest="command", required=True)

    validate = subcommands.add_parser(
        "validate",
        help="check that a pack loads, and report exactly what is wrong if it does not",
    )
    target = validate.add_mutually_exclusive_group(required=True)
    target.add_argument("--domain", help="the pack to check, i.e. its directory name")
    target.add_argument("--all", action="store_true", help="check every pack under the knowdocs root")
    validate.add_argument("--knowdocs", default=None, help="override the knowdocs root")
    validate.add_argument(
        "--strict",
        action="store_true",
        help="treat warnings as failures, for a deployment that requires complete provenance",
    )
    return parser


def validate_command(arguments: argparse.Namespace) -> int:
    """
    Check one pack or all of them, and report in plain language.

    :param arguments: The parsed arguments.
    :return: An exit code: 0 usable, 1 at least one pack unusable, 2 a usage problem.
    """
    root: str | None = arguments.knowdocs
    if arguments.all:
        packs: list[KnowledgePack] = load_catalogue(root)
        if not packs:
            print(f"No knowledge packs found under {knowdocs_root(root)}", file=sys.stderr)
            return EXIT_USAGE
        print(f"Checking {len(packs)} packs in {knowdocs_root(root)}\n")
        print(render_summary(packs))
    else:
        try:
            packs = [load_pack(arguments.domain, root)]
        except (FileNotFoundError, OSError) as exception:
            available: str = ", ".join(discover_domains(root)) or "none"
            print(f"{exception}\nAvailable packs: {available}", file=sys.stderr)
            return EXIT_USAGE
        print(f"Checking {arguments.domain} in {knowdocs_root(root)}\n")

    reports: list[str] = [render_pack_report(pack, show_clean=not arguments.all) for pack in packs]
    for report in [text for text in reports if text]:
        print(f"\n{report}")

    unusable: list[KnowledgePack] = [pack for pack in packs if pack.validate_errors()]
    warned: list[KnowledgePack] = [pack for pack in packs if pack.validate_warnings()]

    print()
    if unusable:
        print(f"{len(unusable)} of {len(packs)} packs cannot be used yet.")
        return EXIT_PROBLEM
    if arguments.strict and warned:
        print(f"{len(warned)} of {len(packs)} packs are incomplete, and --strict was given.")
        return EXIT_PROBLEM
    if warned:
        print(f"All {len(packs)} packs are usable. {len(warned)} could be more complete (marked OK*).")
        return EXIT_OK
    print(f"All {len(packs)} packs are usable.")
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    """
    Command line entry point.

    :param argv: Argument vector, or None to read sys.argv.
    :return: The exit code.
    """
    arguments: argparse.Namespace = build_parser().parse_args(argv)
    if arguments.command == "validate":
        return validate_command(arguments)
    return EXIT_USAGE
