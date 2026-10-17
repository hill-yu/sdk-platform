import { describe, expect, it } from "vitest";
import requestSource from "./request.ts?raw";
import request from "./request";

describe("admin request security", () => {
  it("uses credential cookies and does not contain token prompts or storage", () => {
    expect(request.defaults.withCredentials).toBe(true);
    expect(requestSource).not.toContain("sessionStorage");
    expect(requestSource).not.toContain("prompt(");
    expect(requestSource).not.toContain("ADMIN_TOKEN");
  });
});
