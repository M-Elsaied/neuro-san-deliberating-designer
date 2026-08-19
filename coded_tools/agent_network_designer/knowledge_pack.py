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
Knowledge packs - the domain layer (L2) of the deliberating agent network designer.

A pack is a directory of curated knowledge for one domain:

    <knowdocs root>/<domain_id>/
        pack.hocon              manifest: identity, provenance, id pattern, standard roles
        operating_standards.md  the non-negotiables, each carrying a stable id
        open_variables.md       the interview script

The designer's method layer (L1) holds no domain facts; everything domain-specific lives here.
This module is what makes that boundary real rather than aspirational:

  * domains are DISCOVERED by scanning the root, not listed in Python, so adding one is
    "drop a folder in" and needs no fork;
  * the root is configurable, so a deployment can point at its own knowledge store;
  * a pack declares its OWN standard id pattern, so ids are not assumed to look like ours;
  * a pack can be VALIDATED, so a malformed pack fails loudly at load instead of producing a
    confident, subtly wrong agent network several minutes later.

Packs written before this module existed remain loadable: a missing pack.hocon is synthesised
from the directory name and reported as a validation warning rather than an error.
"""

import os
import re
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path
from typing import Any
from typing import Iterator

from pyhocon import ConfigFactory
from pypdf import PdfReader
from pypdf.errors import PyPdfError

# Environment variable pointing at an alternative knowdocs root. Set this to serve packs from
# outside the repository - a mounted volume, a synced knowledge store, anywhere on disk.
KNOWDOCS_ENV_VAR: str = "AGENT_NETWORK_DESIGNER_KNOWDOCS"

# Default root, resolved relative to THIS module rather than the process working directory,
# so the designer works when installed as a package or run from any directory.
DEFAULT_KNOWDOCS_ROOT: Path = Path(__file__).resolve().parent / "knowdocs"

MANIFEST_FILENAME: str = "pack.hocon"
STANDARDS_FILENAME: str = "operating_standards.md"
VARIABLES_FILENAME: str = "open_variables.md"

# Used only when a pack does not declare its own. Deliberately permissive: any uppercase
# prefix followed by a number, which covers ODB-01, K8S-01, SOP-4.2 and CTRL-0093 alike.
DEFAULT_STANDARD_ID_PATTERN: str = r"[A-Z][A-Z0-9]*-[0-9.]+"

# Temporal role determines topology: a precondition becomes a gate agent upstream of the work,
# a postcondition becomes a validator downstream of it. Declaring the role in the manifest
# takes that judgement away from the language model and makes it checkable.
VALID_ROLES: tuple[str, ...] = ("precondition", "work", "postcondition")

_DOCUMENT_SUFFIXES: tuple[str, ...] = (".md", ".txt", ".pdf")
_BULLET_RE: re.Pattern = re.compile(r"^\s*[-*]\s+")


# --------------------------------------------------------------------------------------
# Text normalisation
# --------------------------------------------------------------------------------------


def normalise(text: str) -> str:
    """
    Collapse a standard's text to a canonical form for comparison.

    Standards wrap across several lines in their markdown source and are emitted on a single
    line inside a generated agent's instructions, so a byte-for-byte comparison would fail on
    every standard regardless of fidelity. Typographic substitutions (curly quotes, en dashes,
    non-breaking spaces) are also folded, because a model swapping a hyphen for an en dash has
    not altered the meaning of the rule and should not be reported as if it had.

    Anything beyond whitespace and typography - a changed word, a dropped clause, altered
    punctuation - survives normalisation and is reported as a fidelity failure.

    :param text: The raw text to normalise.
    :return: The normalised text.
    """
    if not text:
        return ""
    replacements: dict[str, str] = {
        " ": " ",  # non-breaking space
        "‘": "'",
        "’": "'",  # curly single quotes
        "“": '"',
        "”": '"',  # curly double quotes
        "–": "-",
        "—": "-",  # en / em dash
    }
    for original, replacement in replacements.items():
        text = text.replace(original, replacement)
    return re.sub(r"\s+", " ", text).strip()


def _iter_bullets(text: str) -> Iterator[str]:
    """
    Yield each markdown bullet as one logical line, re-joining wrapped continuations.

    Headings, block quotes and free prose between bullets are skipped, which is what allows a
    pack author to put an explanatory preamble at the top of a document without it being parsed
    as a standard.

    :param text: The markdown document text.
    :return: An iterator over the joined bullet strings.
    """
    current: str | None = None
    for raw_line in text.splitlines():
        stripped: str = raw_line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith(">"):
            if current is not None:
                yield current
                current = None
            continue
        if _BULLET_RE.match(raw_line):
            if current is not None:
                yield current
            current = _BULLET_RE.sub("", raw_line).strip()
        elif current is not None:
            # An indented continuation of the bullet above.
            current = f"{current} {stripped}"
    if current is not None:
        yield current


# --------------------------------------------------------------------------------------
# Pack contents
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Standard:
    """One operating standard: an invariant rule carrying a stable id."""

    standard_id: str
    text: str
    role: str | None = None

    @property
    def normalised_text(self) -> str:
        """:return: The standard's text in canonical comparison form."""
        return normalise(self.text)


