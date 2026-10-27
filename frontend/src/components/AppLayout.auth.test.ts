import { mount } from "@vue/test-utils";
import { flushPromises } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { replace, logout } = vi.hoisted(() => ({ replace: vi.fn(), logout: vi.fn() }));
vi.mock("vue-router", () => ({
  RouterLink: { template: "<a><slot /></a>" },
  RouterView: { template: "<div>page</div>" },
  useRoute: () => ({ name: "dashboard" }),
  useRouter: () => ({ replace }),
}));
vi.mock("@/api/auth", () => ({ logout }));

import AppLayout from "./AppLayout.vue";

describe("AppLayout logout", () => {
  beforeEach(() => vi.clearAllMocks());

  it("navigates to login with an explicit unconfirmed-logout message on failure", async () => {
    logout.mockRejectedValueOnce(new Error("network"));
    const wrapper = mount(AppLayout);
    await wrapper.get(".logout-button").trigger("click");
    await flushPromises();
    expect(replace).toHaveBeenCalledWith({ name: "login", query: { logoutError: "1" } });
    wrapper.unmount();
  });

  it("navigates to login without an error after successful logout", async () => {
    logout.mockResolvedValueOnce(undefined);
    const wrapper = mount(AppLayout);
    await wrapper.get(".logout-button").trigger("click");
    await flushPromises();
    expect(replace).toHaveBeenCalledWith({ name: "login" });
    wrapper.unmount();
  });
});
