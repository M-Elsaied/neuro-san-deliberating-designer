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

Failures are reported, not raised — a network covering five of six standards with one flagged is more
useful than an exception. Pass `strict` to make a failure an error instead.

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
5. Confirm it loads and validates:

   ```python
   from coded_tools.agent_network_designer.knowledge_pack import load_pack
   print(load_pack("your_domain").validate())   # [] means clean
   ```

6. Ask the designer to build something in your domain, and read the verified coverage table.

No step edits Python or the designer's prompt. If one did, this would be an example rather than an
extension point.
