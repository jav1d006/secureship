"""Security Score (0-100). Each module gets 100 minus severity penalties; the
overall score is the weighted average over the modules that actually ran."""

WEIGHTS = {
    "secrets": 25,
    "dependencies": 25,
    "iac": 20,
    "code": 20,
    "docker": 10,
}

PENALTY = {"critical": 25, "high": 15, "medium": 7, "low": 2}


def module_score(findings: list[dict]) -> int:
    penalty = sum(PENALTY.get(f.get("severity", "low"), 2) for f in findings)
    return max(0, 100 - penalty)


def overall_score(results: dict[str, dict]) -> tuple[int, dict[str, int]]:
    per_module = {name: module_score(r["findings"]) for name, r in results.items()}
    total_weight = sum(WEIGHTS.get(n, 0) for n in per_module)
    if total_weight == 0:
        return 100, per_module
    weighted = sum(per_module[n] * WEIGHTS.get(n, 0) for n in per_module)
    return round(weighted / total_weight), per_module
