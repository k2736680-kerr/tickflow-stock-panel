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
        title="今日名单"
        subtitle={data?.as_of ? `${data.as_of} 收盘` : '等待收盘数据'}
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
  const pick = data.verdict === 'open' ? data.picks[0] : undefined
  const gap = ((data.open_gap_skip ?? 0.015) * 100).toFixed(1)
  const take = ((data.take_profit ?? 0.05) * 100).toFixed(0)
  const title = closed ? '先去同步数据' : pick ? '明天开盘买' : '今天空仓'
  const reason = closed
    ? '日 K 还没准备好，名单出不来。'
    : pick
      ? `只买这一只。开盘涨超 ${gap}% 就放弃。`
      : data.pick_mode === 'e1_skip_regime'
        ? '沪深300 不在弱势或恐慌。这天不做。'
        : '没有回撤落在 30% 到 50%、成交额靠后、还在放量的主板票。'
  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-5">
      <section
        className={cn(
          'rounded-card border px-6 py-6',
          closed && 'border-warning/40 bg-warning/[0.06]',
          pick && 'border-accent/40 bg-accent/[0.06]',
          !closed && !pick && 'border-border bg-elevated/40',
        )}
      >
        <div className="flex items-center gap-3">
          {closed ? (
            <ShieldOff className="h-8 w-8 shrink-0 text-warning" />
          ) : pick ? (
            <Sparkles className="h-8 w-8 shrink-0 text-accent" />
          ) : (
            <AlertTriangle className="h-8 w-8 shrink-0 text-muted" />
          )}
          <h2 className="text-3xl font-semibold tracking-tight text-foreground">{title}</h2>
        </div>
        <p className="mt-3 text-base leading-relaxed text-secondary">{reason}</p>
      </section>

      {pick && (
        <PickCard
          row={pick}
          onPreview={() => onPreview({ symbol: pick.symbol, name: pick.name })}
          onAdd={() => onAdd(pick.symbol)}
          adding={adding}
        />
      )}

      <section className="grid gap-3 sm:grid-cols-3">
        <Step n="1" title="怎么买" text={pick ? `下一交易日开盘买。涨超 ${gap}% 不买。` : '今天不买。'} />
        <Step n="2" title="当天" text="买入当天卖不掉。" />
        <Step n="3" title="怎么卖" text={`下一天起，碰到买入价 +${take}% 就卖。最晚第 ${data.hold_trading_days} 个可卖日收盘卖。`} />
      </section>

      <section className="grid gap-2 sm:grid-cols-2">
        {data.gates.map(gate => (
          <div key={gate.id} className="rounded-card border border-border px-3 py-3">
            <div className="flex items-center gap-2 text-sm font-medium text-foreground">
              {gate.ok ? (
                <CheckCircle2 className="h-4 w-4 shrink-0 text-bull" />
              ) : (
                <XCircle className="h-4 w-4 shrink-0 text-bear" />
              )}
              {gate.label}
            </div>
            <p className="mt-1 pl-6 text-sm leading-relaxed text-secondary">{gate.detail}</p>
          </div>
        ))}
      </section>

      {data.live_review && <LiveReviewCard review={data.live_review} />}

      <details className="rounded-card border border-border px-4 py-3">
        <summary className="cursor-pointer text-sm font-medium text-foreground">这套规则怎么来的</summary>
        <div className="mt-3 space-y-3 text-sm leading-relaxed text-secondary">
          <p>{data.honesty.why_not_next_day}</p>
          <p>{data.honesty.headline} {data.honesty.historical_note}</p>
          <p>{data.honesty.live_note}</p>
          {data.honesty.evidence?.replay && (
            <p className="text-muted">
              {data.honesty.evidence.replay.sample_start}～{data.honesty.evidence.replay.sample_end}
              ，买进 {data.honesty.evidence.replay.bought} 笔。当天收盘高于开盘 {(data.honesty.evidence.replay.same_day_close_up * 100).toFixed(0)}%。
              可卖日 20 天内摸到 +5% 的占 {(data.honesty.evidence.replay.sellable_plus_5pct_20d * 100).toFixed(0)}%。后半段更低，不是下一笔的保证。
            </p>
          )}
          <p className="text-muted">{data.overlays.note}</p>
          <Link to="/data" className="inline-block text-accent hover:underline">数据不够？去「数据」页同步日 K</Link>
        </div>
      </details>
    </div>
  )
}

