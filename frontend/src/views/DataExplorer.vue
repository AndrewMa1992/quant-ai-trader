<script setup lang="ts">
import { onMounted, ref } from 'vue'
import XmCard from '@/components/ui/XmCard.vue'
import XmBadge from '@/components/ui/XmBadge.vue'
import { useDataStore } from '@/stores/useDataStore'

const dataStore = useDataStore()

const activeTab = ref<'fundamentals' | 'capitalFlow' | 'calendar'>('fundamentals')

// Tab 1 — Fundamentals
const fundTicker = ref('')
const fundData = ref<Record<string, any>>({})
const fundLoading = ref(false)

async function searchFundamentals() {
  if (!fundTicker.value.trim()) return
  fundLoading.value = true
  try {
    await dataStore.fetchFundamentals(fundTicker.value.trim().toUpperCase())
    fundData.value = dataStore.fundamentals[fundTicker.value.trim().toUpperCase()] || {}
  } catch { fundData.value = {} }
  finally { fundLoading.value = false }
}

// Tab 2 — Capital Flow
const flowTicker = ref('')
const flowStartDate = ref('')
const flowEndDate = ref('')
const flowData = ref<any[]>([])
const flowLoading = ref(false)

async function searchCapitalFlow() {
  if (!flowTicker.value.trim()) return
  flowLoading.value = true
  const ticker = flowTicker.value.trim().toUpperCase()
  const params: { start_date?: string; end_date?: string; limit?: number } = { limit: 30 }
  if (flowStartDate.value) params.start_date = flowStartDate.value
  if (flowEndDate.value) params.end_date = flowEndDate.value
  try {
    await dataStore.fetchCapitalFlow(ticker, params)
    flowData.value = dataStore.capitalFlows[ticker] || []
  } catch { flowData.value = [] }
  finally { flowLoading.value = false }
}

// Tab 3 — Calendar
const calMarket = ref('US')

async function loadCalendar() {
  await dataStore.fetchCalendar({ market: calMarket.value, trading_only: true })
}

function fmtNum(v: any) {
  if (v === null || v === undefined) return '-'
  const n = Number(v)
  if (isNaN(n)) return String(v)
  return n.toLocaleString('en-US', { maximumFractionDigits: 2 })
}

function fmtCurrency(v: any) {
  if (v === null || v === undefined) return '-'
  const n = Number(v)
  if (isNaN(n)) return String(v)
  return '$' + n.toLocaleString('en-US', { maximumFractionDigits: 2 })
}

const calendarRecords = ref(dataStore.calendar)

onMounted(() => {
  loadCalendar()
})
</script>

