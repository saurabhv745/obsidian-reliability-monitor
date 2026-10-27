# Obsidian Labs — AI Model Reliability Monitor

A hackathon-ready reliability monitoring SaaS prototype. It combines a responsive React dashboard with a FastAPI drift engine that accepts CSV uploads, detects column types, compares distributions, and returns feature-level findings and alerts. The backend also exposes offline demo snapshots, drift simulation, forecasting, model/version actions, ingest, chat fallback, fairness, security, badges, and PDF export.

## Run locally

Frontend:

```bash
npm install
npm run dev
```

Backend (Python 3.10+):

```bash
cd backend
python -m venv venv
# Windows: venv\\Scripts\\activate
# macOS/Linux: source venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload
```

### Telegram alerts

Telegram delivery is server-side only. After creating the bot, rotate any token that was shared in chat, then set these values in `backend/.env`:

```env
TELEGRAM_BOT_TOKEN=your_rotated_bot_token
TELEGRAM_CHAT_ID=your_chat_id
```

Start a chat with the bot first. The chat ID can be obtained from Telegram's `getUpdates` API or an approved chat-ID helper. Restart FastAPI, then use the Integrations screen or `POST /api/notifications/test` with `{"channel":"telegram","message":"Test alert"}`.

The frontend defaults to `http://localhost:8000`; copy `.env.example` to `.env` to change it. The UI includes a no-backend demo mode, while CSV uploads and analysis use the API. Demo story: load the baseline, load the current dataset, analyze drift, inspect the explanation, acknowledge the alert, and generate a report.

Useful API routes include `GET /api/models`, `GET /api/models/{id}/snapshots`, `GET /api/models/{id}/forecast`, `POST /api/simulator/run`, `POST /api/ingest`, `POST /api/models/{id}/retrain`, `POST /api/models/{id}/chat`, `GET /api/models/{id}/fairness`, `POST /api/models/{id}/badge`, and `GET /api/models/{id}/report.pdf`.

Team: Princi Verma · Abhishek Yadav · Anshika Devi

## Product workflow

The dashboard is organized around the full reliability loop:

```text
Detect → Explain → Investigate → Simulate → Recommend → Verify → Learn
```

The frontend includes the following investigation surfaces:

- Overview: reliability score, drift evidence, timeline, heatmap, human-review workflow.
- Reliability Digital Twin: data sources → input features → model → predictions → outcomes → assessment.
- Early warnings: evidence, uncertainty, potential consequences, and next investigation.
- Model detail: feature distribution comparison, AI/rule-based explanation, Hindi toggle, and Time Machine.
- Drift simulator: mean shift, variance, missingness, category swaps, label noise, and scenario presets.
- Investigator: ranked hypotheses with evidence and reviewer actions.
- Incident memory: similar historical incidents and previously successful corrective actions.
- Experiment Lab: reproducible isolated comparison runs.
- Model comparison: schema, confidence, accuracy, latency, and data-quality impact.
- Retrain, chat, fairness, security, alerts, reports, and settings.

## Evidence labels

Values shown before a real dataset/model is connected are explicitly marked as illustrative or simulated. The UI distinguishes:

- observed measurements from uploaded datasets;
- statistical estimates from drift calculations;
- forecasts from historical demo snapshots;
- simulations from the What-if controls; and
- AI/rule-based hypotheses from confirmed root causes.

Drift is treated as evidence of change, not proof that a model is wrong. Performance claims require labeled outcomes.

## Current prototype limitations

The prototype is offline-first and intentionally uses in-memory demo history. PostgreSQL migrations, authentication/RBAC, tenant isolation, WebSocket live updates, and durable incident/experiment persistence are not yet production-ready. Claude, Telegram, and SMTP integrations degrade to local rule-based/demo behavior until credentials and connectors are configured.

## SEO and launch checklist

The Vite app includes `public/robots.txt`, `public/sitemap.xml`, `public/og-image.svg`, canonical metadata, Open Graph/Twitter metadata, and SoftwareApplication JSON-LD in `index.html`. The sitemap currently uses `https://obsidianlabs.ai/` as the intended production origin; replace that host in `public/sitemap.xml` and the canonical/OG URL tags if the deployed domain differs.

Before launch, deploy over HTTPS, submit `/sitemap.xml` in Google Search Console, validate the structured data, test the Open Graph preview, and configure redirects so only one HTTPS hostname is canonical. Search Console verification and backlink acquisition require access to the real production domain and cannot be completed locally.

## Performance work included

- Vite production minification, CSS minification, sourcemap disabling, and manual React/chart/icon chunks in `vite.config.js`.
- FastAPI GZip compression for responses larger than 1 KB.
- Forecast result caching with a 30-second invalidation window; monitoring writes invalidate the cache.
- SQLite indexes on model/time snapshot reads.
- Small browser-side TTL cache helper at `src/api/cache.js` for read-only API calls.
- Static assets are served from Vite's public pipeline and the generated SVG social image is already compact.

CDN, load balancing, HTTPS enforcement, and Lighthouse scoring are deployment concerns. Configure them at the hosting layer, then run Lighthouse against the deployed HTTPS URL rather than claiming a local score.
