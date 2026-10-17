import { describe, expect, it, vi } from "vitest";

const request = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));
vi.mock("./request", () => ({ default: request }));

import { login, logout, me } from "./auth";
import { adminAuth } from "@/stores/adminAuth";

describe("admin auth API", () => {
  it("stores the server session returned by login and me", async () => {
    const session = { username: "admin", expires_at: 10, csrf_token: "csrf" };
    request.post.mockResolvedValueOnce(session);
    await expect(login("admin", "password")).resolves.toEqual(session);
    expect(adminAuth.session).toEqual(session);
    request.get.mockResolvedValueOnce(session);
    await me();
    expect(request.get).toHaveBeenCalledWith("/auth/me");
  });

  it("clears in-memory auth even when logout fails", async () => {
    adminAuth.session = { username: "admin", expires_at: 10, csrf_token: "csrf" };
    request.post.mockRejectedValueOnce(new Error("network"));
    await expect(logout()).rejects.toThrow("network");
    expect(adminAuth.session).toBeNull();
  });
});
