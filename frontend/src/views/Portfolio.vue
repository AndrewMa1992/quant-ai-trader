<template>
  <div class="portfolio-page">
    <!-- 概览 -->
    <div class="grid-3">
      <div class="metric-card">
        <span class="metric-label">组合价值</span>
        <span class="metric-value green">${{ metrics.total_value?.toLocaleString() }}</span>
      </div>
      <div class="metric-card">
        <span class="metric-label">可用现金</span>
        <span class="metric-value cyan">${{ metrics.cash?.toLocaleString() }}</span>
      </div>
      <div class="metric-card">
        <span class="metric-label">持仓数量</span>
        <span class="metric-value">{{ metrics.num_positions }}</span>
      </div>
    </div>

    <!-- 价值曲线 -->
    <div class="card" style="margin-top: 16px;">
      <div class="card-header">
        <span class="card-title">组合价值曲线</span>
      </div>
      <div class="chart-container" ref="valueChartRef" style="height: 300px;"></div>
    </div>

    <!-- 持仓明细 -->
    <div class="card" style="margin-top: 16px;">
      <div class="card-header">
        <span class="card-title">持仓明细</span>
      </div>
      <table class="data-table">
        <thead>
          <tr>
            <th>股票</th>
            <th>持股数</th>
            <th>均价</th>
            <th>现价</th>
            <th>市值</th>
            <th>盈亏</th>
            <th>占比</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="positions.length === 0">
            <td colspan="7" style="text-align: center; color: var(--text-muted); padding: 40px;">
              💼 暂无持仓，AI 正在分析市场机会...
            </td>
          </tr>
          <tr v-for="p in positions" :key="p.ticker">
            <td><strong>{{ p.ticker }}</strong></td>
            <td>{{ p.shares?.toFixed(2) }}</td>
            <td>${{ p.avg_cost?.toFixed(2) }}</td>
            <td>${{ p.current_price?.toFixed(2) }}</td>
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

    <!-- 交易记录 -->
    <div class="card" style="margin-top: 16px;">
      <div class="card-header">
        <span class="card-title">交易记录</span>
        <span class="badge" style="background: var(--bg-card-hover); color: var(--text-secondary);">
          {{ trades.length }} 笔
        </span>
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
            <th>信号强度</th>
            <th>策略</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="trades.length === 0">
            <td colspan="8" style="text-align: center; color: var(--text-muted); padding: 30px;">
              暂无交易记录
            </td>
          </tr>
          <tr v-for="t in trades" :key="t.id">
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
            <td>{{ (t.signal_strength * 100)?.toFixed(0) }}%</td>
            <td style="font-size: 12px; color: var(--text-muted);">{{ t.strategy }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, nextTick } from 'vue'
import * as echarts from 'echarts'
import { usePortfolioStore } from '../stores/portfolio'

const portfolioStore = usePortfolioStore()
const valueChartRef = ref(null)
let chart = null

const metrics = computed(() => portfolioStore.metrics)
const positions = computed(() => portfolioStore.positionDetails)
const trades = computed(() => portfolioStore.trades)
const valueHistory = computed(() => portfolioStore.valueHistory || [])

function formatTime(ts) {
  if (!ts) return ''
  return ts.slice(5, 19).replace('T', ' ')
}

function initChart() {
  if (!valueChartRef.value) return
  chart = echarts.init(valueChartRef.value)

  const dates = []
  const data = []

  if (valueHistory.value.length > 1) {
    for (const item of valueHistory.value) {
      dates.push(item.time?.slice(5, 16) || '')
      data.push(item.value)
    }
  } else {
    // 暂无历史数据时展示初始值
    const baseValue = metrics.value.total_value || 1000000
    dates.push(new Date().toLocaleDateString('zh-CN'))
    data.push(baseValue)
  }

  const isUp = data.length > 1 ? data[data.length-1] >= data[0] : true
  const lineColor = isUp ? '#22c55e' : '#ef4444'

  chart.setOption({
    backgroundColor: 'transparent',
    tooltip: {
      trigger: 'axis',
      valueFormatter: (v) => '$' + (v || 0).toLocaleString(),
    },
    grid: { left: '8%', right: '5%', bottom: '8%', top: '5%' },
    xAxis: {
      type: 'category',
      data: dates,
      axisLine: { lineStyle: { color: '#1e293b' } },
      axisLabel: { color: '#5c6378', fontSize: 10 },
      splitLine: { show: false },
    },
    yAxis: {
      type: 'value',
      splitLine: { lineStyle: { color: '#1e293b', type: 'dashed' } },
      axisLabel: { color: '#5c6378' },
    },
    series: [{
      type: 'line',
      data,
      smooth: true,
      lineStyle: { color: lineColor, width: 2 },
      areaStyle: {
        color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
          { offset: 0, color: lineColor === '#22c55e' ? 'rgba(34, 197, 94, 0.3)' : 'rgba(239, 68, 68, 0.3)' },
          { offset: 1, color: 'rgba(0,0,0,0.02)' },
        ]),
      },
      symbol: 'none',
    }],
  })
}

onMounted(async () => {
  const res = await portfolioStore.fetchPortfolio()
  if (res?.value_history) {
    portfolioStore.valueHistory = res.value_history
  }
  await portfolioStore.fetchTrades()
  nextTick(() => {
    initChart()
    window.addEventListener('resize', () => chart?.resize())
  })
})
</script>
