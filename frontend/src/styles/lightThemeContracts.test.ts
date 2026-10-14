import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const files = [
  "views/LogViewer.vue",
  "components/LogAnalysisFilters.vue",
  "components/LogMetricsPanel.vue",
  "components/LogParseTaskPanel.vue",
  "components/LogColumnSettings.vue",
  "components/LogFailureDrawer.vue",
  "components/LogDetail.vue",
  "components/LogAnalysisDetail.vue",
  "components/LogExportPanel.vue",
  "components/PackageMultiSelect.vue",
  "components/PackageProfileCell.vue",
  "components/UsageDurationPanel.vue",
].map((file) => resolve(process.cwd(), "src", file));

describe("light theme component contracts", () => {
  it("does not retain legacy dark surfaces or light-on-dark status colors", () => {
    const legacyDark = /#101b1a|#16213e|#f3efe8|#ffb0a8|#ffd27a|#a8e5bd|#c6cbd3|#8cc8ff|#d68c45|#b6622b|rgba\(255,\s*255,\s*255|rgba\(8,\s*13,\s*13|rgba\(0,\s*0,\s*0,\s*\.2[245]\)/i;

    for (const file of files) {
      expect(readFileSync(file, "utf8"), file).not.toMatch(legacyDark);
    }
  });

  it("uses shared semantic tokens for component status and surfaces", () => {
    const source = files.map((file) => readFileSync(file, "utf8")).join("\n");

    expect(source).toContain("var(--panel-bg)");
    expect(source).toContain("var(--error-text)");
    expect(source).toContain("var(--success-text)");
  });
});
