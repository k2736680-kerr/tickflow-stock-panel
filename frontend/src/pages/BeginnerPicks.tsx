import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertTriangle,
  CheckCircle2,
  Loader2,
  RefreshCw,
  ShieldOff,
  Sparkles,
  Star,
  XCircle,
} from 'lucide-react'
import {
  api,
  type BeginnerLiveReview,
  type BeginnerPick,
  type BeginnerPicksResponse,
} from '@/lib/api'
import { QK } from '@/lib/queryKeys'
import { fmtPct, fmtPrice, priceColorClass } from '@/lib/format'
import { PageHeader } from '@/components/PageHeader'
import { StockPreviewDialog } from '@/components/StockPreviewDialog'
import { toast } from '@/components/Toast'
import { cn } from '@/lib/cn'

export function BeginnerPicks() {
  const qc = useQueryClient()
  const query = useQuery({
    queryKey: QK.beginnerPicks,
    queryFn: api.beginnerPicks,
    staleTime: 30_000,
  })
  const [preview, setPreview] = useState<{ symbol: string; name: string } | null>(null)

  const addOne = useMutation({
    mutationFn: (symbol: string) => api.watchlistAdd(symbol),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: QK.watchlist })
      toast('已加入自选', 'success')
    },
  })

  const data = query.data
  return (
    <div className="flex h-full min-h-0 flex-col">
      <PageHeader
        title="今日"
        subtitle={data?.signal_note || (data?.as_of ? `数据截止 ${data.as_of}` : '每天给名单，第 5 个交易日复盘')}
        right={
          <button
            type="button"
            onClick={() => query.refetch()}
            className="inline-flex items-center gap-1.5 rounded-btn border border-border px-2.5 py-1 text-xs text-secondary hover:bg-elevated hover:text-foreground"
          >
            <RefreshCw className={cn('h-3.5 w-3.5', query.isFetching && 'animate-spin')} />
            刷新
          </button>
        }
      />

      <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
        {query.isLoading && (
          <div className="grid h-48 place-items-center text-muted">
            <Loader2 className="h-6 w-6 animate-spin" />
          </div>
        )}
        {query.isError && (
          <div className="rounded-card border border-bear/30 bg-bear/5 px-4 py-3 text-sm text-bear">
            候选计算失败。请先到「数据」页确认日 K 已同步。
          </div>
        )}
        {data && <PicksBody data={data} onPreview={setPreview} onAdd={s => addOne.mutate(s)} adding={addOne.isPending} />}
      </div>

      <StockPreviewDialog
        symbol={preview?.symbol ?? null}
        name={preview?.name}
        onClose={() => setPreview(null)}
      />
    </div>
  )
}

