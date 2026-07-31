# Single sign-on (SSO)

Let users sign in with your organization's identity provider — **Okta, Microsoft
Entra, or Google Workspace** — instead of a separate username and password.

SSO is **optional and off by default**, and each deployment uses **one** provider.
Built on [python-social-auth](https://python-social-auth.readthedocs.io/); the
provider is chosen by a dotted-path backend, the same way NetBox does it.

- Local username/password login keeps working alongside SSO (an administrator can
  always get in, even if the identity provider is down).
- Read-only share links are unaffected.
- With SSO disabled, no extra database tables are created.

## How access works

Signing in **authenticates** a user — it does not grant them access. Authorization
is managed in the app:

1. A new SSO user is created automatically on first login and added to the local
   Django group(s) named in `SSO_DEFAULT_GROUPS`.
2. You give that **group** access once, in Django admin → **Access** (a grant to a
   group applies to every member). New sign-ins then inherit that baseline.
3. For finer control, grant access to individual users, or to other groups you
   create and assign people to.

No groups are synced from the identity provider — the groups are local and managed
by you.

## Step 1 — Register the application with your provider

Create an app registration / OAuth client in your provider and note its **client
ID** and **client secret**. Set the **redirect URI** to your app's callback for the
chosen backend (the path differs per provider — see the table in Step 2):

- Production: `https://<your-host>/oauth/complete/<backend>/`
- Local dev: `http://localhost:5174/oauth/complete/<backend>/` (the Vite dev
  server; use `:5173` if you run `npm run dev` directly)

### Microsoft Entra
1. **Entra admin → App registrations → New registration.** Single-tenant.
2. Redirect URI (Web): `.../oauth/complete/azuread-v2-tenant-oauth2/`.
3. **Certificates & secrets → New client secret** → the *Value* is your secret.
4. From **Overview**, copy the **Application (client) ID** and **Directory
   (tenant) ID**.

### Okta
1. **Okta admin → Applications → Create App Integration → OIDC → Web Application.**
2. Sign-in redirect URI: `.../oauth/complete/okta-openidconnect/`.
3. Copy the **Client ID** and **Client secret**, and note your org URL
   (`https://<org>.okta.com`).

### Google Workspace
1. **Google Cloud Console → APIs & Services → Credentials → Create OAuth client
   ID → Web application.**
2. Authorized redirect URI: `.../oauth/complete/google-oauth2/`.
3. Copy the **Client ID** and **Client secret**.

## Step 2 — Configure the server

Set the following in `.env`, then recreate the server container
(`docker compose up -d server`). Real secrets go in `.env` only — never commit
them.

Pick the backend and set that backend's own `SOCIAL_AUTH_*` variables (they are
imported from the environment automatically):

| Provider | `SSO_BACKEND` | Redirect URI path | Config variables |
|----------|---------------|-------------------|------------------|
| **Entra** | `social_core.backends.azuread_tenant.AzureADV2TenantOAuth2` | `/oauth/complete/azuread-v2-tenant-oauth2/` | `SOCIAL_AUTH_AZUREAD_V2_TENANT_OAUTH2_KEY` / `_SECRET` / `_TENANT_ID` |
| **Okta** | `social_core.backends.okta_openidconnect.OktaOpenIdConnect` | `/oauth/complete/okta-openidconnect/` | `SOCIAL_AUTH_OKTA_OPENIDCONNECT_KEY` / `_SECRET` / `_API_URL` |
| **Google** | `social_core.backends.google.GoogleOAuth2` | `/oauth/complete/google-oauth2/` | `SOCIAL_AUTH_GOOGLE_OAUTH2_KEY` / `_SECRET` |

**Entra example:**