<template>
  <div class="space-y-6 xm-fade-in">
    <!-- Tab Switcher -->
    <div class="flex gap-1 p-1 bg-xm-bg-surface rounded-lg w-fit">
      <button
        v-for="tab in ([
          { key: 'fundamentals', label: 'Fundamentals', icon: '📊' },
          { key: 'capitalFlow', label: 'Capital Flow', icon: '💸' },
          { key: 'calendar', label: 'Calendar', icon: '📅' },
        ] as const)"
        :key="tab.key"
        class="px-4 py-2 rounded-md text-sm font-medium transition-all duration-xm ease-xm"
        :class="activeTab === tab.key
          ? 'bg-white text-xm-primary shadow-xm'
          : 'text-xm-text-secondary hover:text-xm-text-primary'"
        @click="activeTab = tab.key"
      >
        <span class="mr-1.5">{{ tab.icon }}</span>{{ tab.label }}
      </button>
    </div>

    <!-- ═══ Tab 1: Fundamentals ═══ -->
    <div v-if="activeTab === 'fundamentals'" class="space-y-4">
      <div class="flex items-end gap-3">
        <div class="flex-1 max-w-[300px]">
          <label class="block text-xxs text-xm-text-tertiary mb-1">Ticker</label>
          <input
            v-model="fundTicker"
            placeholder="e.g. AAPL"
            class="xm-input w-full"
            @keyup.enter="searchFundamentals"
          />
        </div>
        <button class="xm-btn-primary" :disabled="fundLoading" @click="searchFundamentals">
          {{ fundLoading ? 'Loading...' : 'Search' }}
        </button>
      </div>

      <div v-if="Object.keys(fundData).length > 0" class="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <XmCard class="!p-4">
          <div class="xm-metric-label">PE Ratio</div>
          <div class="xm-metric-value text-base">{{ fmtNum(fundData.pe_ratio) }}</div>
        </XmCard>
        <XmCard class="!p-4">
          <div class="xm-metric-label">PB Ratio</div>
          <div class="xm-metric-value text-base">{{ fmtNum(fundData.pb_ratio) }}</div>
        </XmCard>
        <XmCard class="!p-4">
          <div class="xm-metric-label">EPS</div>
          <div class="xm-metric-value text-base">{{ fmtNum(fundData.eps) }}</div>
        </XmCard>
        <XmCard class="!p-4">
          <div class="xm-metric-label">Dividend Yield</div>
          <div class="xm-metric-value text-base">{{ fundData.dividend_yield ? (fundData.dividend_yield * 100).toFixed(2) + '%' : '-' }}</div>
        </XmCard>
        <XmCard class="!p-4">
          <div class="xm-metric-label">Beta</div>
          <div class="xm-metric-value text-base">{{ fmtNum(fundData.beta) }}</div>
        </XmCard>
        <XmCard class="!p-4">
          <div class="xm-metric-label">Market Cap</div>
          <div class="xm-metric-value text-base">{{ fmtCurrency(fundData.market_cap) }}</div>
        </XmCard>
        <XmCard class="!p-4">
          <div class="xm-metric-label">Sector</div>
          <div class="xm-metric-value text-base">{{ fundData.sector || '-' }}</div>
        </XmCard>
        <XmCard class="!p-4">
          <div class="xm-metric-label">Industry</div>
          <div class="xm-metric-value text-base">{{ fundData.industry || '-' }}</div>
        </XmCard>
      </div>
      <div v-else-if="!fundLoading && fundTicker" class="text-center py-10 text-xm-text-tertiary text-sm">
        No fundamentals found. Try searching a different ticker.
      </div>
    </div>

    <!-- ═══ Tab 2: Capital Flow ═══ -->
    <div v-if="activeTab === 'capitalFlow'" class="space-y-4">
      <div class="flex flex-wrap items-end gap-3">
        <div class="flex-1 min-w-[140px] max-w-[200px]">
          <label class="block text-xxs text-xm-text-tertiary mb-1">Ticker</label>
          <input
            v-model="flowTicker"
            placeholder="e.g. AAPL"
            class="xm-input w-full"
            @keyup.enter="searchCapitalFlow"
          />
        </div>
        <div class="w-[150px]">
          <label class="block text-xxs text-xm-text-tertiary mb-1">Start Date</label>
          <input v-model="flowStartDate" type="date" class="xm-input w-full" />
        </div>
        <div class="w-[150px]">
          <label class="block text-xxs text-xm-text-tertiary mb-1">End Date</label>
          <input v-model="flowEndDate" type="date" class="xm-input w-full" />
        </div>
        <button class="xm-btn-primary" :disabled="flowLoading" @click="searchCapitalFlow">
          {{ flowLoading ? 'Loading...' : 'Search' }}
        </button>
      </div>

      <XmCard v-if="flowData.length > 0" title="Capital Flow History" :subtitle="`${flowData.length} records`">
        <table class="xm-table">
          <thead>
            <tr>
              <th>Date</th>
              <th class="text-right">Net Inflow</th>
              <th class="text-right">Main Inflow</th>
              <th class="text-right">Main Outflow</th>
              <th class="text-right">Super-Large Inflow</th>
              <th class="text-right">Super-Large Outflow</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(row, idx) in flowData" :key="idx">
              <td class="text-xs">{{ row.date || '-' }}</td>
              <td class="text-right font-mono text-sm" :class="(row.net_inflow ?? 0) >= 0 ? 'text-profit' : 'text-loss'">
                {{ fmtCurrency(row.net_inflow) }}
              </td>
              <td class="text-right font-mono text-sm text-profit">{{ fmtCurrency(row.main_inflow) }}</td>
              <td class="text-right font-mono text-sm text-loss">{{ fmtCurrency(row.main_outflow) }}</td>
              <td class="text-right font-mono text-sm text-profit">{{ fmtCurrency(row.super_large_inflow) }}</td>
              <td class="text-right font-mono text-sm text-loss">{{ fmtCurrency(row.super_large_outflow) }}</td>
            </tr>
          </tbody>
        </table>
      </XmCard>
      <div v-else-if="!flowLoading && flowTicker" class="text-center py-10 text-xm-text-tertiary text-sm">
        No capital flow data found. Try adjusting your date range.
      </div>
    </div>

    <!-- ═══ Tab 3: Calendar ═══ -->
    <div v-if="activeTab === 'calendar'" class="space-y-4">
      <div class="flex items-end gap-3">
        <div class="w-[150px]">
          <label class="block text-xxs text-xm-text-tertiary mb-1">Market</label>
          <select v-model="calMarket" class="xm-input w-full" @change="loadCalendar">
            <option value="US">US</option>
            <option value="HK">HK</option>
            <option value="SG">SG</option>
          </select>
        </div>
        <button class="xm-btn-secondary" @click="loadCalendar">Refresh</button>
      </div>

      <XmCard v-if="dataStore.tradingDays.length > 0" title="Trading Days" :subtitle="`${dataStore.tradingDays.length} days`">
        <table class="xm-table">
          <thead>
            <tr>
              <th>Date</th>
              <th>Market</th>
              <th>Open Time</th>
              <th>Close Time</th>
              <th>Holiday</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(day, idx) in dataStore.tradingDays.slice(0, 60)" :key="idx">
              <td class="font-mono text-xs">{{ day.date }}</td>
              <td>
                <XmBadge variant="info">{{ day.market }}</XmBadge>
              </td>
              <td class="text-xs">{{ day.open_time || '-' }}</td>
              <td class="text-xs">{{ day.close_time || '-' }}</td>
              <td class="text-xs text-xm-text-tertiary">{{ day.holiday_name || '-' }}</td>
            </tr>
          </tbody>
        </table>
      </XmCard>
      <div v-else class="text-center py-10 text-xm-text-tertiary text-sm">
        No calendar data available. Try selecting a different market.
      </div>
    </div>

    <!-- Error Banner -->
    <div
      v-if="dataStore.error"
      class="p-3 rounded-lg bg-loss-bg border border-loss/20 text-sm text-loss"
    >
      {{ dataStore.error }}
    </div>
  </div>
</template>
