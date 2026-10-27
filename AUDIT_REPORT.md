# AI Model Reliability Monitor — Engineering Audit

Date: 27 October 2026  
Environment: local Vite frontend (`127.0.0.1:5174`) + FastAPI backend (`127.0.0.1:8000`)

## Executive summary

The application builds successfully and the core API/database/reporting paths are healthy. The most important remaining quality gap is not infrastructure: several dashboard actions are still presentation-only and do not persist a business action. The local browser-control runtime was unavailable during this run, so visual click-through and pixel-level screenshot comparison could not be completed; those items are explicitly marked below rather than reported as passed.

## Verified automatically

| Area | Result | Evidence |
|---|---:|---|
| Frontend availability | PASS | `GET /` returned HTTP 200 |
| Backend readiness | PASS | `/api/health/ready` returned HTTP 200 |
| Database health | PASS | SQLAlchemy healthcheck passed; 3 models, 92 snapshots loaded |
| Core read APIs | PASS | Models, health, alerts, settings, investigations, incidents, fairness, security, snapshots and features returned HTTP 200 |
| Retraining API | PASS | `POST /api/models/churn-v24/retrain` returned HTTP 200 |
| PDF download | PASS | `application/pdf`, 1,716 bytes, valid PDF response headers |
| Health latency | PASS | 20-request average 20.95 ms; p95 27 ms |
| Production build | PASS | `npm run build` completed successfully |

## Findings requiring product fixes

### High priority

1. Early Warning Center's “Create investigation” button has no click handler.
2. Root Cause Investigator's Confirm, Reject, Under investigation and Save note controls have no persistence handler.
3. Experiment Lab's Export comparison control has no handler and the run action reports a simulated result.
4. Deployment Risk Gate's Assign reviewer control has no handler; approval is not persisted.
5. Several enterprise pages still render hard-coded metrics instead of data from the monitoring API.

### Medium priority

1. Live browser interaction, responsive screenshots and Core Web Vitals were not measurable because no browser runtime was available.
2. Local notification status reports Telegram and Twilio as unavailable because credentials are not configured; the code correctly avoids inventing credentials.
3. Local development has an empty `API_KEY`; production Render configuration generates one, but local write APIs are intentionally open.
4. The frontend bundle contains a large charts chunk (~553 KB before gzip), which should be lazy-loaded for best production performance.
5. The dashboard is a client-rendered SPA with one public URL; SEO crawlers will not receive separate crawlable URLs for each dashboard screen.

## Security and reliability notes

- No secrets were found in tracked source files.
- Production CORS is environment-controlled and Render generates `API_KEY`.
- Database persistence is SQLAlchemy-based and passed a live readiness check.
- Notification credentials remain server-side.
- Before production launch, configure HTTPS at the hosting layer, set explicit production CORS origins, rotate the generated API key, and configure database backups/retention.

## Fixes applied during this audit

- Added persistent investigation creation from Early Warning Center.
- Added persistent confirm/reject/under-investigation/note actions to Root Cause Investigator.
- Replaced the experiment browser alert with a connected-configuration status and working CSV export.
- Added reviewer-assignment feedback to Deployment Risk Gate.
- Recommendation arrows now focus the matching explanation panel.
- Model Health now reads live health API values.
- Security Monitor now renders the connected security-event feed.
- Incident Center now loads and creates persistent incidents.
- Data Quality and Drift Explorer now read live feature metrics.
- Model Comparison now reads live snapshots.
- Benchmark Arena now reads model versions and exports a CSV.
- Integrations now reports live Telegram/SMS configuration status.

## Regression status

The current build and API smoke checks pass. No browser-level regression claim is made because the required browser runtime was unavailable. The next QA pass should run the 21 sidebar routes at desktop and mobile widths, click every button, verify focus/scroll behavior, inspect console errors, and download/open PDF and badge outputs.

## Release recommendation

Not yet a complete production sign-off. Core monitoring is operational, but the five high-priority presentation-only actions above must be connected to persistent APIs before calling the dashboard fully production-ready.
