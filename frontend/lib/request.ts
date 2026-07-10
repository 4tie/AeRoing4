import { env } from './env'

export type ApiResponse<T> = {
  success: boolean
  data?: T
  error?: string
}

class RequestError extends Error {
  constructor(public message: string, public status?: number) {
    super(message)
    this.name = 'RequestError'
  }
}

async function request<T>(
  url: string,
  options: RequestInit = {}
): Promise<ApiResponse<T>> {
  const baseUrl = typeof window === 'undefined' 
    ? env.NEXT_PUBLIC_API_URL 
    : window.location.origin

  const fullUrl = url.startsWith('http') ? url : `${baseUrl}${url}`

  try {
    const response = await fetch(fullUrl, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        ...options.headers,
      },
    })

    const data = await response.json()

    if (!response.ok) {
      return {
        success: false,
        error: data.error || response.statusText,
      }
    }

    return {
      success: true,
      data,
    }
  } catch (error) {
    console.error(`Fetch error for ${fullUrl}:`, error)
    return {
      success: false,
      error: error instanceof Error ? error.message : 'Unknown error',
    }
  }
}

export const apiClient = {
  get: <T>(url: string, options?: RequestInit) => 
    request<T>(url, { ...options, method: 'GET' }),
  post: <T>(url: string, body: any, options?: RequestInit) => 
    request<T>(url, { ...options, method: 'POST', body: JSON.stringify(body) }),
  put: <T>(url: string, body: any, options?: RequestInit) => 
    request<T>(url, { ...options, method: 'PUT', body: JSON.stringify(body) }),
  delete: <T>(url: string, options?: RequestInit) => 
    request<T>(url, { ...options, method: 'DELETE' }),
}
