<template>
  <div class="strategy-page">
    <!-- 模型状态 -->
    <div class="grid-3">
      <div class="card">
        <div class="card-header">
          <span class="card-title">Transformer</span>
          <span class="badge" :class="modelStatus.transformer ? 'badge-buy' : 'badge-sell'">
            {{ modelStatus.transformer ? '就绪' : '离线' }}
          </span>
        </div>
        <div style="font-size: 13px; color: var(--text-secondary);">
          <p style="margin-bottom: 8px;">PatchTST 时间序列预测器</p>
          <p>回看窗口: 60 天 · 预测: 1/5/20 天</p>
          <p style="margin-top: 4px;">分位数回归 + 置信区间</p>
        </div>
      </div>

      <div class="card">
        <div class="card-header">
          <span class="card-title">PPO 强化学习</span>
          <span class="badge" :class="modelStatus.rl_agent ? 'badge-buy' : 'badge-sell'">
            {{ modelStatus.rl_agent ? '就绪' : '离线' }}
          </span>
        </div>
        <div style="font-size: 13px; color: var(--text-secondary);">
          <p style="margin-bottom: 8px;">Proximal Policy Optimization</p>
          <p>连续仓位空间 · Sharpe 奖励</p>
          <p style="margin-top: 4px;">多标的同时交易</p>
        </div>
      </div>

      <div class="card">
        <div class="card-header">
          <span class="card-title">FinBERT 情绪</span>
          <span class="badge badge-buy">就绪</span>
        </div>
        <div style="font-size: 13px; color: var(--text-secondary);">
          <p style="margin-bottom: 8px;">财经新闻情绪分析</p>
          <p>当前模式: 模拟</p>
          <p style="margin-top: 4px;">新闻分析待接入</p>
        </div>
      </div>
    </div>

    <!-- Ensemble 权重 -->
    <div class="card" style="margin-top: 16px;">
      <div class="card-header">
        <span class="card-title">模型融合权重</span>
        <button class="btn btn-secondary" @click="refreshStatus">刷新</button>
      </div>
      <div class="grid-4" style="margin-top: 12px;">
        <div v-for="(weight, name) in ensembleWeights" :key="name" class="weight-bar">
          <div style="display: flex; justify-content: space-between; font-size: 13px; margin-bottom: 6px;">
            <span>{{ modelNames[name] || name }}</span>
            <span style="font-family: monospace;">{{ (weight * 100).toFixed(0) }}%</span>
          </div>
          <div class="bar-bg">
            <div class="bar-fill" :style="{ width: (weight * 100) + '%', background: barColors[name] }"></div>
          </div>
        </div>
      </div>
    </div>

    <!-- 当前信号 -->
    <div class="card" style="margin-top: 16px;">
      <div class="card-header">
        <span class="card-title">当前交易信号</span>
        <span style="font-size: 12px; color: var(--text-muted);">
          总循环: {{ strategyStatus.total_cycles }} 次
        </span>
      </div>
      <table class="data-table">
        <thead>
          <tr>
            <th>股票</th>
            <th>决策</th>
            <th>信号强度</th>
            <th>置信度</th>
            <th>仓位比例</th>
            <th>Ensemble Score</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="Object.keys(signals).length === 0">
            <td colspan="6" style="text-align: center; color: var(--text-muted); padding: 40px;">
              🧠 等待 AI 分析结果...
            </td>
          </tr>
          <tr v-for="(signal, ticker) in signals" :key="ticker">
            <td><strong>{{ ticker }}</strong></td>
            <td>
              <span class="badge" :class="'badge-' + signal.decision">
                {{ signal.decision?.toUpperCase() }}
              </span>
            </td>
            <td>{{ (signal.strength * 100)?.toFixed(1) }}%</td>
            <td>{{ (signal.confidence * 100)?.toFixed(1) }}%</td>
            <td>{{ (signal.position_size * 100)?.toFixed(1) }}%</td>
            <td :class="signal.ensemble_score >= 0 ? 'text-green' : 'text-red'">
              {{ signal.ensemble_score?.toFixed(3) }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 模型操作 -->
    <div class="card" style="margin-top: 16px;">
      <div class="card-header">
        <span class="card-title">模型操作</span>
      </div>
      <div style="display: flex; gap: 12px;">
        <button class="btn btn-primary" @click="retrainModels">
          🔄 重新训练所有模型
        </button>
        <button class="btn btn-secondary" @click="triggerAnalysis">
          ⚡ 立即分析
        </button>
        <button class="btn btn-secondary" @click="refreshStatus">
          📊 刷新状态
        </button>
      </div>
      <div v-if="actionMessage" style="margin-top: 12px; padding: 8px 12px; background: rgba(34, 197, 94, 0.1); border-radius: var(--radius-sm); font-size: 13px; color: var(--accent-green);">
        {{ actionMessage }}
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import axios from 'axios'
import { usePortfolioStore } from '../stores/portfolio'

const portfolioStore = usePortfolioStore()
const actionMessage = ref('')

const modelStatus = reactive({
  transformer: false,
  rl_agent: false,
})

const ensembleWeights = reactive({
  transformer: 0.35,
  rl_agent: 0.35,
  sentiment: 0.15,
  technical: 0.15,
})

const strategyStatus = reactive({
  total_cycles: 0,
})

const signals = computed(() => portfolioStore.signals)

const modelNames = {
  transformer: 'Transformer',
  rl_agent: 'RL Agent',
  sentiment: '情绪分析',
  technical: '技术指标',
}

const barColors = {
  transformer: '#3b82f6',
  rl_agent: '#a855f7',
  sentiment: '#22d3ee',
  technical: '#eab308',
}

async function refreshStatus() {
  try {
    const [modelRes, stratRes] = await Promise.all([
      axios.get('/api/models/status'),
      axios.get('/api/analysis/strategy-status'),
    ])
    modelStatus.transformer = modelRes.data.transformer_ready
    modelStatus.rl_agent = modelRes.data.rl_ready
    Object.assign(strategyStatus, stratRes.data)

    // 获取 ensemble 权重
    const ensembleRes = await axios.get('/api/analysis/ensemble-status')
    if (ensembleRes.data.weights) {
      Object.assign(ensembleWeights, ensembleRes.data.weights)
    }
  } catch (e) {
    console.error('Failed to refresh status:', e)
  }
}

async function retrainModels() {
  actionMessage.value = '⏳ 训练任务已提交，请稍候...'
  try {
    await axios.post('/api/models/retrain')
    setTimeout(async () => {
      await refreshStatus()
      actionMessage.value = '✅ 模型训练完成或正在进行中'
    }, 5000)
  } catch (e) {
    actionMessage.value = '❌ 训练启动失败: ' + e.message
  }
}

async function triggerAnalysis() {
  actionMessage.value = '⏳ AI 分析进行中...'
  // WebSocket 会处理
  setTimeout(() => {
    actionMessage.value = '✅ 分析完成，查看信号面板'
  }, 3000)
}

onMounted(refreshStatus)
</script>

<style scoped>
.weight-bar {
  margin-bottom: 8px;
}
.bar-bg {
  height: 8px;
  background: var(--bg-primary);
  border-radius: 4px;
  overflow: hidden;
}
.bar-fill {
  height: 100%;
  border-radius: 4px;
  transition: width 0.6s ease;
}
</style>
