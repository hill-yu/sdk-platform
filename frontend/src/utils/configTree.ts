export type JsonScalar = string | number | boolean | null;
export type JsonValue = JsonScalar | JsonObject | JsonValue[];
export interface JsonObject { [key: string]: JsonValue }
export type TreePath = Array<string | number>;
export type JsonType = "string" | "number" | "boolean" | "null" | "object" | "array";

const REQUIRED_CONFIG_FILES = ["mainConfig", "newTouchConfig", "newTextRuleConfig"] as const;

function isJsonObject(value: JsonValue): value is JsonObject {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function hasOwn(object: object, key: PropertyKey): boolean {
  return Object.prototype.hasOwnProperty.call(object, key);
}

function formatPath(path: TreePath): string {
  return path.reduce<string>(
    (result, segment) => `${result}[${typeof segment === "number" ? segment : JSON.stringify(segment)}]`,
    "$",
  );
}

function invalidPath(path: TreePath): Error {
  return new Error(`树路径无效: ${formatPath(path)}`);
}

function assertArrayIndex(segment: string | number, array: JsonValue[], path: TreePath): number {
  if (!Number.isInteger(segment) || (segment as number) < 0 || (segment as number) >= array.length) {
    throw invalidPath(path);
  }
  return segment as number;
}

export function cloneJson(value: JsonValue): JsonValue {
  if (Array.isArray(value)) return value.map(cloneJson);
  if (isJsonObject(value)) {
    return Object.fromEntries(Object.entries(value).map(([key, child]) => [key, cloneJson(child)]));
  }
  return value;
}

export function getAtPath(root: JsonValue, path: TreePath): JsonValue {
  let current = root;
  const traversed: TreePath = [];

  for (const segment of path) {
    traversed.push(segment);
    if (Array.isArray(current)) {
      current = current[assertArrayIndex(segment, current, traversed)];
      continue;
    }
    if (isJsonObject(current) && typeof segment === "string" && hasOwn(current, segment)) {
      current = current[segment];
      continue;
    }
    throw invalidPath(traversed);
  }

  return current;
}

export function replaceAtPath(root: JsonValue, path: TreePath, value: JsonValue): JsonValue {
  return replaceAtPathFrom(root, path, value, []);
}

function replaceAtPathFrom(
  root: JsonValue,
  path: TreePath,
  value: JsonValue,
  traversed: TreePath,
): JsonValue {
  if (path.length === 0) return cloneJson(value);

  const [segment, ...rest] = path;
  const currentPath = [...traversed, segment];
  if (Array.isArray(root)) {
    const index = assertArrayIndex(segment, root, currentPath);
    const updated = root.slice();
    updated[index] = replaceAtPathFrom(root[index], rest, value, currentPath);
    return updated;
  }
  if (isJsonObject(root) && typeof segment === "string" && hasOwn(root, segment)) {
    return Object.fromEntries(
      Object.entries(root).map(([key, child]) => [
        key,
        key === segment ? replaceAtPathFrom(child, rest, value, currentPath) : child,
      ]),
    );
  }
  throw invalidPath(currentPath);
}

function updateAtPath(
  root: JsonValue,
  path: TreePath,
  update: (value: JsonValue) => JsonValue,
): JsonValue {
  const current = getAtPath(root, path);
  return replaceAtPath(root, path, update(current));
}

export function removeAtPath(root: JsonValue, path: TreePath): JsonValue {
  if (path.length === 0) throw invalidPath(path);

  const parentPath = path.slice(0, -1);
  const segment = path[path.length - 1];
  return updateAtPath(root, parentPath, (parent) => {
    if (Array.isArray(parent)) {
      const index = assertArrayIndex(segment, parent, path);
      const updated = parent.slice();
      updated.splice(index, 1);
      return updated;
    }
    if (isJsonObject(parent) && typeof segment === "string" && hasOwn(parent, segment)) {
      return Object.fromEntries(Object.entries(parent).filter(([key]) => key !== segment));
    }
    throw invalidPath(path);
  });
}

function assertFieldName(key: string): void {
  if (key.length === 0) throw new Error("字段名不能为空");
}

export function addObjectField(
  root: JsonValue,
  objectPath: TreePath,
  key: string,
  value: JsonValue,
): JsonValue {
  assertFieldName(key);
  return updateAtPath(root, objectPath, (target) => {
    if (!isJsonObject(target)) throw new Error(`路径 ${formatPath(objectPath)} 不是对象`);
    if (hasOwn(target, key)) throw new Error(`字段名已存在: ${key}`);
    return Object.fromEntries([...Object.entries(target), [key, cloneJson(value)]]);
  });
}

export function renameObjectField(
  root: JsonValue,
  fieldPath: TreePath,
  nextKey: string,
): JsonValue {
  assertFieldName(nextKey);
  if (fieldPath.length === 0 || typeof fieldPath[fieldPath.length - 1] !== "string") {
    throw invalidPath(fieldPath);
  }

  const parentPath = fieldPath.slice(0, -1);
  const currentKey = fieldPath[fieldPath.length - 1] as string;
  return updateAtPath(root, parentPath, (parent) => {
    if (!isJsonObject(parent) || !hasOwn(parent, currentKey)) throw invalidPath(fieldPath);
    if (nextKey !== currentKey && hasOwn(parent, nextKey)) {
      throw new Error(`字段名已存在: ${nextKey}`);
    }
    return Object.fromEntries(
      Object.entries(parent).map(([key, value]) => [key === currentKey ? nextKey : key, value]),
    );
  });
}

export function appendArrayItem(
  root: JsonValue,
  arrayPath: TreePath,
  value: JsonValue,
): JsonValue {
  return updateAtPath(root, arrayPath, (target) => {
    if (!Array.isArray(target)) throw new Error(`路径 ${formatPath(arrayPath)} 不是数组`);
    return [...target, cloneJson(value)];
  });
}

function arrayItemLocation(
  root: JsonValue,
  itemPath: TreePath,
): { arrayPath: TreePath; array: JsonValue[]; index: number } {
  if (itemPath.length === 0) throw invalidPath(itemPath);
  const arrayPath = itemPath.slice(0, -1);
  const segment = itemPath[itemPath.length - 1];
  const target = getAtPath(root, arrayPath);
  if (!Array.isArray(target)) throw new Error(`路径 ${formatPath(arrayPath)} 不是数组`);
  return { arrayPath, array: target, index: assertArrayIndex(segment, target, itemPath) };
}

export function duplicateArrayItem(root: JsonValue, itemPath: TreePath): JsonValue {
  const { arrayPath, array, index } = arrayItemLocation(root, itemPath);
  const updated = array.slice();
  updated.splice(index + 1, 0, cloneJson(array[index]));
  return replaceAtPath(root, arrayPath, updated);
}

export function moveArrayItem(
  root: JsonValue,
  itemPath: TreePath,
  direction: -1 | 1,
): JsonValue {
  const { arrayPath, array, index } = arrayItemLocation(root, itemPath);
  const destination = index + direction;
  if (destination < 0 || destination >= array.length) return cloneJson(root);

  const updated = array.slice();
  [updated[index], updated[destination]] = [updated[destination], updated[index]];
  return replaceAtPath(root, arrayPath, updated);
}

export function defaultValueForType(type: JsonType): JsonValue {
  const defaults: Record<JsonType, JsonValue> = {
    string: "",
    number: 0,
    boolean: false,
    null: null,
    object: {},
    array: [],
  };
  return defaults[type];
}

export function jsonTypeOf(value: JsonValue): JsonType {
  if (value === null) return "null";
  if (Array.isArray(value)) return "array";
  return typeof value as JsonType;
}

function validationError(configFile: string, path: TreePath, message: string): Error {
  return new Error(`配置文件 ${configFile} 在路径 ${formatPath(path)} ${message}`);
}

function validateJsonValue(value: unknown, configFile: string, path: TreePath): void {
  if (value === null || typeof value === "string" || typeof value === "boolean") return;
  if (typeof value === "number") {
    if (!Number.isFinite(value)) throw validationError(configFile, path, "必须是有限数字");
    return;
  }
  if (Array.isArray(value)) {
    for (let index = 0; index < value.length; index += 1) {
      const childPath = [...path, index];
      if (!(index in value)) throw validationError(configFile, childPath, "不能是稀疏数组空槽");
      validateJsonValue(value[index], configFile, childPath);
    }
    return;
  }
  if (typeof value === "object") {
    const prototype = Object.getPrototypeOf(value);
    if (prototype !== Object.prototype && prototype !== null) {
      throw validationError(configFile, path, "不是合法 JSON 值");
    }
    for (const [key, child] of Object.entries(value)) {
      const childPath = [...path, key];
      if (key.length === 0) throw validationError(configFile, childPath, "字段名不能为空");
      validateJsonValue(child, configFile, childPath);
    }
    return;
  }
  throw validationError(configFile, path, "不是合法 JSON 值");
}

export function validateConfigData(value: unknown): asserts value is JsonObject {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw validationError("config_data", [], "必须是对象");
  }
  const prototype = Object.getPrototypeOf(value);
  if (prototype !== Object.prototype && prototype !== null) {
    throw validationError("config_data", [], "不是普通对象");
  }

  for (const configFile of REQUIRED_CONFIG_FILES) {
    if (!hasOwn(value, configFile)) throw validationError(configFile, [], "缺失");
  }

  for (const [key, child] of Object.entries(value)) {
    if (key.length === 0) throw validationError("config_data", [key], "字段名不能为空");
    if ((REQUIRED_CONFIG_FILES as readonly string[]).includes(key)) {
      validateJsonValue(child, key, []);
    } else {
      validateJsonValue(child, "config_data", [key]);
    }
  }
}
