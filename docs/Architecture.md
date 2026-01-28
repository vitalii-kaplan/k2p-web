## Architecture

### Components

1. **Static UI (HTML + JS)**

   * Served by Nginx or directly by Django.
   * Does: folder select → manifest → create `bundle.zip` → upload → poll status → download result.

2. **API service (Django + DRF)**

   * Accepts `bundle.zip`, validates it, stores it, creates a DB “job”, triggers a Kubernetes Job, and exposes job status + download.
   * Owns the security policy: validation, limits, rate limiting, retention.

3. **Postgres**

   * Stores metadata only: job state, timings, sizes, stderr/stdout tail, keys to objects in storage, IP-hash for abuse controls.

4. **Object storage (S3/MinIO)**

   * Stores blobs:

     * `jobs/<id>/in/bundle.zip`
     * `jobs/<id>/out/result.zip`
     * (optionally) `jobs/<id>/out/logs.txt`
   * API streams `result.zip` back to the user.

5. **Kubernetes Job runner**

   * A per-job pod (short-lived) that:

     * downloads the input bundle from object storage (or API),
     * runs `knime2py`,
     * uploads `result.zip`,
     * reports completion back to API.

### Network stance (Option A)

* The job pod must talk to **something** (S3/MinIO and/or the API). Mitigate it:

  * Kubernetes **NetworkPolicy**: deny all egress except API + object storage endpoints. No public internet egress.
  * Use **short-lived credentials** or **pre-signed URLs** scoped to a single object key.
  * Never give the job pod DB credentials.

---

## Request/response flow

### Public API

* `POST /api/jobs`
  Uploads `bundle.zip`. API validates and stores it. Returns `{job_id}`.
* `GET /api/jobs/{job_id}`
  Returns `{status, error_code, created_at, finished_at, duration_ms, ...}`.
* `GET /api/jobs/{job_id}/result.zip`
  Streams output zip if ready.

### Internal job mechanics (recommended)

* API creates job record + stores `bundle.zip` to S3/MinIO.
* API creates a Kubernetes Job with env:

  * `JOB_ID`
  * `INPUT_URL` (pre-signed GET) or scoped S3 creds
  * `OUTPUT_URL` (pre-signed PUT) or scoped S3 creds
  * `CALLBACK_URL` + one-time token (optional; or you can just have API poll object storage)

Job pod:

1. downloads `bundle.zip` into `/work/in/bundle.zip`
2. unzips into `/work/in/unpacked` (safe unzip)
3. runs `k2p /work/in/unpacked --out /work/out ...`
4. zips `/work/out` into `/work/out/result.zip`
5. uploads to storage
6. reports status to API (or API detects result and marks complete)

---

## Server-side ZIP validation policy (before any k2p run)

Validation should be strict and fast:

1. **Early limits**

   * max compressed size (upload limit)
   * max number of entries
   * max total uncompressed bytes
   * max per-file uncompressed bytes
   * compression ratio limit (zip bomb defense)

2. **Path safety**

   * deny absolute paths / drive letters
   * deny `..` traversal after normalization
   * deny backslash tricks (`\` → `/` then validate)
   * deny duplicates
   * deny symlinks (check ZIP unix mode bits if present)

3. **Allowlist**

   * require `workflow.knime` at ZIP root
   * allow only `**/settings.xml` and `workflow.knime` (everything else rejected)

4. **Consistency**

   * parse `workflow.knime`
   * extract all referenced `node_settings_file` paths
   * verify each exists in the ZIP
   * if components are in scope: recursively apply the same rule for nested workflows (or explicitly reject components for MVP)

Even if you “trust your client”, do not relax this. People will bypass the UI.
