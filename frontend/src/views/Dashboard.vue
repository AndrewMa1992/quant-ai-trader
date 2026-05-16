<template>
  <div class="dashboard">
    <!-- 概述指标 -->
    <div class="grid-4">
      <div class="metric-card">
        <span class="metric-label">组合总价值</span>
        <span class="metric-value green">${{ metrics.total_value.toLocaleString() }}</span>
        <span class="metric-change" :class="metrics.total_return_pct >= 0 ? 'positive' : 'negative'">
          {{ metrics.total_return_pct >= 0 ? '+' : '' }}{{ metrics.total_return_pct?.toFixed(2) }}%
        </span>
      </div>
      <div class="metric-card">
        <span class="metric-label">现金</span>
        <span class="metric-value cyan">${{ metrics.cash.toLocaleString() }}</span>
        <span class="metric-change">持仓 {{ metrics.positions_value?.toFixed(0) }}</span>
      </div>
      <div class="metric-card">
        <span class="metric-label">夏普比率</span>
        <span class="metric-value" :class="metrics.sharpe_ratio >= 1 ? 'green' : 'red'">
          {{ metrics.sharpe_ratio?.toFixed(2) }}
        </span>
        <span class="metric-change">总盈亏 ${{ metrics.total_pnl?.toFixed(0) }}</span>
      </div>
      <div class="metric-card">
        <span class="metric-label">最大回撤</span>
        <span class="metric-value red">{{ metrics.max_drawdown?.toFixed(2) }}%</span>
        <span class="metric-change">交易 {{ metrics.total_trades }} 笔</span>
      </div>
    </div>

    <!-- 实时价格 + 信号 -->
    <div style="display: grid; grid-template-columns: 2fr 1fr; gap: 16px; margin-top: 16px;">
      <div class="card">
        <div class="card-header">
          <span class="card-title">实时行情</span>
          <div style="display: flex; gap: 6px; flex-wrap: wrap;">
            <span style="font-size: 10px; color: var(--text-muted); padding: 2px 4px;">US</span>
            <button
              v-for="t in usTickers.slice(0, 5)"
              :key="t"
              class="btn btn-secondary"
              :class="{ active: selectedTicker === t }"
              @click="selectedTicker = t"
              style="padding: 3px 8px; font-size: 11px;"
            >{{ t }}</button>
            <span style="font-size: 10px; color: var(--text-muted); padding: 2px 4px; margin-left: 4px;">HK</span>
            <button
              v-for="t in hkTickers.slice(0, 4)"
              :key="t"
              class="btn btn-secondary"
              :class="{ active: selectedTicker === t }"
              @click="selectedTicker = t + '.HK'"
              style="padding: 3px 8px; font-size: 11px;"
            >{{ t }}</button>
          </div>
        </div>
        <div class="chart-container" ref="priceChartRef" style="height: 350px;"></div>
      </div>

      <div class="card">
        <div class="card-header">
          <span class="card-title">交易信号</span>
        </div>
        <SignalPanel
          :signals="signals"
          :signal-history="portfolioStore.signalHistory"
          :loading="portfolioStore.analysisLoading"
          :last-updated="formatLastUpdated"
          :auto-refresh="signalAutoRefresh"
          @run-analysis="handleRunAnalysis"
          @toggle-autorefresh="handleToggleRefresh"
        />
      </div>
    </div>

    <!-- 持仓摘要 -->
    <div style="margin-top: 16px;">
      <div class="card">
        <div class="card-header">
          <span class="card-title">持仓摘要</span>
          <button class="btn btn-secondary" @click="refreshData">刷新</button>
        </div>
        <table class="data-table">
          <thead>
            <tr>
              <th>股票</th>
              <th>股数</th>
              <th>市值</th>
              <th>未实现盈亏</th>
              <th>占比</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="positions.length === 0">
              <td colspan="5" style="text-align: center; color: var(--text-muted); padding: 30px;">
                暂无持仓 — AI 正在分析市场...
              </td>
            </tr>
            <tr v-for="p in positions" :key="p.ticker">
              <td><strong>{{ p.ticker }}</strong></td>
              <td>{{ p.shares?.toFixed(2) }}</td>
              <td>${{ p.market_value?.toLocaleString() }}</td>
              <td :class="p.unrealized_pnl >= 0 ? 'text-green' : 'text-red'">
                {{ p.unrealized_pnl >= 0 ? '+' : '' }}${{ p.unrealized_pnl?.toFixed(2) }}
                ({{ p.unrealized_pnl_pct >= 0 ? '+' : '' }}{{ p.unrealized_pnl_pct?.toFixed(2) }}%)
              </td>
              <td>{{ p.allocation?.toFixed(1) }}%</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- 近期交易 -->
    <div style="margin-top: 16px;">
      <div class="card">
        <div class="card-header">
          <span class="card-title">近期交易</span>
          <button class="btn btn-secondary" @click="loadTrades">查看全部</button>
        </div>
        <table class="data-table">
          <thead>
            <tr>
              <th>时间</th>
              <th>股票</th>
              <th>方向</th>
              <th>数量</th>
              <th>价格</th>
              <th>金额</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="trades.length === 0">
              <td colspan="6" style="text-align: center; color: var(--text-muted); padding: 30px;">
                暂无交易记录
              </td>
            </tr>
            <tr v-for="t in recentTrades" :key="t.id">
              <td style="font-size: 12px;">{{ formatTime(t.timestamp) }}</td>
              <td><strong>{{ t.ticker }}</strong></td>
              <td>
                <span class="badge" :class="t.side === 'buy' ? 'badge-buy' : 'badge-sell'">
                  {{ t.side === 'buy' ? '买入' : '卖出' }}
                </span>
              </td>
              <td>{{ t.quantity?.toFixed(2) }}</td>
              <td>${{ t.price?.toFixed(2) }}</td>
              <td>${{ t.value?.toLocaleString() }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, watch, nextTick } from 'vue'
