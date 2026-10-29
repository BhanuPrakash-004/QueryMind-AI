import { useEffect, useMemo, useState } from "react";
import type { FormEvent, KeyboardEvent } from "react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { askQuestion, exportCsv, getExamples, getHealth } from "./api";
import type {
  AskOverrides,
  AskResponse,
  Example,
  FilterApplied,
  Health,
  SupportingRow,
  Visualization,
} from "./types";

const FALLBACK_EXAMPLES: Example[] = [
  {
    preset_id: "total_revenue",
    label: "Total revenue",
    question: "What is the total revenue?",
  },
  {
    preset_id: "top_product_revenue",
    label: "Top product",
    question: "Which product generated the highest revenue?",
  },
  {
    preset_id: "monthly_revenue_trend",
    label: "Monthly trend",
    question: "What is the monthly revenue trend?",
  },
  {
    preset_id: "top_region_revenue",
    label: "Top region",
    question: "Which region generated the highest sales?",
  },
  {
    preset_id: "compare_jan_feb",
    label: "Compare months",
    question: "How did revenue change between January and February?",
  },
];

const METRIC_LABELS: Record<string, string> = {
  net_revenue: "Net revenue",
  gross_sales: "Gross sales",
  total_discounts: "Discounts",
  transaction_count: "Transactions",
  units_sold: "Units sold",
  average_order_value: "Average order value",
};

const DIMENSION_LABELS: Record<string, string> = {
  product: "Product",
  category: "Category",
  region: "Region",
  sales_channel: "Sales channel",
  order_month: "Month",
  status: "Status",
  period: "Period",
};

const COUNT_METRICS = new Set(["transaction_count", "units_sold"]);
const MONEY_METRICS = new Set([
  "net_revenue",
  "gross_sales",
  "total_discounts",
  "average_order_value",
]);

/* Chart palette: warm, high-contrast, per-dimension accents. */
const CHART_COLORS = [
  "#e85d2e",
  "#e0a106",
  "#24866a",
  "#8347c4",
  "#b23a1d",
  "#b98207",
  "#1f6b52",
];
const TREND_STROKE = "#d64a24";
const GRID_STROKE = "#e7ddc9";
const AXIS_TICK = "#8a8474";

const moneyFormatter = new Intl.NumberFormat("en-US", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});
const countFormatter = new Intl.NumberFormat("en-US");
const compactFormatter = new Intl.NumberFormat("en-US", {
  notation: "compact",
  maximumFractionDigits: 1,
});

function metricLabel(key: string): string {
  return METRIC_LABELS[key] ?? key.replaceAll("_", " ");
}
function dimensionLabel(key: string): string {
  return DIMENSION_LABELS[key] ?? key.replaceAll("_", " ");
}
function formatMoney(
  value: number | string | null | undefined,
  currencyCode: string | null,
): string {
  if (value === null || value === undefined || value === "") return "—";
  const numeric = Number(value);
  if (Number.isNaN(numeric)) return "—";
  const formatted = moneyFormatter.format(numeric);
  return currencyCode ? `${currencyCode} ${formatted}` : formatted;
}
function formatCount(value: number | string | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  const numeric = Number(value);
  return Number.isNaN(numeric) ? "—" : countFormatter.format(numeric);
}
function formatMetricValue(
  key: string,
  value: number | string | null | undefined,
  currencyCode: string | null,
): string {
  if (COUNT_METRICS.has(key)) return formatCount(value);
  if (MONEY_METRICS.has(key)) return formatMoney(value, currencyCode);
  if (value === null || value === undefined) return "—";
  return String(value);
}
function formatMonth(value: string | number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  const text = String(value);
  const parsed = new Date(`${text.slice(0, 10)}T00:00:00Z`);
  if (Number.isNaN(parsed.getTime())) return text;
  return parsed.toLocaleDateString("en-US", {
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  });
}
function formatDateRange(range: AskResponse["date_range"]): string {
  if (!range) return "All available dates";
  if (range.start && range.end) return `${range.start} to ${range.end}`;
  if (range.start) return `From ${range.start}`;
  if (range.end) return `Through ${range.end}`;
  return "All available dates";
}
function formatFilter(filter: FilterApplied): string {
  const values = filter.values.join(", ");
  return `${dimensionLabel(filter.field)} ${filter.operator === "in" ? `in (${values})` : `= ${values}`}`;
}
function sourceLabel(source: string): string {
  if (source === "preset") return "Preset plan";
  if (source === "groq") return "Groq interpretation";
  if (source === "rules") return "Rule-based interpretation";
  return "No interpretation";
}
function truncate(value: string, length: number): string {
  return value.length > length ? `${value.slice(0, length - 1)}…` : value;
}

function statusTone(status: string): string {
  if (status === "answered")
    return "bg-pine-100 text-pine-700 ring-pine-600/30";
  if (status === "needs_clarification")
    return "bg-gold-100 text-gold-600 ring-gold-500/30";
  if (status === "unsupported")
    return "bg-cream-100 text-ink-500 ring-ink-300/40";
  return "bg-brand-100 text-brand-700 ring-brand-500/30";
}

