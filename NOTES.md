# NOTES.md

**Live app: https://sanctum-sanctorum-7csw.onrender.com**

Two things that look like faults but aren't. The app runs on Render's free tier, which sleeps after
15 minutes with no traffic, so **the first load takes about a minute** while the service wakes and
the database resumes. And the data lives in a hosted Postgres database rather than inside the
container, so whatever you click through survives restarts and redeploys.

## What's done

Everything in `app/`, with all **219 tests passing** and none skipped.

- **Books**: ISBN-13 checksum, duplicate detection, the full listing endpoint (title and author
  search, restricted and price filters, sorting with id tie-breaks, pagination), and
  `PATCH /books/{id}`.
- **Members**: email normalisation and uniqueness, stats, and a paginated `GET /members`.
- **Orders**: tier and bulk pricing, stock reservation, pay and cancel.
- **Loans**: the model was three columns short so I added them, then the borrowing rules, returns
  and late fees.
- **Reports**: top books by copies sold over paid orders.
- **Row locks** so two concurrent orders can't oversell the last copy.

## What I skipped, and what I'd do with more time

Nothing from the required list, and all three optional extras are in. I didn't add authentication,
but that isn't a skip: the starter kit's UI is built around typing a member id, so adding auth
would have broken the frontend.

With more time, roughly in the order I'd do them:

1. **Close the duplicate-check race.** `create_book` and `create_member` both check-then-insert, so
   two concurrent requests with the same ISBN or email can both pass the check and the unique index
   then raises `IntegrityError`, surfacing as a 500 instead of a 409. Catching `IntegrityError` and
   re-raising 409 is the fix, and that's what I'd ship under real traffic.
2. **Add migrations.** `create_all` on startup is fine for a fresh database and needs Alembic the
   moment the schema has to change in place. Adding the missing `Loan` columns already means
   deleting a local `sanctum.db` (`make reset-db`) rather than migrating it.
3. **Move engine creation out of import time.** `app/db.py` builds its engine when the module is
   imported, so importing it requires the driver for whatever URL is configured. Set
   `SANCTUM_DATABASE_URL` without the `postgres` group installed and even the test suite fails on a
   missing module. It never bites in practice, but it's a sharp edge.

## Decisions and trade-offs

**Services own the rules, routers stay thin.** `create_order` and `create_loan` both need the
restricted-books rule, so they call `members.ensure_can_access_restricted` rather than re-implementing
it. One home for that rule means orders and loans can't drift on what "master or above" means.

**Validation is split across two layers, deliberately.** The spec orders `POST /orders` checks so the
422s come before the 404s. Those 422s live in the Pydantic schema, so FastAPI rejects a bad body
before the handler runs and the ordering is free rather than hand-coded. The 404/403/409 checks stay
in the service. Worth knowing if that endpoint is ever refactored: the ordering is partly enforced by
the request lifecycle, not by the service.

**A failed order can't half-reserve stock.** Every stock check finishes before any `book.stock -=`
runs, with a single `db.commit()` at the end, so a failure leaves nothing half-changed. Same shape in
`create_loan`. That's structural, not a matter of getting the line order right.

**The Postgres driver is an opt-in dependency group.** `ASSIGNMENT.md` forbids new dependencies and
`INSTRUCTIONS.md` requires a hosted database, so the default install stays exactly as specified and
only the deployment opts in with `uv sync --group postgres --no-dev`.

**No keep-alive ping.** Keeping Render awake would also keep Neon's compute running. At 0.25 CU,
720 hours is about 180 CU-hours against a 100/month allowance, which would suspend the database
mid-month. The ~1 minute cold start is the cheaper trade.

## Bugs I found and fixed

- `tier_at_least` used `>` where it needed `>=`, so a `master` failed the `master` minimum and
  masters were locked out of restricted books in both orders and loans. Its own docstring said "at
  or above", so it contradicted itself.
- `cancel_order`'s docstring promised to restore reserved stock, but the body only flipped the
  status. Stock was never coming back.
- `normalize_isbn13` used `str.isdigit()`, which is true for non-ASCII digits like Arabic-Indic `٧`
  or fullwidth `７`. Python's `int()` converts those happily, so a look-alike ISBN passed validation
  and was stored as its own "unique" value, visually identical to a real one. It's matched with
  `[0-9]{13}` now, which is ASCII-only.

## Spec points I'd flag

**Mixed-case title ordering is explicitly unspecified**, and the spec says so. SQLite sorts
uppercase first, Postgres generally doesn't. I left it alone rather than forcing a collation, since
both are accepted.

**`POST /orders` reserves stock immediately and `pay` doesn't touch it.** Cancelling is the only
thing that returns stock, and cancelling requires `pending`, so a paid order can't be undone through
the API at all. I assume that's intentional, though I'd want to confirm it.

**One tension in the brief.** The extras invite "tests for any edge case you think is missing" while
the ground rules say not to modify anything in `tests/`. I read that as add new files and leave the
existing ones alone, so the extra coverage went into a new `tests/test_edge_cases.py` and the
original suite is untouched.

## AI usage

I built the project as the primary developer, using Claude through Reasonix as an engineering assistant. I drove the architecture and implementation, ran the verification, and handled the Neon and Render setup myself. I mainly used the agent to check library documentation, understand unfamiliar SQLAlchemy 2.0 patterns, and help debug test cases. I also validated its suggestions rather than blindly accepting them. For example, testing ISBN validation with non-ASCII numerals uncovered a real edge case that I fixed and covered with dedicated tests.

**Where it was wrong.** I asked early whether the ISBN validation had holes and got a plausible
answer: `isdigit()` accepts non-ASCII digits, so `int()` would fail on those and the request would
come back as a 422 rather than something cleaner. That last part was wrong. When I actually ran the
function against Arabic-Indic and fullwidth numerals, most of them didn't fail at all, because
`int()` converts them without complaint. A look-alike ISBN passed validation and went into the
database as its own "unique" value. Reading the code and running the code gave two different
answers and I'd only been given the first, which is what turned into `tests/test_edge_cases.py`. It
had a related habit of writing defensive code for cases that can't occur, such as an `or 0` after a
`SELECT count(*)` that always returns one row.
