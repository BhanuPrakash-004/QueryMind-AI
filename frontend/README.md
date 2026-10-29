# QueryMind-AI Frontend

The QueryMind-AI web client is a React 19 single-page application built with
TypeScript, Vite 8, Tailwind CSS 4, and Recharts.

## Run locally

```powershell
npm install
npm run dev
```

The development server runs at `http://localhost:5173` and proxies `/api` to the
FastAPI backend at `http://localhost:8000`.

## Checks

```powershell
npm run build
npm run lint
```

## Structure

| File | Responsibility |
|---|---|
| `src/App.tsx` | Filter bar, question composer, presets, results, charts, evidence, and export. |
| `src/api.ts` | Typed client for the QueryMind-AI API. |
| `src/types.ts` | Response contract shared by the UI components. |
| `src/index.css` | Tailwind entry point and theme tokens. |

For full setup, API documentation, and architecture, see the repository
[`README.md`](../README.md) and [`ARCHITECTURE.md`](../ARCHITECTURE.md).