@dataclass(frozen=True)
class OpenVariable:
    """One open variable: a question the requester, and only the requester, can answer."""

    variable_id: str
    question: str
    examples: str = ""
    why: str = ""


@dataclass(frozen=True)
class PackManifest:  # pylint: disable=too-many-instance-attributes
    """
    Identity and provenance for a pack.

    The provenance fields exist so a generated agent network can state which version of which
    pack it was built from, and who stands behind it. A network of unknown ancestry is hard to
    defend in an audit; one that names its source, version and approver is not.
    """

    domain_id: str
    title: str = ""
    summary: str = ""
    version: str = ""
    owner: str = ""
    approved_by: str = ""
    effective_date: str = ""
    source: str = ""
    standard_id_pattern: str = DEFAULT_STANDARD_ID_PATTERN
    roles: dict[str, str] = field(default_factory=dict)
    synthesised: bool = False

    def provenance(self) -> str:
        """
        :return: A single human-readable provenance line, safe to embed in a generated network.
        """
        parts: list[str] = [self.title or self.domain_id]
        if self.version:
            parts.append(f"v{self.version}")
        if self.owner:
            parts.append(f"owned by {self.owner}")
        if self.approved_by:
            parts.append(f"approved by {self.approved_by}")
        if self.effective_date:
            parts.append(f"effective {self.effective_date}")
        return ", ".join(parts)


