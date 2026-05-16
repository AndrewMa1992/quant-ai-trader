<template>
  <div class="signal-panel">
    <!-- 顶部操作栏 -->
    <div class="signal-panel__toolbar">
      <div class="signal-panel__toolbar-left">
        <button
          class="btn btn-primary"
          :disabled="loading"
          @click="$emit('run-analysis')"
        >
          <span v-if="loading" class="spinner"></span>
          {{ loading ? '分析中...' : '运行分析' }}
        </button>
        <label class="signal-panel__autorefresh">
          <input
            type="checkbox"
            :checked="autoRefresh"
            @change="$emit('toggle-autorefresh', $event.target.checked)"
          />
          <span>自动刷新 30s</span>
        </label>
      </div>
      <div class="signal-panel__toolbar-right" v-if="lastUpdated">
        <span class="signal-panel__last-updated">上次更新: {{ lastUpdated }}</span>
      </div>
    </div>

    <!-- 筛选 tabs -->
    <div class="signal-panel__tabs">
      <button
        v-for="tab in filterTabs"
        :key="tab.key"
        class="signal-panel__tab"
        :class="{ active: activeFilter === tab.key }"
        @click="setFilter(tab.key)"
      >
        {{ tab.label }}
        <span class="signal-panel__tab-count">({{ tab.count }})</span>
      </button>
    </div>

    <!-- 加载状态 -->
    <div v-if="loading" class="signal-panel__loading">
      <div class="spinner"></div>
      <span>正在分析市场数据...</span>
    </div>

    <!-- 信号卡片列表 -->
    <div v-else class="signal-panel__list">
      <SignalCard
        v-for="item in filteredSignals"
        :key="item.ticker"
        :signal="item"
        :history="getHistory(item.ticker)"
      />
      <div v-if="filteredSignals.length === 0" class="signal-panel__empty">
        暂无信号数据
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import SignalCard from './SignalCard.vue'

const props = defineProps({
  signals: {
    type: Object,
    required: true,
  },
  signalHistory: {
    type: Object,
    default: () => ({}),
  },
  loading: {
    type: Boolean,
    default: false,
  },
  lastUpdated: {
    type: String,
    default: '',
  },
  autoRefresh: {
    type: Boolean,
    default: false,
  },
})

const emit = defineEmits(['run-analysis', 'toggle-autorefresh', 'filter-change'])

const activeFilter = ref('all')

const filterTabs = computed(() => {
  const allSignals = Object.values(props.signals)
  const buyCount = allSignals.filter((s) => s.decision === 'buy').length
  const sellCount = allSignals.filter((s) => s.decision === 'sell').length
  const holdCount = allSignals.filter((s) => s.decision === 'hold').length
  return [
    { key: 'all', label: '全部', count: allSignals.length },
    { key: 'buy', label: 'Buy', count: buyCount },
    { key: 'sell', label: 'Sell', count: sellCount },
    { key: 'hold', label: 'Hold', count: holdCount },
  ]
})

const filteredSignals = computed(() => {
  const all = Object.values(props.signals)
  if (activeFilter.value === 'all') {
    return all.sort((a, b) => (b.strength || 0) - (a.strength || 0))
  }
  return all
    .filter((s) => s.decision === activeFilter.value)
    .sort((a, b) => (b.strength || 0) - (a.strength || 0))
})

function setFilter(key) {
  activeFilter.value = key
  emit('filter-change', key)
}

function getHistory(ticker) {
  return props.signalHistory[ticker] || []
}

// 不需要自动刷新逻辑，由父组件控制
</script>

<style scoped>
.signal-panel {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.signal-panel__toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}

.signal-panel__toolbar-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.signal-panel__toolbar-right {
  font-size: 11px;
}

.signal-panel__last-updated {
  color: var(--text-muted);
}

.signal-panel__autorefresh {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: var(--text-secondary);
  cursor: pointer;
}
.signal-panel__autorefresh input {
  cursor: pointer;
}

.signal-panel__tabs {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
}

.signal-panel__tab {
  background: none;
  border: 1px solid var(--border-color);
  border-radius: 4px;
  padding: 4px 10px;
  font-size: 11px;
  color: var(--text-secondary);
  cursor: pointer;
  transition: all 0.2s;
}
.signal-panel__tab:hover {
  background: var(--bg-hover);
}
.signal-panel__tab.active {
  background: var(--accent-blue);
  color: white;
  border-color: var(--accent-blue);
}

.signal-panel__tab-count {
  font-size: 10px;
  opacity: 0.8;
}

.signal-panel__loading {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 40px 0;
  color: var(--text-muted);
  font-size: 13px;
}

.signal-panel__list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.signal-panel__empty {
  text-align: center;
  padding: 40px 0;
  color: var(--text-muted);
}

.spinner {
  display: inline-block;
  width: 16px;
  height: 16px;
  border: 2px solid var(--border-color);
  border-top-color: var(--accent-blue);
  border-radius: 50%;
  animation: spin 0.6s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
