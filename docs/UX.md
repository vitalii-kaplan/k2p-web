## 3-step UX (with the tweaks it needs)

### 1) Select a folder with `workflow.knime` at root (or reject)

Good. Also reject if:

* there are **multiple** `workflow.knime` files (usually means they selected a workspace or parent folder)
* total file count is huge (warn at least; optionally hard-stop)

This doesn’t stop the browser from listing files, but it stops you from proceeding and uploading.

### 2) Build and show the exact file list to upload

Good. Make it a real “manifest”:

* relative path
* size
* present/missing (block upload if missing)
* total bytes + file count

Also add one blunt warning: `settings.xml` may contain secrets (DB credentials, API keys, file paths, server URLs). This is not theoretical; people do embed credentials in workflow configs.

Optional but useful: a “Download manifest.json” button so users can audit what will be sent.

### 3) Upload as a ZIP

Fine, and it’s cleaner than a multipart flood.

But do it with these constraints:

* Build the zip from the allowlisted files only:

  * `workflow.knime`
  * the referenced `*/settings.xml` paths you extracted
  * nothing else
* Enforce max total size client-side before uploading.
* Compressing a lot of XML in-browser is fine, but don’t try to zip tens of thousands of files.

## One more thing you’re missing: components and nested workflows

If the workflow uses **components/metanodes**, you may need to include their nested `workflow.knime` + `settings.xml` as well, otherwise conversion will be incomplete. For MVP you can pick one:

* MVP rule: “No components; reject if detected.”
* Better: implement recursive bundling (same logic: parse nested `workflow.knime`, collect referenced settings).

## Non-negotiable backend rules (even with perfect client code)

Do not trust the ZIP:

* reject path traversal (`..`, absolute paths)
* allowlist filenames (`workflow.knime`, `**/settings.xml` only)
* max files, max uncompressed bytes, max compression ratio (zip bomb defense)
* run the converter in a sandbox as you planned

## Net assessment

Your flow is the right direction. If you add the “multiple workflow.knime / huge folder” guardrails and decide how you handle components, it becomes a credible MVP design.

If you want, I’ll give you:

* the minimal client logic for: detect root workflow, parse `workflow.knime`, build manifest, create zip, upload
* plus the server-side validator that enforces the same allowlist and safety checks.
