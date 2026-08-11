type ConfigState = {
  id?: number;
  status?: string;
  version?: string;
  updated_at?: string | null;
};

export function isRequestTimeout(error: unknown): boolean {
  const candidate = error as { code?: string; message?: string };
  return candidate?.code === "ECONNABORTED" || /timeout of \d+ms exceeded/i.test(candidate?.message || "");
}

export function isSaveConfirmed(before: ConfigState, after: ConfigState): boolean {
  return before.id === after.id && Boolean(after.updated_at) && before.updated_at !== after.updated_at;
}

export function isPublishConfirmed(before: ConfigState, after: ConfigState): boolean {
  return before.id === after.id && after.status === "published" && before.version !== after.version;
}
