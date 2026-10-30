from . import bandit, checkov, gitleaks, semgrep, shellcheck, trivy, trivy_config

# key = scoring module name (see scoring.WEIGHTS); each scanner exposes run(path) -> dict
SCANNERS = {
    "secrets": gitleaks.run,
    "dependencies": trivy.run,
    "code": bandit.run,
    "iac": trivy_config.run_iac,
    "docker": trivy_config.run_docker,
    "semgrep": semgrep.run,
    "checkov": checkov.run,
    "shell": shellcheck.run,
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
    {"key": "semgrep", "label": "Multi-language SAST", "type": "SAST", "tool": "Semgrep",
     "description": "Insecure patterns in JavaScript/TypeScript, Python, Go, Java, Ruby, PHP and more (OWASP rules)."},
    {"key": "checkov", "label": "IaC policies", "type": "IaC", "tool": "Checkov",
     "description": "Policy violations in Terraform, Kubernetes, CloudFormation, GitHub Actions, GitLab CI and more."},
    {"key": "shell", "label": "Shell scripts", "type": "SAST", "tool": "ShellCheck",
     "description": "Bugs and unsafe constructs in .sh / .bash scripts."},
]
