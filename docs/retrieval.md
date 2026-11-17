# Retrieve resource metadata

`client.read` provides bounded reads for external integrations. It supports `asp`,
`aspc`, `samples`, `isgl`, `assay_groups` and `diagnoses`. Existing `client.samples`
and other workflow resources keep their current behavior.

These methods require the server's `POST /api/v1/resources/read/{resource}/query`
endpoint. The server checks permissions, assay/environment scope and allowed fields
on every request. An older server without this endpoint returns `NotFoundError`;
the client does not fall back to a different query.

## IDs, records and selected fields

Use an authenticated client as described in [usage](usage.md):

```python
# One page of distinct IDs for active assays.
page = client.read.asp.ids(is_active=True)
print(page.items)

# All matching IDs, fetched lazily through bounded pages.
for sample_id in client.read.samples.iter_ids(
    asp_id="DEMO_DNA", environment="production", per_page=100
):
    print(sample_id)

page = client.read.aspc.list(
    filters={"asp_id": {"in": ["DEMO_DNA", "DEMO_RNA"]}},
    environment="production",
    is_active=True,
    fields=["aspc_id", "asp_id", "version"],
    sort="aspc_id",
    per_page=50,
)
configuration = client.read.aspc.get("DEMO_DNA::base::production", version=1)
```

`list()` returns projected dictionaries. A projection selects only permitted metadata
fields; it cannot retrieve arbitrary stored documents. `get()` returns a dictionary
or `None` when no authorized record matches. For versioned resources it raises
`ValueError` if several versions match; supply `version` or `is_active` to select one.
`ids()` returns distinct logical IDs even when several stored revisions match.

## Combined conditions and aggregates

Equality keywords and `filters` combine with AND. The same field cannot be supplied
in both. Each operator object also combines its conditions with AND:

```python
count = client.read.samples.count(asp_id="DEMO_DNA", reported=False)
exists = client.read.aspc.exists(asp_id="DEMO_DNA", is_active=True)
page = client.read.samples.list(
    filters={"version": {"gte": 2, "lte": 4}},
    environment="production",
    fields=["name", "version"],
)
environments = client.read.samples.distinct("environment", asp_id="DEMO_DNA")
```

Supported predicates are `eq`, `in`, `gte` and `lte`. Ranges apply to integer and
timestamp fields. Use ISO timestamps for timestamp comparisons. Array predicates
compare elements; `distinct()` flattens arrays into distinct scalar values.
Equality with `None` matches explicitly null fields, not absent fields. Missing
fields are omitted from distinct values; projected missing values are null.

The server validates each field's type and permits only declared metadata fields.
No database operators, collection names or arbitrary joins are accepted. At most
20 filter fields and 100 membership values per predicate are supported.

## Related assay and configuration

Samples may filter their active assay and the exact configuration revision stored
on the sample. These conditions apply before counting, ID selection and pagination:

```python
page = client.read.samples.list(
    asp_id="DEMO_DNA",
    related_filters={
        "assay": {"is_active": True},
        "configuration": {"environment": "production", "is_active": True},
    },
    fields=["name", "asp_id", "aspc_id"],
    include=["assay", "configuration"],
)
```

`related_filters` works with every sample read operation. `include` works only with
sample `list()` and `get()`; related metadata appears in each row's `related` object.
Both filtering and inclusion require permission for the related resource. A missing
relation excludes the sample when that relation is filtered; otherwise an included
missing relation is null. The client never treats a related permission failure as
an empty result.

## Pagination and asynchronous reads

`ReadPage` exposes `items`, `total`, `page`, `per_page` and `has_next`. `count()` and
`exists()` return an integer and boolean directly, preserving zero and false.
Default page size is 50, with a maximum of 200 and page numbers from 1 to 10,000.
List results may sort by a permitted scalar field; ID and distinct pages sort by
the returned value. `descending=True` reverses that order.

Use `ReadQuery` for explicit query objects and general iteration:

```python
from coyote_pyclient import ReadQuery

query = ReadQuery(operation="ids", filters={"is_active": True}, per_page=100)
for page in client.read.asp.pages(query):
    print(page.items)

# With an authenticated AsyncCoyoteClient:
page = await async_client.read.asp.ids(is_active=True)
async for sample_id in async_client.read.samples.iter_ids(asp_id="DEMO_DNA"):
    print(sample_id)
```

Both clients expose `query`, `list`, `ids`, `get`, `count`, `exists`, `distinct`,
`pages`, `iter` and `iter_ids` on each reader. Iteration stops if authentication
changes. Early stopping avoids later requests; offset pages are not an immutable
snapshot when records change concurrently. Unsupported options fail locally or
return the server's typed validation error. Successful malformed responses raise
`ResponseValidationError`.
