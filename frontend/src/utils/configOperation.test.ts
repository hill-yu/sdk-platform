import { describe, expect, it } from "vitest";

import { isPublishConfirmed, isRequestTimeout, isSaveConfirmed } from "@/utils/configOperation";

describe("configuration operation confirmation", () => {
  it("recognizes Axios timeouts without treating other errors as timeouts", () => {
    expect(isRequestTimeout({ code: "ECONNABORTED" })).toBe(true);
    expect(isRequestTimeout(new Error("timeout of 60000ms exceeded"))).toBe(true);
    expect(isRequestTimeout(new Error("Request failed with status code 500"))).toBe(false);
  });

  it("confirms a timed-out save only when updated_at changed", () => {
    const before = { id: 3, updated_at: "2026-08-10T07:00:00Z" };
    expect(isSaveConfirmed(before, { id: 3, updated_at: "2026-08-10T07:01:00Z" })).toBe(true);
    expect(isSaveConfirmed(before, { id: 3, updated_at: before.updated_at })).toBe(false);
  });

  it("confirms a timed-out publish from status and version", () => {
    const before = { id: 3, status: "draft", version: "draft_1" };
    expect(isPublishConfirmed(before, { id: 3, status: "published", version: "20260810_v1" })).toBe(true);
    expect(isPublishConfirmed(before, { id: 3, status: "draft", version: "draft_1" })).toBe(false);
  });
});
