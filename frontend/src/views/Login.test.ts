import { mount } from "@vue/test-utils";
import { reactive } from "vue";
import { describe, expect, it, vi } from "vitest";

const replace = vi.fn();
const route = reactive<{ query: Record<string, string> }>({ query: { returnTo: "/config" } });
vi.mock("vue-router", () => ({ useRouter: () => ({ replace }), useRoute: () => route }));
vi.mock("@/api/auth", () => ({ login: vi.fn() }));

import Login from "./Login.vue";
import { login } from "@/api/auth";

describe("Login", () => {
  it("shows a backend error without treating it as a network failure", async () => {
    vi.mocked(login).mockRejectedValueOnce({ response: { status: 401 } });
    const wrapper = mount(Login);
    await wrapper.get("#username").setValue("admin");
    await wrapper.get("#password").setValue("wrong");
    await wrapper.get("form").trigger("submit");
    expect(wrapper.get("[role='alert']").text()).toContain("账号或密码错误");
  });

  it("returns to an internal route after login", async () => {
    vi.mocked(login).mockResolvedValueOnce({ username: "admin", expires_at: 10, csrf_token: "csrf" });
    const wrapper = mount(Login);
    await wrapper.get("#username").setValue("admin");
    await wrapper.get("#password").setValue("correct");
    await wrapper.get("form").trigger("submit");
    expect(replace).toHaveBeenCalledWith("/config");
  });

  it("shows when server-side logout was not confirmed", () => {
    route.query = { logoutError: "1" };
    const wrapper = mount(Login);
    expect(wrapper.get("[role='alert']").text()).toContain("尚未确认服务端会话注销");
    route.query = { returnTo: "/config" };
  });
});
