/* global React, ReactDOM, JSZip, htm */

(() => {
  const { useEffect, useMemo, useState } = React;
  const html = htm.bind(React.createElement);
  const {
    fmtBytes,
    firstPathSegment,
    stripRootPrefix,
    normalizeRel,
    isUnsafeRel,
    extractSettingsPathsFromWorkflowXml,
  } = window.manifestUtils || {};
  const { renderApp } = window.appView || {};

  if (!window.manifestUtils) {
    throw new Error("manifest_utils.js must be loaded before app.js");
  }
  if (!window.appView) {
    throw new Error("app_view.js must be loaded before app.js");
  }

  // Client-side limits (keep aligned with backend limits)
  const MAX_TOTAL_BYTES = 100 * 1024 * 1024; // 100 MiB
  const WARN_FILE_COUNT = 2000;
  const HARD_STOP_FILE_COUNT = 10000;

  function downloadText(filename, text) {
    const blob = new Blob([text], { type: "application/json;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }

  function App() {
    const [stage, setStage] = useState("idle"); // idle | selected | manifest | uploading | submitted
    const [rawFiles, setRawFiles] = useState([]);
    const [rootPrefix, setRootPrefix] = useState("");
    const [errors, setErrors] = useState([]);
    const [warnings, setWarnings] = useState([]);

    const [requiredPaths, setRequiredPaths] = useState([]); // rel paths under workflow root
    const [manifest, setManifest] = useState(null);

    const [job, setJob] = useState(null);
    const [pollStatus, setPollStatus] = useState(null);

    const fileMap = useMemo(() => {
      const m = new Map();
      for (const f of rawFiles) {
        const rel = normalizeRel(stripRootPrefix(f.webkitRelativePath, rootPrefix));
        if (rel) m.set(rel, f);
      }
      return m;
    }, [rawFiles, rootPrefix]);

    const totals = useMemo(() => {
      let count = 0;
      let bytes = 0;
      for (const f of rawFiles) {
        count += 1;
        bytes += f.size || 0;
      }
      return { count, bytes };
    }, [rawFiles]);

    function resetAll() {
      setStage("idle");
      setRawFiles([]);
      setRootPrefix("");
      setErrors([]);
      setWarnings([]);
      setRequiredPaths([]);
      setManifest(null);
      setJob(null);
      setPollStatus(null);
    }

    async function onFolderSelected(ev) {
      resetAll();

      const files = Array.from(ev.target.files || []);
      if (!files.length) return;

      const rp = firstPathSegment(files[0].webkitRelativePath);
      setRootPrefix(rp);
      setRawFiles(files);

      const localFileMap = new Map();
      for (const f of files) {
        const rel = normalizeRel(stripRootPrefix(f.webkitRelativePath, rp));
        if (rel) localFileMap.set(rel, f);
      }

      const totalsLocal = files.reduce(
        (acc, f) => {
          acc.count += 1;
          acc.bytes += f.size || 0;
          return acc;
        },
        { count: 0, bytes: 0 }
      );

      const errs = [];
      const warns = [];

      if (files.length > HARD_STOP_FILE_COUNT) {
        errs.push(`Too many files selected (${files.length}). Select the workflow folder itself, not a workspace or parent directory.`);
      } else if (files.length > WARN_FILE_COUNT) {
        warns.push(`Large folder selected (${files.length} files). Zipping in-browser may be slow.`);
      }

      const relPaths = files
        .map((f) => normalizeRel(stripRootPrefix(f.webkitRelativePath, rp)))
        .filter(Boolean);

      const wfAll = relPaths.filter((p) => p.toLowerCase().endsWith("workflow.knime"));
      const wfRoot = relPaths.filter((p) => p === "workflow.knime");

      if (wfRoot.length !== 1) {
        if (wfRoot.length === 0) errs.push("Missing workflow.knime at the selected folder root.");
        else errs.push("Multiple workflow.knime files found at folder root.");
      }

      // Reject nested workflow.knime (components/metanodes) for MVP
      const nested = wfAll.filter((p) => p !== "workflow.knime");
      if (nested.length > 0) {
        errs.push(`Nested workflow.knime detected (${nested.length}). Components/metanodes are not supported in this MVP.`);
      }

      if (errs.length) {
        setErrors(errs);
        setWarnings(warns);
        setStage("selected");
        return;
      }

      // Parse workflow.knime to find referenced settings.xml paths
      const wfFile =
        localFileMap.get("workflow.knime") ||
        files.find((f) => normalizeRel(stripRootPrefix(f.webkitRelativePath, rp)) === "workflow.knime");
      if (!wfFile) {
        setErrors(["workflow.knime not found (unexpected)."]);
        setStage("selected");
        return;
      }

      const wfText = await wfFile.text();
      // basic XML sanity check
      const doc = new DOMParser().parseFromString(wfText, "application/xml");
      if (doc.querySelector("parsererror")) {
        setErrors(["workflow.knime is not valid XML (DOMParser reported parsererror)."]);
        setStage("selected");
        return;
      }

      const settingsPaths = extractSettingsPathsFromWorkflowXml(wfText);

      // Block unsafe referenced paths
      const unsafeRefs = settingsPaths.filter(isUnsafeRel);
      if (unsafeRefs.length) {
        errs.push(`workflow.knime contains unsafe settings.xml references (path traversal / absolute / URL). Example: ${unsafeRefs[0]}`);
        setErrors(errs);
        setWarnings(warns);
        setStage("selected");
        return;
      }

      const required = ["workflow.knime", ...settingsPaths];
      setRequiredPaths(required);

      // Build manifest
      const items = required.map((p) => {
        const f = localFileMap.get(p);
        return {
          path: p,
          present: Boolean(f),
          size: f ? f.size || 0 : 0,
        };
      });

      const missing = items.filter((x) => !x.present);
      if (missing.length) {
        errs.push(`Missing required settings.xml files (${missing.length}). This workflow cannot be exported without them.`);
      }

      const reqBytes = items.reduce((acc, it) => acc + (it.present ? it.size : 0), 0);
      if (reqBytes > MAX_TOTAL_BYTES) {
        errs.push(`Selected files exceed max total size (${fmtBytes(reqBytes)} > ${fmtBytes(MAX_TOTAL_BYTES)}).`);
      }

      warns.push(
        "We do not make workflows public and take reasonable steps to protect privacy, but we must store the workflow in our database and file system so knime2py can process it. Upload only what you are comfortable sharing."
      );
      warns.push(
        "knime2py expects KNIME nodes in green (executed) or yellow (ready) state. Red nodes will be converted to placeholder (dummy) code."
      );

      setErrors(errs);
      setWarnings(warns);
      setManifest({
        rootPrefix: rp,
        totalSelectedFiles: files.length,
        totalSelectedBytes: totalsLocal.bytes,
        requiredCount: items.length,
        requiredBytes: reqBytes,
        items,
      });

      setStage("manifest");
    }

    async function buildZipBlob() {
      if (!manifest) throw new Error("No manifest");
      const zip = new JSZip();

      for (const it of manifest.items) {
        if (!it.present) continue;
        const f = fileMap.get(it.path);
        if (!f) continue;

        // Zip path must match contract: workflow.knime at archive root, plus relative settings paths
        zip.file(it.path, f);
      }

      const blob = await zip.generateAsync({
        type: "blob",
        compression: "DEFLATE",
        compressionOptions: { level: 6 },
      });

      if (blob.size > MAX_TOTAL_BYTES) {
        throw new Error(`ZIP exceeds max size (${fmtBytes(blob.size)} > ${fmtBytes(MAX_TOTAL_BYTES)}).`);
      }
      return blob;
    }

    async function uploadZip() {
      if (!manifest) return;
      if (errors.length) return;

      setStage("uploading");

      try {
        const blob = await buildZipBlob();

        // Use selected folder name as the uploaded zip filename stem (so outputs become <stem>__gXX.*)
        // If your folder is "discounts", the filename will be "discounts.zip".
        const safeStem = (manifest.rootPrefix || "workflow").replace(/[^\w.-]+/g, "_");
        const filename = `${safeStem}.zip`;

        const fd = new FormData();
        fd.append("bundle", blob, filename);

        const resp = await fetch("/api/jobs", { method: "POST", body: fd });
        const data = await resp.json().catch(() => null);

        if (!resp.ok) {
          const msg = data?.error?.message || `Upload failed (${resp.status})`;
          throw new Error(msg);
        }

        setJob(data);
        setStage("submitted");
      } catch (e) {
        setErrors([String(e?.message || e)]);
        setStage("manifest");
      }
    }

    // Poll job status when submitted
    useEffect(() => {
      if (!job?.id) return;

      let stopped = false;
      const id = job.id;

      async function tick() {
        try {
          const resp = await fetch(`/api/jobs/${id}`);
          const data = await resp.json();
          if (!stopped) setPollStatus(data);

          const st = data?.status;
          if (st === "SUCCEEDED" || st === "FAILED") return;
        } catch (_) {
          // ignore transient errors
        }
        if (!stopped) setTimeout(tick, 800);
      }

      tick();
      return () => {
        stopped = true;
      };
    }, [job?.id]);

    return renderApp(
      html,
      {
        totals,
        warnings,
        errors,
        manifest,
        stage,
        job,
        pollStatus,
        fmtBytes,
      },
      {
        onFolderSelected,
        resetAll,
        uploadZip,
        downloadText,
      }
    );
  }

  const root = ReactDOM.createRoot(document.getElementById("root"));
  root.render(html`<${App} />`);
})();
