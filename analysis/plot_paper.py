"""Generate paper figures from paper-data/ CSVs.

Outputs to docs/paper/figures/ as PDF (vector) and PNG (preview).

Figures:
  fig1_pen_by_channel.pdf       — bar chart, pen rate per channel, color by composition
  fig2_cost_decomposition.pdf   — stacked bar, approve vs reject cost composition
  fig3_latency_distribution.pdf — boxplot/percentile of judgment latency
  fig4_cost_vs_latency.pdf      — scatter, per-judgment cost vs latency
  fig5_pen_by_composition.pdf   — aggregate bars: 3 composition classes
"""

from __future__ import annotations

import csv
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib as mpl

mpl.rcParams.update({
    "font.family": "serif",
    "font.size": 10,
    "axes.labelsize": 10,
    "axes.titlesize": 11,
    "legend.fontsize": 9,
    "xtick.labelsize": 9,
    "ytick.labelsize": 9,
    "figure.dpi": 130,
    "savefig.dpi": 200,
    "axes.spines.top": False,
    "axes.spines.right": False,
})

PAPER_DATA = Path("paper-data")
OUT = Path("docs/paper/figures")
OUT.mkdir(parents=True, exist_ok=True)

# Color palette
COLOR_INJ_META = "#2c7fb8"   # injection + metadata channel — blue
COLOR_INJ_AUDIT = "#cc4c4c"  # injection + audit channel — red
COLOR_PURE = "#969696"       # pure supply chain — grey
COLOR_NEG = "#a86c00"        # negative-framing partial — amber

CATEGORY_COLORS = {
    "metadata": COLOR_INJ_META,
    "audit": COLOR_INJ_AUDIT,
    "pure": COLOR_PURE,
    "neg": COLOR_NEG,
}


def _read(path: Path) -> list[dict]:
    with path.open() as f:
        return list(csv.DictReader(f))


def _f(v) -> float:
    try: return float(v) if v not in ("", None) else 0.0
    except: return 0.0


def category_for(channel: str, composition: str) -> str:
    """Bucket each scenario into one of {metadata, audit, neg, pure}."""
    if composition == "pure-supply":
        return "pure"
    if channel.startswith("inline-comment"):
        return "audit"
    if channel == "claude-md-neg":
        return "neg"
    if channel in {"claude-md", "agents-md", "pkg-metadata", "json-fixture"}:
        return "metadata"
    return "pure"


# ---------------------------------------------------------------------------
# Figure 1: pen rate per scenario, color-coded by category
# ---------------------------------------------------------------------------

def fig1_pen_by_channel():
    rows = _read(PAPER_DATA / "headline_table.csv")
    # Sort: metadata (best) → audit (worst) → pure (middle), then by pen
    cats = []
    for r in rows:
        c = category_for(r["channel"], r["composition"])
        cats.append((c, r))
    order = {"metadata": 0, "neg": 1, "pure": 2, "audit": 3}
    cats.sort(key=lambda x: (order[x[0]], -_f(x[1]["pen_rate_uncond"])))

    labels = [r["scenario_id"].replace("npm-","").replace("pip-","") for _, r in cats]
    pens = [_f(r["pen_rate_uncond"]) for _, r in cats]
    colors = [CATEGORY_COLORS[c] for c, _ in cats]

    fig, ax = plt.subplots(figsize=(7.5, 4.0))
    bars = ax.barh(range(len(labels)), [p*100 for p in pens], color=colors,
                   edgecolor="black", linewidth=0.4)
    ax.set_yticks(range(len(labels)))
    ax.set_yticklabels(labels, fontsize=8)
    ax.set_xlabel("Penetration rate (%)")
    ax.set_xlim(0, 105)
    ax.invert_yaxis()
    # Add pct labels
    for i, (bar, p) in enumerate(zip(bars, pens)):
        ax.text(p*100 + 1.5, i, f"{int(p*100)}%", va="center", fontsize=8)
    # Legend
    from matplotlib.patches import Patch
    legend_handles = [
        Patch(facecolor=COLOR_INJ_META, label="Injection (metadata channel)"),
        Patch(facecolor=COLOR_NEG, label="Injection (negative framing)"),
        Patch(facecolor=COLOR_PURE, label="Pure supply-chain"),
        Patch(facecolor=COLOR_INJ_AUDIT, label="Injection (audit channel)"),
    ]
    ax.legend(handles=legend_handles, loc="lower right", frameon=False, fontsize=8)
    ax.set_title("A1 detection bypass rate by injection channel", fontsize=11)
    plt.tight_layout()
    fig.savefig(OUT / "fig1_pen_by_channel.pdf", bbox_inches="tight")
    fig.savefig(OUT / "fig1_pen_by_channel.png", bbox_inches="tight")
    plt.close(fig)


