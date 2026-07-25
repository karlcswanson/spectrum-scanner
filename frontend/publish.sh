#!/bin/sh
set -e
# Frontend publish step: inject the analytics embed (if ANALYTICS_EMBED is set)
# into index.html, then copy the static build to the shared volume. Runtime env,
# so the tracker snippet changes with a container restart — no rebuild needed.
#
# ANALYTICS_EMBED holds a raw HTML snippet (e.g. an Umami/Plausible <script> tag);
# it replaces the <!--ANALYTICS--> marker in index.html. awk inserts it literally,
# so </>, &, quotes etc. need no escaping.

INDEX=/dist/index.html

if [ -n "$ANALYTICS_EMBED" ]; then
  printf '%s\n' "$ANALYTICS_EMBED" > /tmp/embed.html
  awk '
    /<!--ANALYTICS-->/ {
      while ((getline line < "/tmp/embed.html") > 0) print line
      next
    }
    { print }
  ' "$INDEX" > "$INDEX.tmp"
  mv "$INDEX.tmp" "$INDEX"
  echo "publish: injected ANALYTICS_EMBED into index.html"
fi

cp -r /dist/. /srv/frontend/
echo "publish: static files copied to /srv/frontend"
