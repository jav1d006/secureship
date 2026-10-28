from . import gitleaks

# Add trivy, semgrep, checkov here later; each exposes `run(path) -> dict`.
SCANNERS = {
    "secrets": gitleaks.run,
}
