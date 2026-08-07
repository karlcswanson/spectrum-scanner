// Branding.
//
// NetBox-style: the config lives in Django settings (BRAND_* env → settings.py
// BRANDING) and the server is the single source of truth. The SPA fetches it
// once on load from the public /api/config/ endpoint (see loadConfig below) —
// no rebuild, no frontend env, one place to set branding (the server).


import { reactive } from 'vue'

const DEFAULT_NAME = 'Spectrum Server'
const DEFAULT_LOGO = '/logo.png'

// Reactive brand state. Starts at the defaults and is filled in by loadConfig()
// when /api/config/ resolves; components read it directly.
export const brand = reactive({
  name: DEFAULT_NAME,
  logoUrl: DEFAULT_LOGO,
  logoAlt: DEFAULT_NAME,
  accent: '', // empty keeps the built-in blue
})

// Static project attribution — NOT client-configurable. Always rendered in the
// footer + login so a branded deploy still points home. Edit if the repo URL
// ever changes.
export const project = {
  name: 'Micboard Spectrum',
  github: 'https://github.com/karlcswanson/spectrum-scanner',
}

function apply(b) {
  const name = (b.name || '').trim()
  const logoUrl = (b.logo_url || '').trim()
  const accent = (b.accent || '').trim()
  const title = (b.title || '').trim()
  brand.name = name || DEFAULT_NAME
  brand.logoUrl = logoUrl || DEFAULT_LOGO
  brand.logoAlt = name || DEFAULT_NAME
  brand.accent = accent
  // Great default, explicit override: set the tab title verbatim from
  // BRAND_TITLE when provided, otherwise leave index.html's default untouched.
  if (title) {
    document.title = title
  }
}

// Fetch the public bootstrap config and apply branding. Fail-safe: awaited
// before first paint so the login/header never flash the default identity, but
// bounded by a short timeout so a slow or dead server can't block the app — on
// any error the defaults simply stand. Call once at startup.
export async function loadConfig() {
  try {
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), 4000)
    const res = await fetch('/api/config/', {
      headers: { Accept: 'application/json' },
      signal: controller.signal,
    })
    clearTimeout(timer)
    if (!res.ok) return
    const data = await res.json()
    if (data && data.branding) apply(data.branding)
  } catch {
    // Server unreachable / slow / bad response — keep the default identity.
  }
}
