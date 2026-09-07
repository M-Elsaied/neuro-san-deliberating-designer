# Knowledge packs

The deliberating designer separates **method** from **content**. The method — how to elicit, brief,
gate and structure a network — lives in the designer's prompt and holds no domain facts. The content
lives in **knowledge packs**: folders of curated documents, owned by whoever owns the subject matter.

This document is for whoever writes the content. No Python required.

---

## What a pack is

```text
<knowdocs root>/<domain_id>/
    pack.hocon              identity, provenance, id pattern, standard roles
    operating_standards.md  the non-negotiables, each with a stable id
    open_variables.md       the interview script
```

Adding a domain is dropping a folder in. Domains are **discovered** by scanning the root, so no code
change and no prompt change is required, and you do not need to fork the repository to add your own.

---

## Where packs are read from

In precedence order:

1. an explicit path passed by a caller;
2. the `AGENT_NETWORK_DESIGNER_KNOWDOCS` environment variable;
3. `coded_tools/agent_network_designer/knowdocs`, resolved **relative to the installed module** —
   not to the process working directory, so the designer works whatever directory the server was
   started from, and works when installed as a package.

To serve your own packs without touching this repository:

```bash
export AGENT_NETWORK_DESIGNER_KNOWDOCS=/srv/agent-knowledge/packs
```

---

## Scale: what this handles, and where it stops

Packs are read once per process, not once per tool call. Measured on the three shipped packs:

| | Before | After |
|---|---|---|
| `load_catalogue()` | 19.8 ms, every call | 0.6 ms warm (46x) |
| Where that ran | on the event loop | in a worker thread on a miss |

Freshness is a full walk of the knowdocs root, capturing each document's modification time. That
walk *is* the 0.6 ms, and it is the whole warm cost. It is deliberately the most expensive probe
available: it means an edited pack is picked up with no restart, no TTL to tune and no staleness
window. A cache that could serve a stale pack would be worse than no cache, because the designer
and the verifier read the same copy — they would agree with each other about a document that had
already changed.

**The ceiling is the prompt, not the filesystem.** `ListDomains` returns every domain, and that
payload then sits in context for the rest of the conversation:

| Domains | Catalogue payload |
|---|---|
| 10 | ~2,700 chars (~680 tokens) |
| 50 | ~13,600 chars (~3,400 tokens) |
| 200 | ~54,600 chars (~13,700 tokens) |

Reporting a standard *count* per domain rather than the full id list took this from 330 to 273
characters per domain — a fifth off a term that is still linear in the number of domains. Caching
removes repeated work; it does not remove that. Somewhere past a few dozen domains, "list
everything and let the model choose" stops being a catalogue and becomes a retrieval problem.

**Where a retrieval layer would go.** `ListDomains` and `ExtractDocs` are a two-call seam: *choose
a domain from a catalogue*, then *fetch that domain whole*. Replacing the bodies of those two
coded tools — `ListDomains` becoming a query against an index, `ExtractDocs` a fetch by id — is
sufficient to put a retrieval or MCP-backed knowledge layer underneath, and it changes neither the
designer's prompt, nor the pack format, nor `standards_verifier.py`, which compares against a
loaded pack regardless of where that pack came from. That is deliberately not built here.

---

## `operating_standards.md`

One bullet per standard: an id, a colon, then the rule. Wrap freely across lines — continuations are
re-joined. Prose and headings between bullets are ignored, so you can explain the pack at the top.

```markdown
# Operating standards - Oracle database patching

These represent typical practice. Confirm against your own SOP before relying on them.

- ODB-03: Take a full RMAN backup before applying any patch, and confirm the backup is
  restorable.
- ODB-04: Run datapatch after applying the database binaries; the patch is not complete, and
  the environment is not handed back, until datapatch has succeeded.
```

Standards are **quoted verbatim** into the generated agents and checked afterwards, so write them as
you want them to appear. Keep them short: these are standards, not a manual.

## `open_variables.md`

One bullet per question, four pipe-separated fields: **id | question | examples | why**.

```markdown
- V1 | Topology: single instance, RAC, Data Guard standby, or Exadata?
  | examples: single instance, no standby; two-node RAC; Exadata X8M
  | why: decides rolling versus a full outage, and whether a standby has to be patched too.
```

The **why** matters more than it looks. It is what lets the designer justify a question it does not
itself understand — it has no idea what Data Guard is, and does not need to. A pack that omits the
why-clause is reported by validation.

The **examples** carry a second job: `InterviewLog` renders them to the user as a numbered list, one
option per line, verbatim and in your order, followed by *something else* and *not sure*. So write them
as answers a requester could pick, not as a hint about the shape of an answer — and keep them genuinely
distinct. Two examples that differ only in a detail the user is likely to leave out (*the same change
record approved by two different bodies*) are the case the designer must stop and ask about: an answer
that is a shortening of both is reported as ambiguous and sent back, so the distinction has to be in the
wording rather than implied.