@dataclass(frozen=True)
class KnowledgePack:
    """A loaded pack: its manifest, its parsed contents, and its raw documents."""

    manifest: PackManifest
    standards: list[Standard] = field(default_factory=list)
    open_variables: list[OpenVariable] = field(default_factory=list)
    documents: dict[str, str] = field(default_factory=dict)
    # Ids that look like a standard but that the pack's declared pattern rejected, so they were
    # never loaded. Kept so validate() can report them rather than let a rule vanish in silence.
    unmatched_standard_ids: list[str] = field(default_factory=list)

    @property
    def domain_id(self) -> str:
        """:return: The pack's domain identifier."""
        return self.manifest.domain_id

    def standard(self, standard_id: str) -> Standard | None:
        """
        :param standard_id: The id to look up.
        :return: The matching standard, or None if this pack does not define it.
        """
        for candidate in self.standards:
            if candidate.standard_id == standard_id:
                return candidate
        return None

    def validate(self) -> list[str]:
        """
        Check the pack is well formed.

        Returned problems are advisory: the caller decides whether a malformed pack is fatal.
        Every message names the pack and the offending item so it is actionable without opening
        the files.

        :return: A list of human-readable problems. Empty means the pack is well formed.
        """
        problems: list[str] = []
        domain: str = self.manifest.domain_id

        if self.manifest.synthesised:
            problems.append(
                f"{domain}: no {MANIFEST_FILENAME} found - identity and provenance were inferred "
                f"from the directory name. Add one to record version, owner and approval."
            )
        elif not self.manifest.version:
            problems.append(f"{domain}: {MANIFEST_FILENAME} declares no version.")

        if not self.standards:
            problems.append(f"{domain}: no operating standards found in {STANDARDS_FILENAME}.")
        if not self.open_variables:
            problems.append(f"{domain}: no open variables found in {VARIABLES_FILENAME}.")

        problems.extend(self._standard_problems())
        problems.extend(self._open_variable_problems())
        return problems

    def _standard_problems(self) -> list[str]:
        """
        Check the standards: unique ids matching the declared pattern, non-empty text, valid roles.

        :return: A list of human-readable problems. Empty means the standards are well formed.
        """
        problems: list[str] = []
        domain: str = self.manifest.domain_id

        try:
            id_pattern: re.Pattern = re.compile(f"^(?:{self.manifest.standard_id_pattern})$")
        except re.error as exception:
            problems.append(f"{domain}: standard_id_pattern is not a valid regular expression: {exception}")
            id_pattern = re.compile(f"^(?:{DEFAULT_STANDARD_ID_PATTERN})$")

        seen: set[str] = set()
        for standard in self.standards:
            if standard.standard_id in seen:
                problems.append(f"{domain}: duplicate standard id {standard.standard_id}.")
            seen.add(standard.standard_id)
            if not id_pattern.match(standard.standard_id):
                problems.append(
                    f"{domain}: standard id {standard.standard_id} does not match the pack's "
                    f"declared pattern {self.manifest.standard_id_pattern!r}."
                )
            if not standard.text.strip():
                problems.append(f"{domain}: standard {standard.standard_id} has no text.")
            if standard.role is not None and standard.role not in VALID_ROLES:
                problems.append(
                    f"{domain}: standard {standard.standard_id} declares role {standard.role!r}; "
                    f"expected one of {', '.join(VALID_ROLES)}."
                )

        # A bullet that reads as a standard but whose id the declared pattern rejects is not parsed
        # as a standard at all. Left unreported it would vanish between the document and the network,
        # which is the failure the verifier exists to catch, one link earlier in the chain.
        for unmatched_id in self.unmatched_standard_ids:
            problems.append(
                f"{domain}: {unmatched_id} reads as a standard but does not match the pack's declared "
                f"pattern {self.manifest.standard_id_pattern!r}, so it was NOT loaded. Fix the id or "
                f"the pattern."
            )

        # A role assigned to an id the pack no longer defines: usually a standard renamed or removed
        # without the manifest being updated, which would silently drop it from the structural check.
        for declared_id in self.manifest.roles:
            if declared_id not in seen:
                problems.append(
                    f"{domain}: {MANIFEST_FILENAME} assigns a role to {declared_id}, which is not "
                    f"a standard in this pack."
                )
        return problems

    def _open_variable_problems(self) -> list[str]:
        """
        Check the open variables: unique ids, and all of question, examples and why present.

        :return: A list of human-readable problems. Empty means the open variables are well formed.
        """
        problems: list[str] = []
        domain: str = self.manifest.domain_id

        variable_ids: set[str] = set()
        for variable in self.open_variables:
            if variable.variable_id in variable_ids:
                problems.append(f"{domain}: duplicate open variable id {variable.variable_id}.")
            variable_ids.add(variable.variable_id)
            fields: tuple[tuple[str, str], ...] = (
                ("question", variable.question),
                ("examples", variable.examples),
                ("why", variable.why),
            )
            for label, value in fields:
                if not value.strip():
                    problems.append(f"{domain}: open variable {variable.variable_id} is missing its {label}.")
        return problems


# --------------------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------------------


def knowdocs_root(root: str | os.PathLike | None = None) -> Path:
    """
    Resolve the knowdocs root.

    Precedence: an explicit argument, then the environment variable, then a path relative to
    this module. The last of those is deliberately NOT relative to the working directory - the
    original implementation was, which meant the designer only worked when the server happened
    to be started from the repository root.

    :param root: An explicit root, or None to resolve from the environment or the default.
    :return: The resolved root path.
    """
    if root is not None:
        return Path(root).expanduser().resolve()
    from_environment: str | None = os.environ.get(KNOWDOCS_ENV_VAR)
    if from_environment:
        return Path(from_environment).expanduser().resolve()
    return DEFAULT_KNOWDOCS_ROOT


def discover_domains(root: str | os.PathLike | None = None) -> list[str]:
    """
    List the domains available under the knowdocs root.

    A domain is any immediate subdirectory holding at least one readable document. Nothing is
    registered in Python, so adding a domain is a filesystem operation: no code change, no fork.

    :param root: The knowdocs root, or None to resolve it.
    :return: Sorted domain identifiers.
    """
    resolved: Path = knowdocs_root(root)
    if not resolved.is_dir():
        return []
    domains: list[str] = []
    for candidate in sorted(resolved.iterdir()):
        if not candidate.is_dir() or candidate.name.startswith("."):
            continue
        has_documents: bool = any(
            path.is_file() and path.suffix.lower() in _DOCUMENT_SUFFIXES for path in candidate.rglob("*")
        )
        if has_documents:
            domains.append(candidate.name)
    return domains


