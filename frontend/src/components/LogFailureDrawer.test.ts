import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import LogFailureDrawer from "@/components/LogFailureDrawer.vue";

describe("LogFailureDrawer", () => {
  it("shows failure categories, shares, and emits close", async () => {
    const wrapper = mount(LogFailureDrawer, {
      props: {
        open: true,
        items: [
          { failure_category: "timeout", failure_count: 2, share: 0.5 },
          { failure_category: "unknown", failure_count: 2, share: null },
        ],
      },
    });

    expect(wrapper.get("[data-testid='failure-drawer']").text()).toContain("timeout");
    expect(wrapper.get("[data-testid='failure-share-timeout']").text()).toContain("50%");
    expect(wrapper.get("[data-testid='failure-share-unknown']").text()).toBe("-");
    await wrapper.get("[data-testid='close-failure-drawer']").trigger("click");
    expect(wrapper.emitted("close")).toHaveLength(1);
  });

  it("shows request errors instead of presenting them as an empty result", () => {
    const wrapper = mount(LogFailureDrawer, { props: { open: true, items: [], error: "failure unavailable" } });
    expect(wrapper.get("[data-testid='failure-error']").text()).toContain("failure unavailable");
    expect(wrapper.find(".empty-state").exists()).toBe(false);
  });
});