# ---------------------------------------------------------------------------
# Figure 2: cost decomposition — approve vs reject
# ---------------------------------------------------------------------------

def fig2_cost_decomposition():
    rows = _read(PAPER_DATA / "cost_decomposition.csv")
    # rows have decision, mean_cost_input, cache_read, cache_write, output
    decisions = [r["decision"] for r in rows]
    cats_ordered = ["approve", "reject"]
    rows_dict = {r["decision"]: r for r in rows}

    components = [
        ("Cache-read",  "mean_cost_cache_read_usd",  "#4a90c2"),
        ("Output",      "mean_cost_output_usd",      "#e89c4a"),
        ("Cache-write", "mean_cost_cache_write_usd", "#7ab87a"),
        ("Input (new)", "mean_cost_input_usd",       "#cc6677"),
    ]

    fig, ax = plt.subplots(figsize=(5.0, 4.0))
    x = list(range(len(cats_ordered)))
    bottoms = [0.0] * len(cats_ordered)
    for label, key, color in components:
        vals = [_f(rows_dict[d][key]) for d in cats_ordered]
        ax.bar(x, vals, bottom=bottoms, color=color, edgecolor="black",
               linewidth=0.4, label=label)
        # Label each segment with %
        for i, v in enumerate(vals):
            total = sum(_f(rows_dict[cats_ordered[i]][k]) for _, k, _ in components)
            if total > 0 and v / total > 0.04:
                ax.text(i, bottoms[i] + v/2, f"{v/total*100:.0f}%",
                        ha="center", va="center", fontsize=8, color="white",
                        weight="bold")
        bottoms = [b + v for b, v in zip(bottoms, vals)]
    ax.set_xticks(x)
    ax.set_xticklabels([d.capitalize() for d in cats_ordered])
    ax.set_ylabel("Cost per judgment (USD)")
    ax.set_title("Per-judgment cost decomposition\n(Haiku 4.5 pricing)", fontsize=11)
    # Add total cost annotations
    for i, d in enumerate(cats_ordered):
        total = sum(_f(rows_dict[d][k]) for _, k, _ in components)
        n = rows_dict[d]["n_judgments"]
        ax.text(i, total + 0.003, f"${total:.4f}\n(n={n})",
                ha="center", va="bottom", fontsize=8)
    ax.legend(loc="upper left", frameon=False, fontsize=8)
    plt.tight_layout()
    fig.savefig(OUT / "fig2_cost_decomposition.pdf", bbox_inches="tight")
    fig.savefig(OUT / "fig2_cost_decomposition.png", bbox_inches="tight")
    plt.close(fig)


# ---------------------------------------------------------------------------
# Figure 3: latency distribution
# ---------------------------------------------------------------------------

def fig3_latency_distribution():
    judg = _read(PAPER_DATA / "per_judgment_costs.csv")
    lat = sorted([_f(r["latency_ms"])/1000 for r in judg if _f(r["latency_ms"]) > 0])

    fig, axes = plt.subplots(1, 2, figsize=(8.5, 3.5),
                             gridspec_kw={"width_ratios": [2, 1.2]})

    # CDF
    ax0 = axes[0]
    cdf = [(i+1)/len(lat) for i in range(len(lat))]
    ax0.plot(lat, cdf, color="#2c7fb8", linewidth=1.5)
    # Mark percentiles
    for p, label in [(0.5, "median"), (0.75, "p75"), (0.90, "p90")]:
        idx = int(len(lat) * p)
        v = lat[idx-1] if idx > 0 else lat[0]
        ax0.axvline(v, color="grey", linestyle="--", linewidth=0.8)
        ax0.text(v, p, f" {label}={v:.1f}s", fontsize=8, va="bottom")
    ax0.set_xlabel("Latency per judgment (seconds)")
    ax0.set_ylabel("Cumulative fraction")
    ax0.set_title(f"Judgment latency CDF (n={len(lat)})", fontsize=11)
    ax0.grid(True, alpha=0.3)

    # Histogram
    ax1 = axes[1]
    ax1.hist(lat, bins=20, color="#2c7fb8", edgecolor="black", linewidth=0.4)
    ax1.set_xlabel("Latency (s)")
    ax1.set_ylabel("Count")
    ax1.set_title("Histogram", fontsize=11)
    plt.tight_layout()
    fig.savefig(OUT / "fig3_latency_distribution.pdf", bbox_inches="tight")
    fig.savefig(OUT / "fig3_latency_distribution.png", bbox_inches="tight")
    plt.close(fig)


