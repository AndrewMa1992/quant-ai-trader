/** api/logsApi.ts – /api/v2/logs server log viewer endpoints */
import apiClient from './index'

const BASE = '/v2/logs'

export interface LogFileInfo {
  name: string
  size_bytes: number
  modified_at: string
}

export interface LogTail {
  name: string
  size_bytes: number
  modified_at: string
  requested_lines: number
  returned_lines: number
  grep: string | null
  truncated_head: boolean
  lines: string[]
}

export async function listLogs(): Promise<{ dir: string; files: LogFileInfo[] }> {
  const { data } = await apiClient.get(BASE)
  return data.data
}

export async function tailLog(name: string, tail = 200, grep?: string): Promise<LogTail> {
  const params: Record<string, string | number> = { tail }
  if (grep) params.grep = grep
  const { data } = await apiClient.get(`${BASE}/${encodeURIComponent(name)}`, { params })
  return data.data
}
