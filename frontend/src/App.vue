<template>
  <div class="app">
    <aside class="sidebar">
      <div class="logo">
        <div class="logo-icon">Q</div>
        <div class="logo-text">
          <span class="logo-title">Quant AI</span>
          <span class="logo-subtitle">Trader</span>
        </div>
      </div>

      <nav class="nav">
        <router-link to="/" class="nav-item" exact-active-class="active">
          <span class="nav-icon">📊</span>
          <span>仪表盘</span>
        </router-link>
        <router-link to="/portfolio" class="nav-item" active-class="active">
          <span class="nav-icon">💼</span>
          <span>持仓</span>
        </router-link>
        <router-link to="/strategy" class="nav-item" active-class="active">
          <span class="nav-icon">🧠</span>
          <span>策略</span>
        </router-link>
        <router-link to="/backtest" class="nav-item" active-class="active">
          <span class="nav-icon">📈</span>
          <span>回测</span>
        </router-link>
      </nav>

      <div class="sidebar-footer">
        <div class="status-dot" :class="{ online: connected }"></div>
        <span>{{ connected ? '已连接' : '断开' }}</span>
      </div>
    </aside>

    <main class="main">
      <header class="header">
        <h1 class="page-title">{{ currentPageTitle }}</h1>
        <div class="header-right">
          <span class="live-badge" v-if="connected">
            <span class="live-dot"></span>
            LIVE
          </span>
          <div class="portfolio-value">
            <span class="label">组合价值</span>
            <span class="value" :class="{ up: portfolioChange >= 0, down: portfolioChange < 0 }">
              ${{ portfolioValue.toLocaleString() }}
            </span>
          </div>
        </div>
      </header>

      <div class="content">
        <router-view />
      </div>
    </main>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { useRoute } from 'vue-router'
import { useMarketStore } from './stores/market'
import { usePortfolioStore } from './stores/portfolio'

const route = useRoute()
const marketStore = useMarketStore()
const portfolioStore = usePortfolioStore()

const connected = ref(false)
let ws = null

const pageTitles = {
  '/': '仪表盘',
  '/portfolio': '持仓管理',
  '/strategy': '策略中心',
  '/backtest': '回测分析',
}

const currentPageTitle = computed(() => {
  return pageTitles[route.path] || 'Quant AI Trader'
})

const portfolioValue = computed(() => portfolioStore.metrics.total_value || 0)
const portfolioChange = computed(() => portfolioStore.metrics.total_return_pct || 0)

function connectWebSocket() {
  const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
  const host = location.hostname
  const port = location.port || '8000'
  const wsUrl = `${protocol}//${host}:${port}/ws`

  try {
    ws = new WebSocket(wsUrl)
    ws.onopen = () => {
      connected.value = true
      ws.send(JSON.stringify({ type: 'subscribe', channels: ['market', 'analysis'] }))
    }
    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data)
        if (msg.type === 'market_tick') {
          marketStore.updateTicks(msg.data.ticks)
          if (msg.data.portfolio) {
            portfolioStore.updateMetrics(msg.data.portfolio)
          }
        } else if (msg.type === 'analysis_result') {
          portfolioStore.updateSignals(msg.data.signals)
        } else if (msg.type === 'market_update') {
          // 实时更新：价格、信号、交易、组合
          const d = msg.data
          if (d.prices) marketStore.updatePrices(d.prices)
          if (d.signals) portfolioStore.updateSignals(d.signals)
          if (d.trades && d.trades.length > 0) {
            portfolioStore.prependTrades(d.trades)
          }
          if (d.portfolio) portfolioStore.updateMetrics(d.portfolio)
        }
      } catch (e) {
        console.error('WS parse error:', e)
      }
    }
    ws.onclose = () => {
      connected.value = false
      setTimeout(connectWebSocket, 3000)
    }
    ws.onerror = () => {
      ws?.close()
    }
  } catch (e) {
    console.error('WS connection error:', e)
    setTimeout(connectWebSocket, 3000)
  }
}

onMounted(() => {
  connectWebSocket()
  portfolioStore.fetchPortfolio()
})

onBeforeUnmount(() => {
  ws?.close()
})
</script>
