# SPDX-FileCopyrightText: 2026 Ram Nanduri
# SPDX-License-Identifier: GPL-3.0-only

"""Synchronous and asynchronous retrieval of named, permission-scoped resources."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from typing import Any, Protocol, cast

from coyote_pyclient.errors import ResponseValidationError, parse_model
from coyote_pyclient.read_models import (
    RESOURCE_IDS,
    FilterValue,
    ReadPage,
    ReadQuery,
    RelatedFilters,
    ResourceName,
    Scalar,
)


class ReadTransport(Protocol):
    """Authenticated synchronous request capability supplied by the owning client."""

    _session_generation: int

    def _request(self, method: str, path: str, **kwargs: Any) -> Any: ...


class AsyncReadTransport(Protocol):
    """Authenticated asynchronous request capability supplied by the owning client."""

    _session_generation: int

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any: ...


def _filters(explicit: dict[str, FilterValue] | None, equalities: dict[str, Any]) -> dict:
    """Combine explicit predicates and equality keywords without replacing a condition."""
    if set(explicit or {}) & set(equalities):
        raise ValueError("A filter must be supplied once, either in filters or as a keyword")
    return {**(explicit or {}), **equalities}


def _identity_filters(resource: ResourceName, identity: str, filters: dict) -> dict:
    """Require an unambiguous logical identifier without silently replacing a filter."""
    if not isinstance(identity, str) or not identity.strip():
        raise ValueError("The resource identifier must be nonempty text")
    return _filters(filters, {RESOURCE_IDS[resource]: identity})


def _page(payload: Any, query: ReadQuery) -> ReadPage:
    """Validate operation-specific rows and continuation before exposing a response."""
    page = parse_model(ReadPage, payload)
    if page.page != query.page or page.per_page != query.per_page:
        raise ResponseValidationError("Response pagination does not match the requested page")
    if len(page.items) > page.per_page or (page.has_next and not page.items):
        raise ResponseValidationError("Response continuation is inconsistent with its rows")
    if query.operation == "list" and any(not isinstance(item, dict) for item in page.items):
        raise ResponseValidationError("A resource list must contain object rows")
    if query.operation == "ids" and any(not isinstance(item, str) for item in page.items):
        raise ResponseValidationError("Resource IDs must be strings")
    if query.operation == "distinct" and any(isinstance(item, dict) for item in page.items):
        raise ResponseValidationError("Distinct results must contain scalar values")
    if query.operation == "count" and page.count is None:
        raise ResponseValidationError("A count response must provide count")
    if query.operation == "exists" and page.exists is None:
        raise ResponseValidationError("An existence response must provide exists")
    return page


def _record(page: ReadPage) -> dict[str, Any] | None:
    """Return one record, or require a version/active predicate when identity is ambiguous."""
    if page.total > 1 or len(page.items) > 1:
        raise ValueError("Multiple records match; constrain the query by version or active status")
    if page.total == 0:
        if page.items:
            raise ResponseValidationError("An empty result count cannot contain a record")
        return None
    if not page.items:
        raise ResponseValidationError("The requested record is absent from a nonempty result")
    return cast(dict[str, Any], page.items[0])


class ReadResource:
    """Read one logical resource without accepting database collection names or operators."""

    def __init__(self, client: ReadTransport, resource: ResourceName) -> None:
        """Bind the authenticated transport and declared resource name without network I/O."""
        self._client, self._resource = client, resource
        self._path = f"resources/read/{resource}/query"

    def query(self, request: ReadQuery) -> ReadPage:
        """Execute one validated read and retain the complete response envelope.

        Args:
            request: Operation, permitted fields, predicates and bounded pagination.

        Returns:
            Validated page with projected records or scalar results.

        Raises:
            ValueError: A request option, field or relation is invalid.
            CoyoteAPIError: Server authorization or validation rejects the request.
            ResponseValidationError: A successful response violates the wire contract.
        """
        request = ReadQuery.model_validate(request.model_dump()).for_resource(self._resource)
        return _page(self._client._request("POST", self._path, json=request.model_dump()), request)

    def list(
        self,
        *,
        filters: dict[str, FilterValue] | None = None,
        related_filters: RelatedFilters | None = None,
        fields: list[str] | None = None,
        sort: str | None = None,
        descending: bool = False,
        page: int = 1,
        per_page: int = 50,
        include: list[str] | None = None,
        **equals: Any,
    ) -> ReadPage:
        """Fetch a page of records, combining explicit predicates and equality keywords.

        Args:
            filters: Allowed field predicates, combined using AND.
            related_filters: Predicates on a sample's active assay or stored configuration.
            fields: Selected response fields; None uses the server's metadata projection.
            sort: Permitted sort field, or the server's default stable order.
            descending: Reverse the selected order.
            page: One-based result page.
            per_page: Maximum rows per page, from 1 through 200.
            include: For samples, optional assay and configuration relations.
            **equals: Additional field-equals-value predicates.

        Returns:
            One page of projected metadata, including requested related records.
        """
        return self.query(
            ReadQuery(
                filters=_filters(filters, equals),
                related_filters=related_filters or {},
                fields=fields,
                sort=sort,
                descending=descending,
                page=page,
                per_page=per_page,
                include=include or [],
            )
        )

    def ids(
        self,
        *,
        filters: dict[str, FilterValue] | None = None,
        related_filters: RelatedFilters | None = None,
        descending: bool = False,
        page: int = 1,
        per_page: int = 50,
        **equals: Any,
    ) -> ReadPage:
        """Fetch one page of distinct logical IDs satisfying the supplied predicates."""
        return self.query(
            ReadQuery(
                operation="ids",
                filters=_filters(filters, equals),
                related_filters=related_filters or {},
                descending=descending,
                page=page,
                per_page=per_page,
            )
        )

    def get(
        self,
        resource_id: str,
        *,
        filters: dict[str, FilterValue] | None = None,
        related_filters: RelatedFilters | None = None,
        fields: list[str] | None = None,
        include: list[str] | None = None,
        **equals: Any,
    ) -> dict[str, Any] | None:
        """Fetch a unique logical ID, returning None when it is not visible or absent.

        Args:
            resource_id: Resource-specific logical ID, such as asp_id or sample name.
            filters: Additional predicates, including version or active status if needed.
            related_filters: Predicates on a sample's related assay or configuration.
            fields: Optional metadata projection.
            include: Optional sample relations.
            **equals: Additional equality predicates.

        Returns:
            One projected record, or None if no authorized record matches.

        Raises:
            ValueError: Multiple versions match or the ID predicate is supplied twice.
        """
        filters = _identity_filters(self._resource, resource_id, _filters(filters, equals))
        return _record(
            self.list(
                filters=filters,
                fields=fields,
                include=include,
                related_filters=related_filters,
                per_page=2,
            )
        )

    def count(
        self,
        *,
        filters: dict[str, FilterValue] | None = None,
        related_filters: RelatedFilters | None = None,
        **equals: Any,
    ) -> int:
        """Count matching authorized records, preserving zero as a valid result."""
        result = self.query(
            ReadQuery(
                operation="count",
                filters=_filters(filters, equals),
                related_filters=related_filters or {},
            )
        )
        assert result.count is not None
        return result.count

    def exists(
        self,
        *,
        filters: dict[str, FilterValue] | None = None,
        related_filters: RelatedFilters | None = None,
        **equals: Any,
    ) -> bool:
        """Return whether any authorized record satisfies all predicates."""
        result = self.query(
            ReadQuery(
                operation="exists",
                filters=_filters(filters, equals),
                related_filters=related_filters or {},
            )
        )
        assert result.exists is not None
        return result.exists

    def distinct(
        self,
        field: str,
        *,
        filters: dict[str, FilterValue] | None = None,
        related_filters: RelatedFilters | None = None,
        page: int = 1,
        per_page: int = 50,
        descending: bool = False,
        **equals: Any,
    ) -> ReadPage:
        """Fetch a bounded page of distinct scalar values for a supported field."""
        return self.query(
            ReadQuery(
                operation="distinct",
                field=field,
                filters=_filters(filters, equals),
                related_filters=related_filters or {},
                page=page,
                per_page=per_page,
                descending=descending,
            )
        )

    def pages(self, request: ReadQuery) -> Iterator[ReadPage]:
        """Lazily traverse list, ID or distinct pages within the current session.

        Args:
            request: Initial query including its starting page and page size.

        Yields:
            Each validated response, stopping at the first page without continuation.

        Raises:
            ValueError: The operation is not paginated.
            RuntimeError: Authentication changes between page requests.
        """
        if request.operation not in {"list", "ids", "distinct"}:
            raise ValueError("Only list, ids and distinct operations support pagination")
        generation = self._client._session_generation
        while True:
            if generation != self._client._session_generation:
                raise RuntimeError("Authentication changed during resource pagination")
            result = self.query(request)
            yield result
            if not result.has_next:
                return
            request = request.model_copy(update={"page": request.page + 1})

    def iter(self, request: ReadQuery) -> Iterator[dict[str, Any] | Scalar]:
        """Yield rows across explicit paginated queries without accumulating all results."""
        for page in self.pages(request):
            yield from page.items

    def iter_ids(
        self,
        *,
        filters: dict[str, FilterValue] | None = None,
        related_filters: RelatedFilters | None = None,
        per_page: int = 50,
        **equals: Any,
    ) -> Iterator[str]:
        """Yield all matching logical IDs lazily through bounded server pages."""
        query = ReadQuery(
            operation="ids",
            filters=_filters(filters, equals),
            related_filters=related_filters or {},
            per_page=per_page,
        )
        for page in self.pages(query):
            yield from cast(list[str], page.items)


class AsyncReadResource:
    """Awaitable counterpart to ReadResource with the same request and result contracts."""

    def __init__(self, client: AsyncReadTransport, resource: ResourceName) -> None:
        """Bind one authenticated async transport and logical resource without network I/O."""
        self._client, self._resource = client, resource
        self._path = f"resources/read/{resource}/query"

    async def query(self, request: ReadQuery) -> ReadPage:
        """Execute one validated read; server permissions apply to all operations."""
        request = ReadQuery.model_validate(request.model_dump()).for_resource(self._resource)
        payload = await self._client._request("POST", self._path, json=request.model_dump())
        return _page(payload, request)

    async def list(
        self,
        *,
        filters: dict[str, FilterValue] | None = None,
        related_filters: RelatedFilters | None = None,
        fields: list[str] | None = None,
        sort: str | None = None,
        descending: bool = False,
        page: int = 1,
        per_page: int = 50,
        include: list[str] | None = None,
        **equals: Any,
    ) -> ReadPage:
        """Fetch projected metadata with the same options as the synchronous list method."""
        return await self.query(
            ReadQuery(
                filters=_filters(filters, equals),
                related_filters=related_filters or {},
                fields=fields,
                sort=sort,
                descending=descending,
                page=page,
                per_page=per_page,
                include=include or [],
            )
        )

    async def ids(
        self,
        *,
        filters: dict[str, FilterValue] | None = None,
        related_filters: RelatedFilters | None = None,
        descending: bool = False,
        page: int = 1,
        per_page: int = 50,
        **equals: Any,
    ) -> ReadPage:
        """Fetch a bounded page of distinct logical IDs."""
        return await self.query(
            ReadQuery(
                operation="ids",
                filters=_filters(filters, equals),
                related_filters=related_filters or {},
                descending=descending,
                page=page,
                per_page=per_page,
            )
        )

    async def get(
        self,
        resource_id: str,
        *,
        filters: dict[str, FilterValue] | None = None,
        related_filters: RelatedFilters | None = None,
        fields: list[str] | None = None,
        include: list[str] | None = None,
        **equals: Any,
    ) -> dict[str, Any] | None:
        """Fetch one logical ID, returning None if absent and rejecting ambiguous versions."""
        filters = _identity_filters(self._resource, resource_id, _filters(filters, equals))
        return _record(
            await self.list(
                filters=filters,
                fields=fields,
                include=include,
                related_filters=related_filters,
                per_page=2,
            )
        )

    async def count(
        self,
        *,
        filters: dict[str, FilterValue] | None = None,
        related_filters: RelatedFilters | None = None,
        **equals: Any,
    ) -> int:
        """Count records using current server permissions."""
        result = await self.query(
            ReadQuery(
                operation="count",
                filters=_filters(filters, equals),
                related_filters=related_filters or {},
            )
        )
        assert result.count is not None
        return result.count

    async def exists(
        self,
        *,
        filters: dict[str, FilterValue] | None = None,
        related_filters: RelatedFilters | None = None,
        **equals: Any,
    ) -> bool:
        """Check existence without losing a false result."""
        result = await self.query(
            ReadQuery(
                operation="exists",
                filters=_filters(filters, equals),
                related_filters=related_filters or {},
            )
        )
        assert result.exists is not None
        return result.exists

    async def distinct(
        self,
        field: str,
        *,
        filters: dict[str, FilterValue] | None = None,
        related_filters: RelatedFilters | None = None,
        page: int = 1,
        per_page: int = 50,
        descending: bool = False,
        **equals: Any,
    ) -> ReadPage:
        """Fetch distinct scalar values using the same predicates as synchronous reads."""
        return await self.query(
            ReadQuery(
                operation="distinct",
                field=field,
                filters=_filters(filters, equals),
                related_filters=related_filters or {},
                page=page,
                per_page=per_page,
                descending=descending,
            )
        )

    async def pages(self, request: ReadQuery) -> AsyncIterator[ReadPage]:
        """Lazily await pages, stopping when complete or authentication changes."""
        if request.operation not in {"list", "ids", "distinct"}:
            raise ValueError("Only list, ids and distinct operations support pagination")
        generation = self._client._session_generation
        while True:
            if generation != self._client._session_generation:
                raise RuntimeError("Authentication changed during resource pagination")
            result = await self.query(request)
            yield result
            if not result.has_next:
                return
            request = request.model_copy(update={"page": request.page + 1})

    async def iter(self, request: ReadQuery) -> AsyncIterator[dict[str, Any] | Scalar]:
        """Yield individual results without buffering all server pages."""
        async for page in self.pages(request):
            for item in page.items:
                yield item

    async def iter_ids(
        self,
        *,
        filters: dict[str, FilterValue] | None = None,
        related_filters: RelatedFilters | None = None,
        per_page: int = 50,
        **equals: Any,
    ) -> AsyncIterator[str]:
        """Yield all matching IDs lazily using the current session."""
        query = ReadQuery(
            operation="ids",
            filters=_filters(filters, equals),
            related_filters=related_filters or {},
            per_page=per_page,
        )
        async for page in self.pages(query):
            for item in page.items:
                yield cast(str, item)


class ReadResources:
    """Named resource readers; constructing or selecting a reader does not send requests."""

    def __init__(self, client: ReadTransport) -> None:
        """Expose the documented resource catalog without arbitrary collection access."""
        self.asp = ReadResource(client, "asp")
        self.aspc = ReadResource(client, "aspc")
        self.samples = ReadResource(client, "samples")
        self.isgl = ReadResource(client, "isgl")
        self.assay_groups = ReadResource(client, "assay-groups")
        self.diagnoses = ReadResource(client, "diagnoses")


class AsyncReadResources:
    """Named async readers sharing the synchronous client's resource catalog."""

    def __init__(self, client: AsyncReadTransport) -> None:
        """Expose explicit readers without performing network I/O."""
        self.asp = AsyncReadResource(client, "asp")
        self.aspc = AsyncReadResource(client, "aspc")
        self.samples = AsyncReadResource(client, "samples")
        self.isgl = AsyncReadResource(client, "isgl")
        self.assay_groups = AsyncReadResource(client, "assay-groups")
        self.diagnoses = AsyncReadResource(client, "diagnoses")
