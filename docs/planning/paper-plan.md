# Paper Plan (Code-Side)

> Code-side mirror of the Obsidian paper-plan note.
> Locked 2026-04-17 — single paper, four ablation conditions, two RQs.

---

## Title (working)

*"Does Triple Modular Redundancy Transfer to LLM Agentic Voting for Coding-Agent Tool-Call Safety? Plus a Byzantine-Tolerance Ablation."*

## Research Questions

Two RQs in one 2-page paper, both on the same scenario library and same honest-judge stack.

### RQ1 — TMR transfer

**Does 3-judge agentic majority voting detect trojaned codebases at a higher rate than a single agentic judge, and at what false-positive cost?**

### RQ2 — BFT transfer

**Does 2-of-3 agentic majority voting retain its detection rate when one judge's system prompt is silently replaced with a Byzantine ("always approve") variant?**

## Headline Metrics

```
Δ = detection_rate(A4) − detection_rate(A1)      # TMR transfer, RQ1
S = detection_rate(A6) / detection_rate(A4)      # BFT transfer, RQ2
```

Each reported with 95% bootstrap CI over 3 reps × ~10 malicious scenarios. FPR on 5 benign controls reported alongside Δ.

Additionally reported as context: **A0 detection rate** — the live coding agent's own self-defense rate against trojaned codebases with no voting guard. Voting's contribution (Δ) and Byzantine cost (1−S) are framed as incremental on top of this baseline.

## Ablation Matrix

| ID | Judges | Model | Prompt | Temp |
|---|---|---|---|---|
| **A0** | 0 | — (agent alone, no guard) | — | — |
| **A1** | 1 | Sonnet 4.6 | General security reviewer | 0.0 |
| **A4** | 3 | Sonnet 4.6 ×3 | Param / Intent / Threat (honest) | 0.0 |
| **A6** | 3 | Sonnet 4.6 ×3 | Param / Intent / **Byzantine-Threat (naive)** | 0.0 |

Four conditions × ~15 scenarios × 3 reps ≈ 180 runs. Wall clock ~4–6 hours. Budget ~$40.

## Classical Anchoring

| Concept | Paper instantiation | Citation |
|---|---|---|
| TMR | 2-of-3 agentic-judge majority vote (A4) | von Neumann 1956; Lyons & Vanderkulk 1962 |
| Condorcet Jury Theorem | Analytic prediction `P_maj = 3p² − 2p³` under independence | Condorcet 1785 |
| Coverage factor | Per-judge investigation success probability | Bouricius et al. 1969 |
| N-version programming | 3 specialist prompts (Param / Intent / Threat) | Avizienis & Chen 1977 |
| Byzantine Generals | One judge adversarial; majority must reach correct decision | Lamport, Shostak, Pease 1982 |
| PBFT 3f+1 | 2-of-3 tolerates f=1 Byzantine | Castro & Liskov 1999 |
| Byzantine Quorum Systems | Our 2-of-3 is minimal BQS | Malkhi & Reiter 1998 |
| Common-mode failure | Discussion: substrate-level correlation | IEEE Std 352 |

## Byzantine Prompt (Naive Variant)

Already in repo at `judge_config/byzantine/naive/IDENTITY.md` and `prompts/byzantine/naive.md`. Takes the honest Threat Modeler prompt and appends an "always approve" override. Design grounded in Maloyan & Namiot (2025)'s CUA methodology — published attack, not ad-hoc.

## Mandatory Daylight Sentences (§2 Related Work)

These three claims must appear in §2 to preempt reviewer objections, per the 2026-04-17 novelty audit:

1. *"No prior work measures the A1→A4 (single-judge vs 2-of-3 TMR majority) detection gap for **agentic** LLM judges — judges with filesystem access and investigation tools — applied to coding-agent tool-call admission against trojaned codebases. Prior multi-agent LLM safety work is either (i) non-agentic panels on text tasks [Verga'24, Zheng'25], (ii) single agentic judges [Xiang'24, ShieldAgent'25, Zhuge'24], or (iii) divided-labor pipelines for package-level classification [CHASE'26, LAMPS'26]."*

2. *"Unlike BFT/consensus work on multi-agent LLMs [Zheng'25], we anchor on classical TMR (von Neumann 1956; Lyons 1962) and PBFT (Castro-Liskov 1999) with 2-of-3 majority to isolate the redundancy gain attributable to voter independence in the Condorcet sense [Condorcet 1785] — not to a new consensus protocol."*

