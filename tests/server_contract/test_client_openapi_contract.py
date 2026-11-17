"""Client workflow URLs must exist in the authoritative FastAPI OpenAPI specification."""

import re

import httpx
import pytest
from coyote.contracts.retrieval import ReadResource, ResourceReadPage, ResourceReadQuery
from coyote_api.app.main import create_api_app

from coyote_pyclient import AsyncCoyoteClient, CoyoteClient


@pytest.fixture
def contract_transport():
    """Reject client requests whose actual HTTP method/path is absent from OpenAPI."""
    paths = create_api_app().openapi()["paths"]
    calls = []

    def respond(request):
        path = request.url.path.removeprefix("/mounted")
        matched = [
            operations
            for template, operations in paths.items()
            if re.fullmatch(re.sub(r"\{[^}]+\}", "[^/]+", template), path)
        ]
        assert matched, f"Client invented an endpoint: {path}"
        assert request.method.lower() in matched[0], (request.method, path)
        calls.append((request.method, path))
        payload = {"name": "SYNTHETIC", "reported": False}
        if path.endswith("/auth/session"):
            payload = {"user": {"username": "synthetic"}}
        elif "/resources/read/" in path:
            name = path.split("/resources/read/", 1)[1].split("/", 1)[0]
            query = ResourceReadQuery.model_validate_json(request.content).validate_resource(
                ReadResource(name)
            )
            payload = ResourceReadPage(
                items=[],
                page=query.page,
                per_page=query.per_page,
                count=0 if query.operation == "count" else None,
                exists=False if query.operation == "exists" else None,
            ).model_dump(mode="json")
        elif path.endswith("/tiered"):
            payload = [{"_id": "synthetic-variant"}]
        elif path.endswith("/preview/bundle"):
            payload = {
                "html": "<p>Synthetic</p>",
                "pdf_base64": "JVBERi0=",
                "filename": "trial",
                "snapshot_count": 1,
            }
        elif path.endswith("/preview"):
            payload = {
                "meta": {"preview_fingerprint": "a" * 64},
                "report": {"html": "<p>Synthetic</p>", "context": {}},
            }
        elif path.endswith("/reports/dna") and request.method == "POST":
            payload = {"report": {"id": "synthetic-report", "file": "synthetic.html"}}
        elif path.endswith("/small-variants"):
            payload = {
                "display_sections_data": {"snvs": [{"_id": "synthetic-variant"}]},
                "meta": {"page": 1, "per_page": 50, "has_next": False},
            }
        return httpx.Response(200, json=payload)

    return httpx.MockTransport(respond), calls


def test_synchronous_typed_workflows_match_actual_server_operations(contract_transport):
    transport, calls = contract_transport
    with CoyoteClient("https://example.test/mounted", transport=transport) as client:
        client.login_with_token("synthetic-token")
        sample = client.samples.get("SYNTHETIC")
        sample.variants.list()
        sample.variants.tiered_variants()
        preview = sample.reports.preview("dna")
        sample.reports.save("dna", preview_fingerprint=preview.meta.preview_fingerprint)
        sample.reports.preview_bundle("dna")
    assert len(calls) == 7


@pytest.mark.asyncio
async def test_asynchronous_typed_workflows_use_the_same_openapi_operations(contract_transport):
    transport, calls = contract_transport
    async with AsyncCoyoteClient("https://example.test/mounted", transport=transport) as client:
        await client.login_with_token("synthetic-token")
        sample = await client.samples.get("SYNTHETIC")
        await sample.variants.list()
        await sample.variants.tiered_variants()
        preview = await sample.reports.preview("dna")
        await sample.reports.save("dna", preview_fingerprint=preview.meta.preview_fingerprint)
        await sample.reports.preview_bundle("dna")
    assert len(calls) == 7


@pytest.mark.parametrize(
    "collection", ["asp", "aspc", "samples", "isgl", "assay_groups", "diagnoses"]
)
def test_read_catalog_matches_server_routes_and_request_contract(contract_transport, collection):
    transport, calls = contract_transport
    with CoyoteClient("https://example.test/mounted", transport=transport) as client:
        client.login_with_token("synthetic-token")
        reader = getattr(client.read, collection)
        assert reader.list().items == []
        assert reader.ids().items == []
        assert reader.count() == 0
        assert reader.exists() is False
    assert len(calls) == 5


@pytest.mark.asyncio
async def test_async_combined_sample_read_matches_server_contract(contract_transport):
    transport, _ = contract_transport
    async with AsyncCoyoteClient("https://example.test/mounted", transport=transport) as client:
        await client.login_with_token("synthetic-token")
        page = await client.read.samples.list(
            asp_id="SYNTHETIC",
            environment="production",
            filters={"time_added": {"gte": "2026-01-01T00:00:00Z"}},
            fields=["name", "asp_id"],
            include=["assay", "configuration"],
            related_filters={"configuration": {"environment": "production", "is_active": True}},
        )
        assert page.items == []
        page = await client.read.samples.distinct("asp_id", reported=False)
        assert page.items == []
