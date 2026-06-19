<script setup lang="ts">
import { computed } from 'vue'
import XmCard from '@/components/ui/XmCard.vue'
import XmSparkline from '@/components/ui/XmSparkline.vue'
import XmStatusDot from '@/components/ui/XmStatusDot.vue'

interface Props {
  nav: number
  dailyPnl: number
  dailyPnlPct: number
  drawdown: number
  sharpeRatio: number
  navHistory: number[]
}

const props = defineProps<Props>()

const kpiCards = computed(() => [
  {
    label: 'Net Asset Value',
    value: `$${(props.nav || 0).toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`,
    change: props.dailyPnlPct,
    changeText: `${props.dailyPnlPct >= 0 ? '+' : ''}${(props.dailyPnlPct * 100).toFixed(2)}%`,
    isPositive: props.dailyPnlPct >= 0,
    sparkColor: props.dailyPnlPct >= 0 ? '#16A34A' : '#DC2626',
  },
  {
    label: 'Daily P&L',
    value: `$${(props.dailyPnl || 0).toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`,
    change: props.dailyPnl,
    changeText: `${props.dailyPnl >= 0 ? '+' : ''}$${Math.abs(props.dailyPnl).toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`,
    isPositive: props.dailyPnl >= 0,
    sparkColor: props.dailyPnl >= 0 ? '#16A34A' : '#DC2626',
  },
  {
    label: 'Max Drawdown',
    value: `${((props.drawdown || 0) * 100).toFixed(2)}%`,
    change: -props.drawdown,
    changeText: `${((props.drawdown || 0) * 100).toFixed(2)}%`,
    isPositive: false,
    sparkColor: '#EAB308',
    isRisk: true,
  },
  {
    label: 'Sharpe Ratio',
    value: (props.sharpeRatio || 0).toFixed(2),
    change: props.sharpeRatio,
    changeText: (props.sharpeRatio || 0).toFixed(2),
    isPositive: (props.sharpeRatio || 0) >= 1,
    sparkColor: (props.sharpeRatio || 0) >= 1 ? '#16A34A' : '#999999',
  },
])

const sparkData = computed(() => props.navHistory.length > 0 ? props.navHistory : [100, 102, 101, 103, 105])

function fmtCurrency(v: number): string {
  const abs = Math.abs(v)
  if (abs >= 1e6) return `${(v / 1e6).toFixed(2)}M`
  if (abs >= 1e3) return `${(v / 1e3).toFixed(0)}K`
  return v.toFixed(2)
}
</script>

<template>
  <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
    <XmCard
      v-for="card in kpiCards"
      :key="card.label"
      class="!p-4"
    >
      <div class="flex items-start justify-between mb-2">
        <span class="xm-metric-label">{{ card.label }}</span>
        <XmStatusDot
          :status="card.isPositive ? 'green' : 'red'"
          :pulsing="card.label === 'Daily P&L'"
        />
      </div>
      <div class="xm-metric-value text-lg mb-1">{{ card.value }}</div>
      <div class="flex items-end justify-between">
        <span
          class="xm-metric-change"
          :class="card.isPositive ? 'xm-pnl-positive' : card.isRisk ? 'text-risk-yellow' : 'xm-pnl-negative'"
        >
          {{ card.changeText }}
        </span>
      </div>
      <!-- Mini sparkline -->
      <div class="mt-3 -mx-1">
        <XmSparkline
          :data="sparkData"
          :color="card.sparkColor"
          :height="36"
          :show-area="true"
        />
      </div>
    </XmCard>
  </div>
</template>
