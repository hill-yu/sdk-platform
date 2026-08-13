import { describe, expect, it } from "vitest";
import {
  addObjectField,
  appendArrayItem,
  cloneJson,
  defaultValueForType,
  duplicateArrayItem,
  getAtPath,
  jsonTypeOf,
  moveArrayItem,
  removeAtPath,
  renameObjectField,
  replaceAtPath,
  validateConfigData,
  type JsonObject,
  type JsonType,
  type JsonValue,
} from "./configTree";

describe("config tree paths and immutable operations", () => {
  it("reads and replaces special object keys without parsing their text", () => {
    const source: JsonObject = {
      "a.b": {
        "a[0]": [{ "中文 字段": 1 }],
      },
    };
    const path = ["a.b", "a[0]", 0, "中文 字段"];

    expect(getAtPath(source, path)).toBe(1);

    const updated = replaceAtPath(source, path, 2);
    expect(updated).toEqual({
      "a.b": {
        "a[0]": [{ "中文 字段": 2 }],
      },
    });
    expect(source["a.b"]).toEqual({ "a[0]": [{ "中文 字段": 1 }] });
    expect(updated).not.toBe(source);
  });

  it("deep clones JSON values", () => {
    const source: JsonObject = { nested: [{ enabled: true }] };

    const cloned = cloneJson(source) as JsonObject;

    expect(cloned).toEqual(source);
    expect(cloned).not.toBe(source);
    expect(cloned.nested).not.toBe(source.nested);
    expect((cloned.nested as JsonValue[])[0]).not.toBe((source.nested as JsonValue[])[0]);
  });

  it("replaces and removes values without mutating the input", () => {
    const source: JsonObject = { object: { keep: 1, remove: 2 }, array: ["a", "b", "c"] };

    const replaced = replaceAtPath(source, ["object", "keep"], 3);
    const objectRemoved = removeAtPath(source, ["object", "remove"]);
    const arrayRemoved = removeAtPath(source, ["array", 1]);

    expect(replaced).toEqual({ object: { keep: 3, remove: 2 }, array: ["a", "b", "c"] });
    expect(objectRemoved).toEqual({ object: { keep: 1 }, array: ["a", "b", "c"] });
    expect(arrayRemoved).toEqual({ object: { keep: 1, remove: 2 }, array: ["a", "c"] });
    expect(source).toEqual({ object: { keep: 1, remove: 2 }, array: ["a", "b", "c"] });
  });

  it("reports the failing path segment for invalid paths", () => {
    const source: JsonObject = { list: [{ value: 1 }] };

    expect(() => getAtPath(source, ["list", 2, "value"])).toThrow("$[\"list\"][2]");
    expect(() => replaceAtPath(source, ["list", "0"], 2)).toThrow("$[\"list\"][\"0\"]");
    expect(() => removeAtPath(source, [])).toThrow("$");
  });
});

describe("config tree object operations", () => {
  it("adds and renames object fields while preserving values and input", () => {
    const source: JsonObject = { section: { before: { nested: true } } };

    const added = addObjectField(source, ["section"], "a.b", [1, 2]);
    const renamed = renameObjectField(source, ["section", "before"], "中文 字段");

    expect(added).toEqual({ section: { before: { nested: true }, "a.b": [1, 2] } });
    expect(renamed).toEqual({ section: { "中文 字段": { nested: true } } });
    expect(source).toEqual({ section: { before: { nested: true } } });
  });

  it("rejects empty and duplicate field names", () => {
    const source: JsonObject = { section: { existing: 1, other: 2 } };

    expect(() => addObjectField(source, ["section"], "", null)).toThrow("不能为空");
    expect(() => addObjectField(source, ["section"], "existing", null)).toThrow("已存在");
    expect(() => renameObjectField(source, ["section", "other"], "")).toThrow("不能为空");
    expect(() => renameObjectField(source, ["section", "other"], "existing")).toThrow("已存在");
  });
});

describe("config tree array operations", () => {
  it("appends without mutating the source or retaining the appended reference", () => {
    const source: JsonObject = { list: [1] };
    const value: JsonObject = { nested: { value: 2 } };

    const updated = appendArrayItem(source, ["list"], value) as JsonObject;
    ((value.nested as JsonObject).value as number) = 3;

    expect(updated).toEqual({ list: [1, { nested: { value: 2 } }] });
    expect(source).toEqual({ list: [1] });
  });

  it("duplicates array elements by deep copy", () => {
    const source: JsonObject = { list: [{ nested: [1] }] };

    const updated = duplicateArrayItem(source, ["list", 0]) as JsonObject;
    const list = updated.list as JsonObject[];
    (list[1].nested as JsonValue[]).push(2);

    expect(list[0]).toEqual({ nested: [1] });
    expect(list[1]).toEqual({ nested: [1, 2] });
    expect(list[0]).not.toBe(list[1]);
    expect(source).toEqual({ list: [{ nested: [1] }] });
  });

  it("moves items and keeps boundary moves unchanged", () => {
    const source: JsonObject = { list: ["a", "b", "c"] };

    expect(moveArrayItem(source, ["list", 1], -1)).toEqual({ list: ["b", "a", "c"] });
    expect(moveArrayItem(source, ["list", 1], 1)).toEqual({ list: ["a", "c", "b"] });

    const firstUp = moveArrayItem(source, ["list", 0], -1);
    const lastDown = moveArrayItem(source, ["list", 2], 1);
    expect(firstUp).toEqual(source);
    expect(lastDown).toEqual(source);
    expect(firstUp).not.toBe(source);
    expect(lastDown).not.toBe(source);
  });
});

