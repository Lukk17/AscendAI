## Context

`fetch_with_curl_cffi` turns automatic redirect following off so that every hop passes the SSRF guard before it is
fetched. The loop reads `response.headers["location"]`, pins the session to it through `pin_safe_host`, and issues
the next request. That is correct for an absolute `Location` and wrong for every other kind, because
`pin_safe_host` starts with `urlparse` and a relative reference has no host for it to validate. The `None` it
returns is indistinguishable, at the call site, from the `None` that means "this host resolves to
169.254.169.254", so a perfectly ordinary redirect is reported and handled as an attack.

The same lines are described by a published requirement that was written when a second mechanism was believed to
exist. `validate_redirect_chain` inspected `Response.history` hop by hop, had no caller, and could not have failed
even if it had one: with `allow_redirects=False` there is no history, and curl_cffi 0.15.0 leaves the list empty
in the automatic case too. It was removed. The requirement text outlived it.

## Goals / Non-Goals

Goals:

- A relative `Location` of any form is followed, and the read is served by the tier that received it.
- The resolved URL faces the identical validation an absolute `Location` faces, so the guard's coverage is
  unchanged.
- The published requirement names the mechanism the code implements, per-hop validation before the hop is fetched.

Non-Goals:

- Changing the hop bound, the refusal behaviour, or the address rules.
- Extending anything to the out-of-process or browser tiers, which never observe a `Location` here.
- Reopening the pinning decision recorded in ADR-012, which this change leaves intact.

## Decisions

### D1, resolve with `urljoin` against the hop that returned the header

`urllib.parse.urljoin(current_url, location)` implements the RFC 3986 section 5 reference resolution that RFC 9110
section 10.2.2 requires for `Location`. It covers the three relative forms in one call: root-relative (`/article`),
path-relative (`../index.html`) and protocol-relative (`//other.example/page`, which inherits the scheme of the
base and only the scheme). An already-absolute `Location` is returned unchanged, so the existing behaviour is a
special case of the new one rather than a branch beside it.

The base is the URL of the hop that returned the header, not the URL the read started from. A chain that goes
`/page` then `/docs/intro` then `../index.html` lands on `/index.html`, and resolving the last hop against the
original URL would land somewhere else. Tracking the current hop is one assignment at the bottom of the loop.

Rejected: parsing the `Location` by hand to detect a leading `/` or `//`. It reimplements a standard-library
function badly, and the path-relative and dot-segment cases are exactly where a hand-rolled version goes wrong.

Rejected: letting curl_cffi follow redirects and validating afterwards. That is the mechanism the removed
`validate_redirect_chain` assumed, it cannot be observed on this client, and it would mean the internal address is
connected to before anything checks it, which is the whole failure the guard exists to prevent.

### D2, validation and pinning stay exactly where they are

The resolved URL is handed to the same `_pin_session_to` call the raw value used to reach, before any request is
issued for it. Nothing about the guard is relaxed for a relative hop, and nothing is skipped on the grounds that
the host has already been validated once: a relative `Location` usually keeps the same host, and that host is
resolved and validated again for the hop, so a name that rebinds between the first hop and the second is refused
exactly as it would be for an absolute `Location` naming the same host. The refusal path still returns an empty
string and still issues no request for the refused target.

The log line now carries the resolved URL and the hop that produced it. `/doc/` on its own never said which host
the fetch was headed for, which is why the live symptom read as a security event.

### D3, the requirement describes per-hop validation, not a history

The corrected requirement states that re-validation happens before each hop is fetched, and says why there is no
history to inspect: the tier follows the chain itself, one request at a time. Relative resolution belongs in the
same requirement rather than a new one, because it is a step in validating a hop, not a separate promise. Splitting
it out would leave two requirements that must be read together to know what happens to one `Location` header.

The scenarios gain the three cases that carry the behaviour: a relative hop that resolves to a safe public URL and
is followed, a protocol-relative hop that changes host, and a relative hop whose resolved host is internal and is
still refused. The existing scenarios, the internal absolute redirect, the hop bound, and out-of-process dispatch,
are unchanged.

## Risks / Trade-offs

- **A relative `Location` that resolves onto a second host now gets followed where it used to be refused.** That is
  the point of the change, and the refusal it replaces was never a security decision. The resolved host is
  validated and pinned before the hop is fetched, so the guard's coverage is the same as for an absolute hop to
  that host.
- **`urljoin` accepts schemes the guard does not.** A `Location` of `mailto:` or `javascript:` resolves to itself
  rather than to an http(s) URL. `pin_safe_host` refuses any scheme outside http and https, so those still end the
  read with a refusal, which is the behaviour they have today.
- **The refusal log line changes shape.** Nothing asserts on it: the e2e suite asserts observable behaviour only,
  and no test matches the message text.

## Open Questions

None. The scope is one function and one published clause.
