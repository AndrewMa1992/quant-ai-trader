<script setup lang="ts">
import { computed, onMounted } from 'vue'
import XmCard from '@/components/ui/XmCard.vue'
import XmStatusDot from '@/components/ui/XmStatusDot.vue'
import XmBadge from '@/components/ui/XmBadge.vue'
import { useDataStore } from '@/stores/useDataStore'

const dataStore = useDataStore()

const syncOkCount = computed(() => dataStore.syncStatuses.filter(s => s.status === 'success').length)
const syncErrCount = computed(() => dataStore.syncErrorCount)

function statusDot(status: string) {
  switch ((status || '').toLowerCase()) {
    case 'success': return 'green'
    case 'error': return 'red'
    case 'running': return 'yellow'
    default: return 'gray'
  }
}

function statusBadge(status: string) {
  switch ((status || '').toLowerCase()) {
    case 'success': return 'success'
    case 'error': return 'danger'
    case 'running': return 'warning'
    default: return 'info'
  }
}

function fmtTime(val?: string) {
  if (!val) return '-'
  try { return new Date(val).toLocaleString() } catch { return val }
}

onMounted(() => {
  dataStore.fetchSyncStatus()
})
</script>

<template>
  <div class="space-y-6 xm-fade-in">
    <!-- Header -->
    <div class="flex items-center justify-between">
      <div>
        <h2 class="text-lg font-semibold text-xm-text-primary">Data Sync Dashboard</h2>
        <p class="text-sm text-xm-text-tertiary mt-1">Monitor data synchronization status</p>
      </div>
      <div class="flex items-center gap-3">
        <button class="xm-btn-secondary" @click="dataStore.fetchSyncStatus()">
          Refresh Status
        </button>
        <button
          class="xm-btn-primary"
          :disabled="dataStore.syncInProgress"
          @click="dataStore.triggerSync(false)"
        >
          {{ dataStore.syncInProgress ? 'Syncing...' : 'Trigger Full Sync' }}
        </button>
      </div>
    </div>

    <!-- KPI Row -->
    <div class="grid grid-cols-2 sm:grid-cols-4 gap-4">
      <XmCard class="!p-4">
        <div class="xm-metric-label">Sync Types</div>
        <div class="xm-metric-value text-lg">{{ dataStore.syncStatuses.length }}</div>
      </XmCard>
      <XmCard class="!p-4">
        <div class="xm-metric-label">Success</div>
        <div class="xm-metric-value text-lg text-profit">{{ syncOkCount }}</div>
      </XmCard>
      <XmCard class="!p-4">
        <div class="xm-metric-label">Errors</div>
        <div class="xm-metric-value text-lg" :class="syncErrCount > 0 ? 'text-loss' : 'text-xm-text-secondary'">
          {{ syncErrCount }}
        </div>
      </XmCard>
      <XmCard class="!p-4">
        <div class="xm-metric-label">Sync Progress</div>
        <div class="xm-metric-value text-lg" :class="dataStore.syncInProgress ? 'text-xm-primary' : 'text-xm-text-secondary'">
          {{ dataStore.syncInProgress ? 'Running' : 'Idle' }}
        </div>
      </XmCard>
    </div>

    <!-- Rate Limiter Card -->
    <XmCard v-if="Object.keys(dataStore.rateLimiterStats).length > 0" title="Rate Limiter" class="!p-5">
      <div class="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <div
          v-for="(value, key) in dataStore.rateLimiterStats"
          :key="key"
          class="p-3 rounded-lg bg-xm-bg-surface"
        >
          <div class="text-xxs text-xm-text-tertiary uppercase">{{ key }}</div>
          <div class="text-sm font-mono font-semibold mt-1">{{ value }}</div>
        </div>
      </div>
    </XmCard>

    <!-- Sync Status Cards -->
    <XmCard title="Sync Status" :subtitle="`${dataStore.syncStatuses.length} sync types registered`">
      <div v-if="dataStore.syncStatuses.length > 0" class="divide-y divide-xm-border-light">
        <div
          v-for="sync in dataStore.syncStatuses"
          :key="sync.sync_type"
          class="flex items-center gap-4 py-3 px-1"
        >
          <XmStatusDot :status="statusDot(sync.status) as any" />
          <div class="flex-1 min-w-0">
            <div class="flex items-center gap-2">
              <span class="text-sm font-mono font-semibold">{{ sync.sync_type }}</span>
              <XmBadge :variant="statusBadge(sync.status) as any">{{ sync.status }}</XmBadge>
            </div>
            <div class="flex items-center gap-4 mt-1 text-xs text-xm-text-tertiary">
              <span v-if="sync.last_sync_at">Last sync: {{ fmtTime(sync.last_sync_at) }}</span>
              <span v-if="sync.last_success_at">Last success: {{ fmtTime(sync.last_success_at) }}</span>
              <span v-if="sync.record_count !== undefined">Records: {{ sync.record_count }}</span>
            </div>
            <div
              v-if="sync.error_message"
              class="mt-1.5 text-xs text-loss bg-loss-bg rounded px-2 py-1 inline-block"
            >
              {{ sync.error_message }}
            </div>
          </div>
        </div>
      </div>
      <div v-else class="text-center py-10 text-xm-text-tertiary text-sm">
        No sync data available. Trigger a sync to populate.
      </div>
    </XmCard>

    <!-- Error Banner -->
    <div
      v-if="dataStore.error"
      class="p-3 rounded-lg bg-loss-bg border border-loss/20 text-sm text-loss"
    >
      {{ dataStore.error }}
    </div>
  </div>
</template>
