export type AskStatus =
  | 'answered'
  | 'needs_clarification'
  | 'unsupported'
  | 'error'

export type Visualization = {
  type: 'line' | 'bar'
  x_key: string
  y_key: string
  title: string
}

export type FilterApplied = {
  field: string
  operator: string
  values: string[]
}

export type AskOverrides = {
  date_range?: { start: string | null; end: string | null } | null
  filters?: FilterApplied[]
}

export type DateRange = {
  start: string | null
  end: string | null
}

export type SupportingRow = Record<string, string | number | null>

export type PeriodResult = {
  label: string
  start: string
  end: string
  metrics: Record<string, number | null>
  row_count: number
  has_data: boolean
}

export type ChangeResult = {
  metric: string
  absolute_change: number | null
  percentage_change: number | null
  baseline_zero: boolean
}

export type ExecutionTraceStep = {
  step: number
  name: string
  detail: string
}

export type QueryPlanSummary = {
  status?: string
  operation?: string
  metrics?: string[]
  group_by?: string[]
  filters?: FilterApplied[]
  date_range?: DateRange | null
  limit?: number
}

export type AskResponse = {
  status: AskStatus
  answer: string
  metrics: Record<string, number | null>
  supporting_data: SupportingRow[]
  calculation: string
  filters_applied: FilterApplied[]
  date_range: DateRange | null
  visualization: Visualization | null
  warnings: string[]
  suggestions: string[]
  metric_definitions: Record<string, string>
  interpretation_source: string
  interpretation_confidence?: number
  response_time_ms?: number
  query_plan_summary?: QueryPlanSummary | null
  agent_execution_trace?: ExecutionTraceStep[]
  has_data: boolean
  question?: string
  reconciliation?: Record<string, number | null>
  periods?: PeriodResult[]
  changes?: ChangeResult[]
  clarification_question?: string | null
  unsupported_reason?: string | null
}

export type DatasetSummary = {
  row_count: number
  date_coverage: {
    start: string | null
    end: string | null
  }
  status_counts: Record<string, number>
  data_quality_warnings: string[]
}

export type Example = {
  preset_id: string
  label: string
  question: string
}

export type Health = {
  status: string
  database: string
  groq_configured: boolean
  groq_model_configured?: boolean
  currency_code?: string | null
}
