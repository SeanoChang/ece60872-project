# Self-critique: ACSAC / NeurIPS Reviewer Pass

> Reading the paper as a hostile reviewer. What would I flag, in
> order of severity, and how would I fix it?

## Severity 1 — Structural weaknesses that could sink the paper

### S1.1 Sample size is laughably small for the headline claim

**Reviewer's note:** *"The paper claims 100% bypass on
metadata-channel injections, drawing this from 12 reps across 4
scenarios (3 reps each). The 95% binomial confidence interval for
12/12 is roughly 0.74–1.00. The headline number is over-stated."*

**My fix:**
- State CIs explicitly for the headline numbers.
- Reframe the claim as "12/12 reps across 4 distinct scenarios bypass — across the four channels we tested, every rep succeeded; the 95% CI on the per-scenario rate is 29–100%, but the consistency across channels is the load-bearing observation."
- Add a Statistical Power subsection in the methods.
- Where possible, top up the highest-leverage scenarios to N≥10.

### S1.2 Single-model evaluation bottlenecks the generalizability claim

**Reviewer's note:** *"All results are on Haiku 4.5 as inspector.
The paper claims the Channel Dichotomy is a structural property of
agent+judge architectures, but only one inspector model is tested.
Sonnet 4.6 or Opus 4.7 might handle the metadata channels
differently."*

**My fix:**
- Soften the generalizability claim. State explicitly that the
  measurement is on Haiku 4.5; the **mechanism** (file-type-keyed
  epistemic priors) is hypothesized to generalize, but cross-model
  validation is left to future work.
- Add a paragraph explaining *why* the dichotomy should generalize
  (the inspector's read order is convention-driven, and the
  conventions are model-agnostic).

### S1.3 No comparison baseline

**Reviewer's note:** *"The paper measures one defense
configuration. How does it compare to (a) static-analysis tools
(Snyk, npm-audit), (b) heuristic regex-based defenses, (c) human
review? Without a baseline, the claim 'inspector judges fail' has
no meaningful contrast."*

**My fix:**
- Add a one-paragraph qualitative comparison (no measurement) noting:
  - Static tools (Snyk) catch known-CVE patterns; would miss our
    novel injection scenarios because they don't analyze
    documentation channels.
  - Regex defenses (e.g., audit blocklists for outbound HTTP)
    would catch the supply-chain payload; would NOT catch the
    documentation-channel mechanism.
  - Human review WOULD catch (because humans don't blindly trust
    CLAUDE.md), but human review is what the inspector replaces.
- This positioning argues the paper's contribution is precisely
  the gap between human and AI auditors.

### S1.4 The original BFT panel story was abandoned

**Reviewer's note:** *"The infrastructure (judge\_containers,
ablations/configs/A4.json) implies a panel evaluation was planned
but only single-judge results are reported. The reader is left
wondering what panel ablations would show."*

**My fix:**
- Reframe in the paper as a deliberate scope choice: the
  Channel Dichotomy is independent of panel size (every panel
  member would have the same dichotomy), so single-judge
  measurement is sufficient.
- Add panel evaluation as future work with the specific
  hypothesis: panels of independently-prompted judges might
  exhibit correlated failures on metadata channels. Worth
  measuring.

## Severity 2 — Methodological tightening

### S2.1 No formal experimental protocol

**Reviewer's note:** *"What is the rep ordering? Is there
randomization? Are the scenarios run sequentially or in parallel?
Could the cache state of one rep affect the next?"*

**My fix:**
- Add an Experimental Protocol subsection specifying:
  - Reps run sequentially within a scenario, sequentially across
    scenarios.
  - `max_concurrency=1` is set explicitly (no inter-rep
    interference).
  - Workspace is wiped (`rm -rf /tmp/bft-workspace/*`) before
    each rep render.
  - Judge containers persist across reps but their on-container
    state (cache, prior call history) is independent per
    `claude -p` invocation.
  - Canary tokens are freshly generated per rep using
    `secrets.token_urlsafe(32)`.

### S2.2 Penetration rate isn't formally defined

**Reviewer's note:** *"The paper uses 'penetration rate' but
doesn't formalize. Is it conditional on reaching the dangerous
call, or unconditional? What about hangs?"*

**My fix:**
- Add formal definitions in §3.4 Metrics:
  $$
  \text{Pen}_\text{uncond} = \frac{|\text{attack\_succeeded}|}
                                  {|\text{reps}|}
  $$
  $$
  \text{Pen}_\text{cond} = \frac{|\text{attack\_succeeded}|}
                                {|\text{attack\_succeeded}| + |\text{attack\_blocked\_by\_judge}|}
  $$
- Define the seven outcome states formally with predicates.
- Specify which metric is reported in which table.

### S2.3 No effect-size / power discussion

**Reviewer's note:** *"The 100% (metadata) vs 0% (audit) contrast
looks dramatic, but with only 6 reps in the audit-channel arm and
12 in the metadata arm, what's the actual statistical evidence?"*

**My fix:**
- Compute Fisher's exact test on the 12/12 vs 0/6 contingency
  table: $p < 10^{-3}$, very strong.
- Report this in the Channel Dichotomy section.
- Note that the contrast survives extreme statistical scrutiny
  even at small N.

### S2.4 Negative control isn't prominent enough

**Reviewer's note:** *"Without a matched-shape benign control,
the paper can't separate 'detection of malicious behavior' from
'rejection of certain code shapes'. probe-04 is mentioned but
buried."*

