<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { BarChart, HeatmapChart, LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, VisualMapComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import XmCard from '@/components/ui/XmCard.vue'
import XmBadge from '@/components/ui/XmBadge.vue'
import DecayCurve from '@/components/factor/DecayCurve.vue'
import ICRankChart from '@/components/factor/ICRankChart.vue'
import { useFactorStore } from '@/stores/useFactorStore'

use([BarChart, HeatmapChart, LineChart, GridComponent, TooltipComponent, VisualMapComponent, CanvasRenderer])

const factorStore = useFactorStore()

interface FactorRow {
  name: string
  category: string
  icMean: number
  icStd: number
  ir: number
  rank: number
}

const factors = computed<FactorRow[]>(() => {
  const raw = [...factorStore.factors]
  const sorted = raw.sort((a, b) => (b.ic_mean ?? 0) - (a.ic_mean ?? 0))
  return sorted.map((f, i) => ({
    name: f.name,
    category: f.category,
    icMean: f.ic_mean ?? 0,
    icStd: f.ic_std ?? 0,
    ir: f.ir ?? 0,
    rank: i + 1,
  }))
})

const selectedFactor = ref<string | null>(null)
const detailLoading = ref(false)
const loading = ref(false)
const noData = computed(() => !loading.value && factorStore.factors.length === 0)

const icSeries = computed(() => factorStore.icData?.ic_series ?? [])
const decayHalfLife = computed(() => {
  const withHl = factorStore.decayData.find((d) => d.half_life != null)
  return withHl?.half_life
})

onMounted(async () => {
  loading.value = true
  try {
    await factorStore.fetchFactors()
    if (factorStore.factors.length > 0) {
      const names = factorStore.factors.slice(0, 20).map((f) => f.name)
      await factorStore.fetchCorrelation(names)
    }
  } catch {
    // store error already set
  } finally {
    loading.value = false
  }
})

async function selectFactor(name: string) {
  selectedFactor.value = name
  detailLoading.value = true
  try {
    await Promise.allSettled([
      factorStore.fetchIC(name),
      factorStore.fetchDecay(name),
    ])
  } finally {
    detailLoading.value = false
  }
}

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
    data: [...factors.value].sort((a, b) => b.icMean - a.icMean).map((f) => f.name),
    axisLabel: { fontSize: 10, color: '#666666' },
    inverse: true,
  },
  series: [
    {
      type: 'bar',
      data: [...factors.value].sort((a, b) => b.icMean - a.icMean).map((f) => ({
        value: f.icMean,
        itemStyle: { color: f.icMean >= 0 ? '#16A34A' : '#DC2626', borderRadius: [0, 3, 3, 0] },
      })),
      barWidth: 14,
    },
  ],
}))

const corrNames = computed<string[]>(() => Object.keys(factorStore.correlationMatrix).slice(0, 12))

const corrData = computed<Array<[number, number, number]>>(() => {
  const names = corrNames.value
  const matrix = factorStore.correlationMatrix
  if (names.length === 0) return []
  const data: Array<[number, number, number]> = []
  for (let i = 0; i < names.length; i++) {
    for (let j = 0; j < names.length; j++) {
      const val = matrix[names[i]]?.[names[j]] ?? (i === j ? 1 : 0)
      data.push([j, i, parseFloat(val.toFixed(2))])
    }
  }
  return data
})

const heatmapOption = computed(() => ({
  grid: { top: 4, right: 4, bottom: 50, left: 100 },
  tooltip: {
    backgroundColor: '#fff',
    borderColor: '#EEEEEE',
    textStyle: { color: '#1A1A1A', fontSize: 12 },
  },
  xAxis: {
    type: 'category' as const,
    data: corrNames.value,
    axisLabel: { fontSize: 9, color: '#666666', rotate: 45 },
  },
  yAxis: {
    type: 'category' as const,
    data: corrNames.value,
    axisLabel: { fontSize: 9, color: '#666666' },
  },
  visualMap: {
    min: -1,
    max: 1,
    inRange: { color: ['#DC2626', '#FFFFFF', '#16A34A'] },
    show: false,
  },
  series: [
    {
      type: 'heatmap',
      data: corrData.value,
      label: { show: false },
      emphasis: { itemStyle: { shadowBlur: 10, shadowColor: 'rgba(0,0,0,0.15)' } },
    },
  ],
}))
</script>

<template>
  <div class="space-y-6 xm-fade-in">
    <XmCard title="Factor IC Ranking" subtitle="Information Coefficient — higher = better predictive power">
      <div v-if="loading" class="flex items-center justify-center h-[340px] text-xm-text-tertiary text-sm">
        Loading factor data...
      </div>
      <div v-else-if="noData" class="flex items-center justify-center h-[340px] text-xm-text-tertiary text-sm">
        No factor data available. Run data sync first.
      </div>
      <VChart v-else :option="icChartOption" style="height: 340px" autoresize />
    </XmCard>

    <XmCard title="Factor Details" subtitle="Click a row to load IC series and decay">
      <div v-if="loading" class="text-center py-8 text-xm-text-tertiary text-sm">Loading...</div>
      <div v-else-if="noData" class="text-center py-8 text-xm-text-tertiary text-sm">
        No factor data available. Run data sync first.
      </div>
      <table v-else class="xm-table">
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
            @click="selectFactor(f.name)"
          >
            <td class="text-xm-text-tertiary">{{ f.rank }}</td>
            <td class="font-mono text-xs font-semibold">{{ f.name }}</td>
            <td><XmBadge variant="info">{{ f.category }}</XmBadge></td>
            <td class="text-right font-mono" :class="f.icMean >= 0 ? 'xm-pnl-positive' : 'xm-pnl-negative'">
              {{ f.icMean >= 0 ? '+' : '' }}{{ f.icMean.toFixed(3) }}
            </td>
            <td class="text-right font-mono text-xm-text-secondary">{{ f.icStd.toFixed(3) }}</td>
            <td
              class="text-right font-mono font-semibold"
              :class="f.ir >= 0.3 ? 'text-profit' : 'text-xm-text-secondary'"
            >
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

    <div v-if="selectedFactor" class="grid grid-cols-1 lg:grid-cols-2 gap-6">
      <XmCard :title="`IC Series — ${selectedFactor}`">
        <div v-if="detailLoading" class="text-center py-10 text-xm-text-tertiary text-sm">Loading IC...</div>
        <ICRankChart
          v-else-if="icSeries.length > 0"
          :data="icSeries"
          :title="`${selectedFactor} IC`"
        />
        <div v-else class="text-center py-10 text-xm-text-tertiary text-sm">
          No IC series for this factor.
        </div>
      </XmCard>

      <XmCard :title="`Decay Curve — ${selectedFactor}`">
        <div v-if="detailLoading" class="text-center py-10 text-xm-text-tertiary text-sm">Loading decay...</div>
        <DecayCurve
          v-else
          :data="factorStore.decayData"
          :half-life="decayHalfLife"
        />
      </XmCard>
    </div>

    <XmCard title="Factor Correlation Matrix">
      <div
        v-if="corrNames.length === 0"
        class="flex items-center justify-center h-[380px] text-xm-text-tertiary text-sm"
      >
        Correlation data not yet available — load factor data first
      </div>
      <VChart v-else :option="heatmapOption" style="height: 380px" autoresize />
    </XmCard>
  </div>
</template>
