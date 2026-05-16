<template>
  <div class="signal-card" :class="'signal-card--' + signal.decision">
    <div class="signal-card__header">
      <div class="signal-card__ticker-row">
        <strong class="signal-card__ticker">{{ signal.ticker }}</strong>
        <span class="badge" :class="'badge-' + signal.decision">{{ signal.decision?.toUpperCase() }}</span>
      </div>
      <div class="signal-card__metrics">
        <div class="signal-card__metric">
          <span class="signal-card__metric-label">强度</span>
          <div class="signal-card__strength-bar-wrapper">
            <div
              class="signal-card__strength-bar"
              :style="{ width: strengthPercent, backgroundColor: strengthBarColor }"
            ></div>
          </div>
          <span class="signal-card__metric-value">{{ strengthPercent }}</span>
        </div>
        <div class="signal-card__metric">
          <span class="signal-card__metric-label">置信度</span>
          <span class="signal-card__metric-value">{{ (signal.confidence * 100)?.toFixed(0) }}%</span>
        </div>
        <div class="signal-card__metric" v-if="signal.position_size !== undefined">
          <span class="signal-card__metric-label">建议仓位</span>
          <span class="signal-card__metric-value">{{ (signal.position_size * 100)?.toFixed(0) }}%</span>
        </div>
      </div>
    </div>

    <div class="signal-card__trend" v-if="history && history.length > 1">
      <SignalTrendChart
        :ticker="signal.ticker"
        :history="history"
        height="60px"
      />
    </div>

    <div class="signal-card__actions">
      <button class="signal-card__expand-btn" @click="expanded = !expanded">
        {{ expanded ? '收起详情' : '展开详情' }}
        <span class="signal-card__arrow" :class="{ expanded }">&#9660;</span>
      </button>
    </div>

    <div class="signal-card__details" v-if="expanded && signal.details">
      <table class="signal-card__details-table">
        <thead>
          <tr>
            <th>模型</th>
            <th>评分</th>
            <th>权重</th>
            <th>置信度</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(detail, modelName) in signal.details" :key="modelName">
            <td class="signal-card__model-name">{{ modelLabel(modelName) }}</td>
            <td>{{ detail.score?.toFixed(3) }}</td>
            <td>{{ (detail.weight * 100)?.toFixed(0) }}%</td>
            <td>{{ (detail.confidence * 100)?.toFixed(0) }}%</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import SignalTrendChart from './SignalTrendChart.vue'

const props = defineProps({
  signal: {
    type: Object,
    required: true,
  },
  history: {
    type: Array,
    default: () => [],
  },
})

const expanded = ref(false)

const strengthPercent = computed(() => {
  const pct = Math.abs(props.signal.strength || 0) * 100
  return pct.toFixed(0) + '%'
})

const strengthBarColor = computed(() => {
  const strength = Math.abs(props.signal.strength || 0)
  if (strength >= 0.6) return '#8b5cf6'
  if (strength >= 0.3) return '#a78bfa'
  return '#c4b5fd'
})

function modelLabel(name) {
  const labels = {
    transformer: 'Transformer',
    rl_agent: 'RL Agent',
    sentiment: 'Sentiment',
    technical: 'Technical',
  }
  return labels[name] || name
}
</script>

<style scoped>
.signal-card {
  background: var(--bg-card-hover);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm);
  padding: 12px;
  transition: border-color 0.2s;
}
.signal-card--buy {
  border-left: 3px solid #22c55e;
}
.signal-card--sell {
  border-left: 3px solid #ef4444;
}
.signal-card--hold {
  border-left: 3px solid #6b7280;
}

.signal-card__header {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.signal-card__ticker-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.signal-card__ticker {
  font-size: 14px;
}

.signal-card__metrics {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.signal-card__metric {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
}

.signal-card__metric-label {
  color: var(--text-muted);
  min-width: 56px;
}

.signal-card__metric-value {
  color: var(--text-secondary);
  font-variant-numeric: tabular-nums;
  min-width: 40px;
  text-align: right;
}

.signal-card__strength-bar-wrapper {
  flex: 1;
  height: 6px;
  background: var(--border-color);
  border-radius: 3px;
  overflow: hidden;
}

.signal-card__strength-bar {
  height: 100%;
  border-radius: 3px;
  transition: width 0.3s ease;
}

.signal-card__trend {
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px solid var(--border-color);
}

.signal-card__actions {
  margin-top: 8px;
  text-align: center;
}

.signal-card__expand-btn {
  background: none;
  border: none;
  color: var(--text-muted);
  font-size: 11px;
  cursor: pointer;
  padding: 4px 8px;
  border-radius: 4px;
  transition: background 0.2s;
}
.signal-card__expand-btn:hover {
  background: var(--bg-hover);
}

.signal-card__arrow {
  display: inline-block;
  font-size: 8px;
  margin-left: 4px;
  transition: transform 0.2s;
}
.signal-card__arrow.expanded {
  transform: rotate(180deg);
}

.signal-card__details {
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px solid var(--border-color);
}

.signal-card__details-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 11px;
}

.signal-card__details-table th,
.signal-card__details-table td {
  padding: 4px 6px;
  text-align: right;
}

.signal-card__details-table th {
  color: var(--text-muted);
  font-weight: normal;
  text-align: right;
}

.signal-card__model-name {
  text-align: left;
  color: var(--text-primary);
}
</style>
