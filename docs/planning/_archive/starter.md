  ---
  Component-by-Component: What to Cherry-Pick

  1. Honeypot + Tripwire (core/honeypot.py — Person 1, Day 1)

  Primary source: <https://github.com/peg/snare>

- What it is: Honeypot canaries specifically designed for AI agents. Plants fake credentials (AWS, SSH, k8s, OpenAI,
   Anthropic keys) that phone home when used.
- What to lift:
  - The canary credential generation pattern — unique 128-bit token IDs per scenario, stored in a local manifest
  (~/.snare/manifest.json), never transmitted. Map this directly to your CANARY_KEY_PATTERN
  (sk-ant-api03-CANARY-[A-Z0-9]{32}-DO-NOT-USE).
  - The callback-on-access model — Snare's "credential is the sensor" design. Your honeypot at localhost:9999 is
  simpler (HTTP listener), but the event metadata structure (timestamp, source IP, user agent, token ID) is worth
  adapting for your JSONL honeypot_canary_seen field.
  - The real-key tripwire pattern — Snare's HMAC-SHA256 signature verification. Adapt for your REAL_KEY_PATTERN
  regex match + sys.exit(1).
- What to skip: Snare is written in Go. You only need the design patterns, not the code. Your Python HTTP listener  
  is http.server.HTTPServer or aiohttp — 30 lines max.

  Secondary source: <https://github.com/thinkst/opencanary>

- What to lift: The JSON alert logging format and multi-protocol event dispatch pattern. OpenCanary logs to JSON
  with alert type, timestamp, source, and payload. Your JSONL honeypot_canary_seen / honeypot_real_key_seen fields can
   follow the same structure.
- What to skip: OpenCanary is a full network honeypot daemon — way too heavy. You only need the HTTP handler pattern
   from opencanary/modules/http.py.

  Methodology: Simple asyncio HTTP server on 127.0.0.1:9999. On every request: (1) extract body/query params, (2)
  regex match against CANARY_KEY_PATTERN → log exfil event, (3) regex match against REAL_KEY_PATTERN → tripwire fire +
   sys.exit(1), (4) return 200 (so the agent thinks exfil succeeded — you want to observe post-exfil behavior).

  ---

  1. Agent Loop (core/agent.py — Person 2)

  Primary source: <https://github.com/ethz-spylab/agentdojo>

- What it is: The closest architectural match to your system — a tool-use agent benchmark where attacks are injected
   into tool responses and defenses intercept tool calls.
