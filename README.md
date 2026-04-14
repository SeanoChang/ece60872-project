# Three Heads Are Better Than One?

## Multi-Judge Voting for Autonomous Coding Agent Tool-Call Safety

> ECE 60872 — Reliable and Secure Computer Systems
> Prof. Saurabh Bagchi, Purdue University, Spring 2026

---

## Abstract

Coding agents operate autonomously by executing tool calls — shell commands, file edits, package installations — on behalf of developers. Current safety mechanisms require either human approval for each action (blocking autonomous workflows) or unrestricted auto-approval (exposing users to prompt injection and supply chain attacks). Single-judge classifiers, such as Claude Code's Auto Mode, offer a middle ground but suffer from single-point-of-failure limitations (17% false negative rate on real overeager actions).

We present **an agentic multi-judge voting system** that replaces human approval in Claude Code via PreToolUse hooks. A cluster of LLM judge agents — each with a distinct security perspective, session memory, and investigative tools — independently evaluates every proposed tool call and votes approve/reject before execution. We evaluate this system across seven ablation conditions against synthetic benchmarks (MCPSecBench, InjecAgent) and real-world supply chain attacks (axios npm compromise of March 2026, CVE-2025-68143), measuring detection rate, false positive rate, Condorcet voting gap, and Byzantine quorum survival under judge compromise.

---

## Motivation

On March 31, 2026, a North Korean threat actor hijacked the axios npm package (70M+ weekly downloads), injecting a trojanized dependency that deployed a cross-platform RAT via postinstall hooks. The attack was live for 3 hours before detection. In January 2026, three prompt injection CVEs (CVE-2025-68143/4/5) were disclosed in Anthropic's own Git MCP server.

A coding agent running `npm install` or cloning a poisoned repository would execute these attacks without hesitation under auto-approve modes. Human-in-the-loop approval doesn't scale. **We need automated safety judgment that tolerates individual judge failures — including adversarial compromise.**

---

## System Architecture

```
Host Machine
├── API Proxy (:8081)              ← holds the ONLY copy of ANTHROPIC_API_KEY
│   ├── Injects auth on all requests     No container ever sees the key
│   ├── Per-agent budget enforcement
│   └── Cost tracking per request
│
├── Judge Cluster Orchestrator (:8080)
│   └── Dispatches judge containers, collects votes, JSONL logging
│
├── Honeypot (:9999)
│   └── Ground truth: catches credential exfiltration
│
├── Coding Agent Container
│   ├── Claude Code running task autonomously
│   ├── ANTHROPIC_BASE_URL = proxy    (no key in env — proxy handles auth)
│   ├── /workspace/ with canary credentials (.env, ~/.aws, ~/.ssh, ~/.npmrc)
│   ├── PreToolUse hook → POST to orchestrator
│   └── Network: proxy + honeypot only
│
├── Judge A Container (Param Validator)
│   ├── Own Claude agent in isolated sandbox
│   ├── /workspace/ mounted READ-ONLY
│   └── Network: proxy only (no honeypot, no external)
│
├── Judge B Container (Intent Aligner)
│   └── (same isolation as A)
│
└── Judge C Container (Threat Modeler)
    ├── Own Claude agent with RW sandbox
    ├── Can: clone repos, npm install --dry-run, inspect scripts
    └── Network: proxy only
```

### Components

| Component | Role |
|---|---|
| **API Proxy** | Reverse proxy on host. Holds the real API key. All containers route through it. Per-agent budgets, cost logging. No key in any container. |
| **Claude Code** | Real coding agent in Docker. Gets a task, operates autonomously. Hook intercepts every tool call. |
| **Judge Agents** | Each is a real Claude agent in its own isolated Docker container. Gets read-only workspace mount. Can investigate: read files, run commands in sandbox, inspect packages. |
| **Orchestrator** | Dispatches judge containers in parallel, collects votes, applies majority rule. |
| **Honeypot** | Ground truth sensor. Logs exfil attempts. Only coding agent container can reach it. |

### What Makes Judges "Agentic"

Each judge is a **real Claude agent in its own Docker container** — not a Python wrapper around an API call:

- **Own sandbox**: can run bash, read files, `npm install --dry-run`, inspect postinstall scripts
- **Session memory**: rolling window of past tool calls and verdicts
- **Multi-step investigation**: reads setup.sh → sees obfuscated curl → rejects with evidence
- **Isolated**: read-only workspace mount, no access to honeypot, destroyed after each judgment