Because the rendering is computed from this file, the options a user sees cannot drift from what you
wrote here. The question **order** is the order of these bullets, and it is also the order the user
navigates by when they go back — the first bullet is `Q1` for the whole session.

## `pack.hocon`

```hocon
{
    domain_id = "oracle_database_patching"
    title = "Oracle database patching"
    summary = "applying Oracle RU/PSU patches across a database estate"

    version = "1.0.0"
    owner = "Database Engineering"
    approved_by = "Change Advisory Board"
    effective_date = "2026-06-01"
    source = "Derived from SOP-DB-014 rev 3"

    standard_id_pattern = "ODB-\\d{2}"

    roles {
        "ODB-03" = precondition
        "ODB-04" = postcondition
    }
}
```

What each field is for:

- **`version`, `owner`, `approved_by`, `effective_date`, `source`** — stamped into the generated
  network, so an artifact states what it was built from and who stands behind it. A network of
  unknown ancestry is hard to defend in an audit.
- **`standard_id_pattern`** — your ids, not ours. `SOP-4.2.1`, `CTRL-0093`, `std-001`: whatever your
  organisation already numbers its standards with. An id that reads like a standard but falls outside
  this pattern is **not loaded**, and validation reports it rather than letting the rule disappear.
- **`roles`** — temporal role drives topology. Declaring it here takes the decision away from the
  language model and makes the resulting shape checkable.

`roles` values are `precondition`, `work` or `postcondition`:

```text
precondition   ->  a gate agent, upstream of the work
                   (take the backup / snapshot etcd / close the queries)
work           ->  the operation itself
                   (apply the RU / drain the node / apply the soft lock)
postcondition  ->  a validator agent, downstream, owning hand-back
                   (run datapatch / check workload health / hard-lock signature)
```

Roles are optional. A pack that declares none simply skips the structural check.

A pack with no `pack.hocon` at all still loads: identity is inferred from the directory name and a
warning is reported. Existing packs keep working across this change.

---

## Verification

After a network is built, its standards are **checked**, not asserted. The designer calls
`VerifyStandards` and prints the computed result rather than writing a coverage table about its own
work.

| Property | What it means |
|---|---|
| **Coverage** | Every standard in the pack is embedded in exactly one agent. None missing, none ambiguous. |
| **Fidelity** | Embedded text matches the pack text. Re-wrapping and typography are tolerated; a changed word is not. |
| **Provenance** | Every embedded id exists in the pack. Nothing was invented. |
| **Structure** | Where roles are declared, no single agent owns both a precondition and the work it guards. |
| **Pack** | The pack itself loaded soundly. A standard that never loaded cannot have reached the network. |

**What blocks a build, and what does not.** A standard that was paraphrased, or an id the pack does
not define, is sent back to be corrected — and if the wording still cannot be reproduced within the
retry budget, the network is not written at all. Neither is a judgement call: a rule stated in words
nobody in the domain agreed to is a different rule wearing its id, and a rule with no source is
unchallengeable.

Coverage, ambiguous ownership and topology are reported but never block. A network carrying five of
six standards with the sixth flagged is more useful than an exception, and a gate that refused it
would be switched off — taking the fidelity check with it. Set
`AGENT_NETWORK_DESIGNER_ENFORCE_STANDARDS=false` to make everything advisory again.

### Errors and warnings

Pack problems come in two severities, and the line between them decides whether verification fails:

- **Errors** mean the pack cannot be trusted to have delivered its standards — an id outside the
  declared pattern, a standard with no text, a duplicate id, a role pointing at a standard that no
  longer exists. Any of these and a standard is missing or ambiguous *before the build even starts*,
  so however carefully the network was assembled it cannot carry the pack. These fail verification.
- **Warnings** mean the pack is under-specified but its standards are intact — no `pack.hocon`, no
  `version`, an open variable missing its `why`. Reported, never blocking. This is also what keeps a
  pack written before manifests existed working.

## Provenance in the generated network

Once a network is built from a pack, the pack's provenance line is written into the network's own
`metadata`, next to `date_created`:

```hocon
    "metadata": {
        "sample_queries": [ ... ],
        "date_created": "2026-08-21T09:14:02+00:00",
        "knowledge_pack": "Oracle database patching, v1.0.0, owned by Database Engineering"
    },
```

So the artifact states its own ancestry rather than leaving it in a chat transcript. Networks built
without a pack simply have no `knowledge_pack` key, rather than an empty one that would read as
"source unknown".

### Running it yourself

Nothing here needs a language model or an API key, so it runs in CI:

```bash
python -m coded_tools.agent_network_designer.standards_verifier \
    registries/generated/oracle_patching.hocon \
    --domain oracle_database_patching
```

