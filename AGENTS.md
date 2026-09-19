# AGENTS.md

Members' bookstore backend: FastAPI + SQLAlchemy 2.x (`Mapped[]`) + Pydantic v2 + SQLite.
This is a deliberately part-finished take-home: some services raise `NotImplementedError`,
some helpers contain bugs. **[SPEC.md](SPEC.md) is the source of truth** and `tests/` is the
acceptance criteria — when the spec and intuition disagree, the spec wins.

## Commands

[uv](https://docs.astral.sh/uv/) is the toolchain ([README.md](README.md)); it is installed at
`/opt/homebrew/bin/uv`. Run from the repository root:

```
uv sync                                 # install Python 3.12 + dependencies
uv run pytest                           # full suite
uv run pytest tests/test_books.py       # one file
uv run pytest -k late_fee -x            # by name, stop at first failure
uv run uvicorn app.main:app --reload    # http://localhost:8000
```

`uv sync` creates the gitignored `.venv/` and downloads Python per `.python-version` (resolved to
3.12.14). The `Makefile` targets are thin wrappers over the same commands. Python 3.14 also ran the
suite identically, so the pinned version is not load-bearing for test results.

Baseline `pytest` at the time of writing: **125 failed, 73 passed, 4 errors**. Failures are
expected — unfinished services raise `NotImplementedError`, which `app/main.py` maps to **501**.
Do not "fix" a 501 by catching it; implement the service.

## Layout and ownership

- `app/routers/*` — HTTP only: parse input, call a service, return the result. No business rules.
- `app/services/*` — **all** business logic and the raising of `HTTPException` (404/403/409).
- `app/schemas.py` — field-level validation (trim/length, ISBN, email) so bad input fails with 422
  before any service runs.
- `app/models.py` — ORM models; importing the module registers tables on `Base.metadata`.
- `app/main.py` — `create_app(init_db: bool = True)` factory and module-level `app`.
- `frontend/` — plain static HTML/CSS/JS (no build step), calls root-relative paths (`/books`).
- `tests/` — acceptance criteria. **Do not modify anything in `tests/`.**

## Non-obvious contracts

- **Time:** get "now" only through `Depends(get_now)` (`app/clock.py`), never `datetime.now()`.
  Tests swap in a frozen clock starting `2026-01-01T12:00:00` and move it with
  `clock.advance(days=...)`. All datetimes are naive UTC and serialize as naive ISO-8601.
- **Test wiring:** `tests/conftest.py` builds its own in-memory SQLite engine, overrides `get_db`,
  and calls `create_app(init_db=False)`. Keep that no-DB code path working.
- Money is always integer cents. API routes live at the root (no `/api` prefix).
- A route declared as `""` is served **without** a trailing slash; `GET /books/` returns 404
  because the `StaticFiles` mount at `/` catches it.
- `SANCTUM_DATABASE_URL` selects the database (default `sqlite:///./sanctum.db`), created and
  seeded with 12 books and 4 members on first start when empty.
- Errors are `{"detail": ...}`; validation errors are FastAPI's default 422.
- **Do not add dependencies** beyond `pyproject.toml`.

## Completion criteria

1. `pytest` passes with **no changes under `tests/`**.
2. The app boots, serves the UI at `/` and docs at `/docs`, and still uses plain SQLite by default.

## Assignment constraints

From [ASSIGNMENT.md](ASSIGNMENT.md) / [INSTRUCTIONS.md](INSTRUCTIONS.md): keep routers thin and
business rules in services; a failed order must leave stock untouched; commit incrementally with
real messages and write a `NOTES.md`. A public deployed URL is part of the submission, but it must
not make the local SQLite test run depend on external services.

Note: this working copy has **no `.git` directory** (it was unpacked from an archive), so the
Git-history expectations in `INSTRUCTIONS.md` apply to the repository the author creates.

