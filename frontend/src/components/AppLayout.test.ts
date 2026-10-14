import { mount } from "@vue/test-utils";
import { nextTick, reactive } from "vue";
import { describe, expect, it, vi } from "vitest";

vi.mock("vue-router", () => ({
  RouterLink: { template: "<a><slot /></a>" },
  RouterView: { template: "<div data-testid='router-view-content'>page</div>" },
  useRoute: () => route,
}));

const route = reactive({ name: "dashboard" });

import AppLayout from "@/components/AppLayout.vue";
import appLayoutSource from "@/components/AppLayout.vue?raw";

describe("AppLayout internal scroll structure", () => {
  it("uses the light shell and route title on every route", async () => {
    const wrapper = mount(AppLayout);

    expect(wrapper.find(".brand-mark").exists()).toBe(true);
    expect(wrapper.text()).toContain("SDK 运营中台");
    for (const name of ["dashboard", "logs", "config", "version"]) {
      route.name = name;
      await nextTick();
      expect(wrapper.find(".shell.light-shell").exists()).toBe(true);
      expect(wrapper.find(".token-tip").exists()).toBe(false);
    }
    route.name = "dashboard";
  });

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
    expect(appLayoutSource).toContain("overflow: hidden");
    expect(appLayoutSource).toContain("overflow-x: auto");
  });
});
