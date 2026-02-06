
## Plan of work (implementation order)

### Phase 0 — Define knime2py contract for web usage (do this first)

You need a stable CLI + container contract so the web stack doesn’t become guesswork.

Deliverables:

* A pinned Docker image tag/digest for `knime2py` with a stable `k2p` CLI.
* Deterministic output locations and filenames.
* Stable exit codes and error messages (machine-usable).

### Phase 1 — Django skeleton + DB models

* `Job` model: status, timestamps, sizes, version, stderr/stdout tail, storage keys.
* Basic admin screens: list jobs, filter by status/date, inspect logs/tails.
* Minimal API endpoints: create job, read job, download result.

### Phase 2 — Upload handler + ZIP validator + object storage

* Implement upload size caps at reverse proxy + Django.
* Validate zip strictly (rules above).
* Store `bundle.zip` in S3/MinIO; write DB record.
* Return `job_id`.

### Phase 3 — Docker runner integration

* A worker loop that runs the `knime2py` container via `docker run`.
* Hardening flags:

  * non-root, read-only rootfs, no privilege escalation
  * CPU/mem limits
  * hard timeout
* No network for the runner container.

### Phase 5 — End-to-end happy path + UI integration

* JS uploads zip, polls status, downloads result zip.
* Add clear error rendering (validation errors vs conversion failures).

### Phase 6 — Hardening + ops

* rate limiting (IP-hash token bucket)
* retention cleanup job (delete old S3 objects + mark expired)
* structured logging + request/job IDs
* metrics (job durations, failure codes, queue depth)

### Phase 7 — CI/CD

* build/push API image
* build/push knime2py image (already part of k2p repo ideally)
* smoke test: known tiny workflow bundle → assert output exists
* image scan + SBOM publishing (optional but recommended)

---

## Do you need to prepare knime2py before using it in the web service?

Yes. If you don’t tighten the CLI/container contract now, the web service will be unstable.

Minimum knime2py readiness checklist:

* Accepts an **unpacked** minimal workflow folder containing `workflow.knime` + per-node `settings.xml` (no data).
* Works in a container with:

  * read-only root filesystem
  * non-root user
  * no HOME assumptions
* Writes all outputs under `--out` and never outside.
* Emits stable exit codes and clear stderr for:

  * missing workflow.knime
  * missing node settings
  * unsupported node types
  * parse errors
* Produces a predictable output set (py/ipynb + graphs) with bounded verbosity.
* Has `k2p --version` suitable for logging provenance.

Optional (nice):

* ability to consume a zip directly (`k2p --in-zip bundle.zip`) to simplify runner logic. Not required.

---

## Message to send in the knime2py development chat (copy/paste)

Please implement “web-service readiness” for knime2py:

1. Define a stable CLI contract for k2p-web:

* Input: minimal workflow folder containing `workflow.knime` at root and per-node `settings.xml` files (no data folders).
* Output: deterministic filenames and locations under `--out` (at least workbook `.py`; optional `.ipynb`; graph `.json`/`.dot`).
* `k2p --version` must be reliable for provenance logging.

2. Add strict, machine-usable failure behavior:

* Stable exit codes for: missing workflow.knime, missing referenced settings.xml, invalid XML, unsupported workflow constructs, general failure.
* Error messages in stderr should be concise and structured enough to map to an API error code.

3. Container/runtime constraints:

* Must run as non-root, with read-only root filesystem, no network assumptions, no writes outside `--out`.
* Avoid using temp paths that require special permissions; honor `$TMPDIR` if set.

4. (Optional but helpful) Support `--in-zip` (bundle.zip) to avoid unzip logic in the runner container; otherwise document exact expected input layout.

5. Provide a small “golden” sample bundle for CI smoke testing:

* minimal workflow with a few nodes + their settings.xml
* expected outputs committed as assertions (existence + basic sanity).

This is needed to integrate knime2py into the k2p-web service that runs Docker jobs and returns result.zip to users.