function Step({ n, title, text }: { n: string; title: string; text: string }) {
  return (
    <div className="rounded-card border border-border bg-elevated/20 px-4 py-3">
      <div className="text-xs text-muted">{n}</div>
      <div className="mt-1 text-sm font-semibold text-foreground">{title}</div>
      <p className="mt-1 text-sm leading-relaxed text-secondary">{text}</p>
    </div>
  )
}

function LiveReviewCard({ review }: { review: BeginnerLiveReview }) {
  const sessions = review.sessions.filter(s => (s.picks && s.picks.length > 0) || s.pick_mode === 'e1_skip_regime').slice(0, 5)
  const bought = review.stats.rose_after_buy_n ?? 0
  const rose = review.stats.rose_after_buy_win ?? 0
  return (
    <section className="rounded-card border border-border px-4 py-4">
      <h3 className="text-sm font-semibold text-foreground">最近账本</h3>
      <p className="mt-1 text-sm text-secondary">
        {bought > 0
          ? `已买 ${bought} 只，当天收盘高于开盘 ${rose} 只。`
          : '名单先记下来。下一交易日收盘后，才知道买后有没有收红、后来有没有摸到 +5%。'}
      </p>
      {sessions.length > 0 && (
        <ul className="mt-3 divide-y divide-border">
          {sessions.map(session => (
            <li key={session.as_of} className="py-2 text-sm">
              <div className="flex flex-wrap gap-x-3">
                <span className="font-medium text-foreground">{session.as_of}</span>
                {session.pick_mode === 'e1_skip_regime' ? (
                  <span className="text-secondary">空仓</span>
                ) : (
                  <span className="text-muted">{session.buy_date ? `次日 ${session.buy_date}` : '等收盘'}</span>
                )}
              </div>
              {session.picks.length > 0 && (
                <div className="mt-1 text-secondary">
                  {session.picks.map(pick => (
                    <span key={pick.symbol} className="mr-3 inline-flex items-baseline gap-1">
                      <span className="text-foreground">{pick.name}</span>
                      {pick.skipped_gap ? (
                        <span className="text-warning">高开不买</span>
                      ) : pick.rose_after_buy == null ? (
                        <span className="text-muted">待收盘</span>
                      ) : (
                        <span className={pick.rose_after_buy ? 'text-bull' : 'text-bear'}>
                          {pick.rose_after_buy ? '收红' : '收绿'} {fmtPct(pick.next_close_vs_buy)}
                        </span>
                      )}
                      {pick.tp_hit === true && <span className="text-bull">+5%</span>}
                    </span>
                  ))}
                </div>
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
    <article className="rounded-card border border-border bg-elevated/20 px-6 py-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <button type="button" onClick={onPreview} className="min-w-0 text-left">
          <div className="text-3xl font-semibold text-foreground">{row.name}</div>
          <div className="mt-1 font-mono text-sm text-muted">{row.symbol}</div>
          <div className="mt-3 flex flex-wrap gap-x-4 text-base">
            <span className="font-mono text-foreground">昨收 {fmtPrice(row.close)}</span>
            <span className={cn('font-mono', priceColorClass(row.change_pct))}>{fmtPct(row.change_pct)}</span>
            {row.vol_ratio_5d != null && <span className="text-secondary">量比 {row.vol_ratio_5d.toFixed(2)}</span>}
          </div>
        </button>
        <button
          type="button"
          onClick={onAdd}
          disabled={adding}
          className="inline-flex items-center gap-1.5 rounded-btn border border-border px-3 py-2 text-sm text-secondary hover:bg-elevated hover:text-foreground disabled:opacity-50"
        >
          <Star className="h-4 w-4" />
          加入自选
        </button>
      </div>
    </article>
  )
}
