"""Guards the monitoring config: valid files, in sync with the generated K8s ConfigMaps,
and every metric they query is really exported by the API."""
import importlib.util
import json
import re
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
MON = REPO / "monitoring"


def _builder():
    spec = importlib.util.spec_from_file_location("build_k8s", MON / "build_k8s.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_k8s_configmaps_are_in_sync():
    assert (REPO / "k8s" / "monitoring-config.yaml").read_text() == _builder().render(), \
        "run: python monitoring/build_k8s.py"


def test_rules_and_dashboard_are_valid():
    rules = yaml.safe_load((MON / "rules.yml").read_text())["groups"][0]["rules"]
    assert rules and all({"alert", "expr", "for", "annotations"} <= set(r) for r in rules)
    dash = json.loads((MON / "grafana/dashboards/secureship.json").read_text())
    assert dash["uid"] and len(dash["panels"]) >= 10
    assert len({p["id"] for p in dash["panels"]}) == len(dash["panels"])


def test_every_queried_metric_is_exported():
    src = (Path(__file__).resolve().parents[1] / "app" / "main.py").read_text()
    exported = set(re.findall(r'"(secureship_[a-z_]+)"', src))
    exported |= {m + s for m in list(exported) for s in ("_total", "_bucket", "_sum", "_count")}
    text = (MON / "rules.yml").read_text() + (MON / "grafana/dashboards/secureship.json").read_text()
    used = set(re.findall(r"secureship_[a-z_]+", text))
    assert used and used <= exported, used - exported


def test_prometheus_scrapes_the_api():
    cfg = yaml.safe_load((MON / "prometheus.yml").read_text())
    jobs = {j["job_name"]: j for j in cfg["scrape_configs"]}
    assert jobs["secureship-backend"]["static_configs"][0]["targets"] == ["backend:8000"]
