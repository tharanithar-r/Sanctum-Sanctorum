"""Extra coverage for edge cases the main suite doesn't reach.

New file rather than edits to the existing tests, since those are the acceptance criteria
and shouldn't move.
"""
import pytest
from sqlalchemy import Select, create_engine, event
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import Book
from app.services import books as book_service
from tests.conftest import isbn13


def book_payload(**overrides) -> dict:
    payload = {
        "title": "Edge Case",
        "author": "Tester",
        "isbn": isbn13(9001),
        "price_cents": 1000,
        "stock": 5,
    }
    payload.update(overrides)
    return payload


class TestIsbnDigits:
    """`str.isdigit()` accepts non-ASCII digits and `int()` converts them, so
    Arabic-Indic and fullwidth numerals used to be stored as valid-looking ISBNs."""

    @pytest.mark.parametrize("digit", ["\u0667", "\uff17", "\u00b2"])
    def test_non_ascii_digit_is_rejected(self, client, digit):
        isbn = isbn13(9001)[:12] + digit
        assert client.post("/books", json=book_payload(isbn=isbn)).status_code == 422

    def test_non_ascii_lookalike_does_not_become_a_second_book(self, client):
        """The same digits in Arabic-Indic numerals must not slip past as a distinct ISBN."""
        isbn = isbn13(9001)
        assert client.post("/books", json=book_payload(isbn=isbn)).status_code == 201

        arabic_indic = "\u0660\u0661\u0662\u0663\u0664\u0665\u0666\u0667\u0668\u0669"
        lookalike = isbn[:12] + arabic_indic[int(isbn[12])]

        assert client.post("/books", json=book_payload(isbn=lookalike)).status_code == 422
        assert client.get("/books?limit=100").json()["total"] == 1

    def test_ascii_isbn_still_accepted(self, client):
        assert client.post("/books", json=book_payload()).status_code == 201


class TestFalsyFilters:
    """0 is a legitimate price bound, so the filters must test `is not None`, not truthiness."""

    def test_max_price_zero_keeps_only_free_books(self, client, make_book):
        free = make_book(price_cents=0)
        make_book(price_cents=500)
        response = client.get("/books", params={"max_price": 0})
        assert [b["id"] for b in response.json()["items"]] == [free["id"]]

    def test_min_price_zero_keeps_everything(self, client, make_book):
        books = [make_book(price_cents=p) for p in [0, 100, 200]]
        response = client.get("/books", params={"min_price": 0})
        assert [b["id"] for b in response.json()["items"]] == [b["id"] for b in books]


class TestPatchTolerance:
    def test_unknown_fields_are_ignored(self, client, make_book):
        book = make_book()
        response = client.patch(f"/books/{book['id']}", json={"stock": 3, "nonsense": "ignored"})
        assert response.status_code == 200
        assert response.json() == {**book, "stock": 3}


class TestMemberPagination:
    def test_page_and_total(self, client, make_member):
        members = [make_member() for _ in range(5)]
        body = client.get("/members", params={"limit": 2, "offset": 2}).json()
        assert [m["id"] for m in body["items"]] == [members[2]["id"], members[3]["id"]]
        assert body["total"] == 5
        assert body["limit"] == 2
        assert body["offset"] == 2

    def test_default_limit_is_20(self, client, make_member):
        for _ in range(21):
            make_member()
        body = client.get("/members").json()
        assert len(body["items"]) == 20
        assert body["total"] == 21

    def test_offset_past_end_returns_no_items_but_total(self, client, make_member):
        make_member()
        make_member()
        body = client.get("/members", params={"offset": 10}).json()
        assert body["items"] == []
        assert body["total"] == 2

    @pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 101}, {"offset": -1}])
    def test_out_of_range_pagination_returns_422(self, client, params):
        assert client.get("/members", params=params).status_code == 422

    def test_items_are_full_member_objects(self, client, make_member):
        member = make_member()
        assert client.get("/members").json()["items"] == [member]


class TestStockRowLock:
    """A live race can't be reproduced on SQLite, which ignores FOR UPDATE, so assert
    the statement the service builds instead."""

    def _locked_statements(self, session, **kwargs) -> list:
        captured = []

        @event.listens_for(session.get_bind(), "before_execute")
        def _capture(conn, clauseelement, multiparams, params, execution_options):
            captured.append(clauseelement)

        book_service.get_book(session, 1, **kwargs)
        event.remove(session.get_bind(), "before_execute", _capture)
        return [
            str(s.compile(dialect=postgresql.dialect()))
            for s in captured
            if isinstance(s, Select)
        ]

    @pytest.fixture
    def session(self):
        engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        Base.metadata.create_all(engine)
        with sessionmaker(bind=engine, expire_on_commit=False)() as db:
            db.add(Book(title="Locked", author="A", isbn=isbn13(9001), price_cents=1, stock=1))
            db.commit()
            yield db
        engine.dispose()

    def test_for_update_requests_a_lock(self, session):
        compiled = self._locked_statements(session, for_update=True)
        assert compiled and all("FOR UPDATE" in sql for sql in compiled)

    def test_plain_get_takes_no_lock(self, session):
        compiled = self._locked_statements(session)
        assert compiled and not any("FOR UPDATE" in sql for sql in compiled)
