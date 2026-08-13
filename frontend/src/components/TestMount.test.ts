import { mount } from "@vue/test-utils";
import { defineComponent } from "vue";
import { expect, it } from "vitest";

it("mounts a Vue component", () => {
  const wrapper = mount(defineComponent({ template: "<p>ready</p>" }));
  expect(wrapper.text()).toContain("ready");
});
