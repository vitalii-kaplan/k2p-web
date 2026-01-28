import { describe, it, expect } from "vitest";
import {
  fmtBytes,
  firstPathSegment,
  stripRootPrefix,
  normalizeRel,
  isUnsafeRel,
  extractSettingsPathsFromWorkflowXml,
} from "../../api/static/ui/manifest_utils.js";

describe("manifest utils", () => {
  it("fmtBytes formats human readable sizes", () => {
    expect(fmtBytes(0)).toBe("0 B");
    expect(fmtBytes(1024)).toBe("1.0 KiB");
    expect(fmtBytes(1024 * 1024)).toBe("1.0 MiB");
  });

  it("firstPathSegment extracts the root folder", () => {
    expect(firstPathSegment("root/inner/file.txt")).toBe("root");
    expect(firstPathSegment("\\root\\inner\\file.txt")).toBe("root");
  });

  it("stripRootPrefix removes the leading folder", () => {
    expect(stripRootPrefix("root/a/b.txt", "root")).toBe("a/b.txt");
    expect(stripRootPrefix("other/a/b.txt", "root")).toBe("other/a/b.txt");
  });

  it("normalizeRel and isUnsafeRel behave as expected", () => {
    expect(normalizeRel("./a/b.txt")).toBe("a/b.txt");
    expect(isUnsafeRel("../a")).toBe(true);
    expect(isUnsafeRel("/abs/path")).toBe(true);
    expect(isUnsafeRel("a/b/settings.xml")).toBe(false);
  });

  it("extractSettingsPathsFromWorkflowXml prefers full paths with spaces", () => {
    const xml = `
      <config>
        <entry key="path" value="CSV Reader (#1)/settings.xml" />
        <entry key="path2" value="Line Plot (#2)/settings.xml" />
        <entry key="bad" value="(#1)/settings.xml" />
      </config>
    `;
    const paths = extractSettingsPathsFromWorkflowXml(xml);
    expect(paths).toContain("CSV Reader (#1)/settings.xml");
    expect(paths).toContain("Line Plot (#2)/settings.xml");
    expect(paths).not.toContain("(#1)/settings.xml");
  });
});