function PicksBody({
  data,
  onPreview,
  onAdd,
  adding,
}: {
  data: BeginnerPicksResponse
  onPreview: (row: { symbol: string; name: string }) => void
  onAdd: (symbol: string) => void
  adding: boolean
}) {
  const closed = data.verdict === 'closed'
  const open = data.verdict === 'open'
  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-4">
      <section
        className={cn(
          'rounded-card border px-5 py-4',
          closed && 'border-warning/40 bg-warning/[0.06]',
          open && 'border-accent/30 bg-accent/[0.06]',
          data.verdict === 'no_candidates' && 'border-border bg-elevated/40',
        )}
      >
        <div className="flex items-start gap-3">
          {closed ? (
            <ShieldOff className="mt-0.5 h-7 w-7 shrink-0 text-warning" />
          ) : open ? (
            <Sparkles className="mt-0.5 h-7 w-7 shrink-0 text-accent" />
          ) : (
            <AlertTriangle className="mt-0.5 h-7 w-7 shrink-0 text-muted" />
          )}
          <div className="min-w-0">
            <h2 className="text-2xl font-semibold tracking-tight text-foreground">{data.headline}</h2>
            <p className="mt-1 text-sm leading-relaxed text-secondary">
              {closed
                ? '日 K 还没准备好，先去「数据」页同步。'
                : open
                  ? `下面 ${data.picks.length} 只是深跌抄底。下一交易日开盘买；开盘涨超 ${((data.open_gap_skip ?? 0.015) * 100).toFixed(1)}% 不追。盘中碰到 +${(((data.take_profit ?? 0.05) * 100).toFixed(0))}% 就卖，否则最多拿 ${data.hold_trading_days} 日。`
                  : data.pick_mode === 'e1_skip_regime'
                    ? '沪深300现在不弱。这套规则只在弱势或恐慌做。今日空仓。'
                    : '今天没有落入规则的票，名单空了。'}
            </p>
          </div>
        </div>
      </section>

      <section className="grid gap-2 sm:grid-cols-3">
        {data.gates.map(gate => (
          <div key={gate.id} className="rounded-card border border-border bg-elevated/30 px-3 py-2.5">
            <div className="flex items-center gap-1.5 text-xs font-medium text-foreground">
              {gate.ok ? (
                <CheckCircle2 className="h-3.5 w-3.5 text-bull" />
              ) : (
                <XCircle className="h-3.5 w-3.5 text-bear" />
              )}
              {gate.label}
              {!gate.hard && <span className="text-[10px] text-muted">参考</span>}
            </div>
            <p className="mt-1 text-[11px] leading-relaxed text-secondary">{gate.detail}</p>
          </div>
        ))}
      </section>

      {open && data.picks.length > 0 && (
        <section className="flex flex-col gap-2">
          {data.picks.map(row => (
            <PickCard
              key={row.symbol}
              row={row}
              onPreview={() => onPreview({ symbol: row.symbol, name: row.name })}
              onAdd={() => onAdd(row.symbol)}
              adding={adding}
            />
          ))}
        </section>
      )}

      {data.live_review && <LiveReviewCard review={data.live_review} />}

      <section className="rounded-card border border-warning/30 bg-warning/[0.04] px-4 py-3">
        <h3 className="text-xs font-semibold text-foreground">这套规则怎么来的</h3>
        <p className="mt-1.5 text-[12px] leading-relaxed text-secondary">{data.honesty.why_not_next_day}</p>
        {data.honesty.evidence && (
          <p className="mt-1.5 text-[11px] leading-relaxed text-muted">
            回放记录区间 {data.honesty.evidence.sample_start}～{data.honesty.evidence.sample_end}。
            数字在 {data.honesty.evidence.path}，实盘以本页账本为准。
          </p>
        )}
      </section>

      <section className="rounded-card border border-border px-4 py-3">
        <h3 className="text-xs font-semibold text-foreground">已经拆过的上涨原因</h3>
        <p className="mt-1 text-[11px] text-muted">
          看涨过的票倒推原因，会把「已经涨完」当成「明天还会涨」。下面是你们自己数据里测过的结果。
        </p>
        <ul className="mt-2 space-y-2">
          {data.honesty.rise_causes.map(item => (
            <li key={item.cause} className="text-[12px] leading-relaxed">
              <div className="flex items-start gap-1.5">
                <span className={item.use === 'keep' ? 'text-bull' : 'text-muted'}>
                  {item.use === 'keep' ? '用' : '不用'}
                </span>
                <span>
                  <span className="text-foreground">{item.cause}</span>
                  <span className="mt-0.5 block text-secondary">{item.result}</span>
                </span>
              </div>
            </li>
          ))}
        </ul>
      </section>

      <section className="rounded-card border border-border px-4 py-3">
        <h3 className="text-xs font-semibold text-foreground">{data.honesty.headline}</h3>
        <p className="mt-1.5 text-[12px] leading-relaxed text-secondary">{data.honesty.historical_note}</p>
        <p className="mt-1 text-[12px] leading-relaxed text-secondary">{data.honesty.live_note}</p>
        <ol className="mt-3 list-decimal space-y-1 pl-4 text-[12px] text-secondary">
          {data.how_to_use.map(item => (
            <li key={item}>{item}</li>
          ))}
        </ol>
        <p className="mt-3 text-[11px] text-muted">{data.overlays.note}</p>
        <Link to="/data" className="mt-2 inline-block text-[11px] text-accent hover:underline">
          数据不够？去「数据」页同步日 K
        </Link>
      </section>
    </div>
  )
}

