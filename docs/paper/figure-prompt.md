# Prompt: Generate Paper Figures for `report.tex`

> **Copy everything below the `---` line into a Claude conversation.** The receiving Claude will produce three diagrams; render them, save to `docs/paper/figures/`, embed via `\includegraphics`.

---

## Role

You are a technical illustration assistant. I need three diagrams for an academic paper on coding-agent supply-chain trojan detection (ECE 60872 final report, single-column, 1-inch margins, 11pt). Choose whatever format and visual design produces the cleanest paper-quality output. I will embed the rendered images into `report.tex`.

## Output goal

For each figure, return:
- A self-contained source you can render or that I can render.
- A one-sentence caption I can paste into LaTeX `\caption{}`.
- A LaTeX include hint such as `\includegraphics[width=\textwidth]{figures/figN}`.

## Project context (use these exact labels)

The paper measures whether coding agents (Claude Code on Haiku 4.5) detect supply-chain trojans during `npm install` / `pip install` when running with `--dangerously-skip-permissions`. Across 33 runs over 11 trojan archetypes: 0/33 strict inspection coverage, 33/33 attack success.

Key technical objects:
- **Host services**: API Proxy on port 8081, Orchestrator on port 8080, Honeypot on port 9999 (FastAPI).
- **Container**: image `bft-agent:latest`, runs Claude Code 2.1 with `--dangerously-skip-permissions`.
- **Canary watcher**: polls `honeypot.jsonl` at 1 Hz; on hit, kills container in ~1 s.
- **Coverage factor**: c = Pr(R ∩ D | T) where R = "agent reads trojan source," D = "agent refuses install," T = "trojan present" (Bouricius 1969).

---

## Figure 1 — System architecture

**Content:** the experimental harness, organized as a host group and a container group connected by a feedback loop.

**Nodes:**
- Group "Host machine" containing:
  - "API Proxy" — port 8081 — "injects key, enforces budgets"
  - "Orchestrator" — port 8080 — "experiment driver"
  - "Honeypot" — port 9999 — "FastAPI; canary regex match"
- Group "Docker container `bft-agent:latest`" containing:
  - "Claude Code 2.1 + Haiku 4.5" — "`--dangerously-skip-permissions`"

**Edges:**
- Agent → API Proxy, label "API calls via proxy"
- Agent → Honeypot, label "trojan exfil POST"
- Honeypot → Orchestrator, label "canary fire event"
- Orchestrator → Agent, label "docker kill on canary"

**Caption:** "System architecture of the agent-vs-trojan harness. The runner agent executes inside a Docker container with `--dangerously-skip-permissions`; the host runs the proxy, orchestrator, and honeypot. The honeypot's canary fire event triggers immediate container termination via the orchestrator (median latency ~1 s)."

**LaTeX:** `\includegraphics[width=\textwidth]{figures/fig1-architecture}`. Reference as `Figure~\ref{fig:arch}`.

---

## Figure 2 — Coverage-factor pipeline

**Content:** the Bouricius 1969 fault-activation chain, with the agent's self-inspection as the coverage check between latent fault and activation.

**Nodes:**
- "Latent fault" — "trojan in repo"
- "Coverage check" — "c = Pr(R ∩ D | T)"
- "Activation" — "npm install runs postinstall hook"
- "Consequence" — "canary exfiltrated"
- "Refuse install"

**Edges:**
- Latent fault → Coverage check
- Coverage check → Refuse install, label "c = 1: detected, refused"
- Coverage check → Activation, label "c = 0: missed"
- Activation → Consequence

**Annotation below the diagram:** "Empirical c = 0 across 11 archetypes (this work)."

**Caption:** "Coverage-factor framing of agent self-inspection (after Bouricius et al.\ 1969). For a latent supply-chain trojan, the coverage check is the conditional probability that the agent reads the trojan source and refuses the dangerous call. We measure $c = 0$ across all 11 archetypes."

**LaTeX:** `\includegraphics[width=0.9\textwidth]{figures/fig2-coverage}`. Reference as `Figure~\ref{fig:coverage}`.

---

## Figure 3 — Threat model contrast

**Content:** the structural difference between Claude Code's two operating modes — the convenience flag removes the only working defense.

**Two parallel paths.**

**Top path "Default mode":**
- "Agent emits Bash call" → "Permission gate"
- Permission gate → "Bash runs", label "user approves"
- Permission gate → "blocked", label "user refuses"

**Bottom path "`--dangerously-skip-permissions`":**
- "Agent emits Bash call" → "(no gate)" → "Bash runs immediately"

**Annotation between the two paths:** "the convenience flag eliminates the only structural defense"

**Caption:** "Threat model contrast. In default mode, Claude Code's permission gate intercepts every Bash call before execution, and a user prompt can refuse. The `--dangerously-skip-permissions` flag removes the gate; the agent's own caution is the only remaining defense."

**LaTeX:** `\includegraphics[width=\textwidth]{figures/fig3-threat-model}`. Reference as `Figure~\ref{fig:threat}`.

---

## Output format

Return three sections in this order, one per figure:

```
## Figure N — <name>

[your diagram source]

**Caption:** "..."

**LaTeX:** \includegraphics[...]{figures/figN-...}
```

## Constraints

- Use only the labels listed under each figure's "Nodes" / "Edges" sections.
- The output must be reproducible from your source alone.
- Do not produce slides, prose, or LaTeX wrapping. Only the three diagrams, their captions, and the LaTeX include hints.

## What I'll do with the output

1. Render each diagram from your source.
2. Save to `docs/paper/figures/fig1-architecture.pdf`, `fig2-coverage.pdf`, `fig3-threat-model.pdf`.
3. Reference in `report.tex` via the include hints you provided.

Begin now. If anything is ambiguous, default to the simpler interpretation.
