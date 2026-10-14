<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, nextTick } from 'vue'
import XmCard from '@/components/ui/XmCard.vue'
import { apiErrorMessage } from '@/api'
import { listLogs, tailLog, type LogFileInfo, type LogTail } from '@/api/logsApi'

const files = ref<LogFileInfo[]>([])
const logsDir = ref('')
const selected = ref<string>('')
const tail = ref<LogTail | null>(null)
const tailLines = ref(200)
const grep = ref('')
const loading = ref(false)
const error = ref('')
const autoRefresh = ref(true)
const refreshSeconds = ref(10)
let timer: ReturnType<typeof setInterval> | null = null
const bodyEl = ref<HTMLElement | null>(null)

const sortedFiles = computed(() => files.value)

function fmtSize(bytes: number): string {
  if (bytes >= 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${bytes} B`
}

function fmtTime(val?: string) {
  if (!val) return '-'
  try { return new Date(val).toLocaleString() } catch { return val }
}

function lineClass(line: string): string {
  const l = line.toLowerCase()
  if (l.includes('error') || l.includes('traceback') || l.includes('[err]')) return 'text-risk-red'
  if (l.includes('warn')) return 'text-risk-yellow'
  return 'text-xm-text-secondary'
}

async function refreshList() {
  try {
    const data = await listLogs()
    files.value = data.files
    logsDir.value = data.dir
    if (!selected.value && data.files.length) {
      await select(data.files[0].name)
    }
  } catch (e: unknown) {
    error.value = apiErrorMessage(e)
  }
}

async function refreshTail() {
  if (!selected.value) return
  loading.value = true
  error.value = ''
  try {
    tail.value = await tailLog(selected.value, tailLines.value, grep.value || undefined)
    await nextTick()
    if (bodyEl.value) bodyEl.value.scrollTop = bodyEl.value.scrollHeight
  } catch (e: unknown) {
    error.value = apiErrorMessage(e)
  } finally {
    loading.value = false
  }
}

async function select(name: string) {
  selected.value = name
  await refreshTail()
}

function applyTimer() {
  if (timer) { clearInterval(timer); timer = null }
  if (autoRefresh.value) {
    timer = setInterval(() => { refreshTail(); refreshList() }, refreshSeconds.value * 1000)
  }
}

function toggleAuto() {
  autoRefresh.value = !autoRefresh.value
  applyTimer()
}

onMounted(async () => {
  await refreshList()
  applyTimer()
})

onBeforeUnmount(() => { if (timer) clearInterval(timer) })
</script>

<template>
  <div class="space-y-4 xm-fade-in">
    <div class="flex items-center justify-between flex-wrap gap-3">
      <div>
        <h2 class="text-lg font-semibold text-xm-text-primary">Server Logs</h2>
        <p class="text-sm text-xm-text-tertiary mt-1">
          Live tail of {{ logsDir || 'logs/' }} — services, pipeline, watchdogs, CD deploys
        </p>
      </div>
      <div class="flex items-center gap-2 flex-wrap">
        <input
          v-model="grep"
          placeholder="filter (grep)"
          class="xm-input !w-40"
          @keyup.enter="refreshTail()"
        >
        <select v-model.number="tailLines" class="xm-input !w-28" @change="refreshTail()">
          <option :value="100">100 lines</option>
          <option :value="200">200 lines</option>
          <option :value="500">500 lines</option>
          <option :value="1000">1000 lines</option>
          <option :value="2000">2000 lines</option>
        </select>
        <button class="xm-btn-secondary" :disabled="loading" @click="refreshTail()">
          {{ loading ? 'Loading…' : 'Refresh' }}
        </button>
        <button
          class="xm-btn-secondary"
          :class="autoRefresh ? '!text-xm-primary' : ''"
          @click="toggleAuto()"
        >
          Auto {{ autoRefresh ? 'ON' : 'OFF' }} ({{ refreshSeconds }}s)
        </button>
      </div>
    </div>

    <div v-if="error" class="text-sm text-risk-red">{{ error }}</div>

    <div class="grid grid-cols-1 lg:grid-cols-4 gap-4">
      <!-- File list -->
      <XmCard class="!p-2 lg:col-span-1 max-h-[70vh] overflow-y-auto">
        <button
          v-for="f in sortedFiles"
          :key="f.name"
          class="w-full text-left px-3 py-2 rounded-lg text-xs font-mono transition-colors"
          :class="f.name === selected
            ? 'bg-xm-primary-light text-xm-primary'
            : 'text-xm-text-secondary hover:bg-xm-bg-surface'"
          @click="select(f.name)"
        >
          <div class="truncate font-semibold">{{ f.name }}</div>
          <div class="text-xxs text-xm-text-tertiary mt-0.5">
            {{ fmtSize(f.size_bytes) }} · {{ fmtTime(f.modified_at) }}
          </div>
        </button>
        <div v-if="!sortedFiles.length" class="p-3 text-xs text-xm-text-tertiary">
          No log files found
        </div>
      </XmCard>

      <!-- Tail view -->
      <XmCard class="!p-0 lg:col-span-3 overflow-hidden">
        <div class="px-4 py-2 border-b border-xm-border-light flex items-center justify-between text-xs text-xm-text-tertiary">
          <span class="font-mono">{{ selected || '—' }}</span>
          <span v-if="tail">
            {{ tail.returned_lines }} lines
            <template v-if="tail.grep"> · grep "{{ tail.grep }}"</template>
            · {{ fmtSize(tail.size_bytes) }}
          </span>
        </div>
        <div
          ref="bodyEl"
          class="h-[62vh] overflow-y-auto bg-xm-bg-sidebar px-4 py-3 font-mono text-xs leading-5 whitespace-pre-wrap break-all"
        >
          <div v-if="tail && tail.truncated_head" class="text-xm-text-tertiary">
            … (older lines truncated — file is {{ fmtSize(tail.size_bytes) }})
          </div>
          <div
            v-for="(line, i) in tail?.lines || []"
            :key="i"
            :class="lineClass(line)"
          >{{ line }}</div>
          <div v-if="tail && !tail.lines.length" class="text-xm-text-tertiary">
            (no matching lines)
          </div>
          <div v-if="!tail && !loading" class="text-xm-text-tertiary">
            Select a log file on the left
          </div>
        </div>
      </XmCard>
    </div>
  </div>
</template>
