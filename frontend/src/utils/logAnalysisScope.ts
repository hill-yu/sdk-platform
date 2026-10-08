import { defaultRecentThreeDays } from "@/utils/logDateRange";

export interface AnalysisScopeDraft {
  package_name: string;
  date_from: string;
  hour_from: number;
  date_to: string;
  hour_to: number;
}

export function defaultAnalysisScope(now = new Date()): AnalysisScopeDraft {
  return { package_name: "", ...defaultRecentThreeDays(now) };
}

function calendarDay(value: string): number {
  const [year, month, day] = value.split("-").map(Number);
  return Date.UTC(year, month - 1, day);
}

export function validateAnalysisScope(scope: AnalysisScopeDraft): string | null {
  if (!scope.package_name.trim()) return "包名为必填条件。";
  if (!scope.date_from || !scope.date_to || calendarDay(scope.date_to) < calendarDay(scope.date_from)) {
    return "结束日期不能早于开始日期。";
  }
  if (calendarDay(scope.date_to) - calendarDay(scope.date_from) > 6 * 24 * 60 * 60 * 1000) {
    return "时间范围不能超过 7 天（北京时间日历日）。";
  }
  if (scope.hour_from < 0 || scope.hour_from > 23 || scope.hour_to < 0 || scope.hour_to > 23) {
    return "小时必须在 0 到 23 之间。";
  }
  if (scope.date_from === scope.date_to && scope.hour_to < scope.hour_from) {
    return "结束小时不能早于开始小时。";
  }
  return null;
}
