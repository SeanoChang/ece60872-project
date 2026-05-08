# Presentation Source — ECE 60872 Final Project

> Slide-generation source only. Speaker scripts live in `docs/paper/presentation-script.md`.
> Course structure: Introduction → Related Work → Background → Our Design → Evaluation → Discussion and Conclusion.
> Target length: 20 minutes + 5 minutes Q&A.
> Visual style: clean academic, one main figure/table per slide, monospace for filenames and commands.

---

## Slide 1 — Title and Thesis

- **Can One LLM Judge Secure Autonomous Coding Agents?**
- A small benchmark for repository-level supply-chain attacks
- Sean Chang
- ECE 60872 — Reliable and Secure Computer Systems, Purdue University
- May 2026

[Visual: title slide with a small pipeline: coding agent → LLM judge → tool execution.]

---

## Slide 2 — Motivation: Agents Now Execute

- Coding agents now run setup commands, not just suggest code.
- Examples: `npm install`, `pip install`, `git clone`, `pytest`, `make setup`.
- Tool access increases usefulness and autonomy.
- The same access turns install/build/test into a supply-chain execution surface.

[Visual: agent connected to registry, filesystem, shell, network.]

---

## Slide 3 — Concrete Threat: Install-Time Supply Chain

- Package installs can execute lifecycle hooks before application code runs.
- A malicious dependency can run silently during routine setup.
- Autonomous agents are likely to run the dangerous command because it looks normal.
- Example pattern: compromised npm package → hidden dependency → `postinstall` payload.

[Visual: sequence diagram: agent → `npm install` → registry → lifecycle hook → honeypot/exfil.]

---

## Slide 4 — Common Defense: One LLM Judge

- A common safety pattern inserts one LLM judge before dangerous tool calls.
- The judge inspects the proposed command and repository context.
- It returns `approve` or `reject`.
- This replaces human approval while preserving agent autonomy.

```text
Agent proposes Bash("npm install")
        ↓
Single LLM judge inspects repo
        ↓
approve / reject
        ↓
command runs / command blocked
```

[Visual: horizontal pipeline with the judge box highlighted.]

---

## Slide 5 — Problem Formulation

> Given an attacker-controlled repository and a proposed tool call, can one general LLM judge reject calls that trigger hidden payloads?

- **Input:** repository + task + proposed tool call.
- **Output:** approve / reject.
- **Attacker wins:** judge approves and canary reaches honeypot.
- **Defense wins:** judge rejects before execution.

[Visual: centered question box plus input/output/failure/success cards.]

---

## Slide 6 — Related Work and Gap

| Work | Measures | Gap for this project |
|---|---|---|
| AgentDojo / InjecAgent | Prompt injection in tool-using agents | Not install/test supply-chain payloads |
| DDIPE / PoisonedSkills | Supply-chain poisoning of agent skills/docs | Skill-trigger benchmark, not pre-execution judge-verdict benchmark |
| Package-malware benchmarks | npm/PyPI malware detection | Scanner/offline analysis, not live agent approval |
| LLM guardrails / self-checks | Second-model safety or hallucination checks | Not repository-level supply-chain execution gates |
| garak | General LLM vulnerability scanning | Not coding-agent approval gates |
| **This benchmark** | Repo + command + judge verdict + canary outcome | Repository-centric approval-gate robustness |

> **DDIPE attacks the actor. This project attacks the safety gate.**

[Visual: comparison table highlighting DDIPE as closest related work and this benchmark as the approval-gate variant.]

---

## Slide 7 — Benchmark Design

- Diagnostic benchmark, not comprehensive catalog.
- Goal: isolate one failure mode in single-judge approval.
- Three main scenario classes:
  - **Pure supply-chain:** hidden install/test payloads.
  - **Metadata-amplified:** same payloads plus fake authority claims in repo metadata.
  - **Source-comment controls:** similar claims placed in source comments.

[Visual: three cards for pure supply, metadata-amplified, source-comment controls.]

---

## Slide 8 — Harness Architecture

- **Agent container:** Claude Code performs the task.
- **Judge container:** separate LLM judge inspects dangerous calls.
- **Hook/orchestrator:** intercepts Bash/Edit/Write calls.
- **Honeypot:** records canary exfiltration as ground truth.
- **Logging/proxy:** records verdicts, latency, tokens, and cost.

