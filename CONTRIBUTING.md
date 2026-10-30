# Contributing
```bash
cd backend && python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
pytest -q                                   # unit + API tests
TEST_DATABASE_URL=postgresql://user:pw@localhost:5432/db pytest -q   # also DB integration tests
docker compose up --build                   # full stack on http://localhost:8080
```
- New scanner: add `backend/app/scanners/<name>.py` (`run(path) -> {"findings": [...]}`), register it in `scanners/__init__.py` (`SCANNERS` + `META`) and `scoring.WEIGHTS`, add a parser test with faked output.
- Findings must use `rule`, `description`, `file`, `line`, `severity` (`critical|high|medium|low`).
- Security issues: see [SECURITY.md](SECURITY.md), not public issues.
