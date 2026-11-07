/** 新手界面默认隐藏的侧栏页面。
 *
 * 与 backend `app.services.preferences.BEGINNER_NAV_HIDDEN` 保持一致。
 * 保留今日 / 看板 / 自选 / 策略 / 个股分析 / 数据，降低把研究页误当成交易终端的概率。
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
