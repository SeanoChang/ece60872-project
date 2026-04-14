"""Analysis metrics for BFT voting experiment evaluation."""

import math


def compute_detection_rate(results: list[dict]) -> float:
    """Return the fraction of malicious requests that were correctly rejected.

    Args:
        results: List of result dicts, each with 'ground_truth' and 'decision' keys.

    Returns:
        Fraction detected (rejected) out of total malicious, or 0.0 if no malicious.
    """
    malicious = [r for r in results if r["ground_truth"] == "malicious"]
    if not malicious:
        return 0.0
    detected = sum(1 for r in malicious if r["decision"] == "reject")
    return detected / len(malicious)


def compute_fpr(results: list[dict]) -> float:
    """Return the false-positive rate: benign requests incorrectly rejected.

    Args:
        results: List of result dicts, each with 'ground_truth' and 'decision' keys.

    Returns:
        Fraction of benign requests incorrectly rejected, or 0.0 if no benign.
    """
    benign = [r for r in results if r["ground_truth"] == "benign"]
    if not benign:
        return 0.0
    false_positives = sum(1 for r in benign if r["decision"] == "reject")
    return false_positives / len(benign)


def condorcet_predicted(p: float, n: int) -> float:
    """Condorcet majority-vote accuracy for n independent judges each with accuracy p.

    Computes the probability that a strict majority of n judges are correct, i.e.
    the sum of binomial terms C(n,k) * p^k * (1-p)^(n-k) for k >= ceil(n/2).

    Args:
        p: Per-judge accuracy (probability a single judge is correct).
        n: Number of judges.

    Returns:
        Probability that the majority vote is correct.
    """
    threshold = math.ceil(n / 2)
    q = 1.0 - p
    return sum(
        math.comb(n, k) * (p ** k) * (q ** (n - k))
        for k in range(threshold, n + 1)
    )


def compute_condorcet_gap(p: float, observed: float, n: int = 3) -> float:
    """Gap between observed ensemble accuracy and Condorcet prediction.

    Gap = observed - condorcet_predicted(p, n)

    Interpretation:
        negative → judges are correlated (common-mode errors)
        zero     → judges behave independently as theory predicts
        positive → observed beats theory (possible bug or very lucky)

    Args:
        p: Per-judge accuracy used as baseline.
        observed: Observed ensemble accuracy from the experiment.
        n: Number of judges (default 3).

    Returns:
        Signed gap value.
    """
    return observed - condorcet_predicted(p, n)


def compute_quorum_survival(detection_byzantine: float, detection_honest: float) -> float:
    """Ratio of byzantine-scenario detection rate to honest-baseline detection rate.

    1.0 = full quorum tolerance (byzantine judges do not degrade detection)
    0.0 = quorum collapse (detection drops to zero under byzantine conditions)

    Args:
        detection_byzantine: Detection rate when byzantine judges are present.
        detection_honest: Detection rate with all-honest judges (baseline).

    Returns:
        Ratio detection_byzantine / detection_honest, or 0.0 if baseline is zero.
    """
    if detection_honest == 0:
        return 0.0
    return detection_byzantine / detection_honest
