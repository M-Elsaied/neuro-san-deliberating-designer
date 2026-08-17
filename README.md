# Neuro SAN - Deliberating Agent Network Designer

An agent network designer that **gathers requirements before it builds**.

Ask a stock designer for "an agent network for Oracle database patching" and you get a plausible DAG of job
titles in four seconds - because one sentence does not contain what a real design needs. It never asks
whether the estate is RAC or single-instance, whether production can take an outage, or who signs the
change record, and those answers change the shape of the network rather than its wording.

This designer looks up curated knowledge for the domain, interviews you one question at a time, presents a
design brief separating what you confirmed from what it assumed, and builds only once you approve - with
each operating standard embedded verbatim, and traceable by id, in the agent that owns it.

> Derived from [cognizant-ai-lab/neuro-san-studio](https://github.com/cognizant-ai-lab/neuro-san-studio)
> (Apache-2.0). Changed here: `registries/agent_network_designer.hocon` and
> `coded_tools/agent_network_designer/` (new). Everything else is upstream; see
> [upstream docs](https://github.com/cognizant-ai-lab/neuro-san-studio#readme) for the platform itself.

---

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pip install -e .
echo "OPENAI_API_KEY=sk-..." > .env
ns run                                              # UI at http://127.0.0.1:4173
```

Select **`agent_network_designer`** in the UI. Its four sample queries are the four scenarios below.

Ports already taken? `ns run --nsflow-port 4174 --server-http-port 8081`.

---

## What is different

- **It deliberates first.** Curated knowledge for the domain is retrieved, then you are interviewed one
  question at a time. Nothing is built until you approve.
- **Knowledge lives in documents, not in the prompt.** Each domain is a folder of `.md` files under
  `coded_tools/agent_network_designer/knowdocs/<domain>/`, read by the `ExtractDocs` coded tool - the same
  pattern `airline_policy` uses. Documents are returned whole and verbatim, never chunked, so a standard
  reaches the designed agents word for word.
- **It ends with a design brief** that separates confirmed requirements from flagged assumptions.
- **Standards stay traceable.** Each one appears in its owning agent as `MUST: <text> [<id>]`, and the
  closing summary maps every id to an agent.

| Domain | `app_name` | Standard ids |
|---|---|---|
| Oracle database patching | `oracle_database_patching` | `ODB-01`…`ODB-06` |
| Kubernetes cluster upgrade | `kubernetes_cluster_upgrade` | `K8S-01`…`K8S-06` |
| Clinical trial database lock | `clinical_trial_database_lock` | `DBL-01`…`DBL-06` |

---

## Design theory: how one designer stays industry-agnostic

**Mechanism is separated from content.** The designer is a shell plus a knowledge base - an
elicitation-and-assembly procedure holding no domain facts, and swappable domain facts holding no
procedure.

| Layer | Holds | Lives in | Owned by |
|---|---|---|---|
| **L1 - method** | how to elicit, brief, gate, structure a network | the designer prompt | platform team |
| **L2 - domain** | operating standards and open variables | `knowdocs/<domain>/*.md` | domain expert |
| **L3 - instance** | this estate, this window, this approver | the interview | the requester |

Industry-agnosticism is precisely the claim that **L1 contains no L2**. Any domain-specific noun surviving
in the designer's instructions is a defect, because it biases every other domain - which is why the prompt
carries no Oracle vocabulary, not even in its formatting examples.

**Two kinds of knowledge are enough.** *Normative* knowledge is invariant, carries a stable id and is
quoted verbatim (*take a full RMAN backup before applying any patch*) - it is **retrieved**. *Situational*
knowledge varies per instance and only the requester has it (*RAC or single instance?*) - it is
**elicited**, one question per turn. Open variables are written as
`id | question | example answers | why it changes the design`, so the shell can justify a question it does
not itself understand.

**Temporal role determines topology.** This is the rule that turns knowledge into architecture, and it is
domain-neutral:

```text
precondition  -> gate agent, upstream of the work agent
                 (RMAN backup / etcd snapshot / query closure)
work          -> the operation itself
                 (apply the RU / drain the node / apply the soft lock)
postcondition -> validator agent, downstream, owns hand-back
                 (datapatch and connectivity / workload health / hard-lock e-signature)
```

All three shipped domains are the same shape in different vocabulary: prove you can recover, do the work,
prove it still works, hand back. The designer does not know Oracle from Kubernetes; it knows a precondition
produces a gate.

**Review becomes a property check.** Verbatim text plus ids makes correctness mechanical - *coverage*
(every standard has exactly one owning agent), *fidelity* (agent text matches document text exactly), and
*provenance* (every rule traces to an id). A domain expert is needed once, to author the pack; after that a
reviewer who has never patched a database can audit any generated network.

**How to falsify it.** The scenarios below hold L1 constant and vary L2. Three domains must yield different
questions, topologies and ids. Pizza delivery is the control: with no pack the designer must degrade
honestly rather than improvise standards - if it invents confident "pizza standards", L1 is contaminated
and the claim fails.

### Known limits

1. **A `MUST:` line is not a control.** Embedding a standard makes it salient, not enforced. Real
   enforcement is deterministic tooling that refuses to proceed.
2. **Packs are asserted, not verified.** A wrong pack yields an authoritative-looking wrong network, which
   is why versioning, ownership and approval of packs are the natural next step.
3. **Intent matching is an unsolved classifier.** Matching the *wrong* domain is worse than matching none,
   and nothing resolves the case where two domains both apply.
4. **The meta-model favours runbook-shaped work.** Sequential, gate-heavy processes fit well; optimisation,
   negotiation and open-ended judgement do not reduce to invariants plus parameters.

---

## Try it

Send each line as its own turn.

### 1. A curated domain - Oracle

| Send | Expect |
|---|---|
| `Build me an agent network for Oracle db patching` | Names the matched domain, then **one** question with examples |
| `Two-node RAC in prod with a Data Guard standby; dev and QA single instance.` | The next single question |
| `Skip the questions, just build it.` | **Refuses**, naming what is still open and what would break |
| `About 40 databases. DEV, then QA, then PROD. Four-hour Saturday window, PROD rolling with no full outage.` | Carries it forward |
| `DBA team takes the RMAN backup, verified restore point required. Production gated by a ServiceNow CR approved by CAB` | The remaining variables |
| `opatch rollback, and the DBA team signs off connectivity.` | The **design brief** |
| `APPROVED` | Builds, then the standards-coverage table |

In the brief: confirmed requirements contain only what you said, assumptions are listed separately,
standards are verbatim with `ODB-0x` ids, and the shape names real agents.

### 2. A different domain - Kubernetes

`Build me an agent network to upgrade our Kubernetes clusters`, then `AKS, three clusters: dev, staging,
prod.` → `1.29 to 1.31.` → `Surge upgrade, we have spare capacity.` → `Yes, stateful workloads with PVCs
and strict PDBs on the payment service.` → `assume sensible defaults` → `APPROVED`

It must ask about node strategy and PodDisruptionBudgets, never RMAN, and carry `K8S-0x` ids. A blanket
"assume sensible defaults" ends the interview and goes straight to the brief. Watch whether it treats
1.29 → 1.31 as two sequential upgrades, since `K8S-01` forbids skipping a minor version.

### 3. A non-IT domain - clinical trial database lock

`Build me an agent network for our clinical trial database lock process`, then `Phase III, 120 sites, 900
subjects, double-blind.` → `Medidata Rave with Argus for safety.` → `Risk-based SDV on critical
variables.` → `assume sensible defaults` → `APPROVED`

Expect questions about the SDV model, coding dictionaries and who authorises the lock, with `DBL-0x` ids.

### 4. No curated knowledge - the control

`Build me an agent network for pizza delivery`

It must say it has no curated knowledge, name the domains it does have, call its standards unverified - and
still interview you. Inventing confident standards is a failure.

### Check the artifact, not the chat

```bash
ls registries/generated/
grep -c "MUST:" registries/generated/<name>.hocon
grep -oE "(ODB|K8S|DBL)-0[1-6]" registries/generated/<name>.hocon | sort -u
```

Each standard should sit inside the agent that owns it - the backup gate carrying the backup standard, the
validator carrying the validation standard.

---

## Adding a domain

1. Create `coded_tools/agent_network_designer/knowdocs/<your_domain>/` with `operating_standards.md` and
   `open_variables.md` (copy an existing pair for the shape).
2. Add one line to `docs_path` in `coded_tools/agent_network_designer/extract_docs.py`.
3. Add the domain to the `ExtractDocs` description in `registries/agent_network_designer.hocon`.

No prompt logic changes - the deliberation itself is domain-agnostic. Keep packs short: documents are
returned whole, so they are standards and open variables, not manuals.

---

## Upstream

Platform documentation - install options, architecture, tutorials, other agent networks - lives upstream:
[cognizant-ai-lab/neuro-san-studio](https://github.com/cognizant-ai-lab/neuro-san-studio),
[user guide](https://github.com/cognizant-ai-lab/neuro-san-studio/blob/main/docs/user_guide.md),
[tutorial](https://github.com/cognizant-ai-lab/neuro-san-studio/blob/main/docs/tutorial.md).
