<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { ScatterChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import XmCard from '@/components/ui/XmCard.vue'
import XmBadge from '@/components/ui/XmBadge.vue'
import { usePortfolioStore } from '@/stores/usePortfolioStore'

use([ScatterChart, GridComponent, TooltipComponent, LegendComponent, CanvasRenderer])

const portfolioStore = usePortfolioStore()

interface HoldingRow {
  ticker: string
  name: string
  shares: number
  price: number
  value: number
  weight: number
  dailyChange: number
  dailyChangePct: number
}

const holdings = ref<HoldingRow[]>([
  { ticker: 'AAPL', name: 'Apple Inc.', shares: 150, price: 195.20, value: 29280, weight: 0.15, dailyChange: 2.30, dailyChangePct: 1.19 },
  { ticker: 'MSFT', name: 'Microsoft Corp.', shares: 80, price: 420.45, value: 33636, weight: 0.17, dailyChange: -1.20, dailyChangePct: -0.28 },
  { ticker: 'NVDA', name: 'NVIDIA Corp.', shares: 30, price: 875.30, value: 26259, weight: 0.13, dailyChange: 12.40, dailyChangePct: 1.44 },
  { ticker: 'GOOGL', name: 'Alphabet Inc.', shares: 100, price: 175.80, value: 17580, weight: 0.09, dailyChange: -0.50, dailyChangePct: -0.28 },
  { ticker: 'TSLA', name: 'Tesla Inc.', shares: 60, price: 245.10, value: 14706, weight: 0.07, dailyChange: -3.20, dailyChangePct: -1.29 },
  { ticker: '0700.HK', name: 'Tencent', shares: 500, price: 38.50, value: 19250, weight: 0.10, dailyChange: 0.80, dailyChangePct: 2.12 },
])

const totalValue = computed(() => holdings.value.reduce((s, h) => s + h.value, 0))
const totalDailyPnL = computed(() => holdings.value.reduce((s, h) => s + h.dailyChange * h.shares, 0))

// Efficient Frontier
const frontierPoints = ref<Array<[number, number]>>([])
const currentPoint = ref<[number, number]>([0.15, 0.12])

function generateFrontier() {
  const pts: Array<[number, number]> = []
  for (let i = 0; i < 50; i++) {
    const risk = 0.08 + (i / 50) * 0.18
    const ret = 0.06 + risk * 0.5 - Math.pow(risk - 0.13, 2) * 2 + Math.random() * 0.01
    pts.push([parseFloat(risk.toFixed(4)), parseFloat(ret.toFixed(4))])
  }
  frontierPoints.value = pts
  currentPoint.value = [0.146, 0.121]
}
generateFrontier()

const frontierOption = computed(() => ({
  grid: { top: 16, right: 24, bottom: 8, left: 60 },
  tooltip: {
    trigger: 'item' as const,
    backgroundColor: '#fff',
    borderColor: '#EEEEEE',
    textStyle: { color: '#1A1A1A', fontSize: 12 },
    formatter: (p: any) => `Risk: ${(p.value[0] * 100).toFixed(2)}%<br/>Return: ${(p.value[1] * 100).toFixed(2)}%`,
  },
  xAxis: {
    type: 'value' as const,
    name: 'Risk (Volatility)',
    nameTextStyle: { fontSize: 10, color: '#999999' },
    axisLabel: { fontSize: 10, color: '#999999', formatter: (v: number) => `${(v * 100).toFixed(0)}%` },
    splitLine: { lineStyle: { color: '#F5F5F5' } },
  },
  yAxis: {
    type: 'value' as const,
    name: 'Return',
    nameTextStyle: { fontSize: 10, color: '#999999' },
    axisLabel: { fontSize: 10, color: '#999999', formatter: (v: number) => `${(v * 100).toFixed(0)}%` },
    splitLine: { lineStyle: { color: '#F5F5F5' } },
  },
  series: [
    {
      type: 'scatter',
      name: 'Portfolios',
      data: frontierPoints.value,
      symbolSize: 6,
      itemStyle: { color: '#E0E0E0' },
    },
    {
      type: 'scatter',
      name: 'Current',
      data: [{
        value: currentPoint.value,
        symbolSize: 16,
        itemStyle: { color: '#FF6700', borderColor: '#fff', borderWidth: 2 },
      }],
    },
  ],
}))
</script>

<template>
  <div class="space-y-6 xm-fade-in">
    <!-- Summary Row -->
    <div class="grid grid-cols-1 sm:grid-cols-3 gap-4">
      <XmCard class="!p-4">
        <div class="xm-metric-label">Total Value</div>
        <div class="xm-metric-value text-lg">${{ totalValue.toLocaleString() }}</div>
      </XmCard>
      <XmCard class="!p-4">
        <div class="xm-metric-label">Holdings</div>
        <div class="xm-metric-value text-lg">{{ holdings.length }}</div>
      </XmCard>
      <XmCard class="!p-4">
        <div class="xm-metric-label">Daily P&L</div>
        <div class="xm-metric-value text-lg" :class="totalDailyPnL >= 0 ? 'xm-pnl-positive' : 'xm-pnl-negative'">
          {{ totalDailyPnL >= 0 ? '+' : '' }}${{ totalDailyPnL.toLocaleString() }}
        </div>
      </XmCard>
    </div>

    <!-- Efficient Frontier -->
    <XmCard title="Efficient Frontier" subtitle="Risk vs Return optimization">
      <VChart :option="frontierOption" style="height: 380px" autoresize />
    </XmCard>

    <!-- Holdings Table -->
    <XmCard title="Holdings" subtitle="Color-coded: green = gain, red = loss">
      <table class="xm-table">
        <thead>
          <tr>
            <th>Ticker</th>
            <th>Name</th>
            <th class="text-right">Shares</th>
            <th class="text-right">Price</th>
            <th class="text-right">Value</th>
            <th class="text-right">Weight</th>
            <th class="text-right">Daily Δ</th>
            <th class="text-right">Δ %</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="h in holdings" :key="h.ticker">
            <td class="font-mono font-semibold">{{ h.ticker }}</td>
            <td class="text-xm-text-secondary text-xs">{{ h.name }}</td>
            <td class="text-right font-mono">{{ h.shares.toFixed(0) }}</td>
            <td class="text-right font-mono">${{ h.price.toFixed(2) }}</td>
            <td class="text-right font-mono font-semibold">${{ h.value.toLocaleString() }}</td>
            <td class="text-right font-mono">{{ (h.weight * 100).toFixed(1) }}%</td>
            <td class="text-right font-mono" :class="h.dailyChange >= 0 ? 'xm-pnl-positive' : 'xm-pnl-negative'">
              {{ h.dailyChange >= 0 ? '+' : '' }}${{ h.dailyChange.toFixed(2) }}
            </td>
            <td class="text-right font-mono">
              <span class="xm-badge" :class="h.dailyChangePct >= 0 ? 'xm-badge-success' : 'xm-badge-danger'">
                {{ h.dailyChangePct >= 0 ? '+' : '' }}{{ h.dailyChangePct.toFixed(2) }}%
              </span>
            </td>
          </tr>
        </tbody>
      </table>
    </XmCard>
  </div>
</template>
