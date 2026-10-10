# Active Energy — Smart Energy Management Platform

**Problem statement:** A Self-Learning, Negotiation-Based Multi-Agent AI Platform for Smart Energy Management

A runnable full-stack prototype based on the submitted presentation. It demonstrates a multi-agent energy workflow, transparent negotiation, explainable recommendations, human approval/edit/reject controls, configurable energy settings, persistent plan history, and a lightweight feedback-driven learning loop.

## Features

- Energy dashboard: simulated demand, solar generation, grid import, battery state of charge, cost, energy-flow visualization, and optimization priorities.
- Six specialized agents: Load, Solar, Battery, Price, Weather, and Comfort.
- Negotiation engine: transparent rule-based proposals, weighted objective scores (cost 35%, comfort 30%, battery health 20%, renewable use 15%), and conflict resolution.
- Decision optimizer: tariff-aware load shifting, solar-first behavior, battery charge/discharge suggestions, comfort bounds, and a 20% battery reserve guardrail.
- Explainability: reason codes, trade-offs, action impacts, and estimated costs/savings.
- Human-in-the-loop: approve, reject, or edit proposed actions; safety guardrails cannot be disabled.
- Learning feedback: submit outcome/rating/notes; data is saved in SQLite and positive/negative feedback adjusts a small bounded preference parameter.
- Settings: tune site type, load, solar, battery, tariffs, occupancy, comfort, and budget.
- Machine manager: add equipment, assign category/rated kW/priority, switch simulated machines on/off, refresh the inventory, and delete devices. Machine inventory and states persist in SQLite.
- History and JSON export; responsive layout for desktop and mobile, with a violet/dark professional visual system and larger typography.

## Quick start

Requires Python 3.10+.

### Windows

```powershell
cd smart-energy-platform
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
uvicorn app.main:app --reload
```

### macOS / Linux

```bash
cd smart-energy-platform
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open **http://127.0.0.1:8000**. Interactive API docs: **http://127.0.0.1:8000/docs**. Health check: **http://127.0.0.1:8000/api/health**.

## How to demo

1. Open Overview and explore the energy metrics and energy-flow diagram.
2. Visit **AI Agents** to see the six agents and their observations.
3. Click **Generate smart plan**. Review estimated savings, objective scores, action explanations, and conflicts.
4. Disable/enable optional actions and select **Save edits**, or **Approve plan** / **Reject**. The comfort guardrail is intentionally locked.
5. Open **Energy Settings**, change solar, tariffs, load, or battery state of charge, save, and generate another plan to see how the recommendations change.
6. After approval, submit outcome feedback. See saved plans and feedback in **Learning & History**, and export the history as JSON.

## API overview

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/health` | Health check |
| GET | `/api/dashboard` | Current simulated energy metrics |
| GET/PUT | `/api/settings` | Read/update validated site settings |
| GET | `/api/agents` | Agent status and observations |
| POST | `/api/plan` | Generate and persist a new plan |
| GET | `/api/plans` | List saved plans |
| POST | `/api/plans/{id}/decision` | Approve, reject, or edit a plan |
| POST | `/api/plans/{id}/feedback` | Save outcome feedback / learning signal |
| GET | `/api/feedback` | List feedback |
| POST | `/api/reset` | Reset demo settings (history remains) |\n| GET/POST | `/api/machines` | List or add machine records |\n| PATCH/DELETE | `/api/machines/{id}` | Toggle a machine or delete it |

## Architecture

- **Frontend:** HTML, CSS, JavaScript (no Node/npm build step); served by FastAPI.
- **Backend:** Python + FastAPI REST endpoints.
- **Agent layer:** specialized role/observation definitions and deterministic proposal heuristics.
- **Negotiation/optimization:** transparent objective scoring and safety guardrails in `app/engine.py`.
- **Persistence:** SQLite database created at first run in `data/energy.db`.

## Scope and honest limitations

This is a functional, locally runnable prototype. Readings and weather confidence are simulated; the planner uses transparent heuristics rather than a trained forecasting or reinforcement-learning model. Feedback updates a bounded preference signal but does not train a neural model. Approval records a decision only — **no physical device is controlled**. No real smart-meter, utility tariff, weather, IoT, authentication, or cloud integration is configured. A production deployment should add authenticated users, audited device adapters, calibrated forecasts, optimization tests, safety review, secure secrets, monitoring, and explicit actuator fail-safes.

## Project structure

```text
smart-energy-platform/
├── app/
│   ├── main.py              # FastAPI application and REST API
│   ├── engine.py            # agents, negotiation, and optimization heuristics
│   └── static/
│       ├── index.html       # application shell
│       ├── styles.css       # responsive dashboard design
│       └── app.js           # frontend interactions
├── data/                    # SQLite database created at runtime
├── requirements.txt
└── README.md
```


## Upgrade notes (v1.1)

- Added simulated telemetry capture and a recent-demand trend chart on the dashboard. Use **Simulate new readings** to append readings to the local SQLite database. Configured solar capacity and base load remain unchanged; readings vary around the configured values.
- Added saved-plan detail retrieval. Select any row in Learning & History to reopen its complete plan in Negotiation Plans.
- Added plan history search, status filtering, and clear-filter controls.
- Added CSV export alongside JSON export. CSV fields include plan ID, timestamp, status, action count, estimated hourly savings, and decision note.
- Persisted site settings and the lightweight feedback preference in SQLite so they survive application restarts.
- Added `/api/telemetry`, `/api/telemetry/simulate`, and `/api/plans/{plan_id}` endpoints.
- Improved refresh feedback and made the brand mark return to Overview.

### API smoke test

With the virtual environment activated and the server dependencies installed, run `python -m compileall -q app` and `node --check app/static/app.js`. The interactive UI and REST API use local demo data; no real meter, utility, weather provider, or physical appliance is connected.


## Professional UX update (v3)

The machine control center now includes:

- A seeded starter inventory of ten common device types on first use.
- Search by name/category/priority, category and ON/OFF filters, and sorting by name or rated power.
- Create, edit, toggle ON/OFF, and delete machine records.
- Select individual or all visible machines and run bulk ON, OFF, or delete actions.
- Summary cards for registered, running, stopped, active-load, and total rated-power figures.
- CSV export of the full machine inventory.
- Clear empty states, action feedback, form validation, responsive layouts, keyboard focus styles, and larger default type.
- A persistent text-size control in the top bar (A− / A+).

### Machine API

- `GET /api/machines` — list machines
- `GET /api/machines/summary` — machine totals and rated load
- `POST /api/machines` — create a machine
- `PATCH /api/machines/{id}` — edit fields, or toggle ON/OFF with an empty JSON object
- `DELETE /api/machines/{id}` — remove a machine
- `POST /api/machines/bulk` — bulk `on`, `off`, or `delete` using `{ "ids": ["..."], "action": "on" }`

The application remains a local simulation. Device state is stored in SQLite; it does not operate real appliances or connect to physical meters. Energy estimates are illustrative, not guaranteed savings or certified safety advice. The SQLite database is created automatically on first run, and a fresh database seeds ten starter machines.
