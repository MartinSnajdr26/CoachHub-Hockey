# CoachHub Hockey Architecture

## Application Structure

CoachHub Hockey is a Flask application organized around blueprints, SQLAlchemy
models, Jinja templates, static JavaScript/CSS, and small service modules.

- `app.py` creates and configures the Flask app, extensions, security hooks,
  context processors, blueprints, CLI commands, upload/export folders, and
  legacy endpoint aliases.
- `blueprints/` contains request handlers grouped by feature area.
- `models/` contains SQLAlchemy models.
- `services/` contains integration and utility logic that should not live in
  route handlers.
- `templates/` contains Jinja templates.
- `static/` contains global and feature-specific CSS/JS/assets.
- `tests/` contains parser, route, permission, integration-cache, and regression
  tests.

## Blueprints

- `teamauth`: team-key login, team creation, logout, and key rotation.
- `calendar`: dashboard, calendar events, attendance, and team messages.
- `players`: player CRUD and Týmuj roster import from cached data.
- `roster`: match nomination roster.
- `lines`: lineup/formation editor and lineup PDF export.
- `drills`: drill CRUD, drill session folders, and drill PDF export.
- `files`: protected export downloads with team ownership checks.
- `settings`: branding, Týmuj URL, league settings, explicit integration refresh,
  and team deletion.
- `admin`: team audit log.
- `legal` and `public`: public/legal pages.

## Models

Core team data:

- `Team`
- `TeamKey`
- `TeamLoginAttempt`
- `AuditEvent`

Sport/team workflow:

- `Player`
- `Roster`
- `LineAssignment`
- `TrainingEvent`
- `AttendanceEntry`
- `Drill`
- `TrainingSession`
- `LineupSession`

Integrations:

- `LeagueIntegration` stores league configuration and cached normalized league data.
- `AuditEvent(event='tymuj.cache')` stores cached Týmuj event/participant data.

## Services

- `services.keys`: team key generation and verification.
- `services.exports`: protected export cleanup.
- `services.retention`: retention CLI helpers.
- `services.team_utils`: team-name helper queries.
- `services.url_safety`: validates server-side fetch URLs against SSRF risk.
- `services.tymuj`: Týmuj ICS parsing and cache access.
- `services.league`: connector registry, safe fetch/parser base, generic HTML
  parser, vysledky.com parser, and cached view-model service.

## Integrations

### Týmuj

The app stores only the coach-provided ICS URL on `Team.tymuj_ics_url`.
Týmuj data is fetched only during explicit coach actions:

- saving settings with a Týmuj ICS URL
- pressing the Týmuj refresh button on the import page

Normal dashboard, attendance, and import GET rendering reads from the local
`AuditEvent(event='tymuj.cache')` cache.

### League

League configuration and cached public competition data are stored in
`LeagueIntegration`. Dashboard rendering uses `league.service.get_view()` only
and never fetches external pages. External league fetches happen only through
explicit settings actions such as test/refresh.

### WhatsApp

WhatsApp integration is client-side only. `static/wa.js` builds local message
previews and opens WhatsApp/share/copy flows. No phone numbers, group IDs, or
server-side WhatsApp API calls are stored or executed.

## Cache Layer

The cache strategy is intentionally simple:

- League cache: `LeagueIntegration.data_json`, refreshed explicitly.
- Týmuj cache: `AuditEvent(event='tymuj.cache').meta`, refreshed explicitly.
- Dashboard/calendar/attendance pages read cached/local data only.

Future integrations should follow the same rule: route rendering reads local
state; external calls happen in explicit refresh actions or background jobs.

## Authentication

Authentication is team-key based:

- Team has one active coach key and one active player key.
- Keys are hashed with scrypt and displayed only once when generated/rotated.
- Session keys are `team_id`, `team_role`, and `team_login`.
- `team_login_required` gates team pages.
- `coach_required` gates mutating coach actions.

Flask-Login remains initialized for template compatibility, but current
application behavior is team-session based.

## Adding Future Integrations

Add future integrations in `services/`, not directly in blueprints:

1. Add URL/input validation in the service.
2. Store configuration on a model or existing settings record.
3. Store fetched external data in a local cache.
4. Expose `refresh(...)` for explicit refresh actions.
5. Expose `get_view(...)` or `get_cached_*` for templates/routes.
6. Add parser tests and route tests proving normal page rendering does not make
   external network calls.
