import { describe, expect, it } from "vitest";
import { beginFeedback, setFeedbackError, setFeedbackSuccess } from "./feedback";

describe("feedback state", () => {
  it("clears stale messages when a new action begins", () => {
    const state = { error: "配置 JSON 格式错误", success: "旧成功提示" };
    beginFeedback(state);
    expect(state).toEqual({ error: "", success: "" });
  });

  it("success removes the previous error", () => {
    const state = { error: "配置 JSON 格式错误", success: "" };
    setFeedbackSuccess(state, "配置已加密保存");
    expect(state).toEqual({ error: "", success: "配置已加密保存" });
  });

  it("error removes the previous success", () => {
    const state = { error: "", success: "配置已发布" };
    setFeedbackError(state, "请求失败");
    expect(state).toEqual({ error: "请求失败", success: "" });
  });
});
