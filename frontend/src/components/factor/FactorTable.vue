<script setup lang="ts">
import { computed, ref } from 'vue'

interface Factor {
  id: string
  name: string
  category: string
  subcategory: string
  description: string
  frequency: string
  direction: number
}

const props = defineProps<{ factors: Factor[]; loading: boolean }>()
const sortKey = ref('id')
const sortAsc = ref(true)
const filterCategory = ref('')
const filterText = ref('')

const categories = computed(() => [...new Set(props.factors.map((f) => f.category))])

const filtered = computed(() => {
  let list = [...props.factors]
  if (filterCategory.value) list = list.filter((f) => f.category === filterCategory.value)
  if (filterText.value) {
    const q = filterText.value.toLowerCase()
    list = list.filter((f) => f.name.toLowerCase().includes(q) || f.id.toLowerCase().includes(q))
  }
  list.sort((a, b) => {
    const va = String((a as unknown as Record<string, unknown>)[sortKey.value] ?? '')
    const vb = String((b as unknown as Record<string, unknown>)[sortKey.value] ?? '')
    return sortAsc.value ? va.localeCompare(vb) : vb.localeCompare(va)
  })
  return list
})

function toggleSort(key: string) {
  if (sortKey.value === key) sortAsc.value = !sortAsc.value
  else { sortKey.value = key; sortAsc.value = true }
}

function dirLabel(d: number): string {
  if (d > 0) return 'Long'
  if (d < 0) return 'Short'
  return 'Neutral'
}
</script>

<template>
  <div>
    <!-- Filters -->
    <div class="flex gap-3 mb-3 flex-wrap">
      <select v-model="filterCategory" class="bg-bg-card border border-border rounded px-3 py-1 text-sm text-text-primary">
        <option value="">All Categories</option>
        <option v-for="cat in categories" :key="cat" :value="cat">{{ cat }}</option>
      </select>
      <input v-model="filterText" placeholder="Search factors..." class="bg-bg-card border border-border rounded px-3 py-1 text-sm text-text-primary flex-1 min-w-[150px]" />
    </div>

    <!-- Table -->
    <div v-if="loading" class="text-text-muted text-sm py-4">Loading factors...</div>
    <div v-else class="overflow-x-auto">
      <table class="w-full text-sm">
        <thead>
          <tr class="border-b border-border text-text-muted text-xs uppercase tracking-wide">
            <th class="text-left p-2 cursor-pointer select-none" @click="toggleSort('id')">ID {{ sortKey === 'id' ? (sortAsc ? '▲' : '▼') : '' }}</th>
            <th class="text-left p-2 cursor-pointer select-none" @click="toggleSort('name')">Name {{ sortKey === 'name' ? (sortAsc ? '▲' : '▼') : '' }}</th>
            <th class="text-left p-2 cursor-pointer select-none" @click="toggleSort('category')">Category</th>
            <th class="text-left p-2">Frequency</th>
            <th class="text-left p-2">Direction</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="f in filtered.slice(0, 50)" :key="f.id" class="border-b border-border hover:bg-bg-card-hover transition-colors">
            <td class="p-2 font-mono text-accent-cyan text-xs">{{ f.id }}</td>
            <td class="p-2 text-text-primary">{{ f.name }}</td>
            <td class="p-2">
              <span class="px-2 py-0.5 rounded text-xs" :class="{
                'bg-accent-blue/20 text-accent-blue': f.category === 'technical',
                'bg-accent-purple/20 text-accent-purple': f.category === 'fundamental',
                'bg-accent-yellow/20 text-accent-yellow': f.category === 'alternative',
                'bg-accent-cyan/20 text-accent-cyan': f.category === 'microstructure',
              }">{{ f.category }}</span>
            </td>
            <td class="p-2 text-text-muted">{{ f.frequency }}</td>
            <td class="p-2">
              <span class="px-2 py-0.5 rounded text-xs font-medium"
                :class="f.direction > 0 ? 'bg-accent-green/20 text-accent-green' : f.direction < 0 ? 'bg-accent-red/20 text-accent-red' : 'bg-text-muted/20 text-text-muted'"
              >{{ dirLabel(f.direction) }}</span>
            </td>
          </tr>
        </tbody>
      </table>
      <p v-if="filtered.length > 50" class="text-xs text-text-muted mt-2">
        Showing 50 of {{ filtered.length }} factors
      </p>
    </div>
  </div>
</template>
