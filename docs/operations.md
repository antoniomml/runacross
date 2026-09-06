# Operating RunAcross

RunAcross is a synchronous helper for bounded AWS automation. Start with
explicit accounts, a small selection, and the default `max_workers=10`.

## Choosing concurrency

Increase workers only after measuring the actual callback against downstream
service quotas. The pool holds at most `max_workers` submitted, unconsumed
futures. Input validation, account-by-Region targets, cached role credentials,
and returned results still consume memory proportional to the run size.
This is not a streaming API. Avoid returning entire service responses when
only a few fields are needed.

Each callback owns its Session and the clients it creates. Do not share those
Sessions or resources between callbacks, and do not use the global
`boto3.client()` shortcut from worker threads.

## Timeouts and retries

The library does not impose a hard callback deadline. Configure network
timeouts and retries on the clients performing the requests:

```python
from botocore.config import Config

config = Config(
    connect_timeout=5,
    read_timeout=30,
    retries={"mode": "standard", "total_max_attempts": 3},
)


def worker(session, account):
    sts = session.client("sts", config=config)
    return sts.get_caller_identity()["Arn"]
```

Pass `botocore_config=config` separately to the executor to configure clients
RunAcross creates for authentication and discovery. Socket timeouts are per
request operation, not an overall deadline for a paginated callback. RunAcross
never retries a callback automatically because its side effects may not be
idempotent.

An exception in `on_result`, or a `KeyboardInterrupt`, stops new submissions
and cancels queued work. Running callbacks finish before the exception is
returned. Account and Region discovery completes before the callback execution
phase begins, so progress may initially be silent.

## Authentication and troubleshooting

| Symptom | Check |
| --- | --- |
| `phase == "auth"` with `AccessDenied` | Source permissions, target trust, external ID, and the requested role path. |
| Expired Identity Center credentials | Log in with the AWS CLI before running; RunAcross does not run a login flow. |
| Callback runs in an unexpected account | Use `Profile(..., verify_account_id=True)` to verify the authenticated account before the callback. |
| Credentials expire during a long run | Keep the run within the assumed role lifetime; copied Role credentials do not refresh automatically. |
| Region discovery fails | Check `account:ListRegions`, profile Region configuration, and `botocore_config`. |
| No accounts returned | Check SSO scope, organization/OU, exclusions, ACTIVE state, and `limit`. `limit=0` performs no discovery or organization guard. |
| Service throttling | Reduce workers, paginate, and configure retries on the callback's clients. |

Profile resolvers run once per authentication attempt, inside worker threads.
Keep resolvers thread-safe; result metadata reports the name actually selected
for that attempt. Discovery is a separate attempt from each regional callback.

## Results and logging

Use `summary()` for counts and inspect `failed`, `phase`, and `error_code` for
diagnostics. RunAcross DEBUG logs omit exception text and traceback frames.
Original error messages remain available through `result.error` and export
helpers. Application values, errors, account names, IDs, and profile names
should only go to destinations appropriate for that data.

`to_dicts()` neither sanitizes user data nor makes arbitrary return values
JSON-serializable. Return simple dictionaries, lists, numbers, and strings
when planning JSON export. Use a fresh `show_progress()` callback for each run.

## Measuring scheduler overhead

From an editable development installation:

```bash
python benchmarks/pool.py --targets 20000 --workers 10 --repeats 3
```

This offline benchmark compares the old eager scheduling algorithm with the
current bounded pool. It reports median elapsed time and peak Python memory
measured with `tracemalloc`, checks output order, and makes no AWS calls.
It measures scheduler overhead for trivial callbacks, not AWS throughput,
process RSS, or application payload memory. See the
[audit measurements](audit-2026-09.md) for a recorded sample.

For a more representative offline workload:

```bash
python benchmarks/inventory.py --latency-ms 50
```

This runs real SDK clients and EC2 paginators against Stubber responses, with
configurable latency, account/Region counts, and failures. It checks order,
partial failures, exported item counts and STS reuse. The
[readiness record](readiness-1.0.md) includes measurements and their limits.
Session and client setup can dominate fast callbacks and consume substantial
memory even when future submission is bounded. Tune concurrency using actual
workload measurements rather than assuming ten workers is always faster.