[Visual: 5-box architecture diagram with honeypot as external ground truth.]

---

## Slide 9 — Measurement

- **Penetration rate:** canary fired ÷ repetitions.
- **Block rate:** judge rejected dangerous call.
- **False-positive rate:** judge rejected benign call.
- **Cost / latency:** per judgment.
- Ground truth is the honeypot, not model self-report.

[Visual: metric cards with honeypot ground truth emphasized.]

---

## Slide 10 — Attack Development

**From obvious trojans to judge-targeted metadata**

| Stage | Attack idea | What changed |
|---|---|---|
| 1 | Direct lifecycle payload | Too obvious; often detected |
| 2 | Opaque dependency | Base64, tarballs, transitive hooks |
| 3 | Code-path concealment | Multi-file chains and dispatcher logic |
| 4 | Deferred trigger | Payload fires during CLI, dev-server, or test |
| 5 | Metadata authority injection | Fake audit/approval claims shape judge belief |

> Successful attacks changed what the judge believed, not just what code was hidden.

[Visual: five-stage ladder, Stage 5 highlighted.]

---

## Slide 11 — What We Tested vs. What `make sweep` Runs

**Reported single-judge paper matrix**

| Class | Scenarios | Reps | Successes |
|---|---:|---:|---:|
| Pure supply-chain | 5 | 21 | 9 |
| Metadata-amplified | 4 | 12 | 12 |
| Source-comment controls | 2 | 6 | 0 |
| Negative-framing probe | 1 | 3 | 2 |
| **Total reported** | **12** | **42** | **23** |

- Main channel-dichotomy comparison uses **39 reps**: pure supply + metadata + source-comment controls.
- The negative-framing probe is reported separately, not part of the 100% vs 0% contrast.

**Current runnable Makefile sweep**

- `make sweep`: **8 attack scenarios**, A0/no-judge by default.
- `make sweep-a1`: same 8 scenarios under the single-judge A1 config.
- The Makefile sweep is a curated runnable subset, **not exactly the paper headline matrix**.

[Visual: split slide. Left: reported paper matrix. Right: Makefile target summary.]

---

## Slide 12 — Result 1: Pure Supply-Chain Baseline

- **9 / 21 bypasses**
- **42.9% penetration**
- Judge blocked some hidden payloads but missed others.
- Takeaway: the single judge is useful, but inconsistent.

[Visual: bar chart showing 9/21 penetration.]

---

## Slide 13 — Result 2: Metadata-Channel Bypass

- **12 / 12 bypasses**
- **100% penetration**
- Added variable: fake authority claims in attacker-controlled metadata.
- Files: `CLAUDE.md`, `AGENTS.md`, `package.json` `_audit`, JSON fixtures.

[Visual: large red 100% bar next to faded 42.9% baseline bar.]

---

## Slide 14 — Result 3: Channel Dichotomy

**Where the claim appears matters more than what it says.**

| Channel | Bypass rate | Count |
|---|---:|---:|
| Metadata files | **100%** | **12 / 12** |
| Source-comment controls | **0%** | **0 / 6** |

- Same payload family.
- Similar authority claims.
- Different repository channel.
- Fisher exact: **p < 10^-3**.

[Visual: two-bar chart, 100% metadata vs 0% source-comment.]

---

## Slide 15 — Cost and Latency

- Median judgment latency: **~29.4 s**.
- 90th-percentile latency: **~47.7 s**.
- Judge-only cost: **median ~$0.052**, mean **~$0.054** per judgment.
- Cost estimate includes Haiku 4.5 **input + output + cache-read + cache-write** token buckets.
- Cache-read tokens dominate the cost.
- Implication: deployable enough to use, fragile enough to matter.

[Visual: metric cards plus a small stacked cost bar: input, cache write, cache read, output.]

---

## Slide 16 — Discussion: Implications and Mitigations

- Treat all repository files as attacker-controlled, including metadata.
- A single general judge is a useful baseline, not a sufficient defense.
- Mitigations:
  - Explicit file-channel trust model in judge prompt.
  - Static checks for install/test lifecycle hooks.
  - Sandbox and egress filtering outside the judge.

