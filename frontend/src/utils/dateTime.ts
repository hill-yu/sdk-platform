const TIMEZONE_OFFSET_PATTERN = /(Z|[+-]\d{2}:\d{2})$/i;

export function formatBusinessTime(value?: string | null): string {
  if (!value || !TIMEZONE_OFFSET_PATTERN.test(value)) {
    return "-";
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "-";
  }

  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    hour12: false,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  })
    .format(date)
    .replace(/\//g, "-");
}
