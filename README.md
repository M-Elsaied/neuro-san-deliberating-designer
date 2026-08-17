# Neuro SAN Studio — Deliberating Agent Network Designer

> **About this repository.** This is a derivative of
> [cognizant-ai-lab/neuro-san-studio](https://github.com/cognizant-ai-lab/neuro-san-studio) (Apache-2.0),
> carrying one focused change: `agent_network_designer` now **gathers requirements before it builds**. It
> looks up curated domain knowledge held as documents on disk, interviews you one question at a time,
> presents a design brief separating what you confirmed from what it assumed, and builds only once you
> approve — embedding each operating standard verbatim, and traceable by id, in the agent that owns it.
>
> See [**Deliberating Agent Network Designer — how to test it**](#deliberating-agent-network-designer--how-to-test-it)
> for what changed and how to try it. Everything else below is upstream documentation, unchanged.
>
> Modified files: `registries/agent_network_designer.hocon`,
> `coded_tools/agent_network_designer/` (new), `README.md`.

---

**Your launchpad for building intelligent multi-agent systems.** Neuro SAN Studio is a hands-on playground for the
[Neuro SAN](https://github.com/cognizant-ai-lab/neuro-san) framework, featuring ready-to-run examples, tutorials, and
tools that let you design, test, and deploy sophisticated agent networks in minutes—not months. Whether you're a
researcher exploring adaptive AI systems, a developer prototyping production solutions, or a domain expert configuring
agents without code, this studio handles the orchestration complexity so you can focus on solving real problems.

---

<!-- pyml disable-next-line no-inline-html -->
<p align="center">
  Neuro SAN is the open-source library powering the Cognizant Neuro® AI Multi-Agent Accelerator, allowing domain experts,
  researchers and developers to immediately start prototyping and building agent networks across any industry vertical.
</p>

---

<!-- pyml disable-next-line no-inline-html -->
<p align="center">
  <!-- GitHub Stats -->
  <img src="https://img.shields.io/github/stars/cognizant-ai-lab/neuro-san-studio?style=social" alt="GitHub stars">
  <img src="https://img.shields.io/github/forks/cognizant-ai-lab/neuro-san-studio?style=social" alt="GitHub forks">
  <img src="https://img.shields.io/github/watchers/cognizant-ai-lab/neuro-san-studio?style=social" alt="GitHub watchers">
</p>
<p align="center">
  <!-- GitHub Info -->
  <img src="https://img.shields.io/github/last-commit/cognizant-ai-lab/neuro-san-studio" alt="Last Commit">
  <img src="https://img.shields.io/github/issues/cognizant-ai-lab/neuro-san-studio" alt="Issues">
  <img src="https://img.shields.io/github/issues-pr/cognizant-ai-lab/neuro-san-studio" alt="Pull Requests">
  <a href="https://pepy.tech/projects/neuro-san-studio"><img alt="PyPI Downloads"
  src="https://static.pepy.tech/badge/neuro-san-studio" /></a>
  <a href="https://pypi.org/project/neuro-san-studio/">
  <img alt="neuro-san-studio@PyPI" src="https://img.shields.io/pypi/v/neuro-san-studio.svg?style=flat-square"></a>
  <a href="https://deepwiki.com/cognizant-ai-lab/neuro-san-studio">
  <img src="https://deepwiki.com/badge.svg" alt="Ask DeepWiki: Neuro SAN Studio" /></a>

</p>

<!-- pyml disable-next-line no-inline-html -->
<p align="center">
  <!-- Neuro SAN Stats -->
  Neuro SAN library <br>
  <a href="https://github.com/cognizant-ai-lab/neuro-san"><img alt="GitHub Repo"
  src="https://img.shields.io/badge/GitHub-Repo-green.svg" /></a>
  <img src="https://img.shields.io/github/commit-activity/m/cognizant-ai-lab/neuro-san" alt="commit activity">
  <a href="https://pepy.tech/projects/neuro-san"><img alt="PyPI Downloads"
  src="https://static.pepy.tech/badge/neuro-san" /></a>
  <a href="https://pypi.org/project/neuro-san/">
  <img alt="neuro-san@PyPI" src="https://img.shields.io/pypi/v/neuro-san.svg?style=flat-square"></a>
  <a href="https://deepwiki.com/cognizant-ai-lab/neuro-san">
  <img src="https://deepwiki.com/badge.svg" alt="Ask DeepWiki: Neuro SAN" /></a>
</p>

## What is Neuro SAN?

[**Neuro AI system of agent networks (Neuro SAN)**](https://github.com/cognizant-ai-lab/neuro-san) is an open-source,
data-driven multi-agent orchestration framework designed to simplify and accelerate the development of collaborative AI
systems. It allows users—from machine learning engineers to business domain experts—to quickly build sophisticated
multi-agent applications without extensive coding, using declarative configuration files (in HOCON format).

Neuro SAN enables multiple large language model (LLM)-powered agents to collaboratively solve complex tasks, dynamically
delegating subtasks through adaptive inter-agent communication protocols. This approach addresses the limitations inherent
to single-agent systems, where no single model has all the expertise or context necessary for multifaceted problems.

<!-- pyml disable line-length -->
| Build a multi-agent network in minutes                                              | Neuro SAN overview                                                                     | Quick start                                                              |
|-------------------------------------------------------------------------------------|----------------------------------------------------------------------------------------|--------------------------------------------------------------------------|
| [![Build](./docs/images/designer.png)](https://www.youtube.com/watch?v=wGxvPBN34Mk) | [![Overview](./docs/images/overview.png)](https://www.youtube.com/watch?v=NmniQWQT6vI) | [![Start](./docs/images/nsflow_thumb.png)](https://youtu.be/gfem8ylphWA) |

<!-- pyml enable line-length -->
---

### ✨ Key Features

* **🗂️ Data-Driven Configuration**: Entire agent networks are defined declaratively via simple HOCON files, empowering
technical and non-technical stakeholders to design agent interactions intuitively.
* **🔀 Adaptive Communication ([AAOSA Protocol](https://arxiv.org/abs/cs/9812015))**: Agents autonomously determine how
to delegate tasks, making interactions fluid and dynamic with decentralized decision-making.
* **🔒 Sly-Data**: Sly Data facilitates safe handling and transfer of sensitive data between agents without exposing it
directly to any language models.
* **🧩 Dynamic Agent Network Designer**: Includes a meta-agent called the Agent Network Designer – essentially, an agent
that creates other agent networks. Provided as an example with Neuro SAN, it can take a high-level description of a
use-case as input and generate a new custom agent network for it.
* **🛠️ Flexible Tool Integration**: Integrate custom Python-based "coded tools," APIs, databases, and even external
agent ecosystems (Agentforce, Agentspace, CrewAI, MCP, A2A agents, LangChain tools and more) seamlessly into your agent workflows.
* **📈 Robust Traceability**: Detailed logging, tracing, and session-level metrics enhance transparency, debugging, and
operational monitoring.
* **🌐 Extensible and Cloud-Agnostic**: Compatible with a wide variety of LLM providers (OpenAI, Anthropic, Azure, Ollama,
etc.) and deployable in diverse environments (local machines, containers, or cloud infrastructures).

---

### Use Cases

Here are a few examples of use-cases that have been implemented with Neuro SAN.
For more examples, check out [docs/examples.md](docs/examples.md).
<!-- pyml disable no-inline-html -->
<table>
  <thead>
    <tr>
      <th>Agent Network</th>
      <th>Use-Case</th>
      <th>Description</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td>🧬 <strong>Agent Network Designer</strong></td>
      <td>Automated generation of multi-agent HOCON configurations.</td>
      <td>Generates complex multi-agent configurations from natural language input, simplifying the creation of intricate
      agent workflows.</td>
    </tr>
    <tr>
      <td>🛫 <strong>Airline Policy Assistance</strong></td>
      <td>Customer support for airline policies.</td>
      <td>Agents interpret and explain airline policies, assisting customers with inquiries about baggage allowances, cancellations,
      and travel-related concerns.</td>
    </tr>
    <tr>
      <td>🏦 <strong>Banking Operations & Compliance</strong></td>
      <td>Automated financial operations and regulatory compliance.</td>
      <td>Automates tasks such as transaction monitoring, fraud detection, and compliance reporting, ensuring adherence to
      regulations and efficient routine operations.</td>
    </tr>
    <tr>
      <td>🛍️ <strong>Consumer Packaged Goods (CPG)</strong></td>
      <td>Market analysis and product development in CPG.</td>
      <td>Gathers and analyzes market trends, customer feedback, and sales data to support product development and strategic
      marketing.</td>
    </tr>
    <tr>
      <td>🛡️ <strong>Insurance Agents</strong></td>
      <td>Claims processing and risk assessment.</td>
      <td>Automates claims evaluation, assesses risk factors, ensures policy compliance, and improves claim-handling efficiency
      and customer satisfaction.</td>
    </tr>
    <tr>
      <td>🏢 <strong>Intranet Agents</strong></td>
      <td>Internal knowledge management and employee support.</td>
      <td>Provides employees with quick access to policies, HR, and IT support, enhancing internal communications and resource
      accessibility.</td>
    </tr>
    <tr>
      <td>🛒 <strong>Retail Operations & Customer Service</strong></td>
      <td>Enhancing retail customer experience and operational efficiency.</td>
      <td>Handles customer inquiries, inventory management, and supports sales processes to optimize operations and service
      quality.</td>
    </tr>
    <tr>
      <td>📞 <strong>Telco Network Support</strong></td>
      <td>Technical support and network issue resolution.</td>
      <td>Diagnoses network problems, guides troubleshooting, and escalates complex issues, reducing downtime and enhancing
      customer service.</td>
    </tr>
    <tr>
      <td>📞 <strong>Therapy Vignette Supervision</strong></td>
      <td>Generates treatment plan for a given therapy vignette.</td>
      <td>A good example of using multiple different expert agents working together to come up with a single plan.</td>
    </tr>
  </tbody>
</table>
<!-- pyml enable no-inline-html -->

And many more: check out [docs/examples.md](docs/examples.md).

---

## High level Architecture

<!-- pyml disable no-inline-html -->
<p align="left">
  <img src="./docs/images/neuroai_arch_diagram.png" alt="neuro-san architecture" width="800"/>
</p>
<!-- pyml enable no-inline-html -->

---

## Install

These instructions are for Linux and macOS systems. Please adjust the commands accordingly for Windows.

### Install `uv`

[`uv`](https://docs.astral.sh/uv/) is a fast Python package and project manager built by Astral.

Official installation docs:
👉 [https://docs.astral.sh/uv/getting-started/installation/](https://docs.astral.sh/uv/getting-started/installation/)

### Create a new Python project

Create a folder for your project:

```bash
mkdir my_project
cd my_project
```

Create a virtual environment, initialize a git repo and install `neuro-san-studio`

```bash
uv init
uv venv
source .venv/bin/activate
uv add neuro-san-studio
```

### Initialize neuro-san-studio

Run `ns init` to initialize a Neuro SAN Studio project. `ns` stands for Neuro SAN. You can also use the long command
`neuro-san-studio` instead. It will:
* let you choose an LLM provider
* create a `config` folder with your choice of LLM models and plugins configuration
* create an `mcp` folder with a list of MCP tools
* create a `registries` folder with a simple agent network

To learn more about the `ns` command run `ns --help`.

```bash
ns init
```

```bash
Which LLM providers do you want to enable?

#  Provider       Default model
1  OpenAI         gpt-5.2 (default)
2  Anthropic      claude-sonnet
3  Google Gemini  gemini-3-flash

Enter numbers separated by commas (default: 1):
```

### Set your LLM API key(s)

1. Set your provider key, e.g. `OPENAI_API_KEY`, `ANTHROPIC_API_KEY` or `GOOGLE_API_KEY`
(or create a `.env` file in the current directory).
See [docs/api_key.md](docs/api_key.md) for details and other providers.

   ```bash
   export OPENAI_API_KEY="XXX"
   ```

2. Check your LLM API keys are correctly configured:

    ```bash
    ns check-llm-keys
    ```

3. Check your `config/llm_config.hocon` is working:

    ```bash
    ns check-config
    ```

    If the configuration is valid you will get a `hello` response from the configured LLMs.

### Import agent networks

You can import the agent networks that ship with `neuro-san-studio` using the `ns import` command.
It will run an interactive prompt. You can for instance import the `root` agent networks to use the
Agent Network Designer to create your own agent network.

See [`docs/cli/import.md`](docs/cli/import.md) for details.

```bash
ns import
```

Shows the following prompt:

```bash
[info]  Discovering available agent networks...

? What do you want to import? (Use arrow keys)
   Basic (17)
   Experimental (9)
   Industry (22)
 » Root (6)
   Tools (28)
   ---------------
   Custom selection
   All (82)
```

Choose `root` and press Enter. Confirm with `Y` to import the agent networks that are listed.

From `Experimental`, also import:

```bash
   ● cruse_theme_agent
 » ● cruse_widget_agent
````

to enable CRUSE, the interactive UI that adapts the UI to the user/agents' needs.

### Start the developer UI

You can start a `neuro-san` server and the `nsflow` UI with the `ns run` command:

```bash
ns run
```

The Neuro SAN server listens on `localhost:8080`.

The nsflow UI is served at
[http://localhost:4173/](http://localhost:4173/).

Logs land under `logs/` (`server.log`, `nsflow.log`, `thinking_dir/`).

Screenshot:

![NSFlow UI Snapshot](https://raw.githubusercontent.com/cognizant-ai-lab/nsflow/main/docs/snapshot01.png)

### Agent Network Designer

Use the Agent Network Designer to create your own agent network.

1. From the `nsflow` UI, click the `NEW` button at the top, center of the screen.
![AND Button](docs/images/agent_network_designer_new_button.png)
2. In the new window that opens, type your prompts in the text box in the bottom right
corner of the screen. Then Agent Network Designer:
   * Creates the agents
   * Links them together
   * Writes instructions for each agent
   * Generates a few sample queries you can ask this agent network
   * Saves the agent network in the `registries/generated` folder
3. Once the Agent Network Designer is done and comes back with an answer in the chat window,
you can continue the design by asking it to make changes
4. Once you're happy with the design, test it! Click the blue `Launch` button at the top
center of the screen. It opens a new window from which you can chat with the agent network.
5. If you want to make modifications, go back to the editor window and ask for changes.
6. You can also edit any agent network by clicking the pen icon next to its name in the main window.

### Import a project from a file / Export to a file

You can import a project from a .hocon file or from a zip file using the `ns import <PATH>`.

```bash
ns import ~/Downloads/my_project.hocon
```

Similarly, you can export an agent network and all its dependencies using the `ns export` command:

```bash
ns export my_project.hocon
```

See [`docs/cli/export.md`](docs/cli/export.md) for details.

### Command reference

<!-- pyml disable line-length -->

| Command             | Purpose                                                          | Key flags                                                                                                                                                                       |
|---------------------|------------------------------------------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `ns init`           | Scaffold a starter project in the current dir.                   | `--providers openai,anthropic,google`                                                                                                                                           |
| `ns run`            | Start the Neuro SAN server and nsflow UI.                        | `--server-host`, `--server-http-port`, `--nsflow-port`, `--log-level`, `--client-only`, `--server-only`                                                                         |
| `ns chat`           | Chat with an agent network directly (no server needed).          | Positional: agent name, `--connection`,  `--host`, `--port`, `--one-shot`, `--list`.                                                                                            |
| `ns import`         | Import agent networks into the current project.                  | Positional: space-separated group names, network names, or `all`; or local `.hocon` / `.zip` paths (don't mix the two). `--force` to overwrite. Omit args for interactive mode. |
| `ns export`         | Bundle a network from the current project into a shareable file. | Positional: network name (e.g. `music_nerd` or `basic/music_nerd`). `-o` / `--output` to set the output path. Omit args for interactive picker.                                 |
| `ns check-llm-keys` | Validate LLM API keys / env vars.                                | `--tier 1` (placeholder), `--tier 2` (format), `--tier 3` (live API call, default)                                                                                              |
| `ns check-config`   | Validate the LLM configurations in a HOCON file.                 | `--hocon-path` (defaults to `config/llm_config.hocon`)                                                                                                                          |

<!-- pyml enable line-length -->

Use `ns <command> --help` for the full flag list of any subcommand.

---

## Deliberating Agent Network Designer — how to test it

This repository changes `agent_network_designer` so that it **gathers requirements before it builds**, and
grounds what it builds in curated domain knowledge held as documents on disk.

Start the server, open the UI, and select **`agent_network_designer`**:

```bash
ns run
```

### What changed

- **It deliberates first.** The designer looks up curated knowledge for the domain you asked about, then
  interviews you one question at a time, waiting for each answer. It will not build until you approve.
- **Knowledge lives in documents, not in the prompt.** Each domain is a folder of `.md` files under
  `coded_tools/agent_network_designer/knowdocs/<domain>/`, read by the `ExtractDocs` coded tool — the same
  pattern `airline_policy` uses for its policy knowdocs. Documents are returned whole and verbatim, so an
  operating standard reaches the designed agents word for word, with its id intact.
- **It ends with a design brief** separating what you confirmed from what it assumed, and builds only on
  `APPROVED`.
- **Standards stay traceable.** Every operating standard is embedded in the agent that owns it as
  `MUST: <standard text> [<id>]`, and the closing summary maps each id to its owning agent.

Curated domains shipped here:

| Domain | `app_name` | Standard ids |
|---|---|---|
| Oracle database patching | `oracle_database_patching` | `ODB-01`…`ODB-06` |
| Kubernetes cluster upgrade | `kubernetes_cluster_upgrade` | `K8S-01`…`K8S-06` |
| Clinical trial database lock | `clinical_trial_database_lock` | `DBL-01`…`DBL-06` |

### Scenario 1 — a curated domain (Oracle)

Send each line as a separate turn and wait for the reply:

| You send | What should happen |
|---|---|
| `Build me an agent network for Oracle db patching` | Names the domain it matched, calls `ExtractDocs`, then asks **one** question (topology) with example answers |
| `Two-node RAC in prod with a Data Guard standby; dev and QA single instance.` | Asks the next question only |
| `Skip the questions, just build it.` | **Refuses**, names the few questions still open and what would go wrong if it guessed |
| `About 40 databases. DEV, then QA, then PROD. Four-hour Saturday window, PROD rolling with no full outage.` | Carries all of it forward, asks the next open variable |
| `DBA team takes the RMAN backup, verified restore point required. Production gated by a ServiceNow CR approved by CAB` | Asks the remaining variables |
| `opatch rollback, and the DBA team signs off connectivity.` | Presents the **design brief** |
| `APPROVED` | Builds the network and prints the standards-coverage table |

In the brief, check that: confirmed requirements contain only what you actually said; assumptions are
listed separately; the standards are quoted verbatim with `ODB-0x` ids; and the proposed shape names real
agents.

### Scenario 2 — a different curated domain (Kubernetes)

`Build me an agent network to upgrade our Kubernetes clusters`, then answer along the lines of:

- `AKS, three clusters: dev, staging, prod.`
- `1.29 to 1.31.` — it should treat this as two sequential minor upgrades, because `K8S-01` forbids skipping
- `Surge upgrade, we have spare capacity.`
- `Yes, stateful workloads with PVCs and strict PDBs on the payment service.`
- `assume sensible defaults` — a blanket instruction ends the interview and goes straight to the brief
- `APPROVED`

It should ask about node strategy and PodDisruptionBudgets — never about RMAN — and the brief should carry
`K8S-0x` ids. This is the check that the designer is driven by the documents rather than by one hardcoded
domain.

### Scenario 3 — a non-IT domain (clinical database lock)

`Build me an agent network for our clinical trial database lock process`, then:

- `Phase III, 120 sites, 900 subjects, double-blind.`
- `Medidata Rave with Argus for safety.`
- `Risk-based SDV on critical variables.`
- `assume sensible defaults`
- `APPROVED`

Expect questions about the SDV model, coding dictionaries and who authorises the lock, and `DBL-0x` ids in
the brief.

### Scenario 4 — a domain with no curated knowledge

`Build me an agent network for pizza delivery`

It must say it has **no curated knowledge** for that domain, name the domains it does have, state that its
standards are unverified — and then still interview you. Inventing confident "pizza standards" would be a
failure: the designer should only assert what the knowledge documents gave it.

### Check the generated network, not just the chat

```bash
ls registries/generated/
grep -c "MUST:" registries/generated/<name>.hocon
grep -oE "(ODB|K8S|DBL)-0[1-6]" registries/generated/<name>.hocon | sort -u
```

Each standard should appear inside the agent that owns it, verbatim, with its id — the backup gate carrying
the backup standard, the validation agent carrying the validation standard, and so on.

### Adding a domain

1. Create `coded_tools/agent_network_designer/knowdocs/<your_domain>/` with `operating_standards.md` and
   `open_variables.md` (copy an existing pair for the shape).
2. Add one line to `docs_path` in `coded_tools/agent_network_designer/extract_docs.py`.
3. Add the domain to the `ExtractDocs` description in `registries/agent_network_designer.hocon` so the
   designer knows it can be matched.

No prompt logic changes: the deliberation itself is domain-agnostic.

---

## User guide

Ready to dive in? Check out the [user guide](docs/user_guide.md) for a detailed overview of the neuro-san library
and its features.

---

## Tutorial

For a detailed tutorial, refer to [docs/tutorial.md](docs/tutorial.md).

---

## Examples

For examples of agent networks, check out [docs/examples.md](docs/examples.md).

---

## Developer Guide

For the development guide, check out [docs/dev_guide.md](docs/dev_guide.md).

---

## Community Projects

### Applications

* [Climate Change](https://github.com/cognizant-ai-lab/neuro-san-cc):
a tool to answer questions about COP, the Paris Agreement or the Kyoto Protocol using UNFCCC documents.
* [Enterprise Access Portal](https://github.com/M-Elsaied/enterprise-access-portal):
an AI-powered multi-agent system for managing enterprise application access requests and IT operations.
* [F1 fans eval](https://github.com/deepsaia/f1-fan-eval):
an app that evaluates F1 fan submissions about why they are the biggest F1 fans.
* [PDF Knowledge Assistant](https://github.com/M-Elsaied/neuro-san-studio/tree/pdf-knowledge-base/apps/pdf_knowledge_assistant):
a Flask web app that queries PDFs using RAG with topic-based long-term memory synthesis across documents.
* [Loopy Agents](https://github.com/babakatwork/loopy_agent):
run Neuro SAN agents continuously or on triggers through a separate service, with asynchronous messaging.
* [Annual Report Reader](https://github.com/shrushtiimehta/neuro-san-annual-report-reader):
analyzes a LinkedIn profile and delivers a personalized summary of Cognizant's 2024 Annual Report,
surfacing content most relevant to the user's industry and seniority level.
* [Tochiro File Organizer](https://github.com/ofrancon/tochiro):
a macOS file organization assistant with a dedicated UI to analyze a folder,
create a plan for moving the files, ask for approval and execute the moves.
* [Legacy Business-Rule Extractor](https://github.com/Sivakumarraj/neuro-san-legacy-analyzer):
a 6-agent network that extracts business rules from legacy COBOL, Java, and PL/SQL code,
pairing deterministic CodedTool parsers with LLM agents to produce a modernization-ready
specification document.

### Utilities

* [Neuro SAN Web Client](https://github.com/cognizant-ai-lab/neuro-san-web-client):
a basic Flask web client interface for Neuro SAN.
* [Neuro SAN Slack app](./apps/slack/README.md)
a Slack integration that lets you interact with Neuro SAN directly from your workspace.

---

## Links

* Website: [Cognizant AI Lab](https://www.cognizant.com/us/en/ai-lab)
* YouTube: [Decision AI](https://www.youtube.com/@decision-ai)
* X: [@cognizantailab](https://x.com/cognizantailab)
* LinkedIn: [Cognizant AI Lab](https://www.linkedin.com/showcase/cognizant-ai-lab)
* Amazon Marketplace: [Cognizant Neuro SAN](https://aws.amazon.com/marketplace/pp/prodview-z246c4x7j3xb6)
* Azure Marketplace: [Cognizant Neuro SAN](https://marketplace.microsoft.com/en-us/product/virtual-machine/cognizant.cognizant_neurosanai-application)

---

## More details

For more information, check out the [Cognizant AI Lab Neuro SAN landing page](https://www.cognizant.com/us/en/ai-lab/neuro-san).
