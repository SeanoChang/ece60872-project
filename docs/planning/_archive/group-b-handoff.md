# Paper 2 — Group B Handoff (Code-Side)

> Code-side mirror of the Obsidian `Group B — Direction 2 Byzantine Compromise.md`.
> Top-level handoff lives at `HANDOFF.md` in the repo root.
> Locked 2026-04-17 at tag `v0.1-shared-scaffold`.

---

## Title (working)

*"Does Byzantine Fault Tolerance Transfer? Quorum Survival Under Single-Judge Prompt Compromise in LLM Agentic Voting"*

## Research Question (one)

**Does 2-of-3 LLM-agentic majority voting retain its detection rate when one judge's system prompt is replaced with a Byzantine ("always approve") variant?**

## Headline Metric

```
S = detection_rate(A6) / detection_rate(A4)
```

- `S = 1.0`: PBFT transfers cleanly
- `S = 0.0`: Quorum collapses
- Intermediate: partial transfer, per-archetype breakdown

Reported with 95% bootstrap CI over 3 reps × 10 malicious scenarios.

## Ablation Matrix (Minimal)

| ID | Judges | Model | Prompt |
|---|---|---|---|
| **A4** | 3 | Sonnet 4.6 ×3 | Param / Intent / Threat (honest) |
| **A6** | 3 | Sonnet 4.6 ×3 | Param / Intent / **Byzantine-Threat (naive)** |

Two conditions × ~15 scenarios × 3 reps = ~180 runs. A4 may be inherited from Group A's run (saves ~$15, 2 hours).

## Classical Anchoring

| Concept | Paper instantiation | Citation |
|---|---|---|
| Byzantine Generals Problem | One judge adversarial; others must reach correct decision by majority | Lamport 1982 |
| PBFT 3f+1 bound | 2-of-3 tolerates f=1 Byzantine | Castro & Liskov 1999 |
| Byzantine Quorum Systems | Our 2-of-3 is minimal BQS | Malkhi & Reiter 1998 |
| Independence assumption | PBFT requires it; LLM judges share substrate — questionable | Classical reliability literature |

## Byzantine Prompt (Naive Variant)

Already in repo at `judge_config/byzantine/naive/IDENTITY.md` and `prompts/byzantine/naive.md`.

Takes the honest Threat Modeler prompt and appends an "always approve" override. Grounded in Maloyan & Namiot (2025)'s CUA methodology — published attack, not ad-hoc. Cite in §2.

## Mandatory Daylight Sentences (§2 Related Work)

1. *"Prior work on LLM-as-judge ensembles [Maloyan'25] measures attack success under **shared-input prompt injection** — adversarial content visible to all judges. We measure quorum survival under **configuration compromise** — one voter's own system prompt is silently replaced."*

2. *"Unlike CP-WBFT [Zheng'25] and DecentLLMs [Jo'25], which propose new Byzantine-robust aggregation mechanisms and evaluate on QA/math, we perform the prerequisite measurement: does vanilla 2-of-3 majority voting transfer to agentic LLM judges on coding-agent tool-call safety at all?"*

3. *"Unlike persuasion-based subversion of multi-agent debate [Sci. Rep.'26; Amayuelas'24], our Byzantine voter does not debate — it is a silently-compromised voter casting a fixed vote in a single round, matching PBFT's independent-voter assumption."*

## Recommended Citations (12)

1. Lamport, Shostak & Pease (1982). *The Byzantine Generals Problem*.
2. Castro & Liskov (1999). *Practical Byzantine Fault Tolerance*.
3. Malkhi & Reiter (1998). *Byzantine Quorum Systems*.
4. Verga et al. ([2404.18796](https://arxiv.org/abs/2404.18796), 2024). PoLL.
5. Zhuge et al. ([2410.10934](https://arxiv.org/abs/2410.10934), 2024). Agent-as-a-Judge.
6. **Maloyan & Namiot ([2504.18333](https://arxiv.org/abs/2504.18333), 2025).**
7. Shi et al. (CCS 2024). JudgeDeceiver.
8. **Zheng et al. ([2511.10400](https://arxiv.org/abs/2511.10400), 2025). CP-WBFT.**
9. Luo et al. ([2505.05103](https://arxiv.org/abs/2505.05103), 2025). WBFT-MLLMN.
10. Jo et al. ([2507.14928](https://arxiv.org/abs/2507.14928), 2025). DecentLLMs.
11. Amayuelas et al. (EMNLP Findings 2024, [2406.14711](https://arxiv.org/abs/2406.14711)).
12. deVadoss & Artzt ([2504.14668](https://arxiv.org/abs/2504.14668), 2025). BFT for AI Safety.

## Group B Code Delta

**Keep all of shared scaffold unchanged.**

**Build new**:
- `analysis/quorum_survival.py` — ~30 lines: reads A4 + A6 JSONL, computes S per archetype with bootstrap CIs
- (Optional) `analysis/byzantine_detectability.py` — Byzantine vote vs honest-pair votes; post-hoc detectability
- `docs/paper/group-b/` — paper draft

## Week-by-Week

- **Apr 18–24**: Fork, smoke test on 2–3 scenarios, start A6 runs
- **Apr 25 – May 1**: Complete A4 + A6 matrices, compute S per archetype, figures
- **May 2 – May 8**: Paper iteration, internal cross-read, submit

## Paper Outline (2 pages)

- Abstract (~150w)
- §1 Intro (~200w): prompt-substitution realism + PBFT → RQ
- §2 Background (~250w): Byzantine Generals + PBFT + independence; related work with daylight sentences
- §3 Method (~280w): Replay agent + 3 judges + Byzantine via prompt-substitution
- §4 Results (~400w): Table 1 + Figure 1 + per-archetype S + honest-pair agreement
- §5 Discussion (~250w): PBFT-transfer verdict, limitations, future work (subtle, composition, cross-substrate)
- References: 10–12

---

## Companion

- `HANDOFF.md` (repo root) — full Group B handoff with setup commands
- `docs/planning/master-plan.md`
- `docs/planning/shared.md`
- `docs/planning/direction-1-plan.md` (Group A)
- Obsidian canonical: `Group B — Direction 2 Byzantine Compromise.md`
