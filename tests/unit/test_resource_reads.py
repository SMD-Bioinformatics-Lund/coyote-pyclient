"""Resource retrieval preserves predicates, authorization and bounded continuation."""

import json

import httpx
import pytest
from pydantic import ValidationError

from coyote_pyclient import (
    AsyncCoyoteClient,
    CoyoteClient,
    PermissionDeniedError,
    ReadQuery,
    ResponseValidationError,
)


def envelope(query, *, items=None, total=0, count=None, exists=None, has_next=False):
    return {
        "items": items or [],
        "total": total,
        "page": query["page"],
        "per_page": query["per_page"],
        "has_next": has_next,
        "count": count,
        "exists": exists,
    }


@pytest.fixture
def api():
    calls = []
    state = {"items": [{"asp_id": "SYNTHETIC"}], "total": 1, "status": 200}

    def respond(request):
        if request.url.path.endswith("/auth/session"):
            return httpx.Response(200, json={"user": {"username": "synthetic"}})
        calls.append(request)
        body = json.loads(request.content)
        if "response" in state:
            response = state["response"](body)
        else:
            options = {key: value for key, value in state.items() if key != "status"}
            response = envelope(body, **options)
        return httpx.Response(state["status"], json=response)

    return httpx.MockTransport(respond), calls, state


def client(api):
    transport, _, _ = api
    connection = CoyoteClient("https://example.test/mounted", transport=transport)
    connection.login_with_token("synthetic-token")
    return connection


def test_projection_multiple_predicates_and_relations_are_explicit(api):
    _, calls, state = api
    state["items"] = [{"name": "SYNTHETIC", "related": {"assay": None}}]
    with client(api) as connection:
        result = connection.read.samples.list(
            filters={"version": {"gte": 2, "lte": 4}, "asp_id": {"in": ["A", "B"]}},
            environment="production",
            reported=False,
            fields=["name"],
            include=["assay"],
            related_filters={"configuration": {"is_active": True}},
            sort="time_added",
            descending=True,
            page=2,
            per_page=20,
        )
    assert result.items == [{"name": "SYNTHETIC", "related": {"assay": None}}]
    request = calls[0]
    assert request.url.path == "/mounted/api/v1/resources/read/samples/query"
    assert request.method == "POST"
    assert request.headers["Authorization"] == "Bearer synthetic-token"
    assert "cookie" not in request.headers
    body = json.loads(request.content)
    assert body["filters"] == {
        "version": {"gte": 2, "lte": 4},
        "asp_id": {"in": ["A", "B"]},
        "environment": "production",
        "reported": False,
    }
    assert body["fields"] == ["name"]
    assert body["include"] == ["assay"]
    assert body["related_filters"] == {"configuration": {"is_active": True}}
    assert body["sort"] == "time_added" and body["descending"] is True
    assert body["page"] == 2 and body["per_page"] == 20


@pytest.mark.parametrize(
    "attribute,wire",
    [
        ("asp", "asp"),
        ("aspc", "aspc"),
        ("samples", "samples"),
        ("isgl", "isgl"),
        ("assay_groups", "assay-groups"),
        ("diagnoses", "diagnoses"),
    ],
)
def test_resource_catalog_and_counts_preserve_zero(api, attribute, wire):
    _, calls, state = api
    state.update(items=[], total=0, count=0)
    with client(api) as connection:
        assert getattr(connection.read, attribute).count() == 0
    assert calls[0].url.path.endswith(f"/resources/read/{wire}/query")
    assert json.loads(calls[0].content)["operation"] == "count"


def test_exists_ids_and_distinct_preserve_false_null_and_strings(api):
    _, calls, state = api
    with client(api) as connection:
        state.update(items=[], total=0, exists=False)
        assert connection.read.asp.exists(is_active=False) is False
        state.update(items=["A", "B"], total=2, exists=None)
        assert connection.read.asp.ids(is_active=True).items == ["A", "B"]
        state.update(items=[None, False, "value", 0], total=4)
        assert connection.read.asp.distinct("platform").items == [None, False, "value", 0]
    assert [json.loads(item.content)["operation"] for item in calls] == [
        "exists",
        "ids",
        "distinct",
    ]


def test_get_returns_none_for_missing_and_rejects_ambiguous_versions(api):
    _, calls, state = api
    with client(api) as connection:
        assert connection.read.asp.get("SYNTHETIC", version=1) == {"asp_id": "SYNTHETIC"}
        body = json.loads(calls[-1].content)
        assert body["filters"] == {"asp_id": "SYNTHETIC", "version": 1}
        assert body["per_page"] == 2
        state.update(items=[], total=0)
        assert connection.read.asp.get("missing") is None
        state.update(items=[{"asp_id": "A"}, {"asp_id": "A"}], total=2)
        with pytest.raises(ValueError, match="Multiple records"):
            connection.read.asp.get("A")
        with pytest.raises(ValueError, match="identifier"):
            connection.read.asp.get("")
        with pytest.raises(ValueError, match="once"):
            connection.read.asp.get("A", asp_id="B")