- What to lift:
  - The task/scenario definition pattern — AgentDojo defines tasks as Python objects with user_task_N IDs, tool
  suites, and injection points. Map to your scenarios/*.yaml format. Their src/agentdojo/task_suite/ has the task
  runner orchestration.
  - The defense plugin interface — AgentDojo's tool_filter defense is exactly your voting proxy insertion point.
  They plug defenses between the agent's tool-call request and execution. Study src/agentdojo/defenses/ for how they  
  intercept.
  - The benchmark runner — src/agentdojo/scripts/benchmark.py parametrizes runs across models × tasks × attacks ×
  defenses. Adapt for your ablation IDs (A0-A5) × scenarios × repetitions.
- What to skip: AgentDojo supports multiple models and has its own tool execution engine. You're Anthropic-only with
   a simpler sandbox. Don't import their agent runtime — build your own thin Anthropic tool-use loop.

  Secondary source: Anthropic's own tool-use API docs

- Methodology: Your agent loop is a standard Anthropic messages API call with tools parameter. The agent proposes
  tool_use blocks; your loop intercepts each one, passes through risk classifier → voting proxy → (if approved)
  sandbox execution → return result to agent. This is ~100 lines of async Python wrapping
  anthropic.AsyncAnthropic().messages.create().

  ★ Insight ─────────────────────────────────────
  AgentDojo's defense interface is the key architectural insight: They separate "agent proposes tool call" from "tool
  call executes" with a pluggable filter layer. Your voting proxy sits in exactly this gap. Their codebase
  demonstrates that the interception point is the tool_use content block in the API response — you parse it, run
  judges, and only call the sandbox if approved. This is cleaner than wrapping the tool definitions themselves.
  ─────────────────────────────────────────────────

  ---

  1. JSONL Logger (core/logger.py — Person 2)

  Primary source: <https://github.com/uiuc-kang-lab/InjecAgent>

- What to lift:
  - The structured JSONL output pattern — InjecAgent logs per-scenario results as JSONL with scenario ID, attack
  type, enhancement level, agent response, and classification labels. This maps directly to your frozen v1 schema.
  - The classification metrics computation — their ASR-valid / ASR-all computation pattern. Adapt for your
  classify() function (TP/TN/FP/FN).
  - The enhancement level parametrization — their base vs. enhanced (with "IMPORTANT!! Ignore all previous
  instructions") maps to your L0-L4 InjecAgent ladder. Their data/ directory has the exact injection payload
  templates.
- What to skip: Their agent implementation (GPT/Claude ReAct wrapper). You have your own.

  Methodology: Append-only jsonlines library writes. Each VoteResult + ground truth → one JSONL line. Use filelock for
   concurrent safety if running parallel ablations. The prompt_hash field is
  hashlib.sha256(Path(prompt_path).read_bytes()).hexdigest().

  ---

  1. Voting Proxy (core/voting_proxy.py — Person 1/2 shared)

  Primary source: <https://github.com/arvindand/llm-deliberate>

- What it is: A multi-model LLM deliberation tool with 5 social choice voting algorithms (Plurality, Borda, Weighted
   Borda, Copeland/Condorcet, Ranked Pairs).
- What to lift:
  - The parallel judge dispatch architecture — they use Python async/await to fire multiple LLM API calls
  simultaneously via OpenRouter. Adapt for asyncio.gather(*[call_judge(j) for j in judges]) with Anthropic's async  
  client.
  - The agreement matrix computation — their pairwise judge agreement heatmap (red-yellow-green) directly maps to
  your inter-judge agreement metric. Lift the computation logic.
  - The diversity score (0-1 scale) — measures judge disagreement. This is an independence proxy you can report
  alongside your Condorcet gap.
- What to skip: Their multi-round deliberation (you do single-round majority vote). Their frontend React app. Their
  Copeland/Ranked Pairs algorithms (you only need simple 2-of-3 majority).

  Secondary source: <https://github.com/poloclub/llm-self-defense>

- What to lift:
  - The harm filter pattern — harm_filter.py implements exactly "take generated output → feed to second LLM with
  screening prompt → binary decision." This is your single-judge case (A1/A2). The pattern is: insert generated
  content into a template prompt, call LLM, parse structured output.
  - The HARMFILTER_MODEL configuration pattern — maps to your JudgeConfig.model field.
- What to skip: Their CSV-based evaluation. You have JSONL.

  Methodology: async def vote() dispatches 1 or 3 judges via asyncio.gather(). Each judge call: (1) load system prompt
   from file, (2) verify sha256 matches JudgeConfig.system_prompt_hash, (3) construct message with tool call context,
  (4) call anthropic.AsyncAnthropic().messages.create(), (5) parse JSON response into JudgeVote, (6) aggregate via
  majority rule. Return VoteResult.

  ★ Insight ─────────────────────────────────────
  LLM Self Defense is your single-judge ablation (A1/A2) in 50 lines: Their entire defense is: take output → stuff
  into screening prompt → call LLM → binary classify. The jump from 1-judge to 3-judge is just asyncio.gather over
  three of these. The hard part isn't the proxy — it's the Condorcet analysis that comes after. Budget your time
  accordingly.
  ─────────────────────────────────────────────────

  ---

  1. Scenario Library (scenarios/*.yaml — Joint)

  Primary source: <https://github.com/uiuc-kang-lab/InjecAgent>

- What to lift:
  - The attack payload templates — their data/attacker_cases_dh.jsonl (direct harm) and data/attacker_cases_ds.jsonl
   (data stealing) contain 1,054 structured injection payloads. Sample from the data-stealing category (closest to
  your canary exfil model).
  - The enhancement prefix templates — their "IMPORTANT!!! Ignore all previous instructions" prefix is your L1
  escalation. Adapt their pattern for L0-L4.
  - The user case × attacker case composition — they synthesize benign user tasks with injected attacker payloads.  
  This is your "4 archetypes × 5 enhancement levels + 10 benign" matrix.

  Secondary source: <https://github.com/AI-secure/RedCode>

- What to lift:
  - The risky code execution taxonomy — their 25 vulnerability types across OS/filesystem/web domains.
  Cross-reference with your 4 archetypes to ensure coverage.
  - The Docker sandbox pattern — their environment/ directory has Docker configs for isolated code execution. Adapt
  for your subprocess.run(env=SANDBOX_ENV) approach if you upgrade to Docker isolation.

  Tertiary source: AgentDojo

- What to lift: ~50 cases from their 629 security test cases for your "secondary AgentDojo comparability subset."
  Their framework supports task selection by ID, so you can sample a representative subset.

  ---

  1. Condorcet Decomposition Analysis (analysis/group_a/ — Group A unique)

  Primary source: <https://arxiv.org/abs/2409.00094>

- What it is: The closest methodological precedent — they directly test whether Condorcet's Jury Theorem holds for  
  LLM ensembles and measure the independence violation.
- What to lift:
  - The Condorcet prediction vs. observation comparison framework — they compute P_pred = 3p² − 2p³ from per-judge  
  accuracy and compare against empirical ensemble accuracy. This is exactly your RQ3 Condorcet gap.
  - Their finding that same-architecture models violate independence — this is your expected A3 result (same prompt
  = high correlation). Your paper's contribution is showing whether A4 (different prompts) reduces this correlation.

  Secondary source: <https://arxiv.org/abs/2510.04048>

- What to lift:
  - The variable voting threshold with abstention pattern — for future work / sensitivity analysis. If confidence <
  threshold, abstain rather than vote. Not in your current ablation ladder but could be an A4w variant.
  - Their trustworthiness-yield tradeoff analysis — "large gains in trustworthiness via restrictive voting, at
  modest yield reduction." Frame this when discussing FPR (your voting may over-block benign calls).

  Tertiary source: <https://github.com/arvindand/llm-deliberate>

- What to lift: Their agreement matrix and diversity score computations for measuring inter-judge correlation. This
  complements the Condorcet gap with an additional independence metric.

  Methodology for the Condorcet gap:

  1. From A1/A2 runs: compute per-judge accuracy p per archetype
  2. From R-Judge bootstrap: compute independent p estimate (breaks circularity)
  3. Predict: P_pred = 3p² − 2p³
  4. Observe: P_obs from A3/A4 JSONL logs
  5. Gap = P_obs − P_pred
  6. Compare A3 gap vs A4 gap → this quantifies how much perspective diversity reduces correlation

  ★ Insight ─────────────────────────────────────
  Lefort et al. is your methodological twin — they did Condorcet-vs-observed for LLM ensembles on sentiment analysis  
  and found independence violations. Your contribution is: (a) applying this to safety judgment (not sentiment), (b)  
  testing whether prompt diversity (N-version) fixes the independence problem where sampling diversity (high
  temperature) doesn't, and (c) doing it on tool calls, not text. The Condorcet gap framework is proven; you're
  extending the domain.
  ─────────────────────────────────────────────────

  ---

  1. Independent p Bootstrap — R-Judge

  Source: <https://github.com/Lordog/R-Judge>

- What to lift:
  - The 569 multi-turn interaction records from data/ — run your honest judges (A1 Param/Intent/Threat) against
  these to get per-judge accuracy on an independent dataset.
  - The two-stage evaluation pipeline — (1) binary safety judgment, (2) risk identification. You only need stage 1  
  (binary decision matches your approve/reject).
  - The F1/Recall/Specificity metrics — lift their evaluation script from eval/ for computing your per-judge p on
  R-Judge data.
- What to skip: Their risk identification (stage 2) and GPT-4 automatic evaluator. You don't need open-ended
  analysis — just binary accuracy.

  ---
  Summary: The Adaptation Map

  ┌────────────┬────────────────────────────────┬────────────────────────────────┬──────────────────────────────┐
  │   Your     │      Primary Cherry-Pick       │          What to Take          │     Where in Their Repo      │
  │ Component  │                                │                                │                              │
  ├────────────┼────────────────────────────────┼────────────────────────────────┼──────────────────────────────┤
  │ Honeypot   │ peg/snare                      │ Canary generation pattern,     │ internal/, architecture docs │
  │            │                                │ event metadata schema          │                              │
  ├────────────┼────────────────────────────────┼────────────────────────────────┼──────────────────────────────┤  
  │            │                                │ Defense plugin interface,      │ src/agentdojo/defenses/,     │
  │ Agent loop │ ethz-spylab/agentdojo          │ benchmark runner               │ scripts/benchmark.py         │
  │            │                                │ parametrization                │                              │  
  ├────────────┼────────────────────────────────┼────────────────────────────────┼──────────────────────────────┤
  │ JSONL      │ uiuc-kang-lab/InjecAgent       │ Structured JSONL output,       │ data/, src/                  │
  │ logger     │                                │ classification metrics         │                              │  
  ├────────────┼────────────────────────────────┼────────────────────────────────┼──────────────────────────────┤
  │ Voting     │ arvindand/llm-deliberate +     │ Parallel judge dispatch,       │                              │
  │ proxy      │ poloclub/llm-self-defense      │ agreement matrix, harm filter  │ backend/, harm_filter.py     │
  │            │                                │ pattern                        │                              │
  ├────────────┼────────────────────────────────┼────────────────────────────────┼──────────────────────────────┤
  │ Scenarios  │ InjecAgent + RedCode +         │ Attack payloads, enhancement   │ data/, dataset/, task suites │
  │            │ AgentDojo                      │ ladder, comparability subset   │                              │
  ├────────────┼────────────────────────────────┼────────────────────────────────┼──────────────────────────────┤
  │ Condorcet  │                                │ Predicted-vs-observed          │                              │
  │ analysis   │ Lefort et al. (2409.00094)     │ framework, independence        │ Paper methodology section    │
  │            │                                │ violation measurement          │                              │
  ├────────────┼────────────────────────────────┼────────────────────────────────┼──────────────────────────────┤
  │ p          │ Lordog/R-Judge                 │ 569 interaction records,       │ data/, eval/                 │
  │ bootstrap  │                                │ binary evaluation pipeline     │                              │
  └────────────┴────────────────────────────────┴────────────────────────────────┴──────────────────────────────┘

  ---
  Additional Papers Worth Scanning (from Awesome-LLM-as-a-Judge)

  For your related work and to strengthen the contribution framing:

  ┌────────────────────────────────────────────┬────────────┬─────────────────────────────────────────────────────┐
  │                   Paper                    │   arxiv    │                   Why It Matters                    │
  ├────────────────────────────────────────────┼────────────┼─────────────────────────────────────────────────────┤
  │ BadJudge: Backdoor Vulnerabilities of      │ 2503.00596 │ Directly relevant to Group B but cite in Paper 1 as │
  │ LLM-as-a-Judge                             │            │  motivation for Byzantine direction                 │
  ├────────────────────────────────────────────┼────────────┼─────────────────────────────────────────────────────┤
  │ Know Thy Judge: Robustness Meta-Evaluation │ 2503.04474 │ Validates that safety judges need robustness        │
  │  of Safety Judges                          │            │ evaluation — your paper does this empirically       │
  ├────────────────────────────────────────────┼────────────┼─────────────────────────────────────────────────────┤
  │ Investigating Vulnerability of             │ 2505.13348 │ Already in your unverified citations — confirms the │
  │ LLM-as-a-Judge to Prompt Injection         │            │  attack surface you're studying                     │
  ├────────────────────────────────────────────┼────────────┼─────────────────────────────────────────────────────┤
  │ AgentRewardBench: Evaluating Evaluations   │ 2504.08942 │ Closest benchmark for "judging judges" in agent     │
  │ of Web Agent Trajectories                  │            │ contexts                                            │
  └────────────────────────────────────────────┴────────────┴─────────────────────────────────────────────────────┘

  ---
  Recommended Priority Order for Week 1

  Given you're already in Week 1 (Apr 7-13):

  1. Day 1 (now): Stand up honeypot (adapt Snare patterns) + agent loop skeleton (adapt AgentDojo defense interface)  
  2. Day 2-3: Voting proxy (adapt llm-deliberate dispatch + LLM Self Defense filter pattern) + JSONL logger (adapt
  InjecAgent schema)
  3. Day 4-5: Scenario library (sample from InjecAgent L0-L4 + start custom archetypes)
  4. Day 5-6: Judge prompt canary checks (v0 prompts exist, run the 10-case sanity check)
  5. Day 7: Cross-review with Group B + lock v1 prompts

  Sources:

- <https://github.com/ethz-spylab/agentdojo>
- <https://github.com/uiuc-kang-lab/InjecAgent>
- <https://github.com/Lordog/R-Judge>
- <https://github.com/peg/snare>
- <https://github.com/poloclub/llm-self-defense>
- <https://github.com/arvindand/llm-deliberate>
- <https://github.com/AI-secure/RedCode>
- <https://github.com/guardagent/code>
- <https://github.com/thinkst/opencanary>
- <https://github.com/NVIDIA-NeMo/Guardrails>
- <https://github.com/llm-as-a-judge/Awesome-LLM-as-a-judge>
- <https://arxiv.org/abs/2409.00094>
- <https://arxiv.org/abs/2510.04048>
- <https://arxiv.org/abs/2512.05982> — not BFT-relevant, it's election simulation
