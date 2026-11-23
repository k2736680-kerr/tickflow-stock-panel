/** 新手界面默认隐藏的侧栏页面。
 *
 * 与 backend `app.services.preferences.BEGINNER_NAV_HIDDEN` 保持一致。
 * 保留今日(/) / 看板(/market) / 自选 / 策略 / 个股分析 / 数据。首页是今日名单，不是市场看板。
 */
export const BEGINNER_NAV_HIDDEN: readonly string[] = [
  '/backtest',
  '/mining',
  '/limit-ladder',
  '/concept-analysis',
  '/industry-analysis',
  '/regime',
  '/abnormal',
  '/review',
  '/financials',
  '/indices',
  '/monitor',
]

export function isBeginnerNav(hidden: string[] | undefined | null): boolean {
  const set = new Set(hidden ?? [])
  return BEGINNER_NAV_HIDDEN.every((id) => set.has(id))
}
