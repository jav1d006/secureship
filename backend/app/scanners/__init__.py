from . import bandit, gitleaks, trivy, trivy_config

# key = scoring module name (see scoring.WEIGHTS); each scanner exposes run(path) -> dict
SCANNERS = {
    "secrets": gitleaks.run,
    "dependencies": trivy.run,
    "code": bandit.run,
    "iac": trivy_config.run_iac,
    "docker": trivy_config.run_docker,
}

META = [
    {"key": "secrets", "label": "Secrets", "type": "Secrets detection", "tool": "Gitleaks",
     "description": "Hard-coded API keys, tokens and passwords."},
    {"key": "dependencies", "label": "Dependencies", "type": "SCA", "tool": "Trivy",
     "description": "Known CVEs in libraries (requirements.txt, package-lock.json, go.mod ...)."},
    {"key": "code", "label": "Source code", "type": "SAST", "tool": "Bandit",
     "description": "Insecure patterns in Python source code."},
    {"key": "iac", "label": "Infrastructure", "type": "IaC", "tool": "Trivy",
     "description": "Misconfigurations in Terraform, Kubernetes, Helm and CloudFormation."},
    {"key": "docker", "label": "Dockerfile", "type": "Container", "tool": "Trivy",
     "description": "Insecure Dockerfile instructions (root user, latest tags, ADD ...)."},
]