function LiveReviewCard({ review }: { review: BeginnerLiveReview }) {
  const rate = review.stats.next_close_win_rate
  const sessions = review.sessions.filter(s => (s.picks && s.picks.length > 0) || s.pick_mode === 'e1_skip_regime').slice(0, 8)
  return (
    <section className="rounded-card border border-accent/30 bg-accent/[0.04] px-4 py-3">
      <h3 className="text-xs font-semibold text-foreground">实盘复盘账本（不改规则）</h3>
      <p className="mt-1.5 text-[12px] leading-relaxed text-secondary">
        {review.stats.picks_settled > 0
          ? `已对照 ${review.stats.picks_settled} 只：次日收盘上涨 ${review.stats.next_close_win} 只${rate == null ? '' : `，${(rate * 100).toFixed(0)}%`}。`
          : '名单会先记下来。下一交易日收盘数据到了，会自动对比涨跌。'}
        {review.stats.empty_days > 0 ? ` 空仓 ${review.stats.empty_days} 天。` : ''}
      </p>
      <p className="mt-1 text-[11px] text-muted">{review.stats.rule_change?.note ?? review.stats.note}</p>
      {sessions.length > 0 && (
        <ul className="mt-3 space-y-2">
          {sessions.map(session => (
            <li key={session.as_of} className="rounded-btn border border-border/70 bg-background/40 px-3 py-2">
              <div className="flex flex-wrap items-baseline gap-x-2 text-[12px]">
                <span className="font-medium text-foreground">{session.as_of} 推荐</span>
                {session.buy_date && <span className="text-muted">次日 {session.buy_date}</span>}
                {session.pick_mode === 'e1_skip_regime' ? (
                  <span className="text-secondary">空仓</span>
                ) : session.settled ? (
                  <span className="text-secondary">
                    次日收盘对 {(session.next_close_win ?? 0)}/{session.next_close_n ?? 0}
                  </span>
                ) : (
                  <span className="text-muted">等下一交易日收盘</span>
                )}
              </div>
              {session.picks.length > 0 && (
                <ul className="mt-1.5 space-y-0.5 text-[12px]">
                  {session.picks.map(pick => (
                    <li key={pick.symbol} className="flex flex-wrap items-baseline gap-x-2">
                      <span className="text-foreground">{pick.name}</span>
                      <span className="font-mono text-muted">{fmtPrice(pick.signal_close)}</span>
                      {pick.correct_next_close == null ? (
                        <span className="text-muted">待收盘</span>
                      ) : (
                        <>
                          <span className={cn('font-mono', priceColorClass(pick.next_close_vs_signal))}>
                            {fmtPct(pick.next_close_vs_signal)}
                          </span>
                          <span className={pick.correct_next_close ? 'text-bull' : 'text-bear'}>
                            {pick.correct_next_close ? '对' : '错'}
                          </span>
                        </>
                      )}
                      {pick.skipped_gap && <span className="text-warning">开盘涨超不追</span>}
                    </li>
                  ))}
                </ul>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

function PickCard({
  row,
  onPreview,
  onAdd,
  adding,
}: {
  row: BeginnerPick
  onPreview: () => void
  onAdd: () => void
  adding: boolean
}) {
  return (
    <article className="rounded-card border border-border bg-elevated/20 px-4 py-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <button type="button" onClick={onPreview} className="min-w-0 text-left">
          <div className="flex items-baseline gap-2">
            <span className="text-sm font-semibold text-foreground">{row.name}</span>
            <span className="font-mono text-[11px] text-muted">{row.symbol}</span>
          </div>
          <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-[12px]">
            <span className="font-mono text-foreground">昨收 {fmtPrice(row.close)}</span>
            <span className={cn('font-mono', priceColorClass(row.change_pct))}>{fmtPct(row.change_pct)}</span>
            <span className="text-secondary">20日 {fmtPct(row.momentum_20d)}</span>
            {row.vol_ratio_5d != null && <span className="text-secondary">量比 {row.vol_ratio_5d.toFixed(2)}</span>}
            {row.mktcap_yi != null && <span className="text-secondary">{row.mktcap_yi.toFixed(0)} 亿</span>}
          </div>
        </button>
        <button
          type="button"
          onClick={onAdd}
          disabled={adding}
          className="inline-flex items-center gap-1 rounded-btn border border-border px-2 py-1 text-[11px] text-secondary hover:bg-elevated hover:text-foreground disabled:opacity-50"
        >
          <Star className="h-3 w-3" />
          加入自选
        </button>
      </div>
      <ul className="mt-2 space-y-0.5 text-[12px] text-secondary">
        {row.reasons.map(reason => (
          <li key={reason}>· {reason}</li>
        ))}
      </ul>
    </article>
  )
}
