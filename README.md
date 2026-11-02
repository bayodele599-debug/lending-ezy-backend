# Lending Ezy Backend

A sandbox-only global lending platform API. No live lending or financial transfers are enabled.

## Local run

```bash
python -m venv .venv
pip install -r requirements-dev.txt
uvicorn app.main:app --reload
pytest -q
```

Use an isolated development environment. `/docs` exposes the OpenAPI schema.

**Safety:** illustrative rates and demo applications only; do not collect real identifying information or treat this as production-ready lending software.
