import { mount, type DOMWrapper, type VueWrapper } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";

import ConfigTreeEditor from "@/components/ConfigTreeEditor.vue";
import type { JsonValue, TreePath } from "@/utils/configTree";

function nodeAt(wrapper: VueWrapper, path: TreePath): DOMWrapper<Element> {
  const pathText = JSON.stringify(path);
  const node = wrapper
    .findAll("[data-testid='tree-node']")
    .find((candidate) => candidate.attributes("data-path") === pathText);
  if (!node) throw new Error(`missing tree node ${pathText}`);
  return node;
}

async function adoptLastUpdate(wrapper: VueWrapper): Promise<JsonValue> {
  const updates = wrapper.emitted<JsonValue[]>("update:modelValue");
  if (!updates?.length) throw new Error("missing model update");
  const value = updates.at(-1)![0];
  await wrapper.setProps({ modelValue: value });
  return value;
}

describe("ConfigTreeEditor scalar controls and readonly behavior", () => {
  afterEach(() => vi.restoreAllMocks());

  it("renders controls for all six JSON types and updates scalar values", async () => {
    const wrapper = mount(ConfigTreeEditor, {
      props: {
        modelValue: {
          text: "before",
          count: 2,
          enabled: true,
          empty: null,
          section: {},
          list: [],
        },
      },
    });

    expect(nodeAt(wrapper, ["text"]).get("[data-testid='string-input']").element).toBeInstanceOf(HTMLInputElement);
    expect(nodeAt(wrapper, ["count"]).get("[data-testid='number-input']").element).toBeInstanceOf(HTMLInputElement);
    expect(nodeAt(wrapper, ["enabled"]).get("[data-testid='boolean-input']").element).toBeInstanceOf(HTMLSelectElement);
    expect(nodeAt(wrapper, ["empty"]).get("[data-testid='null-value']").text()).toBe("null");
    expect(nodeAt(wrapper, ["section"]).find("[data-testid='container-children']").exists()).toBe(true);
    expect(nodeAt(wrapper, ["list"]).find("[data-testid='container-children']").exists()).toBe(true);

    await nodeAt(wrapper, ["text"]).get("[data-testid='string-input']").setValue("after");
    expect(await adoptLastUpdate(wrapper)).toMatchObject({ text: "after" });
    await nodeAt(wrapper, ["enabled"]).get("[data-testid='boolean-input']").setValue("false");
    expect(await adoptLastUpdate(wrapper)).toMatchObject({ enabled: false });
  });

  it("rejects an invalid number without updating the model", async () => {
    const wrapper = mount(ConfigTreeEditor, { props: { modelValue: { count: 2 } } });

    await nodeAt(wrapper, ["count"]).get("[data-testid='number-input']").setValue("not-a-number");

    expect(nodeAt(wrapper, ["count"]).get("[data-testid='node-error']").text()).toContain("有限数字");
    expect(wrapper.emitted("update:modelValue")).toBeUndefined();
  });

  it("keeps folding and copying available while all mutations are disabled", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText } });
    const wrapper = mount(ConfigTreeEditor, {
      props: { modelValue: { section: { value: 1 }, list: ["a"] }, disabled: true },
    });
    const root = nodeAt(wrapper, []);

    for (const control of wrapper.findAll("[data-mutation-control='true']")) {
      expect(control.attributes("disabled")).toBeDefined();
    }
    expect(root.get("[data-testid='collapse-toggle']").attributes("disabled")).toBeUndefined();
    expect(root.get("[data-testid='copy-node']").attributes("disabled")).toBeUndefined();

    await root.get("[data-testid='collapse-toggle']").trigger("click");
    expect(root.find("[data-testid='container-children']").exists()).toBe(false);
    await root.get("[data-testid='copy-node']").trigger("click");
    await vi.waitFor(() => expect(writeText).toHaveBeenCalledWith(JSON.stringify({ section: { value: 1 }, list: ["a"] }, null, 2)));
    expect(wrapper.emitted("update:modelValue")).toBeUndefined();
  });
});