3. *"Prior work on LLM-as-judge ensembles under attack [Maloyan'25] measures success under **shared-input prompt injection** — adversarial content visible to all judges. We measure quorum survival under **configuration compromise** — one voter's own system prompt is silently replaced — matching PBFT's independent-voter assumption."*

Optional supplementary daylight (drop if §2 overflows): persuasion-based subversion of multi-agent debate [Sci. Rep.'26; Amayuelas'24] — our Byzantine voter does not debate, just casts a fixed vote.

## Recommended Citations (10–12)

1. von Neumann (1956). *Probabilistic Logics and the Synthesis of Reliable Organisms...*
2. Lyons & Vanderkulk (1962). IBM J. R&D — TMR implementation.
3. Condorcet (1785). *Essai sur l'application de l'analyse à la probabilité des décisions...*
4. Lamport, Shostak & Pease (1982). *The Byzantine Generals Problem*. ACM TOPLAS.
5. Castro & Liskov (1999). *Practical Byzantine Fault Tolerance*. OSDI.
6. Malkhi & Reiter (1998). *Byzantine Quorum Systems*.
7. Verga et al. ([2404.18796](https://arxiv.org/abs/2404.18796), 2024). PoLL.
8. Zheng et al. ([2511.10400](https://arxiv.org/abs/2511.10400), 2025). CP-WBFT.
9. Xiang et al. ([2406.09187](https://arxiv.org/abs/2406.09187), 2024). GuardAgent.
10. Zhuge et al. ([2410.10934](https://arxiv.org/abs/2410.10934), 2024). Agent-as-a-Judge.
11. Maloyan & Namiot ([2504.18333](https://arxiv.org/abs/2504.18333), 2025). Adversarial attacks on LLM-as-judge.
12. Lefort et al. ([2409.00094](https://arxiv.org/abs/2409.00094), 2024). Condorcet independence in LLM ensembles.

## Work Dispatch (default, subject to teammate's actual agreement)

### Sean

- Code + experiments: runner/orchestrator/judge pipeline, A0/A1/A4/A6 runs, metrics and aggregation
- Paper §3 Method

### Teammate

- Scenario library (complete the ~15 trojaned-codebase YAMLs; cross-label; `scenarios/label-disputes.md`)
- Paper §1 Intro + §2 Background + §4 Results figures + §5 Discussion

Weekly sync to confirm the split still fits. If teammate prefers a different slice, adjust.

## Week-by-Week

- **Week 2 remainder (Apr 18–24)**: Smoke test live runner on 2–3 scenarios. Complete scenario library. Run A0 (~30 min) and A1 (~45 min).
- **Week 3 (Apr 25 – May 1)**: Run A4 and A6. Compute Δ + S + A0 self-defense rate + per-archetype breakdowns + bootstrap CIs. Build Table 1 + Figure 1 + agreement-rate analysis. Draft §4 Results + §5 Discussion.
- **Week 4 (May 2 – May 8)**: Paper iteration, internal team cross-read, citation verification, camera-ready submit.

## Paper Outline (2 pages)

| Section | Words | Contents |
|---|---|---|
| Abstract | ~150 | TMR + BFT transfer measurements; Δ = X ± Y (CI), S = X ± Y (CI), A0 = X% |
| §1 Intro | ~200 | axios March 2026 + CVE-2025-68143 hook → RQ1 + RQ2 |
| §2 Background | ~250 | TMR + PBFT + Condorcet + independence; related work with the three daylight sentences |
| §3 Method | ~300 | Live Claude Code runner + 3 agentic judges + trojaned-codebase scenarios + A0/A1/A4/A6 matrix |
| §4 Results | ~400 | Table 1 (A0/A1/A4/A6 detection + FPR) + Figure 1 (Δ and S with CIs) + per-archetype + agreement-rate |
| §5 Discussion | ~250 | TMR-transfer verdict + BFT-transfer verdict + independence concerns + limitations + future work |
| References | 10–12 | See above |

## Companion

- `docs/planning/master-plan.md` — high-level scope + schedule
- `docs/planning/infrastructure.md` — shared infrastructure contract
- `scenarios/SOURCES.md` — scenario provenance manifest
- Obsidian canonical: `Paper Plan.md` in the vault
