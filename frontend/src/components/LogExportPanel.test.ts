import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({ createLogExport: vi.fn(), getLogExport: vi.fn(), downloadLogExport: vi.fn() }));
vi.mock("@/api/logExports", () => api);
vi.mock("@/components/PackageMultiSelect.vue", () => ({
  default: { props: ["modelValue"], emits: ["update:modelValue"], template: "<button data-testid='choose' @click=\"$emit('update:modelValue', ['com.a','com.b'])\">choose</button>" },
}));
import LogExportPanel from "@/components/LogExportPanel.vue";

describe("LogExportPanel", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.clearAllMocks();
    api.createLogExport.mockResolvedValue({ data: { id: "job-1", status: "pending" } });
    api.getLogExport.mockResolvedValue({ data: { id: "job-1", status: "success", row_count: 12 } });
  });

  it("creates with selected packages and current filters then polls to success", async () => {
    const wrapper = mount(LogExportPanel, { props: {
      deviceId: "d1", logLevel: "error", dateFrom: "2026-08-01", dateTo: "2026-08-28",
    }});
    expect(wrapper.get("[data-testid='export-button']").attributes("disabled")).toBeDefined();
    await wrapper.get("[data-testid='choose']").trigger("click");
    await wrapper.get("[data-testid='export-button']").trigger("click");
    await flushPromises();
    expect(api.createLogExport).toHaveBeenCalledWith({
      package_names: ["com.a", "com.b"], device_id: "d1", log_level: "error",
      date_from: "2026-08-01", date_to: "2026-08-28",
    });
    await vi.advanceTimersByTimeAsync(2000);
    await flushPromises();
    expect(wrapper.text()).toContain("12 条");
    expect(wrapper.find("[data-testid='download-button']").exists()).toBe(true);
  });
});