describe("ConfigTreeEditor object operations", () => {
  it("adds child and sibling fields, renames fields, and removes scalars", async () => {
    const wrapper = mount(ConfigTreeEditor, {
      props: { modelValue: { section: { first: "one" } } },
    });

    const section = nodeAt(wrapper, ["section"]);
    await section.get("[data-testid='add-key']").setValue("child");
    await section.get("[data-testid='add-type']").setValue("number");
    await section.get("[data-testid='add-child']").trigger("click");
    expect(await adoptLastUpdate(wrapper)).toEqual({ section: { first: "one", child: 0 } });

    const first = nodeAt(wrapper, ["section", "first"]);
    await first.get("[data-testid='sibling-key']").setValue("second");
    await first.get("[data-testid='sibling-type']").setValue("boolean");
    await first.get("[data-testid='add-sibling']").trigger("click");
    expect(await adoptLastUpdate(wrapper)).toEqual({ section: { first: "one", child: 0, second: false } });

    await nodeAt(wrapper, ["section", "first"]).get("[data-testid='rename-input']").setValue("renamed");
    await nodeAt(wrapper, ["section", "first"]).get("[data-testid='rename-button']").trigger("click");
    expect(await adoptLastUpdate(wrapper)).toEqual({ section: { renamed: "one", child: 0, second: false } });

    await nodeAt(wrapper, ["section", "child"]).get("[data-testid='remove-node']").trigger("click");
    expect(await adoptLastUpdate(wrapper)).toEqual({ section: { renamed: "one", second: false } });
  });

  it("shows duplicate-name errors on the operated node and preserves the valid model", async () => {
    const model = { section: { first: 1, existing: 2 } };
    const wrapper = mount(ConfigTreeEditor, { props: { modelValue: model } });
    const first = nodeAt(wrapper, ["section", "first"]);

    await first.get("[data-testid='rename-input']").setValue("existing");
    await first.get("[data-testid='rename-button']").trigger("click");

    expect(nodeAt(wrapper, ["section", "first"]).get("[data-testid='node-error']").text()).toContain("已存在");
    expect(wrapper.emitted("update:modelValue")).toBeUndefined();
    expect(wrapper.props("modelValue")).toEqual(model);
  });
});

