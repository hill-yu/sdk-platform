import { beforeEach, describe, expect, it, vi } from "vitest";

const { me } = vi.hoisted(() => ({ me: vi.fn() }));
vi.mock("@/api/auth", () => ({ me }));

import router from "./index";
import { adminAuth, clearAdminSession, setAdminSession } from "@/stores/adminAuth";

describe("admin router authentication guard", () => {
  beforeEach(async () => {
    clearAdminSession();
    me.mockRejectedValue(new Error("401"));
    await router.replace("/login");
  });

  it("protects a deep link and then allows it after /me succeeds", async () => {
    await router.push("/config");
    expect(router.currentRoute.value.name).toBe("login");
    expect(router.currentRoute.value.query.returnTo).toBe("/config");

    setAdminSession({ username: "admin", expires_at: 10, csrf_token: "csrf" });
    expect(adminAuth.session?.username).toBe("admin");
    await router.push("/config");
    expect(router.currentRoute.value.name).toBe("config");
  });
});