describe("config tree JSON types and validation", () => {
  it("provides defaults and detects all six JSON types", () => {
    const cases: Array<[JsonType, JsonValue]> = [
      ["string", ""],
      ["number", 0],
      ["boolean", false],
      ["null", null],
      ["object", {}],
      ["array", []],
    ];

    for (const [type, value] of cases) {
      expect(defaultValueForType(type)).toEqual(value);
      expect(jsonTypeOf(value)).toBe(type);
    }
  });

  it("accepts the three required config files with legal JSON and special keys", () => {
    const value: unknown = {
      mainConfig: { "a.b": [{ "a[0]": { "中文 字段": null } }] },
      newTouchConfig: [],
      newTextRuleConfig: "enabled",
    };

    expect(() => validateConfigData(value)).not.toThrow();
  });

  it("requires an object root and all three config files", () => {
    expect(() => validateConfigData([])).toThrow(/config_data.*\$/);
    expect(() => validateConfigData({ mainConfig: {}, newTouchConfig: {} })).toThrow(
      /newTextRuleConfig.*\$/,
    );
  });

  it("accepts a null-prototype root but rejects custom root prototypes", () => {
    const nullPrototypeRoot = Object.assign(Object.create(null), {
      mainConfig: {},
      newTouchConfig: {},
      newTextRuleConfig: {},
    });
    const customPrototypeRoot = Object.assign(Object.create({ inherited: true }), {
      mainConfig: {},
      newTouchConfig: {},
      newTextRuleConfig: {},
    });

    expect(() => validateConfigData(nullPrototypeRoot)).not.toThrow();
    expect(() => validateConfigData(customPrototypeRoot)).toThrow(/config_data.*\$/);
  });

  it.each([
    ["undefined", undefined],
    ["function", () => true],
    ["symbol", Symbol("invalid")],
    ["non-finite number", Number.NEGATIVE_INFINITY],
    ["custom-prototype object", Object.create({ inherited: true })],
  ])("rejects an extra root field containing %s", (_description, extra) => {
    const value = {
      mainConfig: {},
      newTouchConfig: {},
      newTextRuleConfig: {},
      extra,
    };

    expect(() => validateConfigData(value)).toThrow(/config_data.*\$\["extra"\]/);
  });

  it("rejects an empty root key at its exact path", () => {
    const value = {
      mainConfig: {},
      newTouchConfig: {},
      newTextRuleConfig: {},
      "": true,
    };

    expect(() => validateConfigData(value)).toThrow(/config_data.*\$\[""\].*字段名不能为空/);
  });

  it("rejects sparse arrays at the missing index", () => {
    const sparse = new Array(2);
    sparse[1] = "present";
    const value = {
      mainConfig: { sparse },
      newTouchConfig: {},
      newTextRuleConfig: {},
    };

    expect(() => validateConfigData(value)).toThrow(/mainConfig.*\$\["sparse"\]\[0\]/);
  });

  it("rejects non-JSON values and empty object keys with file and tree paths", () => {
    const invalidValue = {
      mainConfig: { nested: [undefined] },
      newTouchConfig: {},
      newTextRuleConfig: {},
    };
    const emptyKey = {
      mainConfig: { "": true },
      newTouchConfig: {},
      newTextRuleConfig: {},
    };

    expect(() => validateConfigData(invalidValue)).toThrow(/mainConfig.*\$\["nested"\]\[0\]/);
    expect(() => validateConfigData(emptyKey)).toThrow(/mainConfig.*\$\[""\]/);
  });

  it("rejects non-finite numbers with the config file and exact special-key path", () => {
    const value = {
      mainConfig: { "a.b": [{ "a[0]": Number.POSITIVE_INFINITY }] },
      newTouchConfig: {},
      newTextRuleConfig: {},
    };

    expect(() => validateConfigData(value)).toThrow(/mainConfig.*\$\["a\.b"\]\[0\]\["a\[0\]"\]/);
  });
});
