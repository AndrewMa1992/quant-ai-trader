import axios from 'axios'
import type { AxiosError, AxiosInstance, AxiosResponse, InternalAxiosRequestConfig } from 'axios'

/** Error body returned by the gateway. FastAPI may put a string in `detail`. */
interface ApiErrorBody {
  message?: string
  detail?: unknown
  code?: string
  details?: unknown
}

/** Parsed error attached by the response interceptor for callers. */
export interface ParsedApiError {
  status: number
  message: string
  code: string
  details?: unknown
}

declare module 'axios' {
  interface InternalAxiosRequestConfig {
    _startTime?: number
  }
  interface AxiosError {
    parsedError?: ParsedApiError
  }
}

// baseURL uses /api (vite proxy → localhost:8001)
const API_BASE_URL: string = import.meta.env.VITE_API_BASE_URL || '/api'
const API_KEY: string = import.meta.env.VITE_API_KEY || 'dev-api-key-change-in-production'

function errorMessage(data: ApiErrorBody | undefined, status: number): string {
  const raw = data?.message ?? data?.detail
  if (typeof raw === 'string' && raw) return raw
  return `Request failed with status ${status}`
}

/** Create a pre-configured Axios instance for the QAT API. */
const apiClient: AxiosInstance = axios.create({
  baseURL: API_BASE_URL,
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
    'Accept': 'application/json',
  },
})

// ── Request Interceptor ─────────────────────────────────────
apiClient.interceptors.request.use(
  (config: InternalAxiosRequestConfig) => {
    config.headers.set('X-API-Key', API_KEY)
    config._startTime = Date.now()
    return config
  },
  (error: unknown) => Promise.reject(error),
)

// ── Response Interceptor ────────────────────────────────────
apiClient.interceptors.response.use(
  (response: AxiosResponse) => {
    if (import.meta.env.DEV) {
      const startTime = response.config._startTime
      if (startTime) {
        const duration = Date.now() - startTime
        console.debug(
          `[API] ${response.config.method?.toUpperCase()} ${response.config.url} → ${response.status} (${duration}ms)`,
        )
      }
    }
    return response
  },
  (error: AxiosError<ApiErrorBody>) => {
    if (error.response) {
      const { status, data } = error.response
      const message = errorMessage(data, status)

      switch (status) {
        case 401:
          console.error('[API] Authentication failed. Check your API key.')
          break
        case 403:
          console.error(`[API] Forbidden: ${message}`)
          break
        case 404:
          console.error(`[API] Not found: ${error.config?.url}`)
          break
        case 422:
          console.error(`[API] Validation error: ${JSON.stringify(data?.details)}`)
          break
        case 500:
        case 502:
        case 503:
          console.error(`[API] Server error (${status}): ${message}`)
          break
        default:
          console.error(`[API] Error (${status}): ${message}`)
      }

      error.parsedError = {
        status,
        message,
        code: data?.code || 'UNKNOWN',
        details: data?.details,
      }
    } else if (error.request) {
      console.error('[API] No response received — network or CORS issue')
      error.parsedError = {
        status: 0,
        message: 'Network error — no response received',
        code: 'NETWORK_ERROR',
      }
    } else {
      console.error(`[API] Request setup error: ${error.message}`)
      error.parsedError = {
        status: 0,
        message: error.message || 'Request setup failed',
        code: 'REQUEST_ERROR',
      }
    }

    return Promise.reject(error)
  },
)

/** Message from an API failure, including interceptor-parsed bodies. */
export function apiErrorMessage(error: unknown, fallback = 'Request failed'): string {
  if (axios.isAxiosError(error)) {
    if (error.parsedError?.message) return error.parsedError.message
    if (error.message) return error.message
  }
  if (error instanceof Error && error.message) return error.message
  return fallback
}

export default apiClient
export { API_BASE_URL, API_KEY }
