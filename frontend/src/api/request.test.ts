import { afterEach, describe, expect, it, vi } from "vitest";
import requestSource from "./request.ts?raw";
import request from "./request";
import { adminAuth } from "@/stores/adminAuth";

describe("admin request security", () => {
  const originalAdapter = request.defaults.adapter;

  afterEach(() => {
    request.defaults.adapter = originalAdapter;
    adminAuth.session = null;
  });

  it("uses credential cookies and does not contain token prompts or storage", () => {
    expect(request.defaults.withCredentials).toBe(true);
    expect(requestSource).not.toContain("sessionStorage");
    expect(requestSource).not.toContain("prompt(");
    expect(requestSource).not.toContain("ADMIN_TOKEN");
  });

  it("adds CSRF to a real write adapter request", async () => {
    adminAuth.session = { username: "admin", expires_at: 10, csrf_token: "csrf-token" };
    let observedHeaders: any;
    request.defaults.adapter = async (config) => {
      observedHeaders = config.headers;
      return { data: { ok: true }, status: 200, statusText: "OK", headers: {}, config };
    };
    await request.post("/configs");
    expect(observedHeaders["X-CSRF-Token"]).toBe("csrf-token");
  });

  it("clears the session and emits expiry on a real 401 adapter response", async () => {
    adminAuth.session = { username: "admin", expires_at: 10, csrf_token: "csrf-token" };
    const expired = vi.fn();
    window.addEventListener("admin-auth-expired", expired);
    request.defaults.adapter = async (config) => Promise.reject({ response: { status: 401, data: { detail: "expired" } }, config });
    await expect(request.get("/dashboard")).rejects.toBeTruthy();
    expect(adminAuth.session).toBeNull();
    expect(expired).toHaveBeenCalledTimes(1);
    window.removeEventListener("admin-auth-expired", expired);
  });
});