# ---------------------------------------------------------------------------
# Figure 4: scatter, cost vs latency per judgment
# ---------------------------------------------------------------------------

def fig4_cost_vs_latency():
    judg = _read(PAPER_DATA / "per_judgment_costs.csv")
    approve = [(_f(r["latency_ms"])/1000, _f(r["cost_total_usd"])) for r in judg
               if r["judge_decision"] == "approve" and _f(r["latency_ms"]) > 0]
    reject  = [(_f(r["latency_ms"])/1000, _f(r["cost_total_usd"])) for r in judg
               if r["judge_decision"] == "reject" and _f(r["latency_ms"]) > 0]

    fig, ax = plt.subplots(figsize=(6.5, 4.0))
    if approve:
        xs, ys = zip(*approve)
        ax.scatter(xs, ys, color="#2ca02c", alpha=0.5, s=14, label=f"Approve (n={len(approve)})")
    if reject:
        xs, ys = zip(*reject)
        ax.scatter(xs, ys, color="#d62728", alpha=0.5, s=14, label=f"Reject (n={len(reject)})")
    ax.set_xlabel("Judgment latency (seconds)")
    ax.set_ylabel("Judgment cost (USD)")
    ax.set_title("Per-judgment cost vs. latency", fontsize=11)
    ax.legend(frameon=False, fontsize=9)
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    fig.savefig(OUT / "fig4_cost_vs_latency.pdf", bbox_inches="tight")
    fig.savefig(OUT / "fig4_cost_vs_latency.png", bbox_inches="tight")
    plt.close(fig)


# ---------------------------------------------------------------------------
# Figure 5: aggregate pen rate by composition class (the headline)
# ---------------------------------------------------------------------------

def fig5_aggregate_by_composition():
    rows = _read(PAPER_DATA / "headline_table.csv")
    buckets = {"metadata": [], "audit": [], "neg": [], "pure": []}
    for r in rows:
        c = category_for(r["channel"], r["composition"])
        buckets[c].append(r)

    labels = [
        ("Injection-amplified\n(metadata channels)", "metadata"),
        ("Injection-amplified\n(neg framing)", "neg"),
        ("Pure supply-chain\n(no injection)", "pure"),
        ("Injection-amplified\n(audit channels)", "audit"),
    ]
    pens = []
    counts = []
    for _, key in labels:
        bs = buckets[key]
        n_reps = sum(int(b["n_reps"]) for b in bs)
        n_succ = sum(int(b["n_succ"]) for b in bs)
        pens.append((n_succ / n_reps * 100) if n_reps else 0)
        counts.append((n_succ, n_reps))

    fig, ax = plt.subplots(figsize=(7.5, 4.0))
    colors = [CATEGORY_COLORS[k] for _, k in labels]
    x = list(range(len(labels)))
    bars = ax.bar(x, pens, color=colors, edgecolor="black", linewidth=0.5,
                  width=0.65)
    ax.set_xticks(x)
    ax.set_xticklabels([l for l, _ in labels], fontsize=9)
    ax.set_ylabel("Aggregate penetration rate (%)")
    ax.set_ylim(0, 110)
    ax.set_title("Headline: Channel Dichotomy in injection-amplified attacks",
                 fontsize=11)
    for i, (bar, p, (s, n)) in enumerate(zip(bars, pens, counts)):
        ax.text(i, p + 2, f"{int(p)}%\n({s}/{n})", ha="center", va="bottom",
                fontsize=9)
    ax.grid(axis="y", alpha=0.3)
    plt.tight_layout()
    fig.savefig(OUT / "fig5_aggregate_by_composition.pdf", bbox_inches="tight")
    fig.savefig(OUT / "fig5_aggregate_by_composition.png", bbox_inches="tight")
    plt.close(fig)


def main():
    fig1_pen_by_channel()
    fig2_cost_decomposition()
    fig3_latency_distribution()
    fig4_cost_vs_latency()
    fig5_aggregate_by_composition()
    print(f"Wrote figures to {OUT}/:")
    for p in sorted(OUT.iterdir()):
        size = p.stat().st_size
        print(f"  {p.name}  ({size:,} bytes)")


if __name__ == "__main__":
    main()
