export type ValueType = "string" | "number" | "boolean" | "null" | "object" | "array";
export interface ConfigRow { path: string; type: ValueType; value: string }

function valueType(value: unknown): ValueType {
  if (value === null) return "null";
  if (Array.isArray(value)) return "array";
  return typeof value as ValueType;
}

export function flattenConfig(value: unknown, prefix = ""): ConfigRow[] {
  if (Array.isArray(value)) {
    if (value.length === 0) return [{ path: prefix, type: "array", value: "[]" }];
    return value.flatMap((item, index) => flattenConfig(item, `${prefix}[${index}]`));
  }
  if (value && typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>);
    if (entries.length === 0) return [{ path: prefix, type: "object", value: "{}" }];
    return entries.flatMap(([key, item]) => {
      if (!/^[A-Za-z0-9_-]+$/.test(key)) {
        throw new Error(`字段名 ${key} 包含表格模式不支持的路径字符，请继续使用 JSON 模式`);
      }
      return flattenConfig(item, prefix ? `${prefix}.${key}` : key);
    });
  }
  return [{ path: prefix, type: valueType(value), value: value === null ? "" : String(value) }];
}

function parseValue(row: ConfigRow): unknown {
  if (row.type === "string") return row.value;
  if (row.type === "number") {
    const parsed = Number(row.value);
    if (!Number.isFinite(parsed)) throw new Error(`字段 ${row.path} 不是有效数字`);
    return parsed;
  }
  if (row.type === "boolean") {
    if (row.value !== "true" && row.value !== "false") throw new Error(`字段 ${row.path} 不是有效布尔值`);
    return row.value === "true";
  }
  if (row.type === "null") return null;
  return JSON.parse(row.value || (row.type === "array" ? "[]" : "{}"));
}

function tokens(path: string): Array<string | number> {
  if (!/^[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+|\[\d+\])*$/.test(path)) throw new Error(`字段路径无效: ${path}`);
  return Array.from(path.matchAll(/([^.\[\]]+)|\[(\d+)\]/g), (match) => match[1] ?? Number(match[2]));
}

export function rowsToConfig(rows: ConfigRow[]): Record<string, unknown> {
  const root: Record<string, unknown> = {};
  const seen = new Set<string>();
  for (const row of rows) {
    if (seen.has(row.path)) throw new Error(`字段路径重复: ${row.path}`);
    if ([...seen].some((p) => p.startsWith(`${row.path}.`) || p.startsWith(`${row.path}[`) || row.path.startsWith(`${p}.`) || row.path.startsWith(`${p}[`))) {
      throw new Error(`字段路径存在父子冲突: ${row.path}`);
    }
    seen.add(row.path);
    const parts = tokens(row.path);
    let current: any = root;
    parts.forEach((part, index) => {
      const last = index === parts.length - 1;
      if (last) { current[part] = parseValue(row); return; }
      const nextIsArray = typeof parts[index + 1] === "number";
      if (current[part] === undefined) current[part] = nextIsArray ? [] : {};
      current = current[part];
    });
  }
  return root;
}