```bash
SSO_ENABLED=true
SSO_BACKEND=social_core.backends.azuread_tenant.AzureADV2TenantOAuth2
SOCIAL_AUTH_AZUREAD_V2_TENANT_OAUTH2_KEY=<application-client-id>
SOCIAL_AUTH_AZUREAD_V2_TENANT_OAUTH2_SECRET=<client-secret>
SOCIAL_AUTH_AZUREAD_V2_TENANT_OAUTH2_TENANT_ID=<directory-tenant-id>

# New SSO users are auto-added to these local Django groups (baseline access):
SSO_DEFAULT_GROUPS=SSO Users

# Optional: only allow these email domains to sign in
SOCIAL_AUTH_AZUREAD_V2_TENANT_OAUTH2_WHITELISTED_DOMAINS=yourcompany.com

# Login button appearance
SSO_PROVIDER_BRAND=microsoft
```

**Okta example** — same shape, plus the org URL:

```bash
SSO_ENABLED=true
SSO_BACKEND=social_core.backends.okta_openidconnect.OktaOpenIdConnect
SOCIAL_AUTH_OKTA_OPENIDCONNECT_KEY=<client-id>
SOCIAL_AUTH_OKTA_OPENIDCONNECT_SECRET=<client-secret>
SOCIAL_AUTH_OKTA_OPENIDCONNECT_API_URL=https://<org>.okta.com/oauth2
SSO_DEFAULT_GROUPS=SSO Users
```

The login page now shows the SSO button as the primary action, with local login
below.

## Step 3 — Grant the default group access

Once, in **Django admin → Access → Add**:
- **Principal:** group `SSO Users` (the group from `SSO_DEFAULT_GROUPS`).
- **Scope:** a scanner or scanner group.
- **Permission:** read or read/write.

Every SSO user now inherits that access on first login. To make a user an
administrator, check **Staff status** on their user (SSO users are not staff by
default).

## Testing checklist (dev)

1. `SSO_ENABLED=true` + the provider block above in `server/.env`.
2. Register the matching redirect URI (`http://localhost:5174/oauth/complete/<backend>/`).
3. `docker compose up -d server` — recreates the container so it picks up the
   new `.env` values (a plain `restart` reuses the old environment). Startup runs
   migrations (creates the `social_django` tables and the `Access` group field).
4. Add the `SSO Users` group grant in admin (Step 3).
5. Open `http://localhost:5174`, click the SSO button, sign in.
6. Confirm at `http://localhost:5174/api/auth/user/` that you're authenticated,
   and that the granted scanner is now visible.

> **Dev note:** start the flow from the Vite dev server (`:5174`) so the callback
> host matches what you registered. The dev proxy preserves the browser's host for
> the `/oauth` path; in production (behind Caddy) callbacks are built as HTTPS
> automatically.

## Reference

| Setting | Required | Description |
|---------|----------|-------------|
| `SSO_ENABLED` | yes | Turn SSO on (`true`/`false`). |
| `SSO_BACKEND` | yes | Dotted path to the provider backend (see table). |
| `SOCIAL_AUTH_<BACKEND>_KEY` / `_SECRET` | yes | The app's client ID / secret. |
| `SOCIAL_AUTH_AZUREAD_V2_TENANT_OAUTH2_TENANT_ID` | Entra | Directory (tenant) ID. |
| `SOCIAL_AUTH_OKTA_OPENIDCONNECT_API_URL` | Okta | `https://<org>.okta.com/oauth2`. |
| `SOCIAL_AUTH_<BACKEND>_WHITELISTED_DOMAINS` | no | Restrict sign-in to these email domains. |
| `SSO_DEFAULT_GROUPS` | no | Local Django groups new SSO users join (baseline access). |
| `SSO_LOGIN_REDIRECT_URL` / `SSO_LOGOUT_REDIRECT_URL` | no | Where users land after login/logout (default `/`). |
| `SSO_PROVIDER_BRAND` | no | `microsoft` for the branded button; otherwise neutral. |
| `SSO_BUTTON_LABEL` | no | Login-button text. |

Any other python-social-auth backend also works — set `SSO_BACKEND` to its dotted
path and its `SOCIAL_AUTH_*` variables. SAML is available via the bundled
`social-auth-core` if a provider ever requires it.
