Ok. Let's now develop "Job per request" we will change it later. But we will need to reject requests if the queue is full. With a message to the user that "Your request can't be processed right now, wait for 5 minutes" or something like it. Can we implement it? Where?

Yes. Implement it in the **API layer, before you enqueue the job**. That’s the only place where you can reliably give a clean, user-friendly “try later” response. The worker can only fail late.

## Where exactly

In your Django API endpoint that accepts uploads, e.g.:

* `api/apps/jobs/views.py` (POST `/api/jobs` or `/convert`)
* backed by the worker loop (`api/apps/jobs/management/commands/k2p_worker.py`)
* and settings in `api/k2pweb/settings/base.py` (limits)

## What to implement

### 1) Capacity gate (global queue size)

Define a max number of “in-flight” jobs the system is willing to handle:

* `MAX_INFLIGHT_JOBS` (e.g., 10–50 for MVP)
* optionally `MAX_PENDING_JOBS` if you distinguish pending vs running

On request:

1. Count current in-flight jobs
2. If at/over limit: **reject immediately** with:

   * HTTP `503 Service Unavailable` (or `429 Too Many Requests`)
   * JSON error code like `server_busy`
   * header `Retry-After: 300`
   * message: “Server is busy. Try again in ~5 minutes.”

### 2) How to count “in-flight”

You have two workable options:

**Option A (recommended): DB as the source of truth**

* Your `jobs` table already has `status`.
* Treat `QUEUED` + `RUNNING` as “in-flight”.
* Count: `SELECT count(*) FROM jobs WHERE status IN ('QUEUED','RUNNING')`
* Only if under limit do you insert a new row and let the worker pick it up.

This is fast and doesn’t depend on any external scheduler.

**Option B: Query worker / runner state**

* Not recommended — DB status is the source of truth.

### 3) Race condition handling

If two requests arrive at the same time, both might see “capacity available” and both submit. Fix by making the “check + accept” atomic, e.g.:

* use a short DB transaction + Postgres advisory lock, or
* accept that you may go slightly over the limit (often OK for MVP), and rely on runner resource limits as the hard stop.

For MVP, a transaction + advisory lock is the cleanest.

### 4) What the UI shows

When API returns “busy”:

* show the message
* and respect `Retry-After` (disable button / auto-retry after ~300s if you want)

## Why this is necessary

The worker can reject work late (resource limits, runner failures), but that
won’t give clean user-facing errors. The API must do admission control up front.

If you want, I can give you the exact constants to add (settings), the exact statuses for the `jobs` model, and the precise response payload + HTTP status you should standardize on.
