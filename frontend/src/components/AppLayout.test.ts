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
  it("scopes the light theme and hides the token hint only on the home route", async () => {
    const wrapper = mount(AppLayout);

    expect(wrapper.find(".shell.home-light").exists()).toBe(true);
    expect(wrapper.find(".token-tip").exists()).toBe(false);
    route.name = "logs";
    await nextTick();
    expect(wrapper.find(".shell.home-light").exists()).toBe(false);
    expect(wrapper.find(".token-tip").exists()).toBe(true);
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
  });
});
