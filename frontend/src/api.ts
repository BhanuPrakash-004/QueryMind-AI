import type {
  AskOverrides,
  AskResponse,
  DatasetSummary,
  Example,
  Health,
} from './types'

type ErrorPayload = {
  answer?: string
  message?: string
  detail?: unknown
}

function errorMessage(payload: unknown, fallback: string): string {
  if (payload && typeof payload === 'object') {
    const value = payload as ErrorPayload
    if (typeof value.answer === 'string' && value.answer.trim()) {
      return value.answer
    }
    if (typeof value.message === 'string' && value.message.trim()) {
      return value.message
    }
  }
  return fallback
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(path, {
      ...init,
      headers: {
        'Content-Type': 'application/json',
        ...(init?.headers ?? {}),
      },
    })
  } catch {
    throw new Error(
      'Could not reach the QueryMind-AI API. Check that the backend is running.',
    )
  }

  const payload = await response.json().catch(() => null)
  if (!response.ok) {
    throw new Error(
      errorMessage(payload, 'The request failed. Please try again.'),
    )
  }
  return payload as T
}

export function getSummary(): Promise<DatasetSummary> {
  return request<DatasetSummary>('/api/dataset/summary')
}

export function getExamples(): Promise<{ examples: Example[] }> {
  return request<{ examples: Example[] }>('/api/examples')
}

export function getHealth(): Promise<Health> {
  return request<Health>('/api/health')
}

export function askQuestion(
  question: string,
  presetId: string | null,
  overrides?: AskOverrides,
  sessionId?: string | null,
): Promise<AskResponse> {
  return request<AskResponse>('/api/ask', {
    method: 'POST',
    body: JSON.stringify({
      question,
      preset_id: presetId,
      overrides: overrides ?? null,
      session_id: sessionId ?? null,
    }),
  })
}

export async function exportCsv(
  question: string,
  presetId: string | null,
  overrides?: AskOverrides,
): Promise<void> {
  const response = await fetch('/api/export', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      question,
      preset_id: presetId,
      overrides: overrides ?? null,
    }),
  })
  if (!response.ok) {
    throw new Error('Export failed. Please check the query and try again.')
  }
  const blob = await response.blob()
  const url = window.URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `sales_data_${Date.now()}.csv`
  document.body.appendChild(a)
  a.click()
  a.remove()
  window.URL.revokeObjectURL(url)
}
