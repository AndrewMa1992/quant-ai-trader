<script setup lang="ts">
interface Row {
  ticker: string
  currentWeight: number
  targetWeight: number
  diff: number
  action: string
}

defineProps<{ rows: Row[] }>()

function pct(v: number): string { return (v * 100).toFixed(2) + '%' }
function diffPct(v: number): string { return (v >= 0 ? '+' : '') + (v * 100).toFixed(2) + '%' }
</script>

<template>
  <div class="overflow-x-auto">
    <table class="w-full text-sm">
      <thead>
        <tr class="border-b border-border text-text-muted text-xs uppercase tracking-wide">
          <th class="text-left p-2">Ticker</th>
          <th class="text-right p-2">Current</th>
          <th class="text-right p-2">Target</th>
          <th class="text-right p-2">Δ</th>
          <th class="text-center p-2">Action</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="row.ticker" class="border-b border-border hover:bg-bg-card-hover">
          <td class="p-2 font-mono text-accent-cyan text-xs">{{ row.ticker }}</td>
          <td class="p-2 text-right text-text-primary">{{ pct(row.currentWeight) }}</td>
          <td class="p-2 text-right text-text-primary">{{ pct(row.targetWeight) }}</td>
          <td class="p-2 text-right font-mono" :class="row.diff >= 0 ? 'text-accent-green' : 'text-accent-red'">{{ diffPct(row.diff) }}</td>
          <td class="p-2 text-center">
            <span class="px-2 py-0.5 rounded text-xs font-medium"
              :class="row.action === 'BUY' ? 'bg-accent-green/20 text-accent-green' : row.action === 'SELL' ? 'bg-accent-red/20 text-accent-red' : 'bg-text-muted/20 text-text-muted'"
            >{{ row.action }}</span>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
