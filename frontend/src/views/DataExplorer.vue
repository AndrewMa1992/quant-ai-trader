<script setup lang="ts">
import { computed, ref } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { CandlestickChart, LineChart, BarChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, DataZoomComponent, LegendComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import XmCard from '@/components/ui/XmCard.vue'
import XmBadge from '@/components/ui/XmBadge.vue'
import { syncApi } from '@/api/syncApi'

use([CandlestickChart, LineChart, BarChart, GridComponent, TooltipComponent, DataZoomComponent, LegendComponent, CanvasRenderer])

const tickerInput = ref('AAPL')
const loading = ref(false)
const error = ref('')

const tickerInfo = ref<Record<string, unknown> | null>(null)
const quote = ref<Record<string, unknown> | null>(null)
const bars = ref<Array<Record<string, unknown>>>([])

async function searchTicker() {
  const ticker = tickerInput.value.trim().toUpperCase()
  if (!ticker) return

  loading.value = true
  error.value = ''
  tickerInfo.value = null
  quote.value = null
  bars.value = []

  try {
    const [infoRes, quoteRes, barsRes] = await Promise.allSettled([
      syncApi.getTickerInfo(ticker),
      syncApi.getQuote(ticker),
      syncApi.getBars(ticker),
    ])

    if (infoRes.status === 'fulfilled') {
      tickerInfo.value = (infoRes.value as Record<string, unknown>) ?? null
    }
    if (quoteRes.status === 'fulfilled') {
      quote.value = (quoteRes.value as Record<string, unknown>) ?? null
    }
    if (barsRes.status === 'fulfilled') {
      const payload = barsRes.value as Record<string, unknown> | unknown[]
      if (Array.isArray(payload)) {
        bars.value = payload as Array<Record<string, unknown>>
      } else if (payload && Array.isArray((payload as Record<string, unknown>).bars)) {
        bars.value = (payload as { bars: Array<Record<string, unknown>> }).bars
      } else if (payload && Array.isArray((payload as Record<string, unknown>).data)) {
        bars.value = (payload as { data: Array<Record<string, unknown>> }).data
      } else {
        bars.value = []
      }
    }

    if (!tickerInfo.value && !quote.value && bars.value.length === 0) {
      error.value = `No data found for ${ticker}. API may be offline.`
    }
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : 'Search failed'
  } finally {
    loading.value = false
  }
}

function fmtNum(v: unknown) {
  if (v === null || v === undefined) return '-'
  const n = Number(v)
  if (isNaN(n)) return String(v)
  return n.toLocaleString('en-US', { maximumFractionDigits: 2 })
}

const closeSeries = computed(() =>
  bars.value.map((b) => Number(b.close ?? b.adj_close ?? 0)),
)
const dateSeries = computed(() =>
  bars.value.map((b) => String(b.date ?? b.timestamp ?? '').slice(0, 10)),
)

const barsChartOption = computed(() => ({
  grid: { top: 16, right: 16, bottom: 40, left: 56 },
  tooltip: {
    trigger: 'axis' as const,
    backgroundColor: '#fff',
    borderColor: '#EEEEEE',
    textStyle: { color: '#1A1A1A', fontSize: 12 },
  },
  dataZoom: [{ type: 'inside' as const }, { type: 'slider' as const, height: 18 }],
  xAxis: {
    type: 'category' as const,
    data: dateSeries.value,
    axisLabel: { fontSize: 10, color: '#999999' },
  },
  yAxis: {
    type: 'value' as const,
    scale: true,
    splitLine: { lineStyle: { color: '#F5F5F5' } },
    axisLabel: { fontSize: 10, color: '#999999' },
  },
  series: [{
    type: 'line',
    name: 'Close',
    data: closeSeries.value,
    smooth: true,
    symbol: 'none',
    lineStyle: { color: '#FF6700', width: 2 },
    areaStyle: {
      color: {
        type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
        colorStops: [
          { offset: 0, color: '#FF670025' },
          { offset: 1, color: '#FF670005' },
        ],
      },
    },
  }],
}))

const infoFields = computed(() => {
  const info = tickerInfo.value ?? {}
  return [
    { label: 'Name', value: String(info.name ?? info.longName ?? '-') },
    { label: 'Sector', value: String(info.sector ?? '-') },
    { label: 'Industry', value: String(info.industry ?? '-') },
    { label: 'Market', value: String(info.market ?? info.exchange ?? '-') },
    { label: 'Currency', value: String(info.currency ?? '-') },
  ]
})

const quoteFields = computed(() => {
  const q = quote.value ?? {}
  return [
    { label: 'Last', value: fmtNum(q.last ?? q.price ?? q.close) },
    { label: 'Bid', value: fmtNum(q.bid) },
    { label: 'Ask', value: fmtNum(q.ask) },
    { label: 'Volume', value: fmtNum(q.volume) },
    { label: 'Change %', value: q.change_pct != null ? `${Number(q.change_pct).toFixed(2)}%` : fmtNum(q.changePercent) },
  ]
})
</script>

<template>
  <div class="space-y-6 xm-fade-in">
    <XmCard class="!p-4">
      <div class="flex flex-wrap items-end gap-3">
        <div class="flex-1 min-w-[160px] max-w-[280px]">
          <label class="block text-xxs text-xm-text-tertiary mb-1">Ticker</label>
          <input
            v-model="tickerInput"
            class="xm-input w-full"
            placeholder="e.g. AAPL"
            @keyup.enter="searchTicker"
          />
        </div>
        <button class="xm-btn-primary" :disabled="loading" @click="searchTicker">
          {{ loading ? 'Loading...' : 'Search' }}
        </button>
      </div>
    </XmCard>

    <div v-if="error" class="p-3 rounded-lg bg-loss-bg border border-loss/20 text-sm text-loss">
      {{ error }}
    </div>

    <div v-if="tickerInfo || quote" class="grid grid-cols-1 lg:grid-cols-2 gap-6">
      <XmCard title="Ticker Info">
        <div v-if="tickerInfo" class="space-y-3">
          <div class="flex items-center gap-2 mb-2">
            <span class="font-mono font-semibold text-base">{{ String(tickerInfo.ticker || tickerInput).toUpperCase() }}</span>
            <XmBadge variant="info">{{ String(tickerInfo.market || tickerInfo.exchange || 'US') }}</XmBadge>
          </div>
          <div
            v-for="field in infoFields"
            :key="field.label"
            class="flex justify-between py-2 border-b border-xm-border-light last:border-0"
          >
            <span class="text-sm text-xm-text-secondary">{{ field.label }}</span>
            <span class="text-sm font-mono">{{ field.value }}</span>
          </div>
        </div>
        <div v-else class="text-center py-8 text-xm-text-tertiary text-sm">No ticker info</div>
      </XmCard>

      <XmCard title="Quote">
        <div v-if="quote" class="space-y-3">
          <div
            v-for="field in quoteFields"
            :key="field.label"
            class="flex justify-between py-2 border-b border-xm-border-light last:border-0"
          >
            <span class="text-sm text-xm-text-secondary">{{ field.label }}</span>
            <span class="text-sm font-mono font-semibold">{{ field.value }}</span>
          </div>
        </div>
        <div v-else class="text-center py-8 text-xm-text-tertiary text-sm">No quote data</div>
      </XmCard>
    </div>

    <XmCard title="Price Bars" :subtitle="bars.length ? `${bars.length} bars` : 'Search a ticker to load OHLCV'">
      <div v-if="loading" class="flex items-center justify-center h-[320px] text-xm-text-tertiary text-sm">
        Loading bars...
      </div>
      <div
        v-else-if="bars.length === 0"
        class="flex items-center justify-center h-[320px] text-xm-text-tertiary text-sm"
      >
        No bar data. Search a ticker above.
      </div>
      <VChart v-else :option="barsChartOption" style="height: 320px" autoresize />
    </XmCard>
  </div>
</template>