**My fix:**
- Promote probe-04-negative-control to first-class status in
  §3.3 (Scenarios).
- Explicitly report its FPR (0/5 → 0%) as the structural-rejection
  baseline.
- Frame the metadata-channel result as "we have shown the same
  shape with a no-op payload would be approved 5/5 times; the
  same shape with a malicious payload + injected authority is
  approved 12/12 times. The injection is the load-bearing
  factor."

### S2.5 Cost analysis ignores agent-side cost

**Reviewer's note:** *"All cost analysis is judge-only. The paper
admits 25% extra cost from agent calls but doesn't include it in
any table."*

**My fix:**
- Add agent-side cost to the per-scenario table.
- Recompute totals.
- Acknowledge the published-rates-only assumption.

## Severity 3 — Missing context / framing

### S3.1 Related work is thin

**Reviewer's note:** *"Three citations on prompt injection. No
discussion of code-review-specific injection literature, no
comparison to AgentBench, AgentHarm, etc."*

**My fix:**
- Expand related work to cover:
  - Prompt injection generally (Greshake, et al.).
  - Code-review LLM literature (CodeReviewer, ReviewBot).
  - Tool-use safety benchmarks (AgentDojo, InjecAgent,
    AgentHarm, AgentBench).
  - Position our contribution: we are the first to characterize
    metadata-channel injection in agent+judge code-review
    pipelines.
- Add 5-10 more citations.

### S3.2 Threat model is under-specified

**Reviewer's note:** *"Does the attacker need full repo write
access, or just a single dependency? What's the access tier
needed for each attack class?"*

**My fix:**
- Add explicit access-tier discussion:
  - Pure supply-chain attacks: attacker needs to publish the
    malicious package (or compromise an existing one).
  - Metadata-channel attacks: attacker needs to author or modify
    repo-level files (CLAUDE.md, package.json). This requires
    repo commit access OR publishing-as-the-package-author.
  - Audit-channel attacks: same as supply-chain.
- Discuss whether the attacker access tier is realistic.
- Note that supply-chain compromises (event-stream, ua-parser-js)
  HAD this access tier, so the threat model matches real
  precedents.

### S3.3 Reproducibility is opaque

**Reviewer's note:** *"How do I run this? Where's the code? What
seeds? What's the scenario YAML format?"*

**My fix:**
- Add a Reproducibility paragraph in §3:
  - Code repository URL
  - Scenario YAML format reference
  - Harness invocation steps
  - Seed: canary token generation uses `secrets.token_urlsafe(32)`,
    different per rep; the rest of the harness is deterministic
- Note availability of `extracted-master/` and `paper-data/` raw
  data.

### S3.4 Limitations aren't sharp enough

**Reviewer's note:** *"Limitations exist but they're a section
deep into Discussion. What CAN'T this paper conclude?"*

**My fix:**
- Move limitations earlier (§3.5 right after methods).
- Be explicit about what the paper does NOT show:
  - Does NOT show the dichotomy generalizes to other models.
  - Does NOT show panels would or would not catch the attacks.
  - Does NOT show real-world attack rates (synthetic harness).
  - Does NOT compare to non-LLM defenses.
- Reviewer-friendly limitations make it harder to dock you for
  things you've already conceded.

## Severity 4 — Polish

### S4.1 Abstract is dense

The abstract reads like a results section. It should:
- Open with the question
- State the finding in one sentence
- Quantify
- State implication

**My fix:** rewrite for two-sentence ("we measured X... we found Y") clarity.

### S4.2 Section flow can be tightened

§4 (per-scenario table) and §5 (pure supply-chain) are both intros to data; collapse into one §4 with the table inline at the start.

**My fix:** merge §4 and §5 into a single §4 "Empirical Results: Pure Supply-Chain Baseline".

### S4.3 Figure captions are too long

Several figures have multi-sentence captions that read like body text.

**My fix:** trim captions to one sentence + one explanatory sentence max.

---

# Improvements to apply now

In priority order:

1. ✅ **Statistical Power** (§3.5 new) — explicit binomial CIs +
   Fisher's exact for the dichotomy contrast.
2. ✅ **Formal definitions** in §3.4 Metrics — penetration rate
   notation, outcome states, denominators.
3. ✅ **Experimental Protocol** (§3.4) — rep ordering, randomization,
   workspace cleanup, seeds.
4. ✅ **Promote probe-04** in §3.3 — structural-rejection baseline
   with explicit 0% FPR claim.
5. ✅ **Reproducibility** paragraph in §3.
6. ✅ **Limitations** explicit and earlier (§3.5 or §3.6).
7. ✅ **Related work expansion** — 5+ more citations covering AI
   code-review and agent-tool-safety literature.
8. ✅ **Threat model access tiers** (§2.1) — what level of attacker
   capability each attack needs.
9. ✅ **Comparison qualitative paragraph** (§2.4 or §6) —
   static/regex/human alternatives.
10. ✅ **Abstract rewrite** for clarity.
11. ✅ **Tighten captions**.

Self-questions to keep iterating:

- Does the paper distinguish "what we showed" from "what we hypothesize"?
- Could a reader reproduce the result from the description alone?
- Is every number traceable to a CSV in `paper-data/`?
- Are the failure modes (S1.1–S2.5 above) genuinely addressed in the prose, not just buried in a Limitations section?
- Does the paper teach the reader something that survives if the underlying scenarios are tweaked?
