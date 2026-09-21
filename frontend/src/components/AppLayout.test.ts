import { mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";

vi.mock("vue-router", () => ({
  RouterLink: { template: "<a><slot /></a>" },
  RouterView: { template: "<div data-testid='router-view-content'>page</div>" },
  useRoute: () => ({ name: "dashboard" }),
}));

import AppLayout from "@/components/AppLayout.vue";
import appLayoutSource from "@/components/AppLayout.vue?raw";

describe("AppLayout internal scroll structure", () => {
  it("keeps fixed shell nodes outside page content", () => {
    const wrapper = mount(AppLayout);

    expect(wrapper.find(".shell > .sidebar").exists()).toBe(true);
    expect(wrapper.find(".content > .topbar").exists()).toBe(true);
    expect(wrapper.find(".page > [data-testid='router-view-content']").exists()).toBe(true);
  });

  it("publishes fixed viewport and page overflow rules", () => {
    mount(AppLayout);

    expect(appLayoutSource).toContain("100dvh");
    expect(appLayoutSource).toContain("overflow-y: auto");
  });
});
