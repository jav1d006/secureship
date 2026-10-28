from . import bandit, gitleaks, trivy

# key = scoring module name (see scoring.WEIGHTS); each scanner exposes run(path) -> dict
SCANNERS = {
    "secrets": gitleaks.run,
    "dependencies": trivy.run,
    "code": bandit.run,
}

META = [
    {"key": "secrets", "label": "Secrets", "type": "Secrets detection", "tool": "Gitleaks",
     "description": "Hard-coded API keys, tokens and passwords."},
    {"key": "dependencies", "label": "Dependencies", "type": "SCA", "tool": "Trivy",
     "description": "Known CVEs in libraries (requirements.txt, package-lock.json, go.mod ...)."},
    {"key": "code", "label": "Source code", "type": "SAST", "tool": "Bandit",
     "description": "Insecure patterns in Python source code."},
]
