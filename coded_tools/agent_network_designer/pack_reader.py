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

import logging
import os
from pathlib import Path
from typing import Any

from pyhocon import ConfigFactory
from pyhocon.exceptions import ConfigException
from pyparsing.exceptions import ParseBaseException
from pypdf import PdfReader
from pypdf.errors import PyPdfError

from coded_tools.agent_network_designer.knowledge_pack import KnowledgePack
from coded_tools.agent_network_designer.pack_manifest import PackManifest
from coded_tools.agent_network_designer.pack_parser import PackParser

logger = logging.getLogger(__name__)


class PackReader:
    """
    Reads knowledge packs from the knowdocs root. A domain is any subdirectory holding a document, so adding a
    domain is a filesystem change with no code or prompt edit.
    """

    KNOWDOCS_ENV_VAR: str = "AGENT_NETWORK_DESIGNER_KNOWDOCS"
    # Relative to this module rather than the working directory, so the server can be started from anywhere.
    DEFAULT_KNOWDOCS_ROOT: Path = Path(__file__).resolve().parent / "knowdocs"
    MANIFEST_FILENAME: str = "pack.hocon"
    STANDARDS_FILENAME: str = "operating_standards.md"
    VARIABLES_FILENAME: str = "open_variables.md"
    DOCUMENT_SUFFIXES: tuple[str, ...] = (".md", ".txt", ".pdf")

    @staticmethod
    def get_knowdocs_root(root: str | os.PathLike | None = None) -> Path:
        """
        Resolve the directory knowledge packs are read from.

        :param root: An explicit root, which takes precedence over the environment.
        :return: The explicit root, else the one named by AGENT_NETWORK_DESIGNER_KNOWDOCS, else the knowdocs folder
            next to this module.
        """
        if root is not None:
            return Path(root).expanduser().resolve()
        from_environment: str | None = os.environ.get(PackReader.KNOWDOCS_ENV_VAR)
        if from_environment:
            return Path(from_environment).expanduser().resolve()
        return PackReader.DEFAULT_KNOWDOCS_ROOT

    @staticmethod
    def discover_domains(root: str | os.PathLike | None = None) -> list[str]:
        """
        List the domains under the knowdocs root.

        :param root: The knowdocs root, or None to resolve it as get_knowdocs_root() does.
        :return: The sorted ids of every non-hidden directory under the root that holds at least one document.
        """
        resolved: Path = PackReader.get_knowdocs_root(root)
        if not resolved.is_dir():
            return []
        domains: list[str] = []
        for candidate in sorted(resolved.iterdir()):
            if candidate.is_dir() and not candidate.name.startswith(".") and PackReader.has_documents(candidate):
                domains.append(candidate.name)
        return domains

    @staticmethod
    def describe_domains(root: str | os.PathLike | None = None) -> str:
        """
        Name the available domains for an error message the designer can act on.

        :param root: The knowdocs root, or None to resolve it as get_knowdocs_root() does.
        :return: The domain ids, comma separated, or "none".
        """
        return ", ".join(PackReader.discover_domains(root)) or "none"

    @staticmethod
    def has_documents(directory: Path) -> bool:
        """
        Check whether a directory holds any knowledge document.

        :param directory: A candidate pack directory.
        :return: True if any file under it has a document suffix.
        """
        for path in directory.rglob("*"):
            if path.is_file() and path.suffix.lower() in PackReader.DOCUMENT_SUFFIXES:
                return True
        return False

    @staticmethod
    def load_pack(domain_id: str, root: str | os.PathLike | None = None) -> KnowledgePack:
        """
        Read and parse one knowledge pack.

        :param domain_id: The domain id, which is the pack's directory name.
        :param root: The knowdocs root, or None to resolve it as get_knowdocs_root() does.
        :return: The loaded pack.
        :raises FileNotFoundError: If there is no pack directory for the domain, or the id is not a plain
            directory name.
        :raises ValueError: If the pack's pack.hocon cannot be parsed.
        """
        resolved: Path = PackReader.get_knowdocs_root(root)
        directory: Path = resolved / domain_id
        # The id comes from the model, so a path such as "../.." must not read documents from outside the root.
        if not domain_id or Path(domain_id).name != domain_id or domain_id == ".." or not directory.is_dir():
            raise FileNotFoundError(f"""No knowledge pack for domain "{domain_id}" under {resolved}""")

        manifest: PackManifest = PackReader.read_manifest(directory, domain_id)
        documents: dict[str, str] = PackReader.read_documents(directory)
        standards_text: str = documents.get(PackReader.STANDARDS_FILENAME, "")
        return KnowledgePack(
            manifest=manifest,
            standards=PackParser.parse_standards(standards_text, manifest.standard_id_pattern, manifest.roles),
            open_variables=PackParser.parse_open_variables(documents.get(PackReader.VARIABLES_FILENAME, "")),
            documents=documents,
            unloaded_standards=PackParser.find_unloaded_standards(standards_text, manifest.standard_id_pattern),
            unaccounted_lines=PackParser.find_unaccounted_lines(standards_text),
        )

    @staticmethod
    def load_catalog(root: str | os.PathLike | None = None) -> list[KnowledgePack]:
        """
        Read every knowledge pack under the root.

        :param root: The knowdocs root, or None to resolve it as get_knowdocs_root() does.
        :return: Every discoverable pack, in domain id order. A pack that cannot be read or whose pack.hocon cannot be
            parsed is logged and skipped, so one bad pack does not hide the others.
        """
        packs: list[KnowledgePack] = []
        for domain_id in PackReader.discover_domains(root):
            try:
                packs.append(PackReader.load_pack(domain_id, root))
            except (OSError, ValueError) as exception:
                logger.warning("Skipping knowledge pack %s, which could not be read: %s", domain_id, exception)
        return packs

    @staticmethod
    def read_manifest(directory: Path, domain_id: str) -> PackManifest:
        """
        Read a pack's pack.hocon. A pack without one gets a manifest inferred from its directory name, which
        PackValidator reports as a warning. A pack is always addressed by its directory name, so a different
        declared domain_id is logged and ignored, or ListDomains would advertise an id that cannot be loaded.

        :param directory: The pack directory.
        :param domain_id: The domain id, from the directory name.
        :return: The manifest.
        :raises ValueError: If pack.hocon cannot be parsed, or its roles are not a mapping.
        """
        title: str = domain_id.replace("_", " ")
        manifest_path: Path = directory / PackReader.MANIFEST_FILENAME
        if not manifest_path.is_file():
            return PackManifest(domain_id=domain_id, title=title, synthesized=True)

        try:
            config: Any = ConfigFactory.parse_file(str(manifest_path))
            raw_roles: dict[Any, Any] = dict(config.get("roles", {}) or {})
        except (ConfigException, ParseBaseException, TypeError, ValueError) as exception:
            raise ValueError(
                f"Could not parse {manifest_path}: {PackReader.describe_parse_error(exception)}"
            ) from exception
        roles: dict[str, str] = {}
        for standard_id, role in raw_roles.items():
            roles[str(standard_id)] = str(role).strip().lower()
        declared_id: str = PackReader.get_text(config, "domain_id", domain_id)
        if declared_id and declared_id != domain_id:
            logger.warning(
                "%s declares domain_id %r, but packs are addressed by directory name, so it loads as %r",
                manifest_path,
                declared_id,
                domain_id,
            )
        return PackManifest(
            domain_id=domain_id,
            title=PackReader.get_text(config, "title", title),
            summary=PackReader.get_text(config, "summary"),
            version=PackReader.get_text(config, "version"),
            owner=PackReader.get_text(config, "owner"),
            approved_by=PackReader.get_text(config, "approved_by"),
            effective_date=PackReader.get_text(config, "effective_date"),
            source=PackReader.get_text(config, "source"),
            standard_id_pattern=PackReader.get_text(
                config, "standard_id_pattern", PackManifest.DEFAULT_STANDARD_ID_PATTERN
            )
            or PackManifest.DEFAULT_STANDARD_ID_PATTERN,
            roles=roles,
        )

    @staticmethod
    def read_documents(directory: Path) -> dict[str, str]:
        """
        Read every document in a pack directory whole and verbatim, since standards must reach the generated
        agents word for word.

        :param directory: The pack directory.
        :return: Path relative to the directory, mapped to the document's full text.
        """
        documents: dict[str, str] = {}
        for path in sorted(directory.rglob("*")):
            suffix: str = path.suffix.lower()
            if not path.is_file() or suffix not in PackReader.DOCUMENT_SUFFIXES:
                continue
            relative: str = str(path.relative_to(directory))
            if suffix == ".pdf":
                documents[relative] = PackReader.read_pdf(path)
            else:
                documents[relative] = path.read_text(encoding="utf-8", errors="replace")
        return documents

    @staticmethod
    def read_pdf(path: Path) -> str:
        """
        Extract a PDF's text.

        :param path: The PDF path.
        :return: The PDF's text with a marker before each page, or an "ERROR:" line the designer can see if it
            cannot be read.
        """
        try:
            chunks: list[str] = []
            for page_number, page in enumerate(PdfReader(str(path)).pages, start=1):
                chunks.append(f"\n\n--- Page {page_number} ---\n\n")
                chunks.append(page.extract_text() or "")
            return "".join(chunks)
        except (PyPdfError, OSError) as exception:
            logger.warning("Could not read PDF %s: %s", path, exception)
            return f"ERROR: Error reading PDF {path}: {exception}"

    @staticmethod
    def describe_parse_error(exception: Exception) -> str:
        """
        Say why a HOCON file did not parse. A syntax error is given by its position, since its own message spells
        out the parser's whole grammar.

        :param exception: What parsing raised.
        :return: The line and column of a syntax error, otherwise the exception's own message.
        """
        if isinstance(exception, ParseBaseException):
            return f"syntax error at line {exception.lineno}, column {exception.col}"
        return str(exception)

    @staticmethod
    def get_text(config: Any, key: str, default: str = "") -> str:
        """
        Read one pack.hocon value as text.

        :param config: The parsed pack.hocon.
        :param key: The key to read.
        :param default: The value when the key is absent.
        :return: The value as a string, or "" when it is null.
        """
        value: Any = config.get(key, default)
        return "" if value is None else str(value)