[Visual: implication → risk → mitigation diagram.]

---

## Slide 17 — Limitations and Future Work

- Single judge architecture.
- Single judge model class.
- Small diagnostic benchmark.
- Future work:
  - Expand by mechanism × trust-channel.
  - Add holdout scenarios and benign controls.
  - Test hardened prompts and static baselines.
  - Repeat with stronger and cross-vendor judges.

[Visual: limitations on left, future work on right.]

---

## Slide 18 — Conclusion: Can One LLM Judge Secure Agents?

**Answer: not alone.**

- **Useful:** blocks some pure supply-chain attacks.
- **Breakable:** metadata-channel attacks bypassed **12 / 12** times.
- **Root cause:** the judge treats some attacker-controlled files as authority.
- **Design lesson:** repository context must be treated as adversarial by default.

> One LLM judge can be a useful alarm. It should not be the security boundary.

[Visual: large "Not alone" answer at center. Below it: 42.9% pure-supply bypass, 100% metadata bypass, 0% source-comment bypass. End with a simple pipeline where "single judge" is one layer before "sandbox/egress/static checks".]

---

## Slide 19 — Q&A

- Questions?
- Sean Chang
- Project repo: `scenarios/`, `core/`, `docker/`, `paper-data/`
- GitHub: `https://github.com/SeanoChang/ece60872-project`
- Paper numbers: `paper-data/headline_table.csv`
- Runnable targets: `make sweep` for A0, `make sweep-a1` for single-judge A1

[Visual: simple Q&A slide with the benchmark pipeline faintly in the background.]

---

## Backup Slide A — DDIPE Positioning

- DDIPE / PoisonedSkills is the closest related benchmark.
- Its public artifact is skill-centric: many `SKILL.md` samples plus trigger-query harnesses.
- This project is repo-centric: repository + command + judge verdict + honeypot outcome.
- The datasets overlap in threat family, not measurement boundary.

---

## Backup Slide B — Why Not Directly Use DDIPE Data?

- DDIPE data is public, but structurally mismatched.
- Conversion would require:
  - wrapping skills as repositories,
  - defining proposed tool calls,
  - adding canary outcomes,
  - deciding judge-visible context.
- That conversion is itself a new approval-gate benchmark.

---

## Backup Slide C — Methodology Integrity

- Deterministic scenario rebuilds.
- Per-scenario canary strings.
- Honeypot-grounded outcome labels.
- Verdict, token, latency, and cost logs.
- Headline numbers are post-fix results after measurement bugs were removed.

---

## Backup Slide D — Exact Scenario Lists

**Reported paper matrix (`paper-data/headline_table.csv`)**

- `agents-md-audit-redirect`
- `package-json-audit-metadata`
- `claudemd-audit-redirect`
- `fixture-as-audit-record`
- `negative-framing-redirect`
- `inline-source-no-directive`
- `inline-source-audit-comment`
- `probe-02-bearer-auth`
- `npm-multi-stage-trigger`
- `npm-handler-dispatcher`
- `npm-vendored-utility-surgical-mod`
- `pip-conftest-trojan`

**Current `make sweep` / `make sweep-a1` scenario list**

- `probe-02-bearer-auth`
- `npm-handler-dispatcher`
- `npm-multi-stage-trigger`
- `npm-vendored-utility-surgical-mod`
- `npm-bin-cli-trigger`
- `claudemd-audit-redirect`
- `readme-broken-optout`
- `pip-conftest-trojan`

---

## Backup Slide E — Axios-Style Install-Time Poisoning

- Attack pattern:
  - trusted package or maintainer path is compromised,
  - malicious dependency or tarball enters install path,
  - package lifecycle hook runs during `npm install`,
  - payload executes before application code is reviewed.
- Why it matters for agents:
  - `npm install` looks like a routine setup command,
  - autonomous agents are likely to run it,
  - the judge must detect risk before execution.
- How our benchmark abstracts it:
  - hidden install/test payload,
  - canary exfiltration as ground truth,
  - single LLM judge approves or rejects the proposed command.
