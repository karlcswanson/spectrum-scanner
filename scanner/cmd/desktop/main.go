package main

import (
	"embed"
	"log"

	"github.com/wailsapp/wails/v2"
	"github.com/wailsapp/wails/v2/pkg/options"
	"github.com/wailsapp/wails/v2/pkg/options/assetserver"
	"github.com/wailsapp/wails/v2/pkg/options/linux"
	"github.com/wailsapp/wails/v2/pkg/options/mac"
	"github.com/wailsapp/wails/v2/pkg/options/windows"
)

//go:embed all:frontend/dist
var assets embed.FS

func main() {
	// Create the app instance
	app := NewApp()

	// Create application with options
	err := wails.Run(&options.App{
		Title:     "Spectrum Scanner",
		Width:     1280,
		Height:    800,
		MinWidth:  800,
		MinHeight: 600,
		AssetServer: &assetserver.Options{
			Assets: assets,
		},
		BackgroundColour: &options.RGBA{R: 17, G: 24, B: 39, A: 1}, // gray-900
		Debug: options.Debug{
			OpenInspectorOnStartup: false, // Set to true to auto-open devtools
		},
		OnStartup:  app.startup,
		OnShutdown: app.shutdown,
		OnDomReady: app.onDomReady,
		Bind: []interface{}{
			app,
		},
		Mac: &mac.Options{
			About: &mac.AboutInfo{
				Title:   "Spectrum Scanner",
				Message: "RF Spectrum Analyzer for ADALM-Pluto\n\nMicboard Spectrum Scanner",
			},
		},
		Windows: &windows.Options{
			WebviewIsTransparent:              false,
			WindowIsTranslucent:               false,
			DisableWindowIcon:                 false,
			DisableFramelessWindowDecorations: false,
			WebviewUserDataPath:               "", // Use default (AppData)
			Theme:                             windows.Dark,
			CustomTheme: &windows.ThemeSettings{
				DarkModeTitleBar:   windows.RGB(17, 24, 39), // gray-900
				DarkModeTitleText:  windows.RGB(255, 255, 255),
				DarkModeBorder:     windows.RGB(55, 65, 81), // gray-700
				LightModeTitleBar:  windows.RGB(255, 255, 255),
				LightModeTitleText: windows.RGB(0, 0, 0),
				LightModeBorder:    windows.RGB(200, 200, 200),
			},
		},
		Linux: &linux.Options{
			ProgramName:         "Spectrum Scanner",
			WindowIsTranslucent: false,
		},
	})

	if err != nil {
		log.Fatal(err)
	}
}
