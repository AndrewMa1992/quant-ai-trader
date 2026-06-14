<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { BarChart, HeatmapChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, VisualMapComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import XmCard from '@/components/ui/XmCard.vue'
import XmBadge from '@/components/ui/XmBadge.vue'
import { useFactorStore } from '@/stores/useFactorStore'

use([BarChart, HeatmapChart, GridComponent, TooltipComponent, VisualMapComponent, CanvasRenderer])

const factorStore = useFactorStore()

interface FactorRow {
  name: string
  category: string
  icMean: number
  icStd: number
  ir: number
  rank: number
}

const factors = ref<FactorRow[]>([
  { name: 'momentum_20d', category: 'Momentum', icMean: 0.045, icStd: 0.12, ir: 0.375, rank: 1 },
  { name: 'rsi_14', category: 'Technical', icMean: 0.038, icStd: 0.10, ir: 0.380, rank: 2 },
  { name: 'volume_ratio', category: 'Volume', icMean: 0.032, icStd: 0.14, ir: 0.229, rank: 3 },
  { name: 'bb_width', category: 'Technical', icMean: 0.028, icStd: 0.09, ir: 0.311, rank: 4 },
  { name: 'macd_divergence', category: 'Technical', icMean: 0.025, icStd: 0.11, ir: 0.227, rank: 5 },
  { name: 'turnover', category: 'Volume', icMean: 0.022, icStd: 0.13, ir: 0.169, rank: 6 },
  { name: 'volatility_30d', category: 'Risk', icMean: -0.018, icStd: 0.08, ir: -0.225, rank: 7 },
  { name: 'pe_ratio', category: 'Value', icMean: -0.015, icStd: 0.10, ir: -0.150, rank: 8 },
  { name: 'pb_ratio', category: 'Value', icMean: -0.012, icStd: 0.09, ir: -0.133, rank: 9 },
  { name: 'short_interest', category: 'Sentiment', icMean: -0.010, icStd: 0.07, ir: -0.143, rank: 10 },
])

const selectedFactor = ref<string | null>(null)

onMounted(() => {
  // factorStore.fetchFactors() — would fetch from API
})

// IC Rank bar chart
const icChartOption = computed(() => ({
  grid: { top: 8, right: 16, bottom: 4, left: 120 },
  tooltip: {
    trigger: 'axis' as const,
    backgroundColor: '#fff',
    borderColor: '#EEEEEE',
    textStyle: { color: '#1A1A1A', fontSize: 12 },
    axisPointer: { type: 'shadow' as const },
  },
  xAxis: {
    type: 'value' as const,
    splitLine: { lineStyle: { color: '#F5F5F5' } },
    axisLabel: { fontSize: 10, color: '#999999' },
  },
  yAxis: {
    type: 'category' as const,
    data: [...factors.value].sort((a, b) => b.icMean - a.icMean).map(f => f.name),
    axisLabel: { fontSize: 10, color: '#666666' },
    inverse: true,
  },
  series: [{
    type: 'bar',
    data: [...factors.value].sort((a, b) => b.icMean - a.icMean).map(f => ({
      value: f.icMean,
      itemStyle: { color: f.icMean >= 0 ? '#16A34A' : '#DC2626', borderRadius: [0, 3, 3, 0] },
    })),
    barWidth: 14,
  }],
}))

// Correlation heatmap
const corrNames = factors.value.slice(0, 8).map(f => f.name)
const corrData: Array<[number, number, number]> = []
for (let i = 0; i < corrNames.length; i++) {
  for (let j = 0; j < corrNames.length; j++) {
    const val = i === j ? 1 : (0.5 + Math.random() * 0.4) * (Math.random() > 0.5 ? 1 : -1)
    corrData.push([j, i, parseFloat(val.toFixed(2))])
  }
}

const heatmapOption = computed(() => ({
  grid: { top: 4, right: 4, bottom: 50, left: 100 },
  tooltip: {
    backgroundColor: '#fff',
    borderColor: '#EEEEEE',
    textStyle: { color: '#1A1A1A', fontSize: 12 },
  },
  xAxis: {
    type: 'category' as const,
    data: corrNames,
    axisLabel: { fontSize: 9, color: '#666666', rotate: 45 },
  },
  yAxis: {
    type: 'category' as const,
    data: corrNames,
    axisLabel: { fontSize: 9, color: '#666666' },
  },
  visualMap: {
    min: -1,
    max: 1,
    inRange: { color: ['#DC2626', '#FFFFFF', '#16A34A'] },
    show: false,
  },
  series: [{
    type: 'heatmap',
    data: corrData,
    label: { show: false },
    emphasis: { itemStyle: { shadowBlur: 10, shadowColor: 'rgba(0,0,0,0.15)' } },
  }],
}))
</script>

<template>
  <div class="space-y-6 xm-fade-in">
    <!-- IC Rank Chart -->
    <XmCard title="Factor IC Ranking" subtitle="Information Coefficient — higher = better predictive power">
      <VChart :option="icChartOption" style="height: 340px" autoresize />
    </XmCard>

    <!-- Factor Table -->
    <XmCard title="Factor Details">
      <table class="xm-table">
        <thead>
          <tr>
            <th>#</th>
            <th>Factor</th>
            <th>Category</th>
            <th class="text-right">IC Mean</th>
            <th class="text-right">IC Std</th>
            <th class="text-right">IR</th>
            <th>Rating</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="f in factors"
            :key="f.name"
            class="cursor-pointer"
            :class="{ 'bg-xm-primary-light/50': selectedFactor === f.name }"
            @click="selectedFactor = f.name"
          >
            <td class="text-xm-text-tertiary">{{ f.rank }}</td>
            <td class="font-mono text-xs font-semibold">{{ f.name }}</td>
            <td><XmBadge variant="info">{{ f.category }}</XmBadge></td>
            <td class="text-right font-mono" :class="f.icMean >= 0 ? 'xm-pnl-positive' : 'xm-pnl-negative'">
              {{ f.icMean >= 0 ? '+' : '' }}{{ f.icMean.toFixed(3) }}
            </td>
            <td class="text-right font-mono text-xm-text-secondary">{{ f.icStd.toFixed(3) }}</td>
            <td class="text-right font-mono font-semibold" :class="f.ir >= 0.3 ? 'text-profit' : 'text-xm-text-secondary'">
              {{ f.ir.toFixed(3) }}
            </td>
            <td>
              <XmBadge :variant="f.ir >= 0.3 ? 'success' : f.ir >= 0.1 ? 'warning' : 'danger'">
                {{ f.ir >= 0.3 ? 'Strong' : f.ir >= 0.1 ? 'Moderate' : 'Weak' }}
              </XmBadge>
            </td>
          </tr>
        </tbody>
      </table>
    </XmCard>

    <!-- Correlation Heatmap -->
    <XmCard title="Factor Correlation Matrix">
      <VChart :option="heatmapOption" style="height: 380px" autoresize />
    </XmCard>
  </div>
</template>
