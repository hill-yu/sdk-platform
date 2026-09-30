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
      packageName: "", sdkVersion: "", deviceId: "d1", logLevel: "error", dateFrom: "2026-08-01", dateTo: "2026-08-28",
    }});
    expect(wrapper.get("[data-testid='export-button']").attributes("disabled")).toBeDefined();
    await wrapper.get("[data-testid='choose']").trigger("click");
    await wrapper.get("[data-testid='export-button']").trigger("click");
    await flushPromises();
    expect(api.createLogExport).toHaveBeenCalledWith({
      package_names: ["com.a", "com.b"], export_mode: "raw", device_id: "d1", log_level: "error",
      date_from: "2026-08-01", date_to: "2026-08-28",
    });
    await vi.advanceTimersByTimeAsync(2000);
    await flushPromises();
    expect(wrapper.text()).toContain("12 条");
    expect(wrapper.find("[data-testid='download-button']").exists()).toBe(true);
    wrapper.unmount();
  });

  it("uses the page package and sdk version with all current filters", async () => {
    const wrapper = mount(LogExportPanel, { props: {
      packageName: "com.a", sdkVersion: "1.0.6", deviceId: "d1", logLevel: "error",
      dateFrom: "2026-09-01", dateTo: "2026-09-23",
    }});

    expect(wrapper.find("[data-testid='choose']").exists()).toBe(false);
    expect(wrapper.get("[data-testid='export-button']").attributes("disabled")).toBeUndefined();
    await wrapper.get("[data-testid='export-button']").trigger("click");
    await flushPromises();

    expect(api.createLogExport).toHaveBeenCalledWith({
      package_names: ["com.a"], export_mode: "raw", sdk_version: "1.0.6", device_id: "d1", log_level: "error",
      date_from: "2026-09-01", date_to: "2026-09-23",
    });
    wrapper.unmount();
  });

  it("restores multi-package selection when the page package is cleared", async () => {
    const wrapper = mount(LogExportPanel, { props: {
      packageName: "com.a", sdkVersion: "", deviceId: "", logLevel: "", dateFrom: "", dateTo: "",
    }});

    await wrapper.setProps({ packageName: "" });
    expect(wrapper.find("[data-testid='choose']").exists()).toBe(true);
    await wrapper.get("[data-testid='choose']").trigger("click");
    await wrapper.get("[data-testid='export-button']").trigger("click");
    await flushPromises();

    expect(api.createLogExport).toHaveBeenCalledWith(expect.objectContaining({
      package_names: ["com.a", "com.b"],
    }));
    wrapper.unmount();
  });

  it("continues polling after a transient status error", async () => {
    api.getLogExport.mockRejectedValueOnce(new Error("temporary")).mockResolvedValueOnce({
      data: { id: "job-1", status: "success", row_count: 5 },
    });
    const wrapper = mount(LogExportPanel, { props: { packageName: "", sdkVersion: "", deviceId: "", logLevel: "", dateFrom: "", dateTo: "" } });
    await wrapper.get("[data-testid='choose']").trigger("click");
    await wrapper.get("[data-testid='export-button']").trigger("click");
    await flushPromises();
    await vi.advanceTimersByTimeAsync(2000);
    await flushPromises();
    expect(wrapper.text()).toContain("temporary");
    await vi.advanceTimersByTimeAsync(2000);
    await flushPromises();
    expect(wrapper.text()).toContain("5 条");
  });

  it("sends the applied hour filters as numbers", async () => {
    const wrapper = mount(LogExportPanel, { props: {
      packageName: "com.a", sdkVersion: "", deviceId: "", logLevel: "",
      dateFrom: "2026-09-20", hourFrom: "8", dateTo: "2026-09-22", hourTo: "17",
    }});

    await wrapper.get("[data-testid='export-button']").trigger("click");
    await flushPromises();

    expect(api.createLogExport).toHaveBeenCalledWith({
      package_names: ["com.a"], export_mode: "raw", sdk_version: undefined, device_id: undefined, log_level: undefined,
      date_from: "2026-09-20", hour_from: 8, date_to: "2026-09-22", hour_to: 17,
    });
    wrapper.unmount();
  });

  it("defaults to raw, switches to h1 with an explicit fallback note, and sends the mode", async () => {
    const wrapper = mount(LogExportPanel, { props: { packageName: "com.a", sdkVersion: "1.0.6", deviceId: "d1", logLevel: "", dateFrom: "2026-09-01", dateTo: "2026-09-03" } });

    expect((wrapper.get("[data-testid='export-mode']").element as HTMLSelectElement).value).toBe("raw");
    await wrapper.get("[data-testid='export-mode']").setValue("h1");
    expect(wrapper.get("[data-testid='h1-export-note']").text()).toContain("有 H1 按条拆行，无 H1 保留原始 extra");
    await wrapper.get("[data-testid='export-button']").trigger("click");
    await flushPromises();

    expect(api.createLogExport).toHaveBeenCalledWith(expect.objectContaining({ package_names: ["com.a"], export_mode: "h1" }));
  });

  it("binds the selected mode to the created job and disables switching while it is active", async () => {
    api.createLogExport.mockResolvedValueOnce({ data: { id: "job-1", status: "pending" } });
    const wrapper = mount(LogExportPanel, { props: { packageName: "com.a", sdkVersion: "", deviceId: "", logLevel: "", dateFrom: "", dateTo: "" } });
    await wrapper.get("[data-testid='export-mode']").setValue("h1");
    await wrapper.get("[data-testid='export-button']").trigger("click");
    await flushPromises();

    expect(wrapper.get("[data-testid='export-mode']").attributes("disabled")).toBeDefined();
    expect((wrapper.get("[data-testid='export-mode']").element as HTMLSelectElement).value).toBe("h1");
    await wrapper.get("[data-testid='export-mode']").trigger("change");
    expect(wrapper.get("[data-testid='export-mode']").attributes("disabled")).toBeDefined();
    wrapper.unmount();
  });
});