Exit code `0` if the network verifies clean, `1` if it does not, `2` on a usage error.

---

## Checklist for a new pack

1. `mkdir <knowdocs root>/<your_domain>`
2. Write `operating_standards.md` — short, invariant, each rule with a stable id.
3. Write `open_variables.md` — only what the requester alone can answer, each with its why.
4. Write `pack.hocon` — version and owner at minimum, plus your id pattern if it is not `ABC-01`.
5. Check it:

   ```bash
   python -m coded_tools.agent_network_designer.authoring validate --domain your_domain
   ```

   Exit `0` means usable. Anything wrong is reported with the line it is on and what to do about
   it. Add `--strict` if an incomplete `pack.hocon` should also count as a failure.

6. Ask the designer to build something in your domain, and read the verified coverage table.

No step edits Python or the designer's prompt. If one did, this would be an example rather than an
extension point.

### Checking every pack at once

```bash
python -m coded_tools.agent_network_designer.authoring validate --all
```

One line per pack — `OK`, `OK*` for usable but under-specified, `PROBLEM` for unusable — then the
detail for anything that needs attention. This is also what CI runs, so a malformed pack anywhere
under the knowdocs root fails the build rather than surfacing three minutes into a design session.

---

## What this costs to maintain

Verification is deterministic, so it costs nothing per run — no model, no key, no network. The
things it checks *against*, though, do cost something to keep current, and that is worth stating
rather than discovering later.

Measured on this repository:

| | |
|---|---|
| Designer unit tests | 161 passing, ~2s, no model |
| `make validate-packs` | one cached catalogue load, ~0.6ms plus process startup |
| `pymarkdown` over `knowdocs/` | 0 findings |

The recurring costs, named:

- **Adding a pack to this repository** means adding one line to
  `tests/coded_tools/agent_network_designer/shipped_packs.py`. Deliberate: a pack appearing on disk
  with nobody noticing is how a malformed one used to reach a green build.
- **Every pack present is validated by CI**, including a deployment's own. A malformed pack is a
  red build rather than a surprise three minutes into a design session. That is the point, and it
  does mean a half-finished pack cannot sit in the tree.
- **Pack markdown is linted** with the same rules as the rest of the documentation.
- **Editing a standard's wording** is free as far as the tests are concerned — the reference
  networks used by the scenario benchmark are derived from the pack itself, so a new or changed
  domain brings its own coverage rather than needing a hand-written fixture.
- **Changing a standard's id or role** does need the manifest kept in step. `validate` reports the
  mismatch, and it is the one edit that reliably requires touching two files.

What is deliberately *not* in CI: the extractor. It needs a model and an API key, so it runs when
an author runs it and never on a build.

---

## Auditing an estate of generated networks

Verification is a moment-in-time check: it answers *"does this network carry its pack faithfully?"*
as the network is built. Packs then change — a standard is reworded, a control is added, a version
is cut — and every network built before that change quietly stops implementing the document it
claims to. In a regulated context an out-of-date control is the whole problem, not an edge case.

```bash
python -m coded_tools.agent_network_designer.network_audit registries/generated/
```

```text
| Network                        | Pack                       | Built at | Pack now | Status   |
| exadata_oracle_patching.hocon  | oracle_database_patching   | -        | v1.0.0   | unstamped|
| kubeadm_cluster_upgrade.hocon  | kubernetes_cluster_upgrade  | v1.0.0   | v1.2.0   | **stale**|
```

| Status | Meaning |
|---|---|
| `current` | Built from this pack version, and every standard still matches |
| `stale` | The pack has moved on since this network was built |
| `drifted` | A standard's **text** no longer matches, whatever the version says |
| `unstamped` | Predates provenance stamping. Reported, not flagged — its standards may be fine |
| `unknown pack` | Embeds ids belonging to no pack on this deployment |
| `no standards` | Carries no `MUST: … [id]` lines at all, so nothing is traceable |

`drifted` is the one that earns its keep. Someone edits a standard's wording and does not bump the
version — the most likely way for an estate to go quietly out of date — and a version comparison
would call that network current. The text comparison does not, and it names the standard.

Exit code `0` when nothing needs attention, `1` when something does, so this runs as a scheduled
check rather than by eye.

### Traceability

The question an auditor actually asks — *show me everything that implements this rule*:

```bash
python -m coded_tools.agent_network_designer.network_audit registries/generated/ --standard ODB-03
python -m coded_tools.agent_network_designer.network_audit registries/generated/ --pack oracle_database_patching
```

A network is matched to its pack by **the standard ids it embeds**, not by its metadata. That is
deliberate: it needs no parsing of a human-readable provenance line, it works on networks generated
before provenance stamping existed, and it cannot be fooled by metadata that says one thing while
the instructions say another — which is exactly the discrepancy an audit is for.