def _read_manifest(directory: Path, domain_id: str) -> PackManifest:
    """
    Load a pack manifest, synthesising a placeholder if the pack does not carry one.

    :param directory: The pack directory.
    :param domain_id: The domain identifier, taken from the directory name.
    :return: The manifest.
    """
    manifest_path: Path = directory / MANIFEST_FILENAME
    if not manifest_path.is_file():
        return PackManifest(
            domain_id=domain_id,
            title=domain_id.replace("_", " "),
            standard_id_pattern=DEFAULT_STANDARD_ID_PATTERN,
            synthesised=True,
        )

    config: Any = ConfigFactory.parse_file(str(manifest_path))
    raw_roles: Any = config.get("roles", {}) or {}
    roles: dict[str, str] = {str(key): str(value).strip().lower() for key, value in dict(raw_roles).items()}

    def text_of(key: str, default: str = "") -> str:
        value: Any = config.get(key, default)
        return "" if value is None else str(value)

    declared_pattern: str = text_of("standard_id_pattern", DEFAULT_STANDARD_ID_PATTERN)
    return PackManifest(
        domain_id=text_of("domain_id", domain_id) or domain_id,
        title=text_of("title", domain_id.replace("_", " ")),
        summary=text_of("summary"),
        version=text_of("version"),
        owner=text_of("owner"),
        approved_by=text_of("approved_by"),
        effective_date=text_of("effective_date"),
        source=text_of("source"),
        standard_id_pattern=declared_pattern or DEFAULT_STANDARD_ID_PATTERN,
        roles=roles,
    )


def parse_standards(text: str, id_pattern: str, roles: dict[str, str] | None = None) -> list[Standard]:
    """
    Parse operating standards out of a markdown document.

    Expected shape, one per bullet, wrapping freely across lines::

        - ODB-03: Take a full RMAN backup before applying any patch, and confirm the backup
          is restorable.

    :param text: The markdown document text.
    :param id_pattern: The pack's declared standard id pattern.
    :param roles: Optional mapping of standard id to temporal role, from the manifest.
    :return: The parsed standards, in document order.
    """
    roles = roles or {}
    try:
        matcher: re.Pattern = re.compile(rf"^({id_pattern})\s*[:.]\s*(.+)$", re.DOTALL)
    except re.error:
        matcher = re.compile(rf"^({DEFAULT_STANDARD_ID_PATTERN})\s*[:.]\s*(.+)$", re.DOTALL)

    standards: list[Standard] = []
    for bullet in _iter_bullets(text):
        match: re.Match | None = matcher.match(bullet.strip())
        if match is None:
            continue
        standard_id: str = match.group(1).strip()
        standards.append(
            Standard(
                standard_id=standard_id,
                text=match.group(2).strip(),
                role=roles.get(standard_id),
            )
        )
    return standards


def find_unmatched_standard_ids(text: str, id_pattern: str) -> list[str]:
    """
    Find bullets that read as a standard but whose id the pack's declared pattern rejects.

    parse_standards matches on the declared pattern, so a bullet whose id falls outside it is not
    returned at all - the rule disappears with nothing raised and nothing logged. This finds those
    bullets using the permissive default pattern, so validate() can report them.

    Only ids of the shape PREFIX-digits are considered, so ordinary prose containing a colon is not
    mistaken for a mis-numbered standard.

    :param text: The markdown document text.
    :param id_pattern: The pack's declared standard id pattern.
    :return: The rejected ids, in document order.
    """
    permissive: re.Pattern = re.compile(rf"^({DEFAULT_STANDARD_ID_PATTERN})\s*[:.]\s*(.+)$", re.DOTALL)
    try:
        declared: re.Pattern = re.compile(f"^(?:{id_pattern})$")
    except re.error:
        return []

    unmatched: list[str] = []
    for bullet in _iter_bullets(text):
        match: re.Match | None = permissive.match(bullet.strip())
        if match is None:
            continue
        candidate: str = match.group(1).strip()
        if not declared.match(candidate):
            unmatched.append(candidate)
    return unmatched


