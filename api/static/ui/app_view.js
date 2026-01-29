/* global window */

const appView = {
  renderApp(html, state, handlers) {
    const {
      totals,
      warnings,
      errors,
      manifest,
      stage,
      job,
      pollStatus,
      fmtBytes,
    } = state;
    const { onFolderSelected, resetAll, uploadZip, downloadText } = handlers;

    const canUpload = stage === "manifest" && manifest && errors.length === 0;

    return html`
      <div class="work-area">
        <div class="app-intro">
          <p>Convert a KNIME workflow to Python/Jupyter using knime2py</p>
        </div>

        <div class="card">
          <h3>1) Select workflow folder</h3>
          <div class="row">
            <label class="btn" for="workflow-folder">Choose folder</label>
            <input
              id="workflow-folder"
              class="file-input"
              type="file"
              webkitdirectory="true"
              directory="true"
              multiple="true"
              onChange=${onFolderSelected}
            />
            <!--button class="btn" onClick=${resetAll}>Reset</button-->
          </div>
          <div class="app-meta">
            Selected: <b>${totals.count}</b> files, <b>${fmtBytes(totals.bytes)}</b>
            ${manifest?.rootPrefix ? html`<span class="app-meta-sep">·</span> Folder: ${manifest.rootPrefix}` : null}
          </div>
          <div class="app-meta">
            This step is for selection and review only. Actual upload happens in step 3.
          </div>
        </div>

        ${warnings.length
          ? html`<div class="card warn">
              <b>Warnings</b>
              <ul>${warnings.map((w) => html`<li>${w}</li>`)}</ul>
            </div>`
          : null}

        ${errors.length
          ? html`<div class="card err">
              <b>Errors</b>
              <ul>${errors.map((e) => html`<li>${e}</li>`)}</ul>
            </div>`
          : null}

        <div class="card">
          <h3>2) Manifest (files that will be uploaded)</h3>
          ${manifest
            ? html`
                <div>
                  Required: <b>${manifest.requiredCount}</b> files, <b>${fmtBytes(manifest.requiredBytes)}</b>
                </div>
                <div class="app-meta">
                  <button
                    class="btn"
                    onClick=${() =>
                      downloadText(
                        "manifest.json",
                        JSON.stringify(
                          {
                            ...manifest,
                            items: manifest.items,
                          },
                          null,
                          2
                        )
                      )}
                  >
                    Download manifest.json
                  </button>
                </div>

                <div class="manifest-table-wrap">
                  <table class="manifest-table">
                    <thead>
                      <tr>
                        <th>path</th>
                        <th>present</th>
                        <th>size</th>
                      </tr>
                    </thead>
                    <tbody>
                      ${manifest.items.map(
                        (it) => html`
                          <tr>
                            <td><code>${it.path}</code></td>
                            <td>${it.present ? "yes" : "missing"}</td>
                            <td>${it.present ? fmtBytes(it.size) : ""}</td>
                          </tr>
                        `
                      )}
                    </tbody>
                  </table>
                </div>
              `
            : html`<div>No manifest yet.</div>`}
        </div>

        <div class="card">
          <h3>3) Upload ZIP</h3>
          <button class="btn" disabled=${!canUpload} onClick=${uploadZip}>
            ${stage === "uploading" ? "Uploading..." : "Upload"}
          </button>
          ${job?.id
            ? html`<div class="app-meta">
                Job: <code>${job.id}</code>
              </div>`
            : null}
        </div>

        <div class="card">
          <h3>Status</h3>
          ${pollStatus
            ? html`
                <div>Status: <b>${pollStatus.status}</b></div>
                ${pollStatus.status === "SUCCEEDED"
                  ? html`
                      <div class="app-meta">
                        <a class="btn" href=${`/api/jobs/${pollStatus.id}/result.zip`}>Download result.zip</a>
                      </div>
                    `
                  : null}
                ${pollStatus.status === "FAILED"
                  ? html`
                      <div class="app-meta">
                        <b>Error:</b> ${pollStatus.error_code || ""} ${pollStatus.error_message || ""}
                      </div>
                    `
                  : null}
              `
            : html`<div>No job submitted yet.</div>`}
        </div>
      </div>
    `;
  },
};

if (typeof window !== "undefined") {
  window.appView = appView;
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = appView;
}