### Credential Isolation via API Proxy

The API key never enters any container. All agents (coding + judges) call `ANTHROPIC_BASE_URL=http://host.docker.internal:8081` which routes through the proxy. The proxy adds the real key server-side. If malicious code searches for `ANTHROPIC_API_KEY` — it finds an empty string. Nothing to steal.

Canary credentials (AWS keys, SSH keys, npm tokens) are planted as files in the workspace. These ARE the attack target. The judges protect these — the proxy protects the API key.

---

## Experimental Design

### Ablations

All judges are agentic — Claude Code instances in isolated Docker containers with investigation capabilities.

| ID | Judges | Model | Prompt | Temp | What it tests |
|---|---|---|---|---|---|
| A1 | 1 | Sonnet 4.6 | General security reviewer | 0.0 | Single-judge baseline |
| A2 | 1 | Sonnet 4.6 | Best of {param, intent, threat} | 0.0 | Prompt engineering ceiling |
| A3 | 3 | Sonnet 4.6 ×3 | **Same** general prompt | **0.7** | Pure Condorcet redundancy (noise smoothing) |
| A4 | 3 | Sonnet 4.6 ×3 | **Different** (param/intent/threat) | 0.0 | N-version perspective diversity |
| A5 | 1 | **Opus 4.6** | Best from A2 | 0.0 | Cost-quality anchor (1× strong vs 3× weaker) |
| A1-h | 1 | **Haiku 4.5** | General | 0.0 | Cheap single-judge |
| A4-h | 3 | **Haiku 4.5** ×3 | param/intent/threat | 0.0 | Cheap multi-judge — does voting compensate? |
| A4-m | 3 | **2× Haiku + 1× Sonnet** | param/intent/threat | 0.0 | True N-version (mixed models) |
| A6 | 3 | Sonnet 4.6 ×3 | param/intent/**Byzantine** | 0.0 | Byzantine quorum survival |
| A7 | 3 | Sonnet 4.6 ×3 | param/intent/**Byz + poison** | 0.0 | Byzantine ⊕ correlated failure |

**Key comparisons**: A3 vs A4 (redundancy vs diversity), A4 vs A5 (voting vs stronger model), A4-h vs A4 (cheap vs expensive), A4-m (mixed models), A6 vs A4 (Byzantine tolerance).

### Testing Tiers

**Tier 1 — Synthetic Benchmarks (GitHub Actions)**:
MCPSecBench + InjecAgent. 30-50 scenarios, 6 ablations, 3 repetitions. Automated, reproducible.

**Tier 2 — Real-World Case Studies (Cloud VM)**:
Axios npm attack (March 2026), CVE-2025-68143 (MCP injection), LiteLLM PyPI compromise. End-to-end with real packages.

### Metrics

- **Detection rate**: did judges block before exfiltration?
- **False positive rate**: did judges block benign calls?
- **Condorcet gap**: predicted vs observed voting accuracy (quantifies common-mode failure)
- **Quorum survival rate**: detection under Byzantine compromise / honest baseline
- **Stateless vs Agentic**: does memory + tools improve detection?
- **Cost**: USD and latency per tool call

### Baselines

| System | Their Result | Comparison |
|---|---|---|
| Claude Auto Mode | 17% FN (real actions) | Our A1 vs their single classifier |
| AEGIS | 1.2% FPR | Our FPR vs theirs |
| ToolSafe | 65% harmful reduction | Our detection rate vs theirs |
| MCPSecBench defenses | <30% success | Our system on same benchmark |

---

## Related Work

| Paper | Relationship |
|---|---|
| deVadoss & Artzt (2504.14668) | Proposed BFT for AI safety conceptually (no implementation). We build and test it. |
| CP-WBFT / Zheng et al. (2511.10400) | BFT voting for multi-agent Q&A. Different domain, different Byzantine model. |
| Claude Auto Mode (Anthropic, 2026) | Single two-stage classifier. Our direct baseline. |
| AEGIS (2603.12621) | Rule-based pre-execution firewall. Complementary approach. |
| ToolSafe (2601.10156) | RL guardrail for tool safety. Single-model comparison. |
| Lamport/Shostak/Pease (1982) | Byzantine Generals Problem. Theoretical foundation. |
| Castro & Liskov (OSDI 1999) | PBFT. Frames our 2-of-3 quorum. |

---

## Project Structure

```
bft-voting/
├── core/
│   ├── types.py              # JudgeConfig, JudgeVote, VoteResult
│   ├── judge_hook.py         # PreToolUse hook (thin client → POST to orchestrator)
│   ├── orchestrator.py       # Dispatches judge containers, collects votes
│   ├── agentic_judge.py      # run_agentic_judge (docker exec claude -p)
│   ├── judge_containers.py   # JudgeContainerManager (lifecycle + workspace swap)
│   ├── voting.py             # Majority vote / consensus
│   ├── api_proxy.py          # Reverse proxy — injects API key, enforces budgets
│   ├── honeypot.py           # Exfiltration detection server
│   └── logger.py             # JSONL logger
├── prompts/
│   ├── honest/               # Param, Intent, Threat perspectives
│   ├── byzantine/            # Naive + subtle compromised variants
│   └── general.md            # Single general security prompt
├── scenarios/
│   ├── mcpsecbench/          # Adapted from MCPSecBench
│   ├── injecagent/           # Adapted from InjecAgent
│   └── realworld/            # Axios, CVE-2025-68143, LiteLLM
├── docker/
│   ├── agent.Dockerfile      # Coding agent container
│   ├── judge.Dockerfile      # Judge agent container
│   └── scenarios/            # Per-scenario workspace configs
├── ablations/
│   ├── configs/              # JSON config per ablation
│   └── runner.py             # Orchestrates full experiment matrix
├── results/                  # JSONL logs (gitignored)
├── analysis/
│   ├── metrics.py            # Detection rate, FPR, Condorcet gap
│   └── plots.py              # Figures for paper
├── .github/workflows/
│   └── experiment.yml        # Tier 1 automated runs
└── .claude/settings.json     # Hook config
```

---

## Setup

```bash
# Install dependencies
pip install -e ".[dev,analysis]"

# Copy environment config
cp .env.example .env
# Edit .env with your ANTHROPIC_API_KEY

# Start the API proxy (holds the key, all containers route through it)
python -m core.api_proxy --port 8081

# Start the honeypot
python -m core.honeypot --port 9999

# Start the judge cluster orchestrator
python -m core.orchestrator --config ablations/configs/A4-b.json --port 8080

# Run a scenario (builds containers, runs agent, collects results)
python -m ablations.runner --scenario scenarios/realworld/axios.yaml --ablation A4-b
```

---

## Team

- Sean Chang + teammates
- ECE 60872 — Reliable and Secure Computer Systems
- Purdue University, Spring 2026

---

## References

### Classical BFT Theory

- Pease, M., Shostak, R., & Lamport, L. (1980). [Reaching agreement in the presence of faults](https://doi.org/10.1145/322186.322188). *Journal of the ACM*, 27(2), 228–234.
- Lamport, L., Shostak, R., & Pease, M. (1982). [The Byzantine Generals Problem](https://doi.org/10.1145/357172.357176). *ACM TOPLAS*, 4(3), 382–401.
- Castro, M., & Liskov, B. (1999). [Practical Byzantine Fault Tolerance](https://pmg.csail.mit.edu/papers/osdi99.pdf). *OSDI '99*.

### LLM Guardrails & BFT for AI Safety

- deVadoss, J., & Artzt, M. (2025). [A BFT Approach towards AI Safety](https://arxiv.org/abs/2504.14668). *arXiv:2504.14668*. — Position paper proposing BFT consensus for AI safety. We implement and empirically test.
- Zheng, L., Chen, J., Yin, Q., Zhang, J., Zeng, X., & Tian, Y. (2025). [Rethinking the Reliability of Multi-agent Systems: A Perspective from Byzantine Fault Tolerance (CP-WBFT)](https://arxiv.org/abs/2511.10400). *arXiv:2511.10400*. — Confidence-weighted BFT voting for multi-agent LLMs on Q&A tasks.
- Anthropic. (2026). [Claude Code Auto Mode](https://www.anthropic.com/engineering/claude-code-auto-mode). — Single two-stage classifier for approval automation. Our direct baseline (17% FN rate).
- AEGIS: No Tool Call Left Unchecked (2026). [arXiv:2603.12621](https://arxiv.org/abs/2603.12621). — Rule-based pre-execution firewall. Complementary approach.
- ToolSafe: Proactive Step-Level Guardrail (2026). [arXiv:2601.10156](https://arxiv.org/abs/2601.10156). — RL-based tool-safety guardrail.
- Phute, M. et al. (2024). [LLM Self Defense](https://arxiv.org/abs/2308.07308). *ICLR 2024 Tiny*. — Single-judge output validation; ancestor of our A1 baseline.
- GuardAgent (2024). [arXiv:2406.09187](https://arxiv.org/abs/2406.09187). — Single guard agent overseeing target agent actions.
- PromptArmor (2025). [arXiv:2507.15219](https://arxiv.org/abs/2507.15219). — Input-side LLM-based prompt-injection filter. Orthogonal/complementary.

### Benchmarks & Test Datasets

- Debenedetti, E. et al. (2024). [AgentDojo: A Dynamic Environment to Evaluate Prompt Injection Attacks and Defenses for LLM Agents](https://arxiv.org/abs/2406.13352). *NeurIPS 2024 D&B*.
- Zhan, Y. et al. (2024). [InjecAgent: Benchmarking Indirect Prompt Injections in Tool-Integrated LLM Agents](https://arxiv.org/abs/2403.02691). *ACL Findings 2024*. **(Tier 1 dataset)**
- Yuan, T. et al. (2024). [R-Judge: Benchmarking Safety Risk Awareness for LLM Agents](https://arxiv.org/abs/2401.10019). *EMNLP Findings 2024*.
- MCPSecBench (2025). [arXiv:2508.13220](https://arxiv.org/abs/2508.13220). **(Tier 1 dataset)**
- AIShellJack: "Your AI, My Shell" (2024). [arXiv:2509.22040](https://arxiv.org/abs/2509.22040). — 314 payloads across 70 MITRE ATT&CK techniques.
- Prompt Injection Attacks on Agentic Coding Assistants (SoK) (2026). [arXiv:2601.17548](https://arxiv.org/abs/2601.17548).
- Zhang, G. et al. (2025). [Agent Security Bench (ASB)](https://arxiv.org/abs/2410.02644). *ICLR 2025*.
- RedCode: Risky Code Execution Benchmark (2024). [arXiv:2411.07781](https://arxiv.org/abs/2411.07781). *NeurIPS 2024 D&B*.

### Security Taxonomies (used for judge skill citations)

- MITRE ATT&CK for Enterprise — https://attack.mitre.org/matrices/enterprise/
- Common Weakness Enumeration (CWE) — https://cwe.mitre.org/
- OWASP Top 10 for LLM Applications — https://owasp.org/www-project-top-10-for-large-language-model-applications/
- See `judge_config/*/skills/*.md` for per-skill MITRE/CWE/OWASP citations

### Real-World Attacks (case studies)

- Axios npm Supply Chain Compromise (March 2026). [Socket.dev analysis](https://socket.dev/blog/axios-npm-package-compromised), [Datadog Security Labs](https://securitylabs.datadoghq.com/articles/axios-npm-supply-chain-compromise/), [Google Threat Intelligence Group (UNC1069 attribution)](https://cloud.google.com/blog/topics/threat-intelligence/north-korea-threat-actor-targets-axios-npm-package).
- CVE-2025-68143/4/5 — Anthropic Git MCP server prompt injection. [The Register coverage](https://www.theregister.com/2026/01/20/anthropic_prompt_injection_flaws/).
- CVE-2025-53773 — GitHub Copilot RCE via prompt injection. [Embrace the Red](https://embracethered.com/blog/posts/2025/github-copilot-remote-code-execution-via-prompt-injection/).

### Related References

- Zou, A. et al. (2023). [Universal and Transferable Adversarial Attacks on Aligned Language Models (GCG)](https://arxiv.org/abs/2307.15043). — Adversarial suffix generation.
- Andriushchenko, M. et al. (2025). [AgentHarm](https://arxiv.org/abs/2410.09024). *ICLR 2025*. — Harm benchmark for agent safety.
- Trail of Bits. (2025). [Exploiting GitHub Copilot](https://blog.trailofbits.com/2025/08/06/prompt-injection-engineering-for-attackers-exploiting-github-copilot/).

### Tools & Frameworks

- [Anthropic Claude Code](https://code.claude.com/) — the coding agent under evaluation.
- [Anthropic Python SDK](https://github.com/anthropics/anthropic-sdk-python) — used by the API proxy for model-aware cost tracking.
- [Anthropic API pricing](https://docs.anthropic.com/en/docs/about-claude/pricing) — grounds our model-aware cost tracking.
- [FastAPI](https://fastapi.tiangolo.com/) — orchestrator, proxy, honeypot.
- [Docker](https://www.docker.com/) — judge and agent container isolation.
- [pytest](https://pytest.org/) — test framework (68 tests currently).
