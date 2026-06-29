# CoachHub Hockey Roadmap

## Completed

- Team-key authentication with coach/player roles.
- Team branding, logo upload, and protected export storage.
- Dashboard, calendar, attendance, message board, players, roster, formations,
  drill editor, drill/session exports, and audit log.
- Týmuj ICS integration with local cache.
- League integration with normalized parser/cache/view model.
- WhatsApp local preview/share flow.
- Server-side URL validation for external integrations.
- Route smoke tests, parser tests, permission tests, and stabilization regression
  tests.
- Architecture and roadmap documentation.

## In Progress

- Stabilizing production readiness.
- Cleaning invalid HTML and duplicated JavaScript.
- Expanding coverage around permissions, integrations, and rendering.
- Reducing legacy Flask-Login noise after team-only mode migration.

## Future Features

- Background/scheduled refresh jobs for integrations.
- Richer attendance reminders and summaries.
- More league connectors.
- Import/export improvements for drills and rosters.
- Better admin tooling for support and key recovery.

## Technical Debt

- Some templates still contain large inline scripts for complex drill/calendar
  behavior.
- `style.css` is large and should eventually be split by feature.
- SQLAlchemy `Query.get()` calls should be migrated to `db.session.get(...)`.
- Flask-Limiter should use persistent production storage.
- Retention deletion should reuse the same comprehensive team-deletion path as
  settings.
- More browser-level tests would improve confidence for the drill editor and
  formation drag/drop workflows.
