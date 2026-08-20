# RunAcross roadmap

The roadmap records likely directions, not release dates or commitments.
Features should be added only when they preserve the small execution primitive.

## 0.1

- Explicit account IDs and `Account` objects.
- STS AssumeRole and one authenticated Boto3 Session per account.
- Concurrent callback execution with a configurable worker limit.
- Typed, ordered, structured results and per-account error isolation.
- Basic DEBUG logging and duration measurements.
- Optional AWS Organizations discovery with an organization ID safety guard.
- Tests, typing, documentation, packaging, and CI.

## 0.2

- Explicit account-by-Region execution.
- Enabled-Region discovery.
- Small account and Region filters.
- A structured result identity for each account and Region pair.

## 0.3 and later

Candidates requiring evidence from real usage:

- Execution lifecycle hooks.
- Cooperative deadlines and pending-task cancellation semantics.
- Optional rate limiting.
- Richer Organizations selection by OU or tags.
- A configurable role ARN resolver.
- Additional STS session parameters.

RunAcross does not plan to become a CLI, scanner, policy engine, distributed
workflow system, credential store, or infrastructure deployment framework.

