# Owner Admin Access

Owner admin is separate from coach/player team login.

## Development Access

When Flask is running in development (`DEBUG=True` or `IS_DEV=True`) and no
owner secret is configured, the app auto-creates a temporary owner password and
prints it once to the Flask console:

```text
====================================
CoachHub Owner Admin

Owner Login:
http://127.0.0.1:5000/owner/login

Temporary Owner Password:
coachhub-dev-admin
====================================
```

This bootstrap is development-only.

## Environment Variable

Set one of these before starting the app:

```bash
ADMIN_SECRET_KEY="change-this-owner-key"
```

or:

```bash
OWNER_ACCESS_KEY="change-this-owner-key"
```

`ADMIN_SECRET_KEY` takes precedence when both are set.

`OWNER_ACCESS_KEY` is accepted as a development alias only.

In production, configure `ADMIN_SECRET_KEY`. Do not rely on the temporary
development password outside local development.

## Routes

- Login: `/owner/login`
- Dashboard: `/owner`
- Errors: `/owner/errors`
- Integrations: `/owner/integrations`
- Health: `/owner/health`
- League Developer Tools: `/owner/league-debug`
- Logout: `/owner/logout`

The owner link appears in the main navigation only after owner login. Normal
coach/player team login never grants owner access.
