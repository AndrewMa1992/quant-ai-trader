<template>
  <div class="backtest-page">
    <div class="card" style="margin-bottom: 16px;">
      <div class="card-header">
        <span class="card-title">回测分析</span>
        <button class="btn btn-primary" @click="runBacktest">
          🚀 运行回测
        </button>
      </div>
      <p style="font-size: 13px; color: var(--text-secondary);">
        在历史数据上模拟 AI 策略交易，评估策略表现
      </p>
    </div>

    <!-- 回测结果 -->
    <div v-if="results.length > 0">
      <div class="grid-4" style="margin-bottom: 16px;">
        <div class="metric-card">
          <span class="metric-label">年化收益率</span>
          <span class="metric-value" :class="bestResult.annualized_return >= 0 ? 'green' : 'red'">
            {{ bestResult.annualized_return?.toFixed(2) }}%
          </span>
        </div>
        <div class="metric-card">
          <span class="metric-label">夏普比率</span>
          <span class="metric-value" :class="bestResult.sharpe_ratio >= 1 ? 'green' : bestResult.sharpe_ratio > 0 ? 'cyan' : 'red'">
            {{ bestResult.sharpe_ratio?.toFixed(2) }}
          </span>
        </div>
        <div class="metric-card">
          <span class="metric-label">最大回撤</span>
          <span class="metric-value red">{{ bestResult.max_drawdown_pct?.toFixed(2) }}%</span>
        </div>
        <div class="metric-card">
          <span class="metric-label">胜率</span>
          <span class="metric-value cyan">{{ bestResult.win_rate?.toFixed(1) }}%</span>
        </div>
      </div>

      <div class="card">
        <div class="card-header">
          <span class="card-title">回测详情</span>
        </div>
        <table class="data-table">
          <thead>
            <tr>
              <th>名称</th>
              <th>期间</th>
              <th>初始资金</th>
              <th>最终价值</th>
              <th>年化收益</th>
              <th>夏普</th>
              <th>最大回撤</th>
              <th>胜率</th>
              <th>交易次数</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in results" :key="r.name">
              <td><strong>{{ r.name }}</strong></td>
              <td style="font-size: 12px;">{{ r.period }}</td>
              <td>${{ r.initial_capital?.toLocaleString() }}</td>
              <td>${{ r.final_value?.toLocaleString() }}</td>
              <td :class="r.annualized_return >= 0 ? 'text-green' : 'text-red'">
                {{ r.annualized_return?.toFixed(2) }}%
              </td>
              <td :class="r.sharpe_ratio >= 1 ? 'text-green' : 'text-yellow'">
                {{ r.sharpe_ratio?.toFixed(2) }}
              </td>
              <td class="text-red">{{ r.max_drawdown_pct?.toFixed(2) }}%</td>
              <td class="text-green">{{ r.win_rate?.toFixed(1) }}%</td>
              <td>{{ r.total_trades }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <div v-else class="card" style="text-align: center; padding: 60px 20px;">
      <div style="font-size: 48px; margin-bottom: 16px;">📈</div>
      <p style="color: var(--text-muted); font-size: 15px;">
        暂无回测结果
      </p>
      <p style="color: var(--text-muted); font-size: 13px; margin-top: 8px;">
        点击上方「运行回测」按钮开始回测 AI 策略
      </p>
      <button class="btn btn-primary" style="margin-top: 20px;" @click="runBacktest">
        🚀 运行回测
      </button>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import axios from 'axios'

const results = ref([])

const bestResult = computed(() => {
  return results.value[0] || {}
})

async function fetchResults() {
  try {
    const res = await axios.get('/api/analysis/backtest-results')
    if (res.data) {
      results.value = Object.values(res.data)
    }
  } catch (e) {
    console.error('Failed to fetch backtest results:', e)
  }
}

async function runBacktest() {
  try {
    await axios.post('/api/analysis/run-backtest')
    // 模拟延迟后刷新
    setTimeout(fetchResults, 3000)
  } catch (e) {
    console.error('Failed to run backtest:', e)
  }
}

onMounted(fetchResults)
</script>