function StatusBadge({ children, tone }: { children: string; tone?: string }) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-1 text-xs font-semibold ring-1 ring-inset ${tone ?? "bg-cream-100 text-ink-500 ring-ink-300/40"}`}
    >
      {children}
    </span>
  );
}

function MetricCard({
  metricKey,
  value,
  currencyCode,
  index,
}: {
  metricKey: string;
  value: number | null;
  currencyCode: string | null;
  index: number;
}) {
  const accent = CHART_COLORS[index % CHART_COLORS.length];
  return (
    <div className="relative overflow-hidden rounded-2xl border border-cream-200 bg-white p-4 shadow-sm">
      <span
        className="absolute inset-x-0 top-0 h-1"
        style={{ backgroundColor: accent }}
        aria-hidden="true"
      />
      <p className="text-xs font-medium uppercase tracking-wide text-ink-400">
        {metricLabel(metricKey)}
      </p>
      <p className="mt-2 text-xl font-semibold tracking-tight text-ink-900">
        {formatMetricValue(metricKey, value, currencyCode)}
      </p>
    </div>
  );
}

function MetricsGrid({
  metrics,
  currencyCode,
}: {
  metrics: Record<string, number | null>;
  currencyCode: string | null;
}) {
  const entries = Object.entries(metrics).filter(([, value]) => value !== null);
  if (entries.length === 0) return null;
  return (
    <section aria-labelledby="metrics-heading">
      <h3 id="metrics-heading" className="sr-only">
        Key metrics
      </h3>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {entries.map(([key, value], index) => (
          <MetricCard
            key={key}
            metricKey={key}
            value={value}
            currencyCode={currencyCode}
            index={index}
          />
        ))}
      </div>
    </section>
  );
}

function Reconciliation({
  reconciliation,
  currencyCode,
}: {
  reconciliation: Record<string, number | null>;
  currencyCode: string | null;
}) {
  const rows = [
    { key: "gross_sales", label: "Gross sales" },
    { key: "discounts", label: "Discounts" },
    { key: "net_revenue", label: "Net revenue" },
    {
      key: "excluded_net_revenue",
      label: "Excluded non-completed net revenue",
    },
    { key: "excluded_transaction_count", label: "Excluded transactions" },
  ].filter((row) => reconciliation[row.key] !== undefined);
  if (rows.length === 0) return null;
  return (
    <section className="rounded-3xl border border-cream-200 bg-white p-5 shadow-sm sm:p-6">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-base font-semibold text-ink-900">
          Revenue reconciliation
        </h3>
        <p className="text-xs text-ink-400">
          Completed net revenue = gross sales − discounts
        </p>
      </div>
      <dl className="mt-4 grid gap-3 sm:grid-cols-2">
        {rows.map((row) => (
          <div
            key={row.key}
            className="flex items-baseline justify-between gap-4 rounded-xl bg-cream-50 px-4 py-3"
          >
            <dt className="text-sm text-ink-500">{row.label}</dt>
            <dd className="text-sm font-semibold text-ink-900">
              {formatMetricValue(
                row.key,
                reconciliation[row.key],
                currencyCode,
              )}
            </dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

function ChartPanel({
  visualization,
  data,
  currencyCode,
}: {
  visualization: Visualization;
  data: SupportingRow[];
  currencyCode: string | null;
}) {
  const tooltipStyle = {
    borderRadius: "14px",
    border: "1px solid #e7ddc9",
    backgroundColor: "#ffffff",
    boxShadow: "0 12px 30px rgba(28, 26, 21, 0.12)",
    fontSize: "13px",
  };
  const isMoney = MONEY_METRICS.has(visualization.y_key);
  const singleSeries = visualization.type !== "line" && data.length <= 2;

  return (
    <section className="rounded-3xl border border-cream-200 bg-white p-5 shadow-sm sm:p-6">
      <h3 className="text-base font-semibold text-ink-900">
        {visualization.title}
      </h3>
      <div
        className="mt-4 h-72 w-full"
        role="img"
        aria-label={visualization.title}
      >
        <ResponsiveContainer width="100%" height="100%">
          {visualization.type === "line" ? (
            <AreaChart
              data={data}
              margin={{ top: 8, right: 16, left: 0, bottom: 0 }}
            >
              <defs>
                <linearGradient id="trendFill" x1="0" y1="0" x2="0" y2="1">
                  <stop
                    offset="0%"
                    stopColor={TREND_STROKE}
                    stopOpacity={0.35}
                  />
                  <stop
                    offset="100%"
                    stopColor={TREND_STROKE}
                    stopOpacity={0.02}
                  />
                </linearGradient>
              </defs>
              <CartesianGrid
                strokeDasharray="3 3"
                vertical={false}
                stroke={GRID_STROKE}
              />
              <XAxis
                dataKey={visualization.x_key}
                tickFormatter={(value) =>
                  visualization.x_key === "order_month"
                    ? formatMonth(value)
                    : truncate(String(value), 16)
                }
                tick={{ fontSize: 12, fill: AXIS_TICK }}
                axisLine={false}
                tickLine={false}
              />
              <YAxis
                tickFormatter={(value) =>
                  compactFormatter.format(Number(value))
                }
                tick={{ fontSize: 12, fill: AXIS_TICK }}
                axisLine={false}
                tickLine={false}
                width={72}
              />
              <Tooltip
                formatter={(value) =>
                  formatMetricValue(
                    visualization.y_key,
                    Number(value),
                    currencyCode,
                  )
                }
                labelFormatter={(label) =>
                  visualization.x_key === "order_month"
                    ? formatMonth(String(label))
                    : String(label)
                }
                contentStyle={tooltipStyle}
                cursor={{
                  stroke: TREND_STROKE,
                  strokeWidth: 1,
                  strokeDasharray: "4 4",
                }}
              />
              <Area
                type="monotone"
                dataKey={visualization.y_key}
                stroke={TREND_STROKE}
                strokeWidth={3}
                fill="url(#trendFill)"
                dot={{ r: 4, fill: TREND_STROKE, strokeWidth: 0 }}
                activeDot={{ r: 6, fill: TREND_STROKE }}
              />
            </AreaChart>
          ) : (
            <BarChart
              data={data}
              margin={{ top: 8, right: 16, left: 0, bottom: 0 }}
            >
              <defs>
                <linearGradient id="barFill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#e85d2e" />
                  <stop offset="100%" stopColor="#e0a106" />
                </linearGradient>
              </defs>
              <CartesianGrid
                strokeDasharray="3 3"
                vertical={false}
                stroke={GRID_STROKE}
              />
              <XAxis
                dataKey={visualization.x_key}
                tickFormatter={(value) => truncate(String(value), 16)}
                tick={{ fontSize: 12, fill: AXIS_TICK }}
                axisLine={false}
                tickLine={false}
                interval={0}
                angle={-18}
                textAnchor="end"
                height={62}
              />
              <YAxis
                tickFormatter={(value) =>
                  compactFormatter.format(Number(value))
                }
                tick={{ fontSize: 12, fill: AXIS_TICK }}
                axisLine={false}
                tickLine={false}
                width={72}
              />
              <Tooltip
                formatter={(value) =>
                  formatMetricValue(
                    visualization.y_key,
                    Number(value),
                    currencyCode,
                  )
                }
                labelFormatter={(label) => String(label)}
                contentStyle={tooltipStyle}
                cursor={{ fill: "rgba(232, 93, 46, 0.08)" }}
              />
              <Bar
                dataKey={visualization.y_key}
                radius={[8, 8, 0, 0]}
                maxBarSize={64}
              >
                {data.map((_, index) => (
                  <Cell
                    key={index}
                    fill={
                      singleSeries
                        ? "url(#barFill)"
                        : CHART_COLORS[index % CHART_COLORS.length]
                    }
                    fillOpacity={isMoney ? 1 : 0.9}
                  />
                ))}
              </Bar>
            </BarChart>
          )}
        </ResponsiveContainer>
      </div>
    </section>
  );
}

function DataTable({
  rows,
  currencyCode,
  onExport,
  isExporting,
}: {
  rows: SupportingRow[];
  currencyCode: string | null;
  onExport?: () => void;
  isExporting?: boolean;
}) {
  if (rows.length === 0) return null;
  const columns = Object.keys(rows[0]);
  return (
    <section className="overflow-hidden rounded-3xl border border-cream-200 bg-white shadow-sm">
      <div className="flex items-center justify-between border-b border-cream-200 px-5 py-4 sm:px-6">
        <h3 className="text-base font-semibold text-ink-900">
          Supporting data
        </h3>
        {onExport && (
          <button
            type="button"
            onClick={onExport}
            disabled={isExporting}
            className="inline-flex items-center gap-1.5 rounded-xl border border-cream-200 bg-cream-50 px-3 py-1.5 text-xs font-semibold text-ink-700 shadow-sm transition hover:bg-cream-100 hover:text-ink-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-500 disabled:opacity-50"
          >
            <svg
              viewBox="0 0 20 20"
              fill="currentColor"
              className="h-3.5 w-3.5 text-brand-600"
              aria-hidden="true"
            >
              <path d="M10.75 2.75a.75.75 0 0 0-1.5 0v8.614L6.295 8.235a.75.75 0 1 0-1.09 1.03l4.25 4.5a.75.75 0 0 0 1.09 0l4.25-4.5a.75.75 0 0 0-1.09-1.03l-2.955 3.129V2.75Z" />
              <path d="M3.5 12.75a.75.75 0 0 0-1.5 0v2.5A2.75 2.75 0 0 0 4.75 18h10.5A2.75 2.75 0 0 0 18 15.25v-2.5a.75.75 0 0 0-1.5 0v2.5c0 .69-.56 1.25-1.25 1.25H4.75c-.69 0-1.25-.56-1.25-1.25v-2.5Z" />
            </svg>
            {isExporting ? "Exporting…" : "Export CSV"}
          </button>
        )}
      </div>
      <div className="overflow-x-auto">
        <table className="min-w-full divide-y divide-cream-200 text-left text-sm">
          <caption className="sr-only">
            Supporting figures returned by the analytics engine
          </caption>
          <thead className="bg-cream-50">
            <tr>
              {columns.map((column) => (
                <th
                  key={column}
                  scope="col"
                  className="whitespace-nowrap px-5 py-3 text-xs font-semibold uppercase tracking-wide text-ink-400 sm:px-6"
                >
                  {dimensionLabel(column)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-cream-100">
            {rows.map((row, index) => (
              <tr
                key={`${index}-${String(row[columns[0]])}`}
                className="transition-colors hover:bg-cream-50"
              >
                {columns.map((column) => (
                  <td
                    key={column}
                    className="whitespace-nowrap px-5 py-3 text-ink-700 sm:px-6"
                  >
                    {column === "order_month"
                      ? formatMonth(row[column])
                      : formatMetricValue(column, row[column], currencyCode)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function EvidencePanel({ response }: { response: AskResponse }) {
  const definitions = Object.entries(response.metric_definitions);
  const filters = response.filters_applied;
  return (
    <section className="rounded-3xl border border-cream-200 bg-white p-5 shadow-sm sm:p-6">
      <h3 className="text-base font-semibold text-ink-900">
        Evidence and explanation
      </h3>
      <p className="mt-3 text-sm leading-6 text-ink-700">
        {response.calculation || "The calculation details are not available."}
      </p>
      <dl className="mt-4 grid gap-3 sm:grid-cols-2">
        <div className="rounded-xl bg-cream-50 px-4 py-3">
          <dt className="text-xs font-medium uppercase tracking-wide text-ink-400">
            Period
          </dt>
          <dd className="mt-1 text-sm text-ink-800">
            {formatDateRange(response.date_range)}
          </dd>
        </div>
        <div className="rounded-xl bg-cream-50 px-4 py-3">
          <dt className="text-xs font-medium uppercase tracking-wide text-ink-400">
            Filters
          </dt>
          <dd className="mt-1 text-sm text-ink-800">
            {filters.length > 0 ? filters.map(formatFilter).join("; ") : "None"}
          </dd>
        </div>
      </dl>
      {definitions.length > 0 && (
        <div className="mt-4">
          <h4 className="text-xs font-semibold uppercase tracking-wide text-ink-400">
            Metric definitions
          </h4>
          <ul className="mt-2 space-y-2">
            {definitions.map(([key, definition]) => (
              <li key={key} className="text-sm leading-6 text-ink-500">
                <span className="font-medium text-ink-800">
                  {metricLabel(key)}:
                </span>{" "}
                {definition}
              </li>
            ))}
          </ul>
        </div>
      )}

      {response.agent_execution_trace &&
        response.agent_execution_trace.length > 0 && (
          <div className="mt-5 border-t border-cream-100 pt-4">
            <h4 className="text-xs font-semibold uppercase tracking-wide text-ink-400">
              Agentic Execution Trace
            </h4>
            <ol className="mt-3 space-y-2">
              {response.agent_execution_trace.map((step) => (
                <li
                  key={step.step}
                  className="flex items-start gap-2.5 text-xs text-ink-600"
                >
                  <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-brand-100 text-[11px] font-bold text-brand-700">
                    {step.step}
                  </span>
                  <span>
                    <strong className="text-ink-900">{step.name}:</strong>{" "}
                    {step.detail}
                  </span>
                </li>
              ))}
            </ol>
          </div>
        )}

      {response.query_plan_summary && (
        <div className="mt-5 border-t border-cream-100 pt-4">
          <h4 className="text-xs font-semibold uppercase tracking-wide text-ink-400">
            Validated Query Plan (Deterministic Gatekeeper)
          </h4>
          <pre className="mt-2 overflow-x-auto rounded-xl bg-cream-50 p-3 font-mono text-[11px] leading-5 text-ink-700">
            {JSON.stringify(response.query_plan_summary, null, 2)}
          </pre>
        </div>
      )}

      <p className="mt-4 text-xs text-ink-400">
        Interpretation: {sourceLabel(response.interpretation_source)}. Figures
        are calculated by the Python analytics engine from database rows.
      </p>
    </section>
  );
}

function Warnings({ warnings }: { warnings: string[] }) {
  if (warnings.length === 0) return null;
  return (
    <div className="mt-4 rounded-2xl border border-gold-500/40 bg-gold-100 px-4 py-3 text-sm leading-6 text-ink-800">
      <p className="font-semibold">Good to know</p>
      <ul className="mt-1 list-inside list-disc space-y-1">
        {warnings.map((warning) => (
          <li key={warning}>{warning}</li>
        ))}
      </ul>
    </div>
  );
}

function Suggestions({
  suggestions,
  onSuggestion,
  disabled,
}: {
  suggestions: string[];
  onSuggestion: (question: string) => void;
  disabled: boolean;
}) {
  if (suggestions.length === 0) return null;
  return (
    <section aria-labelledby="suggestions-heading">
      <h3
        id="suggestions-heading"
        className="text-xs font-semibold uppercase tracking-wide text-ink-400"
      >
        Related questions
      </h3>
      <div className="mt-2 flex flex-wrap gap-2">
        {suggestions.map((suggestion) => (
          <button
            key={suggestion}
            type="button"
            onClick={() => onSuggestion(suggestion)}
            disabled={disabled}
            className="rounded-full border border-cream-200 bg-white px-3 py-1.5 text-left text-xs font-medium text-ink-700 shadow-sm transition hover:border-brand-500 hover:text-brand-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-500 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {suggestion}
          </button>
        ))}
      </div>
    </section>
  );
}

function MessageCard({
  response,
  onSuggestion,
  disabled,
}: {
  response: AskResponse;
  onSuggestion: (question: string) => void;
  disabled: boolean;
}) {
  const tone = statusTone(response.status);
  const title =
    response.status === "needs_clarification"
      ? "Clarification needed"
      : "Not supported";
  return (
    <section className="rounded-3xl border border-cream-200 bg-white p-6 shadow-sm sm:p-8">
      <StatusBadge tone={tone}>{title}</StatusBadge>
      <p className="mt-4 text-lg font-medium leading-8 text-ink-900">
        {response.answer}
      </p>
      <Warnings warnings={response.warnings} />
      <div className="mt-6">
        <Suggestions
          suggestions={response.suggestions}
          onSuggestion={onSuggestion}
          disabled={disabled}
        />
      </div>
    </section>
  );
}

function ResultsPanel({
  response,
  currencyCode,
  onSuggestion,
  onExport,
  isExporting,
  disabled,
}: {
  response: AskResponse;
  currencyCode: string | null;
  onSuggestion: (question: string) => void;
  onExport?: () => void;
  isExporting?: boolean;
  disabled: boolean;
}) {
  if (
    response.status === "needs_clarification" ||
    response.status === "unsupported"
  ) {
    return (
      <MessageCard
        response={response}
        onSuggestion={onSuggestion}
        disabled={disabled}
      />
    );
  }
  return (
    <div className="space-y-5">
      <section className="rounded-3xl border border-cream-200 bg-white p-6 shadow-sm sm:p-8">
        <div className="flex flex-wrap items-center gap-2">
          <StatusBadge tone={statusTone(response.status)}>Answered</StatusBadge>
          <StatusBadge>
            {sourceLabel(response.interpretation_source)}
          </StatusBadge>
          {response.interpretation_confidence !== undefined && (
            <StatusBadge>{`${Math.round(response.interpretation_confidence * 100)}% confidence`}</StatusBadge>
          )}
          {response.response_time_ms !== undefined && (
            <StatusBadge>{`${response.response_time_ms}ms`}</StatusBadge>
          )}
          {!response.has_data && <StatusBadge>No matching data</StatusBadge>}
        </div>
        <p className="mt-4 text-xl font-medium leading-8 text-ink-900 sm:text-2xl sm:leading-9">
          {response.answer}
        </p>
        <Warnings warnings={response.warnings} />
      </section>
      {response.has_data && (
        <MetricsGrid metrics={response.metrics} currencyCode={currencyCode} />
      )}
      {response.has_data && response.reconciliation && (
        <Reconciliation
          reconciliation={response.reconciliation}
          currencyCode={currencyCode}
        />
      )}
      {response.has_data && response.visualization && (
        <ChartPanel
          visualization={response.visualization}
          data={response.supporting_data}
          currencyCode={currencyCode}
        />
      )}
      {response.has_data && (
        <DataTable
          rows={response.supporting_data}
          currencyCode={currencyCode}
          onExport={onExport}
          isExporting={isExporting}
        />
      )}
      <EvidencePanel response={response} />
      <Suggestions
        suggestions={response.suggestions}
        onSuggestion={onSuggestion}
        disabled={disabled}
      />
    </div>
  );
}

function LoadingState() {
  return (
    <div
      className="space-y-4"
      role="status"
      aria-label="Analyzing the question"
    >
      <div className="rounded-3xl border border-cream-200 bg-white p-6 shadow-sm sm:p-8">
        <div className="h-3 w-24 animate-pulse rounded-full bg-cream-200" />
        <div className="mt-5 h-5 w-3/4 animate-pulse rounded-full bg-cream-200" />
        <div className="mt-3 h-5 w-1/2 animate-pulse rounded-full bg-cream-100" />
      </div>
      <div className="grid gap-3 sm:grid-cols-3">
        {[0, 1, 2].map((item) => (
          <div
            key={item}
            className="h-24 animate-pulse rounded-2xl border border-cream-200 bg-white"
          />
        ))}
      </div>
    </div>
  );
}

function EmptyState() {
  return (
    <section className="rounded-3xl border border-dashed border-cream-200 bg-white/70 p-8 text-center">
      <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-2xl bg-brand-100 text-lg font-bold text-brand-700">
        SI
      </div>
      <h2 className="mt-4 text-lg font-semibold text-ink-900">
        Ask a question to see the evidence
      </h2>
      <p className="mx-auto mt-2 max-w-xl text-sm leading-6 text-ink-500">
        Answers are computed from the imported transactions. The language model
        only interprets the question; it never writes SQL or supplies the
        numbers.
      </p>
    </section>
  );
}

function ErrorState({
  message,
  onRetry,
  canRetry,
}: {
  message: string;
  onRetry: () => void;
  canRetry: boolean;
}) {
  return (
    <section
      role="alert"
      className="rounded-3xl border border-brand-500/40 bg-brand-50 p-6 text-brand-700 sm:p-8"
    >
      <h2 className="text-lg font-semibold">Something went wrong</h2>
      <p className="mt-2 text-sm leading-6">{message}</p>
      {canRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="mt-4 rounded-xl bg-brand-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-brand-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-500 focus-visible:ring-offset-2"
        >
          Try again
        </button>
      )}
    </section>
  );
}

/* ------------------------------------------------------------------ */
/* Filter bar                                                          */
/* ------------------------------------------------------------------ */

const REGIONS = ["East", "North", "South", "West"];
const CATEGORIES = ["Accessories", "Electronics", "Furniture"];
const CHANNELS = ["Online", "Retail"];
const STATUSES = ["completed", "returned"];

type YearPreset = "all" | "2026" | "custom";

function FieldLabel({ children }: { children: string }) {
  return (
    <span className="text-[11px] font-semibold uppercase tracking-wider text-ink-400">
      {children}
    </span>
  );
}

const selectClass =
  "w-full rounded-xl border border-cream-200 bg-white px-3 py-2 text-sm text-ink-900 shadow-sm outline-none transition focus:border-brand-500 focus:ring-2 focus:ring-brand-500/30";
const dateClass = selectClass;

function FilterBar({
  yearPreset,
  startDate,
  endDate,
  region,
  category,
  channel,
  status,
  activeCount,
  onYearPreset,
  onStartDate,
  onEndDate,
  onRegion,
  onCategory,
  onChannel,
  onStatus,
  onClear,
  disabled,
}: {
  yearPreset: YearPreset;
  startDate: string;
  endDate: string;
  region: string;
  category: string;
  channel: string;
  status: string;
  activeCount: number;
  onYearPreset: (value: YearPreset) => void;
  onStartDate: (value: string) => void;
  onEndDate: (value: string) => void;
  onRegion: (value: string) => void;
  onCategory: (value: string) => void;
  onChannel: (value: string) => void;
  onStatus: (value: string) => void;
  onClear: () => void;
  disabled: boolean;
}) {
  return (
    <div aria-label="Filters" className="p-5 sm:p-6">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <svg
            viewBox="0 0 20 20"
            fill="currentColor"
            className="h-4 w-4 text-brand-600"
            aria-hidden="true"
          >
            <path
              fillRule="evenodd"
              d="M2.5 5a1 1 0 0 1 1-1h13a1 1 0 0 1 .8 1.6l-4.4 5.87v4.28a1 1 0 0 1-.45.84l-3 2a1 1 0 0 1-1.55-.84v-6.28L2.7 6.6A1 1 0 0 1 2.5 5Z"
              clipRule="evenodd"
            />
          </svg>
          <h2 className="text-sm font-semibold text-ink-900">Filter scope</h2>
          {activeCount > 0 && (
            <StatusBadge tone="bg-brand-100 text-brand-700 ring-brand-500/30">{`${activeCount} active`}</StatusBadge>
          )}
        </div>
        {activeCount > 0 && (
          <button
            type="button"
            onClick={onClear}
            disabled={disabled}
            className="text-xs font-semibold text-brand-700 underline-offset-2 transition hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-500 disabled:opacity-50"
          >
            Clear all
          </button>
        )}
      </div>

      <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        <label className="flex flex-col gap-1.5">
          <FieldLabel>Period</FieldLabel>
          <select
            value={yearPreset}
            onChange={(e) => onYearPreset(e.target.value as YearPreset)}
            disabled={disabled}
            className={selectClass}
          >
            <option value="all">All time</option>
            <option value="2026">Year 2026</option>
            <option value="custom">Custom range</option>
          </select>
        </label>

        <label className="flex flex-col gap-1.5">
          <FieldLabel>Start date</FieldLabel>
          <input
            type="date"
            value={startDate}
            onChange={(e) => onStartDate(e.target.value)}
            disabled={disabled}
            className={dateClass}
          />
        </label>

        <label className="flex flex-col gap-1.5">
          <FieldLabel>End date</FieldLabel>
          <input
            type="date"
            value={endDate}
            onChange={(e) => onEndDate(e.target.value)}
            disabled={disabled}
            className={dateClass}
          />
        </label>

        <label className="flex flex-col gap-1.5">
          <FieldLabel>Region</FieldLabel>
          <select
            value={region}
            onChange={(e) => onRegion(e.target.value)}
            disabled={disabled}
            className={selectClass}
          >
            <option value="">All regions</option>
            {REGIONS.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
        </label>

        <label className="flex flex-col gap-1.5">
          <FieldLabel>Category</FieldLabel>
          <select
            value={category}
            onChange={(e) => onCategory(e.target.value)}
            disabled={disabled}
            className={selectClass}
          >
            <option value="">All categories</option>
            {CATEGORIES.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </label>

        <label className="flex flex-col gap-1.5">
          <FieldLabel>Channel</FieldLabel>
          <select
            value={channel}
            onChange={(e) => onChannel(e.target.value)}
            disabled={disabled}
            className={selectClass}
          >
            <option value="">All channels</option>
            {CHANNELS.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </label>
      </div>

      <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        <label className="flex flex-col gap-1.5">
          <FieldLabel>Status</FieldLabel>
          <select
            value={status}
            onChange={(e) => onStatus(e.target.value)}
            disabled={disabled}
            className={selectClass}
          >
            <option value="">Completed only (default)</option>
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </label>
      </div>

      <p className="mt-3 text-xs text-ink-400">
        Your question is the source of truth. Filters fill gaps only where the
        question does not specify the same date range or dimension; status
        defaults to completed transactions.
      </p>
    </div>
  );
}

/* ------------------------------------------------------------------ */

function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [examples, setExamples] = useState<Example[]>(FALLBACK_EXAMPLES);
  const [question, setQuestion] = useState("");
  const [presetId, setPresetId] = useState<string | null>(null);
  const [response, setResponse] = useState<AskResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [recent, setRecent] = useState<string[]>([]);
  const [lastRequest, setLastRequest] = useState<{
    question: string;
    presetId: string | null;
  } | null>(null);
  const [sessionId] = useState<string>(
    () => "sess_" + Math.random().toString(36).substring(2, 9),
  );
  const [exporting, setExporting] = useState(false);

  // Filter bar state
  const [yearPreset, setYearPreset] = useState<YearPreset>("all");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [region, setRegion] = useState("");
  const [category, setCategory] = useState("");
  const [channel, setChannel] = useState("");
  const [status, setStatus] = useState("");

  useEffect(() => {
    let cancelled = false;
    Promise.allSettled([getExamples(), getHealth()]).then(
      ([examplesResult, healthResult]) => {
        if (cancelled) return;
        if (examplesResult.status === "fulfilled")
          setExamples(examplesResult.value.examples);
        if (healthResult.status === "fulfilled") setHealth(healthResult.value);
      },
    );
    return () => {
      cancelled = true;
    };
  }, []);

  const currencyCode = health?.currency_code ?? null;

  const overrides: AskOverrides = useMemo(() => {
    const result: AskOverrides = {};
    let start: string | null = null;
    let end: string | null = null;
    if (yearPreset === "2026") {
      start = "2026-01-01";
      end = "2026-12-31";
    } else if (yearPreset === "custom") {
      start = startDate || null;
      end = endDate || null;
    }
    if (start || end) result.date_range = { start, end };

    const filters: FilterApplied[] = [];
    if (region)
      filters.push({ field: "region", operator: "eq", values: [region] });
    if (category)
      filters.push({ field: "category", operator: "eq", values: [category] });
    if (channel)
      filters.push({
        field: "sales_channel",
        operator: "eq",
        values: [channel],
      });
    if (status)
      filters.push({ field: "status", operator: "eq", values: [status] });
    if (filters.length > 0) result.filters = filters;
    return result;
  }, [yearPreset, startDate, endDate, region, category, channel, status]);

  const activeFilterCount = useMemo(() => {
    let count = 0;
    if (
      overrides.date_range &&
      (overrides.date_range.start || overrides.date_range.end)
    )
      count += 1;
    count += overrides.filters?.length ?? 0;
    return count;
  }, [overrides]);

  function handleYearPreset(value: YearPreset) {
    setYearPreset(value);
    if (value !== "custom") {
      setStartDate("");
      setEndDate("");
    }
  }

  function handleStartDate(value: string) {
    setStartDate(value);
    if (value) setYearPreset("custom");
  }

  function handleEndDate(value: string) {
    setEndDate(value);
    if (value) setYearPreset("custom");
  }

  function clearFilters() {
    setYearPreset("all");
    setStartDate("");
    setEndDate("");
    setRegion("");
    setCategory("");
    setChannel("");
    setStatus("");
  }

  async function runAsk(text: string, preset: string | null) {
    const trimmed = text.trim();
    if (!trimmed && !preset) {
      setError("Enter a question or choose an example.");
      return;
    }
    setLoading(true);
    setError(null);
    setResponse(null);
    setLastRequest({ question: trimmed, presetId: preset });
    try {
      const result = await askQuestion(trimmed, preset, overrides, sessionId);
      setResponse(result);
      if (trimmed) {
        setRecent((previous) =>
          [trimmed, ...previous.filter((item) => item !== trimmed)].slice(0, 5),
        );
      }
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : "The request failed. Please try again.",
      );
    } finally {
      setLoading(false);
    }
  }

  async function handleExport() {
    if (!response || !response.has_data) return;
    setExporting(true);
    try {
      await exportCsv(question, presetId, overrides);
    } catch (exportError) {
      alert(
        exportError instanceof Error
          ? exportError.message
          : "Export failed. Please try again.",
      );
    } finally {
      setExporting(false);
    }
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!loading) void runAsk(question, presetId);
  }
  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      if (!loading) void runAsk(question, presetId);
    }
  }
  function handleExample(example: Example) {
    setQuestion(example.question);
    setPresetId(example.preset_id);
    void runAsk(example.question, example.preset_id);
  }
  function handleSuggestion(suggestion: string) {
    setQuestion(suggestion);
    setPresetId(null);
    void runAsk(suggestion, null);
  }
  function handleRecent(item: string) {
    setQuestion(item);
    setPresetId(null);
    void runAsk(item, null);
  }
  function handleRetry() {
    if (lastRequest) void runAsk(lastRequest.question, lastRequest.presetId);
  }

  return (
    <div className="min-h-screen bg-cream-50">
      <header className="sticky top-0 z-20 border-b border-cream-200 bg-cream-50/85 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-5 py-3.5 sm:px-8">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-ink-900 text-sm font-bold tracking-tight text-cream-50">
              QM
            </div>
            <div>
              <p className="text-sm font-semibold tracking-tight text-ink-900">
                QueryMind-AI
              </p>
              <p className="text-[11px] text-ink-400">
                Evidence-backed answers from real transactions
              </p>
            </div>
          </div>
          <div className="hidden items-center gap-2 sm:flex">
            {health && (
              <StatusBadge
                tone={
                  health.groq_configured
                    ? "bg-plum-100 text-plum-700 ring-plum-600/30"
                    : "bg-cream-100 text-ink-500 ring-ink-300/40"
                }
              >
                {health.groq_configured ? "Groq" : "Rule-based"}
              </StatusBadge>
            )}
            <StatusBadge>Structured plans</StatusBadge>
            <StatusBadge>Read-only SQL</StatusBadge>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-5 pb-16 sm:px-8">
        {/* Hero — compact, sets context without dominating the page */}
        <section className="max-w-2xl pb-6 pt-8 sm:pt-10">
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-brand-600">
            Natural-language business intelligence
          </p>
          <h1 className="mt-2 text-2xl font-semibold tracking-tight text-ink-900 sm:text-4xl">
            Ask your sales data a question.
          </h1>
          <p className="mt-3 max-w-xl text-sm leading-6 text-ink-500 sm:text-base sm:leading-7">
            Deterministic answers with the metric definition, calculation,
            filters, and supporting rows behind every number.
          </p>
        </section>

        {/* Control panel: filters + question, grouped as one tool */}
        <section
          aria-label="Ask a question"
          className="mt-5 overflow-hidden rounded-3xl border border-cream-200 bg-white shadow-sm"
        >
          <FilterBar
            yearPreset={yearPreset}
            startDate={startDate}
            endDate={endDate}
            region={region}
            category={category}
            channel={channel}
            status={status}
            activeCount={activeFilterCount}
            onYearPreset={handleYearPreset}
            onStartDate={handleStartDate}
            onEndDate={handleEndDate}
            onRegion={setRegion}
            onCategory={setCategory}
            onChannel={setChannel}
            onStatus={setStatus}
            onClear={clearFilters}
            disabled={loading}
          />

          <div className="border-t border-cream-200 p-5 sm:p-6">
            <form onSubmit={handleSubmit} aria-busy={loading}>
              <div className="flex flex-col gap-3 sm:flex-row sm:items-stretch">
                <div className="relative flex-1">
                  <textarea
                    id="question"
                    value={question}
                    onChange={(event) => {
                      setQuestion(event.target.value);
                      if (presetId) setPresetId(null);
                    }}
                    onKeyDown={handleKeyDown}
                    rows={3}
                    maxLength={500}
                    placeholder="Ask about revenue, products, regions, channels, months, or status…"
                    className="min-h-24 w-full resize-none rounded-2xl border border-cream-200 bg-cream-50/60 px-4 py-3 text-base leading-7 text-ink-900 shadow-sm outline-none transition placeholder:text-ink-300 focus:border-brand-500 focus:bg-white focus:ring-2 focus:ring-brand-500/30"
                  />
                  <span className="pointer-events-none absolute bottom-2.5 right-3 text-[11px] text-ink-300">
                    {question.length}/500
                  </span>
                </div>
                <button
                  type="submit"
                  disabled={loading || (!question.trim() && !presetId)}
                  className="inline-flex min-h-12 items-center justify-center rounded-2xl bg-brand-600 px-6 py-3 text-sm font-semibold text-white shadow-sm transition hover:bg-brand-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-500 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:bg-ink-300 sm:w-32 sm:self-stretch"
                >
                  {loading ? (
                    <span className="flex items-center gap-2">
                      <span
                        className="h-4 w-4 animate-spin rounded-full border-2 border-white/40 border-t-white"
                        aria-hidden="true"
                      />
                      Asking
                    </span>
                  ) : (
                    "Ask"
                  )}
                </button>
              </div>
              <p className="mt-2 text-xs text-ink-400">
                Enter to ask · Shift+Enter for a new line
              </p>
            </form>

            <div className="mt-4 border-t border-cream-100 pt-4">
              <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
                <span className="text-xs font-semibold uppercase tracking-wider text-ink-400">
                  Try
                </span>
                {examples.map((example) => (
                  <button
                    key={example.preset_id}
                    type="button"
                    onClick={() => handleExample(example)}
                    disabled={loading}
                    title={example.question}
                    className="rounded-full border border-cream-200 bg-white px-3 py-1.5 text-xs font-medium text-ink-700 shadow-sm transition hover:border-brand-500 hover:text-brand-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-500 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {example.label}
                  </button>
                ))}
                {recent.length > 0 && (
                  <>
                    <span className="ml-1 text-xs font-semibold uppercase tracking-wider text-ink-300">
                      Recent
                    </span>
                    {recent.map((item) => (
                      <button
                        key={item}
                        type="button"
                        onClick={() => handleRecent(item)}
                        disabled={loading}
                        className="max-w-52 truncate rounded-full bg-cream-100 px-2.5 py-1.5 text-xs font-medium text-ink-500 transition hover:bg-cream-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-500 disabled:opacity-50"
                        title={item}
                      >
                        {item}
                      </button>
                    ))}
                  </>
                )}
              </div>
            </div>
          </div>
        </section>

        {/* Results */}
        <section className="mt-8" aria-live="polite" aria-busy={loading}>
          {loading && <LoadingState />}
          {!loading && error && (
            <ErrorState
              message={error}
              onRetry={handleRetry}
              canRetry={lastRequest !== null}
            />
          )}
          {!loading && !error && response && (
            <ResultsPanel
              response={response}
              currencyCode={currencyCode}
              onSuggestion={handleSuggestion}
              onExport={handleExport}
              isExporting={exporting}
              disabled={loading}
            />
          )}
          {!loading && !error && !response && <EmptyState />}
        </section>

        <footer className="mt-12 border-t border-cream-200 pt-5 text-xs leading-5 text-ink-400">
          <p>
            Answers are computed by Python from the imported PostgreSQL data.
            Groq only interprets the question when configured; it never writes
            SQL or supplies answer numbers.
          </p>
        </footer>
      </main>
    </div>
  );
}

export default App;
