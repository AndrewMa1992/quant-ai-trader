/// <reference types="vite/client" />
import axios from 'axios'
import type { AxiosInstance, AxiosResponse, InternalAxiosRequestConfig } from 'axios'

// ★ baseURL uses /api (vite proxy → localhost:8001)
const API_BASE_URL: string = import.meta.env.VITE_API_BASE_URL || '/api'
const API_KEY: string = import.meta.env.VITE_API_KEY || 'dev-api-key-change-in-production'

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
    // Inject API key into every request
    config.headers.set('X-API-Key', API_KEY)

    // Attach request start time for timing
    ;(config as unknown as Record<string, unknown>)._startTime = Date.now()

    return config
  },
  (error) => {
    return Promise.reject(error)
  },
)

// ── Response Interceptor ────────────────────────────────────
apiClient.interceptors.response.use(
  (response: AxiosResponse) => {
    // Log request duration in dev
    if (import.meta.env.DEV) {
      const config = response.config as unknown as Record<string, unknown>
      const startTime = config._startTime as number | undefined
      if (startTime) {
        const duration = Date.now() - startTime
        console.debug(
          `[API] ${response.config.method?.toUpperCase()} ${response.config.url} → ${response.status} (${duration}ms)`,
        )
      }
    }
    return response
  },
  (error) => {
    // Standardized error handling
    if (error.response) {
      const { status, data } = error.response
      const message = data?.message || data?.detail || `Request failed with status ${status}`

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

      // Attach parsed error for upstream handling
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
        message: error.message,
        code: 'REQUEST_ERROR',
      }
    }

    return Promise.reject(error)
  },
)

export default apiClient
export { API_BASE_URL, API_KEY }