@pytest.mark.parametrize(
    "options",
    [
        {"is_actve": True},
        {"fields": ["password"]},
        {"sort": "$where"},
        {"filters": {"is_active": {"$ne": True}}},
        {"per_page": 201},
        {"page": 0},
        {"filters": {"version": {"in": []}}},
        {"filters": {"version": {"gte": [1, 2]}}},
        {"filters": {"is_active": True}, "is_active": False},
        {"include": ["assay"]},
        {"fields": []},
        {"fields": ["asp_id", "asp_id"]},
    ],
)
def test_invalid_filter_options_fail_before_request(api, options):
    _, calls, _ = api
    with client(api) as connection:
        with pytest.raises(ValueError):
            connection.read.asp.list(**options)
    assert calls == []


@pytest.mark.parametrize(
    "options",
    [
        {"operation": "raw-find"},
        {"operation": "distinct"},
        {"field": "asp_id"},
        {"operation": "count", "fields": ["asp_id"]},
        {"include": ["assay", "assay"]},
        {"filters": {"version": {}}},
        {"filters": {"version": float("nan")}},
        {"page": True},
        {"page": 10001},
        {"operation": "ids", "sort": "asp_id"},
        {"filters": {"version": {"gte": None}}},
        {"filters": {"version": 1.5}},
        {"filters": {"asp_id": "a" * 513}},
        {"related_filters": {"configuration": {}}},
        {"related_filters": {"passwords": {"is_active": True}}},
        {"unknown": 1},
    ],
)
def test_query_model_rejects_unsupported_shapes(options):
    with pytest.raises(ValidationError):
        ReadQuery(**options)


def test_reads_require_authentication_and_preserve_permission_errors(api):
    transport, calls, state = api
    with CoyoteClient("https://example.test", transport=transport) as connection:
        with pytest.raises(RuntimeError, match="Log in"):
            connection.read.asp.list()
        assert calls == []
        connection.login_with_token("synthetic-token")
        state["status"] = 403
        with pytest.raises(PermissionDeniedError):
            connection.read.asp.count()


def test_id_iteration_is_lazy_bounded_and_uses_distinct_id_operation(api):
    _, calls, state = api
    state["response"] = lambda query: envelope(
        query,
        items=["A", "B"] if query["page"] == 1 else ["C"],
        total=3,
        has_next=query["page"] == 1,
    )
    with client(api) as connection:
        iterator = connection.read.asp.iter_ids(is_active=True, per_page=2)
        assert calls == []
        assert next(iterator) == "A"
        assert len(calls) == 1
        assert list(iterator) == ["B", "C"]
    assert [json.loads(item.content)["page"] for item in calls] == [1, 2]
    assert all(json.loads(item.content)["operation"] == "ids" for item in calls)


def test_iteration_stops_when_authentication_changes(api):
    _, calls, state = api
    state["response"] = lambda query: envelope(query, items=["A"], total=2, has_next=True)
    with client(api) as connection:
        iterator = connection.read.asp.iter(ReadQuery(operation="ids", per_page=1))
        assert next(iterator) == "A"
        connection.login_with_token("different-synthetic-token")
        with pytest.raises(RuntimeError, match="Authentication changed"):
            next(iterator)
        with pytest.raises(ValueError, match="pagination"):
            list(connection.read.asp.pages(ReadQuery(operation="count")))
    assert len(calls) == 1


@pytest.mark.parametrize(
    "operation,override",
    [
        ("list", {"items": ["not-an-object"]}),
        ("ids", {"items": [123]}),
        ("distinct", {"items": [{"unexpected": "object"}]}),
        ("count", {"count": None}),
        ("exists", {"exists": None}),
        ("list", {"page": 2}),
        ("list", {"items": [], "has_next": True}),
        ("ids", {"items": ["A", "B"], "per_page": 1}),
    ],
)
def test_invalid_read_responses_are_rejected(api, operation, override):
    _, _, state = api
    state["response"] = lambda query: {**envelope(query), **override}
    with client(api) as connection:
        query = ReadQuery(
            operation=operation, field="platform" if operation == "distinct" else None
        )
        with pytest.raises(ResponseValidationError):
            connection.read.asp.query(query)


