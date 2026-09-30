export interface RecentThreeDayRange {
  date_from: string;
  hour_from: number;
  date_to: string;
  hour_to: number;
}

function beijingDateParts(now: Date): { year: number; month: number; day: number } {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(now);
  return {
    year: Number(parts.find((part) => part.type === "year")?.value),
    month: Number(parts.find((part) => part.type === "month")?.value),
    day: Number(parts.find((part) => part.type === "day")?.value),
  };
}

function formatCalendarDate(date: Date): string {
  const year = date.getUTCFullYear();
  const month = String(date.getUTCMonth() + 1).padStart(2, "0");
  const day = String(date.getUTCDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

export function defaultRecentThreeDays(now = new Date()): RecentThreeDayRange {
  const current = beijingDateParts(now);
  const today = new Date(Date.UTC(current.year, current.month - 1, current.day));
  const start = new Date(today);
  start.setUTCDate(start.getUTCDate() - 2);
  return { date_from: formatCalendarDate(start), hour_from: 0, date_to: formatCalendarDate(today), hour_to: 23 };
}