describe("ConfigTreeEditor array operations and confirmations", () => {
  afterEach(() => vi.restoreAllMocks());

  it("adds, deeply duplicates, removes, and moves array items with boundary buttons disabled", async () => {
    const wrapper = mount(ConfigTreeEditor, {
      props: { modelValue: { list: [{ nested: { value: 1 } }, { nested: { value: 2 } }] } },
    });

    const list = nodeAt(wrapper, ["list"]);
    await list.get("[data-testid='add-type']").setValue("string");
    await list.get("[data-testid='add-child']").trigger("click");
    expect(await adoptLastUpdate(wrapper)).toEqual({ list: [{ nested: { value: 1 } }, { nested: { value: 2 } }, ""] });

    await nodeAt(wrapper, ["list", 0]).get("[data-testid='duplicate-node']").trigger("click");
    const duplicated = (await adoptLastUpdate(wrapper)) as { list: Array<{ nested: { value: number } }> };
    expect(duplicated.list.slice(0, 2)).toEqual([{ nested: { value: 1 } }, { nested: { value: 1 } }]);
    expect(duplicated.list[0]).not.toBe(duplicated.list[1]);
    expect(duplicated.list[0].nested).not.toBe(duplicated.list[1].nested);

    expect(nodeAt(wrapper, ["list", 0]).get("[data-testid='move-up']").attributes("disabled")).toBeDefined();
    const lastPath: TreePath = ["list", duplicated.list.length - 1];
    expect(nodeAt(wrapper, lastPath).get("[data-testid='move-down']").attributes("disabled")).toBeDefined();

    await nodeAt(wrapper, ["list", 1]).get("[data-testid='move-down']").trigger("click");
    expect((await adoptLastUpdate(wrapper) as { list: unknown[] }).list[2]).toEqual({ nested: { value: 1 } });
    await nodeAt(wrapper, ["list", 2]).get("[data-testid='move-up']").trigger("click");
    await adoptLastUpdate(wrapper);

    vi.spyOn(window, "confirm").mockReturnValue(true);
    await nodeAt(wrapper, ["list", 1]).get("[data-testid='remove-node']").trigger("click");
    expect((await adoptLastUpdate(wrapper) as { list: unknown[] }).list).toHaveLength(3);
  });

  it("does not update when deleting a non-empty container is cancelled", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    const wrapper = mount(ConfigTreeEditor, {
      props: { modelValue: { section: { nested: true } } },
    });

    await nodeAt(wrapper, ["section"]).get("[data-testid='remove-node']").trigger("click");

    expect(confirm).toHaveBeenCalledOnce();
    expect(wrapper.emitted("update:modelValue")).toBeUndefined();
  });

  it("does not update when changing a non-empty container type is cancelled", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    const wrapper = mount(ConfigTreeEditor, {
      props: { modelValue: { section: { nested: true } } },
    });

    await nodeAt(wrapper, ["section"]).get("[data-testid='type-select']").setValue("string");

    expect(confirm).toHaveBeenCalledOnce();
    expect(wrapper.emitted("update:modelValue")).toBeUndefined();
    expect(nodeAt(wrapper, ["section"]).get<HTMLSelectElement>("[data-testid='type-select']").element.value).toBe("object");
  });

  it("keeps collapsed state with the moved array value", async () => {
    const wrapper = mount(ConfigTreeEditor, {
      props: { modelValue: { list: [{ label: "first" }, { label: "second" }] } },
    });

    await nodeAt(wrapper, ["list", 0]).get("[data-testid='collapse-toggle']").trigger("click");
    await nodeAt(wrapper, ["list", 0]).get("[data-testid='move-down']").trigger("click");
    await adoptLastUpdate(wrapper);

    expect(nodeAt(wrapper, ["list", 0]).find("[data-testid='container-children']").exists()).toBe(true);
    expect(nodeAt(wrapper, ["list", 1]).find("[data-testid='container-children']").exists()).toBe(false);
  });

  it("does not leave an invalid-number draft on another value after moving", async () => {
    const wrapper = mount(ConfigTreeEditor, {
      props: { modelValue: { list: [1, 2] } },
    });

    await nodeAt(wrapper, ["list", 0]).get("[data-testid='number-input']").setValue("invalid");
    await nodeAt(wrapper, ["list", 0]).get("[data-testid='move-down']").trigger("click");
    await adoptLastUpdate(wrapper);

    expect(nodeAt(wrapper, ["list", 0]).find("[data-testid='node-error']").exists()).toBe(false);
    const movedError = nodeAt(wrapper, ["list", 1]).find("[data-testid='node-error']");
    if (movedError.exists()) expect(movedError.text()).toContain("有限数字");
  });

  it("does not transfer a local operation error to another array value after moving", async () => {
    const wrapper = mount(ConfigTreeEditor, {
      props: {
        modelValue: {
          list: [
            { marker: "first", field: 1, existing: 2 },
            { marker: "second", field: 3, existing: 4 },
          ],
        },
      },
    });

    await nodeAt(wrapper, ["list", 0, "field"]).get("[data-testid='rename-input']").setValue("existing");
    await nodeAt(wrapper, ["list", 0, "field"]).get("[data-testid='rename-button']").trigger("click");
    expect(nodeAt(wrapper, ["list", 0, "field"]).get("[data-testid='node-error']").text()).toContain("已存在");

    await nodeAt(wrapper, ["list", 0]).get("[data-testid='move-down']").trigger("click");
    await adoptLastUpdate(wrapper);

    expect(nodeAt(wrapper, ["list", 0, "field"]).find("[data-testid='node-error']").exists()).toBe(false);
    const movedError = nodeAt(wrapper, ["list", 1, "field"]).find("[data-testid='node-error']");
    if (movedError.exists()) expect(movedError.text()).toContain("已存在");
  });

  it("does not transfer the next item's collapsed state to a duplicated item", async () => {
    const wrapper = mount(ConfigTreeEditor, {
      props: { modelValue: { list: [{ label: "first" }, { label: "second" }] } },
    });

    await nodeAt(wrapper, ["list", 1]).get("[data-testid='collapse-toggle']").trigger("click");
    await nodeAt(wrapper, ["list", 0]).get("[data-testid='duplicate-node']").trigger("click");
    await adoptLastUpdate(wrapper);

    expect(nodeAt(wrapper, ["list", 1]).find("[data-testid='container-children']").exists()).toBe(true);
    expect(nodeAt(wrapper, ["list", 2]).find("[data-testid='container-children']").exists()).toBe(false);
  });

  it("does not transfer a removed item's invalid-number draft to its successor", async () => {
    const wrapper = mount(ConfigTreeEditor, {
      props: { modelValue: { list: [1, 2] } },
    });

    await nodeAt(wrapper, ["list", 0]).get("[data-testid='number-input']").setValue("invalid");
    await nodeAt(wrapper, ["list", 0]).get("[data-testid='remove-node']").trigger("click");
    await adoptLastUpdate(wrapper);

    expect(nodeAt(wrapper, ["list", 0]).find("[data-testid='node-error']").exists()).toBe(false);
    expect(nodeAt(wrapper, ["list", 0]).get<HTMLInputElement>("[data-testid='number-input']").element.value).toBe("2");
  });

  it("gives an appended item fresh state without disturbing existing item state", async () => {
    const wrapper = mount(ConfigTreeEditor, {
      props: { modelValue: { list: [{ label: "first" }] } },
    });

    await nodeAt(wrapper, ["list", 0]).get("[data-testid='collapse-toggle']").trigger("click");
    await nodeAt(wrapper, ["list"]).get("[data-testid='add-type']").setValue("object");
    await nodeAt(wrapper, ["list"]).get("[data-testid='add-child']").trigger("click");
    await adoptLastUpdate(wrapper);

    expect(nodeAt(wrapper, ["list", 0]).find("[data-testid='container-children']").exists()).toBe(false);
    expect(nodeAt(wrapper, ["list", 1]).find("[data-testid='container-children']").exists()).toBe(true);
  });
});
