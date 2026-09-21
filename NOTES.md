# NOTES.md

**Live app:** https://sanctum-sanctorum-7csw.onrender.com

The app is deployed on Render's free tier, so it goes to sleep after 15 minutes without traffic. Because of that, the **first load can take around a minute** while the service and database wake up. The header badge retries for a few seconds before showing "API unreachable", so a red status after that means the API is actually unavailable.

The data is stored in hosted Postgres rather than inside the container, so it persists across restarts and redeploys.

No authentication is required. The starter UI is designed around entering a member ID directly.

## What's done

Everything in `app/` is implemented, with **219 tests passing and none skipped**.

* **Books:** ISBN-13 validation, duplicate detection, listing/search/filter/sort/pagination, and `PATCH /books/{id}`.
* **Members:** email normalization and uniqueness, member stats, and paginated listing.
* **Orders:** tier and bulk pricing, stock reservation, payment, and cancellation.
* **Loans:** borrowing rules, returns, and late fees. The model was also missing three required columns, which I added.
* **Reports:** top books by copies sold from paid orders.
* **Concurrency:** row locking to prevent two concurrent orders from overselling the last copy.

## What I skipped, and what I'd do with more time
All required items are covered, along with the three optional extras.

I did not add authentication because the starter UI is explicitly built around entering a member ID. Adding authentication would have changed that flow without being required by the assignment.

With more time, roughly in the order I'd do them:

1. **Handle duplicate creation races.**
   `create_book` and `create_member` currently use a check-then-insert flow. Concurrent requests can both pass the check and then hit the database unique constraint, resulting in an `IntegrityError` instead of a clean `409`. I'd catch and translate that error.

2. **Add database migrations.**
   `create_all` is fine for the assignment and a fresh database, but schema changes in a real application should go through Alembic migrations. The missing `Loan` columns are a good example of why this matters.

3. **Move database engine creation out of import time.**
   `app/db.py` currently creates the engine during import. It works in the deployed setup, but making initialization more explicit would avoid unnecessary coupling between imports and the configured database driver.

## Decisions and trade-offs

**Services own business rules.**
The routers stay thin, while rules such as restricted-book access live in the service layer. For example, both orders and loans use the same member access check instead of implementing the rule separately.

**Validation happens at two levels.**
Pydantic handles request validation, while business checks such as `404`, `403`, and `409` remain in the service layer. This also preserves the required validation order for `POST /orders`.

**Stock changes happen inside one transaction.**
All stock checks complete before the stock is modified, with the transaction committed only after the operation succeeds. This prevents a failed order or loan from leaving partially updated state.

**Render + Neon instead of keeping SQLite in production.**
The assignment requires a hosted database for deployment, so I kept SQLite as the default for local tests and used Neon Postgres for the deployed application.

I intentionally did not add a keep-alive mechanism. The cold start is inconvenient, but keeping the service and database running continuously would use significantly more of the available free-tier resources.

## Bugs I found and fixed

* `tier_at_least` used `>` instead of `>=`, meaning a `master` member could not satisfy a `master` minimum.
* `cancel_order` changed the order status but did not restore the reserved stock, despite its docstring saying it would.
* `normalize_isbn13` used `str.isdigit()`, which accepts non-ASCII digits. Python's `int()` also accepts many of them, allowing visually similar ISBN values to pass validation. I changed the validation to explicitly accept ASCII digits and added edge-case tests.

## Spec points I flagged

**Mixed-case title ordering is unspecified.**
SQLite and Postgres can order mixed-case strings differently. Since the spec explicitly leaves this unspecified, I did not introduce custom collation behavior.

**Order cancellation and payment behavior.**
Stock is reserved when an order is created and returned only when a pending order is cancelled. A paid order cannot currently be cancelled through the API. I treated this as the intended behavior, but it is something I'd clarify with the author of the spec.

**Extra test coverage.**
The instructions ask for additional edge-case tests while also saying not to modify the existing tests. I interpreted that as leaving the provided tests untouched and adding new coverage in `tests/test_edge_cases.py`.

## AI usage

I built the project as the primary developer, using Deepseek through the Reasonix coding agent as an engineering assistant. I made the implementation decisions, reviewed the diffs, ran the verification, and handled the Neon and Render setup myself.

I mainly used the agent to check library documentation, understand unfamiliar SQLAlchemy 2.0 patterns, and help with repetitive implementation and test debugging. I treated its output as something to verify rather than something to blindly accept.

One useful example was ISBN validation. The agent initially suggested that `isdigit()` followed by `int()` would reject non-ASCII digits. I tested that assumption with Arabic-Indic and fullwidth numerals and found that Python accepts many of them. That exposed a real validation gap where a visually different ISBN could be stored as a separate value. I fixed the validation and added regression tests.
