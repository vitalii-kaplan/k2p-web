/* global window */

function fmtBytes(n) {
  if (n == null) return "";
  const units = ["B", "KiB", "MiB", "GiB"];
  let x = n;
  let i = 0;
  while (x >= 1024 && i < units.length - 1) {
    x /= 1024;
    i += 1;
  }
  return `${x.toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}

function firstPathSegment(p) {
  const s = (p || "").replaceAll("\\", "/");
  const parts = s.split("/").filter(Boolean);
  return parts.length ? parts[0] : "";
}

function stripRootPrefix(webkitRelativePath, rootPrefix) {
  const s = (webkitRelativePath || "").replaceAll("\\", "/");
  const parts = s.split("/").filter(Boolean);
  if (!parts.length) return "";
  if (rootPrefix && parts[0] === rootPrefix) return parts.slice(1).join("/");
  // fallback: if something weird, return as-is
  return parts.join("/");
}

function normalizeRel(p) {
  return (p || "").replaceAll("\\", "/").replace(/^\.\/+/, "");
}

function isUnsafeRel(p) {
  // block path traversal and absolute paths
  const s = normalizeRel(p);
  if (!s) return true;
  if (s.startsWith("/")) return true;
  if (s.includes("..")) return true;
  // block Windows drive letters / URLs
  if (/^[A-Za-z]:\//.test(s)) return true;
  if (/^[a-z]+:\/\//i.test(s)) return true;
  return false;
}

function extractSettingsPathsFromWorkflowXml(xmlText) {
  // Simple, robust heuristic: find substrings ending with settings.xml
  // and normalize to forward slashes.
  const out = new Set();

  // Prefer quoted attribute values (can include spaces)
  const reQuoted = /(["'])([^"']*settings\.xml)\1/g;
  let m;
  while ((m = reQuoted.exec(xmlText)) !== null) {
    const raw = m[2];
    let p = raw.replaceAll("\\", "/");
    if (!p.toLowerCase().endsWith("/settings.xml")) continue;
    p = p.replace(/^\.\/+/, "");
    if (p.startsWith("(#")) continue;
    out.add(p);
  }

  // Fallback: unquoted tokens
  const reUnquoted = /([^\s"'<>]+(?:\/|\\)settings\.xml)/g;
  while ((m = reUnquoted.exec(xmlText)) !== null) {
    const raw = m[1];
    let p = raw.replaceAll("\\", "/");
    if (!p.toLowerCase().endsWith("/settings.xml")) continue;
    p = p.replace(/^\.\/+/, "");
    if (p.startsWith("(#")) continue;
    if (!p.includes("/")) continue; // drop bare fragments
    out.add(p);
  }

  return Array.from(out).sort();
}

const manifestUtils = {
  fmtBytes,
  firstPathSegment,
  stripRootPrefix,
  normalizeRel,
  isUnsafeRel,
  extractSettingsPathsFromWorkflowXml,
};

if (typeof window !== "undefined") {
  window.manifestUtils = manifestUtils;
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = manifestUtils;
}