def parse_open_variables(text: str) -> list[OpenVariable]:
    """
    Parse open variables out of a markdown document.

    Expected shape, four pipe-separated fields, wrapping freely across lines::

        - V1 | Topology: single instance, RAC, Data Guard standby, or Exadata?
          | examples: single instance; two-node RAC
          | why: decides rolling versus a full outage.

    The trailing "why" is what lets the designer justify a question it does not itself
    understand, so a pack that omits it is reported by validate().

    :param text: The markdown document text.
    :return: The parsed open variables, in document order.
    """
    variables: list[OpenVariable] = []
    for bullet in _iter_bullets(text):
        parts: list[str] = [part.strip() for part in bullet.split("|")]
        if len(parts) < 2 or not parts[0]:
            continue
        question_parts: list[str] = []
        examples: str = ""
        why: str = ""
        for part in parts[1:]:
            lowered: str = part.lower()
            if lowered.startswith("examples:"):
                examples = part.split(":", 1)[1].strip()
            elif lowered.startswith("why:"):
                why = part.split(":", 1)[1].strip()
            else:
                question_parts.append(part)
        variables.append(
            OpenVariable(
                variable_id=parts[0],
                question=" | ".join(question_parts).strip(),
                examples=examples,
                why=why,
            )
        )
    return variables


def read_documents(directory: Path) -> dict[str, str]:
    """
    Read every document in a pack directory, whole and verbatim.

    Documents are never chunked or summarised: an operating standard has to reach the generated
    agents word for word, with its id, or the fidelity check downstream is meaningless.

    :param directory: The pack directory.
    :return: A mapping of path (relative to the directory) to full text.
    """
    documents: dict[str, str] = {}
    for path in sorted(directory.rglob("*")):
        if not path.is_file():
            continue
        suffix: str = path.suffix.lower()
        if suffix not in _DOCUMENT_SUFFIXES:
            continue
        relative: str = str(path.relative_to(directory))
        if suffix == ".pdf":
            documents[relative] = _read_pdf(path)
        else:
            documents[relative] = path.read_text(encoding="utf-8", errors="replace")
    return documents


def _read_pdf(path: Path) -> str:
    """
    Extract text from a PDF, preserving page boundaries.

    :param path: The PDF path.
    :return: The extracted text, or an error string beginning with "ERROR:".
    """
    try:
        reader = PdfReader(str(path))
        chunks: list[str] = []
        for page_number, page in enumerate(reader.pages, start=1):
            chunks.append(f"\n\n--- Page {page_number} ---\n\n")
            chunks.append(page.extract_text() or "")
        return "".join(chunks)
    except (PyPdfError, OSError) as exception:
        return f"ERROR: Error reading PDF {path}: {exception}"


def load_pack(domain_id: str, root: str | os.PathLike | None = None) -> KnowledgePack:
    """
    Load one pack by domain identifier.

    :param domain_id: The domain identifier - the pack's directory name.
    :param root: The knowdocs root, or None to resolve it.
    :return: The loaded pack.
    :raises FileNotFoundError: If no pack directory exists for this domain.
    """
    directory: Path = knowdocs_root(root) / domain_id
    if not directory.is_dir():
        raise FileNotFoundError(f'No knowledge pack for domain "{domain_id}" under {knowdocs_root(root)}')

    manifest: PackManifest = _read_manifest(directory, domain_id)
    documents: dict[str, str] = read_documents(directory)
    standards_text: str = documents.get(STANDARDS_FILENAME, "")

    return KnowledgePack(
        manifest=manifest,
        standards=parse_standards(standards_text, manifest.standard_id_pattern, manifest.roles),
        open_variables=parse_open_variables(documents.get(VARIABLES_FILENAME, "")),
        documents=documents,
        unmatched_standard_ids=find_unmatched_standard_ids(standards_text, manifest.standard_id_pattern),
    )


def load_catalogue(root: str | os.PathLike | None = None) -> list[KnowledgePack]:
    """
    Load every discoverable pack.

    :param root: The knowdocs root, or None to resolve it.
    :return: The loaded packs, ordered by domain id.
    """
    packs: list[KnowledgePack] = []
    for domain_id in discover_domains(root):
        try:
            packs.append(load_pack(domain_id, root))
        except (FileNotFoundError, OSError):
            continue
    return packs
