package web

import "embed"

//go:embed *.html *.png assets
var Assets embed.FS