@pytest.mark.asyncio
async def test_async_read_operations_match_sync_wire_contract(api):
    transport, calls, state = api
    async with AsyncCoyoteClient("https://example.test/mounted", transport=transport) as connection:
        await connection.login_with_token("synthetic-token")
        result = await connection.read.asp.list(fields=["asp_id"], is_active=True)
        assert result.items == [{"asp_id": "SYNTHETIC"}]
        assert await connection.read.asp.get("SYNTHETIC", version=1) == {"asp_id": "SYNTHETIC"}
        state.update(items=[], total=0, count=0, exists=False)
        assert await connection.read.asp.count() == 0
        assert await connection.read.asp.exists() is False
        assert await connection.read.asp.get("missing") is None
        state.update(items=["A"], total=1, count=None, exists=None)
        assert (await connection.read.asp.ids()).items == ["A"]
        assert (await connection.read.asp.distinct("platform")).items == ["A"]
        assert [item async for item in connection.read.asp.iter(ReadQuery(operation="ids"))] == [
            "A"
        ]
    assert all(call.url.path.endswith("/resources/read/asp/query") for call in calls)


@pytest.mark.asyncio
async def test_async_pagination_stops_at_completion_and_rejects_session_changes(api):
    transport, _, state = api
    state["response"] = lambda query: envelope(
        query,
        items=["A"] if query["page"] == 1 else ["B"],
        total=2,
        has_next=query["page"] == 1,
    )
    async with AsyncCoyoteClient("https://example.test", transport=transport) as connection:
        await connection.login_with_token("synthetic-token")
        assert [item async for item in connection.read.asp.iter_ids(per_page=1)] == ["A", "B"]
        iterator = connection.read.asp.pages(ReadQuery(operation="ids", per_page=1))
        assert (await anext(iterator)).items == ["A"]
        await connection.login_with_token("replacement-synthetic-token")
        with pytest.raises(RuntimeError, match="Authentication changed"):
            await anext(iterator)
        iterator = connection.read.asp.pages(ReadQuery(operation="exists"))
        with pytest.raises(ValueError, match="pagination"):
            await anext(iterator)


@pytest.mark.parametrize("operation", ["list", "ids", "count", "exists", "distinct", "get"])
def test_sample_related_predicates_are_preserved_for_each_helper(api, operation):
    _, calls, state = api
    predicates = {"assay": {"is_active": True}, "configuration": {"environment": "production"}}
    with client(api) as connection:
        reader = connection.read.samples
        arguments = {"related_filters": predicates, "asp_id": "SYNTHETIC"}
        if operation == "get":
            reader.get("SYNTHETIC_SAMPLE", **arguments)
        elif operation == "distinct":
            state.update(items=["SYNTHETIC"], total=1)
            reader.distinct("asp_id", **arguments)
        else:
            if operation == "ids":
                state.update(items=["SYNTHETIC_SAMPLE"], total=1)
            if operation in {"count", "exists"}:
                state.update(items=[], count=1, exists=True)
            getattr(reader, operation)(**arguments)
    body = json.loads(calls[0].content)
    assert body["related_filters"] == predicates
    assert body["filters"]["asp_id"] == "SYNTHETIC"


@pytest.mark.parametrize(
    "resource,predicates",
    [
        ("asp", {"assay": {"is_active": True}}),
        ("samples", {"assay": {"private_token": "secret"}}),
        ("samples", {"configuration": {"is_active": {"$ne": False}}}),
    ],
)
def test_unsupported_related_predicates_fail_before_request(api, resource, predicates):
    _, calls, _ = api
    with client(api) as connection:
        with pytest.raises(ValueError):
            getattr(connection.read, resource).count(related_filters=predicates)
    assert calls == []


@pytest.mark.asyncio
async def test_async_related_filters_apply_to_every_operation(api):
    transport, calls, state = api
    predicates = {"configuration": {"environment": "production"}}
    async with AsyncCoyoteClient("https://example.test", transport=transport) as connection:
        await connection.login_with_token("synthetic-token")
        reader = connection.read.samples
        await reader.list(related_filters=predicates)
        await reader.get("SYNTHETIC_SAMPLE", related_filters=predicates)
        state.update(items=[], count=1, exists=True)
        assert await reader.count(related_filters=predicates) == 1
        assert await reader.exists(related_filters=predicates) is True
        state.update(items=["SYNTHETIC_SAMPLE"], total=1)
        await reader.ids(related_filters=predicates)
        await reader.distinct("name", related_filters=predicates)
        assert [item async for item in reader.iter_ids(related_filters=predicates)] == [
            "SYNTHETIC_SAMPLE"
        ]
    assert all(json.loads(call.content)["related_filters"] == predicates for call in calls)
