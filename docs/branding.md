# Branding

Optional `BRAND_*` env vars on the Django server (`server/.env`) customize the UI.

## Options

| Var | Effect |
|-----|--------|
| `BRAND_LOGO_URL` | Logo in the header + login. A `/brand/…` path (see below) or any URL |
| `BRAND_NAME` | Text beside the logo |
| `BRAND_ACCENT` | Header underline + primary button colour |
| `BRAND_TITLE` | Browser tab title |

```
# server/.env
BRAND_LOGO_URL=/brand/logo.svg
BRAND_ACCENT=#c81e3c
```

## Logo file

Place the logo file in `frontend/public/brand/` and reference it by path:

```
cp client-logo.svg frontend/public/brand/logo.svg
# server/.env
BRAND_LOGO_URL=/brand/logo.svg
```

Files in that folder are gitignored except `.gitkeep`. Vite serves `/brand/*` in dev; in prod the `caddy` service mounts the folder into the web root (no rebuild). A white/light, transparent-background SVG or PNG works best. `BRAND_LOGO_URL` may also be any absolute URL.

## Apply

```
docker compose -f docker-compose.prod.yml up -d server
```

Values are read at server startup — recreate the server, then refresh the browser.