import * as echarts from 'echarts'
import { useMarketStore } from '../stores/market'
import { usePortfolioStore } from '../stores/portfolio'
import SignalPanel from '../components/SignalPanel.vue'

const marketStore = useMarketStore()
const portfolioStore = usePortfolioStore()

const priceChartRef = ref(null)
const selectedTicker = ref('AAPL')
const usTickers = computed(() => marketStore.usTickers)
const hkTickers = computed(() => marketStore.hkTickers)
let chart = null

const metrics = computed(() => portfolioStore.metrics)
const signals = computed(() => portfolioStore.signals)
const trades = computed(() => portfolioStore.trades)
const positions = computed(() => portfolioStore.positionDetails)
const recentTrades = computed(() => trades.value.slice(0, 10))

const formatLastUpdated = computed(() => {
  if (!portfolioStore.lastAnalysisTime) return ''
  return portfolioStore.lastAnalysisTime.slice(11, 19)
})

const signalAutoRefresh = ref(false)
let refreshTimer = null

function formatTime(ts) {
  if (!ts) return ''
  return ts.slice(5, 19).replace('T', ' ')
}

async function handleRunAnalysis() {
  await portfolioStore.runAnalysis()
}

function handleToggleRefresh(checked) {
  signalAutoRefresh.value = checked
  if (checked) {
    refreshTimer = setInterval(async () => {
      await portfolioStore.fetchLatestSignals()
      await portfolioStore.fetchSignalHistory()
    }, 30000)
  } else {
    if (refreshTimer) {
      clearInterval(refreshTimer)
      refreshTimer = null
    }
  }
}

function initChart() {
  if (!priceChartRef.value) return
  chart = echarts.init(priceChartRef.value)
  updateChart()
}

async function updateChart() {
  if (!chart) return
  const data = await marketStore.fetchHistory(selectedTicker.value, '1mo', '1d')
  if (!data?.data) return

  const ohlc = data.data.map(d => [d.open, d.close, d.low, d.high])
  const dates = data.data.map(d => d.timestamp?.slice(0, 10))
  const volume = data.data.map(d => d.volume)

  // 颜色：A股涨红跌绿
  const colors = ohlc.map(d => d[1] >= d[0] ? '#22c55e' : '#ef4444')

  chart.setOption({
    backgroundColor: 'transparent',
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross' },
    },
    grid: [
      { left: '8%', right: '8%', top: '5%', height: '65%' },
      { left: '8%', right: '8%', top: '78%', height: '15%' },
    ],
    xAxis: [
      {
        type: 'category',
        data: dates,
        axisLine: { lineStyle: { color: '#1e293b' } },
        axisLabel: { color: '#5c6378', fontSize: 10 },
        gridIndex: 0,
      },
      {
        type: 'category',
        data: dates,
        gridIndex: 1,
        axisLabel: { show: false },
        axisLine: { show: false },
      },
    ],
    yAxis: [
      {
        scale: true,
        splitLine: { lineStyle: { color: '#1e293b', type: 'dashed' } },
        axisLabel: { color: '#5c6378' },
        gridIndex: 0,
      },
      {
        scale: true,
        splitLine: { show: false },
        axisLabel: { show: false },
        gridIndex: 1,
      },
    ],
    series: [
      {
        name: 'K线',
        type: 'candlestick',
        data: ohlc,
        itemStyle: {
          color: '#22c55e',
          color0: '#ef4444',
          borderColor: '#22c55e',
          borderColor0: '#ef4444',
        },
      },
      {
        name: '成交量',
        type: 'bar',
        xAxisIndex: 1,
        yAxisIndex: 1,
        data: volume.map((v, i) => ({
          value: v,
          itemStyle: { color: ohlc[i][1] >= ohlc[i][0] ? '#22c55e' : '#ef4444', opacity: 0.4 }
        })),
      },
    ],
  })
}

function refreshData() {
  loadTrades()
}

async function loadTrades() {
  await portfolioStore.fetchTrades()
}

watch(selectedTicker, () => {
  nextTick(() => updateChart())
})

onMounted(async () => {
  await marketStore.fetchTickers()
  await portfolioStore.fetchPortfolio()
  await loadTrades()
  nextTick(() => {
    initChart()
    window.addEventListener('resize', () => chart?.resize())
  })
})

onUnmounted(() => {
  if (refreshTimer) {
    clearInterval(refreshTimer)
    refreshTimer = null
  }
})
</script>

<style scoped>
.dashboard {
  animation: fadeIn 0.3s ease-out;
}
.btn-secondary.active {
  background: var(--accent-blue);
  color: white;
  border-color: var(--accent-blue);
}
</style>
