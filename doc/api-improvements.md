# API Behavior Improvements (Legacy → FastAPI)

This document lists cases where the FastAPI implementation intentionally
deviates from the legacy Werkzeug API to follow HTTP standards and REST
best practices. These are **not bugs in the migration** — they are fixes
to incorrect behavior in the legacy API.

Downstream forks and API clients should review this list when migrating
from `<api-service>legacy</api-service>` to `<api-service>new</api-service>`.

---

## Known Bad API Design (preserved for AS-IS compatibility)

The following behaviors are incorrect but are preserved in the FastAPI
implementation to maintain backward compatibility. They are documented
here for future correction once the legacy API is removed.

### DELETE on nonexistent resource returns 500 (should be 404)

| Endpoint | Legacy | FastAPI (AS-IS) | Correct |
|----------|--------|-----------------|---------|
| `DELETE /v2/account/articles/<fake-uuid>` | 500 | 500 | 404 |

**Legacy behavior:** Returns HTTP 500 (Internal Server Error) when
attempting to delete a dataset that does not exist.

**Correct behavior:** Should return HTTP 404 (Not Found). A missing
resource is not a server error.

**Current status:** FastAPI preserves the 500 to match legacy.
Flagged for correction after legacy removal (2027-01-01).

**Test reference:** `e2e/tests/test_dataset_api.py::TestDatasetApiErrors::test_delete_nonexistent_dataset`

### GET on nonexistent private article returns 200 with empty array (should be 404)

| Endpoint | Legacy | FastAPI (AS-IS) | Correct |
|----------|--------|-----------------|---------|
| `GET /v2/account/articles/<nonexistent-uuid>` | 200 `[]` | 200 `[]` | 404 |

**Legacy behavior:** Returns HTTP 200 with an empty JSON array `[]`
when a private article is not found for the authenticated account.

**Correct behavior:** Should return HTTP 404 (Not Found).

**Current status:** FastAPI preserves the 200 + `[]` to match legacy.
Flagged for correction after legacy removal (2027-01-01).

**Test reference:** `e2e/tests/test_dataset_api.py::TestPrivateDatasetCrud::test_delete_dataset` (verify step)

---

## Input Validation Improvements

### Invalid `order` parameter rejected (was SPARQL injection vector)

| Endpoint | Legacy | FastAPI |
|----------|--------|---------|
| `GET /v2/articles?order=<arbitrary>` | Accepts any string up to 32 chars (SPARQL injection) | Only accepts: `published_date`, `modified_date`, `created_date`, `title`, `defined_type`, `group_id`, `size` |
| `POST /v2/articles/search` | Same | Same |
| `POST /v3/datasets/search` | Same | Same |

**Legacy behavior:** The `order` parameter accepts any string and
injects it directly into `ORDER BY ?{order}` in the SPARQL query.
This allows SPARQL injection (see VULN-10 in `security-audit-2026-04-03.md`).

**Correct behavior:** The `order` parameter is a Pydantic `Literal`
enum. Invalid values return HTTP 422 with a clear error message listing
the allowed values.

**Impact:** Clients that pass custom `order` values not in the allowed
list will receive 422 errors. This is intentional — the legacy behavior
was a security vulnerability.

---

### Malformed search request returns 422 (was 500 with debugger)

| Endpoint | Legacy (debug=1) | Legacy (debug=0) | FastAPI |
|----------|-----------------|-------------------|---------|
| `POST /v3/datasets/search` with `{"search_for": "test"}` | 500 + Werkzeug debugger page (source code, secrets) | 500 empty response | 200 with empty results |

**Legacy behavior:** A search request with only `search_for` and no
other parameters crashes with `TypeError: 'NoneType' object is not
iterable`. With debug mode enabled (the default in example config),
this exposes the interactive Werkzeug debugger.

**Correct behavior:** Missing optional parameters use defaults.
The request succeeds and returns results (or empty array).

**Impact:** This is purely a fix. No client should have depended
on the crash behavior.

---

## Cookie Security Improvements

### Session cookies set with HttpOnly and SameSite (SSI endpoints)

| Endpoint | Legacy | FastAPI |
|----------|--------|---------|
| `GET /v3/redirect-from-ssi/<uuid>/<token>` | `Set-Cookie: djehuty_session=<token>; Secure` | `Set-Cookie: djehuty_session=<token>; Secure; HttpOnly; SameSite=Lax` |

**Legacy behavior:** Session cookies are readable by JavaScript
(`document.cookie`) and sent on cross-origin requests.

**Correct behavior:** `HttpOnly` prevents JavaScript access (mitigates
XSS-based cookie theft). `SameSite=Lax` prevents CSRF attacks.

**Impact:** No impact on normal API clients. JavaScript code that
reads `djehuty_session` from `document.cookie` will no longer work
(this was a security vulnerability, not a feature).

---

## Authentication Improvements

### SSI pre-shared key compared with constant-time function

| Endpoint | Legacy | FastAPI |
|----------|--------|---------|
| `PUT /v3/receive-from-ssi` | `if psk != config.ssi_psk` (timing attack) | `hmac.compare_digest(psk, config.ssi_psk)` |

**Legacy behavior:** Python's `!=` operator short-circuits on the
first differing byte, leaking key information via response timing.

**Correct behavior:** `hmac.compare_digest` takes constant time
regardless of where the strings differ.

**Impact:** No impact on API clients. This is a server-side security
fix.
