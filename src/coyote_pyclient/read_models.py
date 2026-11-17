# SPDX-FileCopyrightText: 2026 Ram Nanduri
# SPDX-License-Identifier: GPL-3.0-only

"""Client-owned contracts for permission-scoped resource retrieval."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from coyote_pyclient.metadata import (
    AssayMetadata,
    ConfigurationMetadata,
    DiagnosisMetadata,
    GeneListMetadata,
    GroupMetadata,
    SampleMetadata,
)

ResourceName = Literal["asp", "aspc", "samples", "isgl", "assay-groups", "diagnoses"]
ReadOperation = Literal["list", "ids", "count", "exists", "distinct"]
Scalar = str | bool | int | float | None
FilterScalar = Annotated[str, Field(max_length=512)] | bool | int | None
FilterValue = FilterScalar | dict[str, FilterScalar | list[FilterScalar]]
RelatedFilters = dict[Literal["assay", "configuration"], dict[str, FilterValue]]

RESOURCE_MODELS = {
    "asp": AssayMetadata,
    "aspc": ConfigurationMetadata,
    "samples": SampleMetadata,
    "isgl": GeneListMetadata,
    "assay-groups": GroupMetadata,
    "diagnoses": DiagnosisMetadata,
}
RESOURCE_IDS = {
    "asp": "asp_id",
    "aspc": "aspc_id",
    "samples": "name",
    "isgl": "isgl_id",
    "assay-groups": "group_id",
    "diagnoses": "diagnosis_id",
}


class ReadQuery(BaseModel):
    """Describe a bounded read using declared fields and explicit predicates.

    Scalar predicates mean equality. Operator objects combine ``eq``, ``in``,
    ``gte`` and ``lte`` conditions with AND. The server validates resource-specific
    types, permissions and relationships; no database operators are accepted.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, allow_inf_nan=False)

    operation: ReadOperation = "list"
    filters: dict[str, FilterValue] = Field(default_factory=dict, max_length=20)
    related_filters: RelatedFilters = Field(default_factory=dict)
    fields: list[str] | None = Field(default=None, min_length=1, max_length=30)
    sort: str | None = None
    descending: bool = False
    page: int = Field(default=1, ge=1, le=10000)
    per_page: int = Field(default=50, ge=1, le=200)
    field: str | None = None
    include: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_shape(self) -> ReadQuery:
        """Reject unsupported operators and incompatible operation options locally."""
        if any(not predicates for predicates in self.related_filters.values()):
            raise ValueError("Related-resource predicates must not be empty")
        for predicates in [self.filters, *self.related_filters.values()]:
            if len(predicates) > 20:
                raise ValueError("At most 20 filter fields may be supplied")
            for condition in predicates.values():
                if not isinstance(condition, dict):
                    continue
                if not condition or set(condition) - {"eq", "in", "gte", "lte"}:
                    raise ValueError("Use a nonempty predicate with eq, in, gte or lte")
                for operator, value in condition.items():
                    if operator == "in":
                        if not isinstance(value, list) or not 1 <= len(value) <= 100:
                            raise ValueError("in requires between 1 and 100 scalar values")
                    elif operator in {"gte", "lte"} and value is None:
                        raise ValueError("Range bounds must not be null")
                    elif isinstance(value, list):
                        raise ValueError(f"{operator} requires a scalar value")
        if self.sort is not None and self.operation != "list":
            raise ValueError("sort is only supported for list")
        if self.operation == "distinct":
            if not self.field:
                raise ValueError("distinct requires a field")
        elif self.field is not None:
            raise ValueError("field is only supported for distinct")
        if self.operation != "list" and (self.fields is not None or self.include):
            raise ValueError("fields and include are only supported for list")
        if self.fields is not None and not self.fields:
            raise ValueError("fields must contain at least one field")
        if len(set(self.fields or [])) != len(self.fields or []):
            raise ValueError("fields must not contain duplicates")
        if len(set(self.include)) != len(self.include):
            raise ValueError("include must not contain duplicates")
        return self

    def for_resource(self, resource: ResourceName) -> ReadQuery:
        """Validate known field names before sending this query to a named resource.

        Args:
            resource: Logical resource name, independent of collection storage names.

        Returns:
            This query after local shape and field-name checks.

        Raises:
            ValueError: A field or relation is unsupported for the selected resource.
        """
        if resource not in RESOURCE_MODELS:
            raise ValueError("Unknown resource")
        allowed = set(RESOURCE_MODELS[resource].model_fields)
        requested = set(self.filters) | set(self.fields or [])
        requested.update(field for field in (self.sort, self.field) if field is not None)
        if requested - allowed:
            raise ValueError("Unknown resource field: " + ", ".join(sorted(requested - allowed)))
        if self.include and (
            resource != "samples" or set(self.include) - {"assay", "configuration"}
        ):
            raise ValueError("Only samples support the assay and configuration relations")
        if self.related_filters and resource != "samples":
            raise ValueError("Only samples support related-resource predicates")
        related_models = {"assay": AssayMetadata, "configuration": ConfigurationMetadata}
        for relation, predicates in self.related_filters.items():
            unknown = set(predicates) - set(related_models[relation].model_fields)
            if unknown:
                raise ValueError("Unknown related-resource field: " + ", ".join(sorted(unknown)))
        return self


class ReadPage(BaseModel):
    """One resource-read response; continuation is explicit and server-controlled."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, allow_inf_nan=False)

    items: list[dict[str, Any] | Scalar]
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    per_page: int = Field(ge=1, le=200)
    has_next: bool
    count: int | None = Field(default=None, ge=0)
    exists: bool | None = None
