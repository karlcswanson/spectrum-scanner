package main

import (
	"flag"
	"log"
	"os"
	"time"

	"scanner/internal/api"
	"scanner/internal/config"
	"scanner/internal/db"
	"scanner/internal/runner"
)

func main() {
	// Command line flags (env vars are also checked by config.LoadWithOptions)
	opts := config.DefaultOptions()
	flag.StringVar(&opts.ListenAddr, "listen", opts.ListenAddr, "HTTP listen address")
	flag.StringVar(&opts.BackendType, "backend", "", "Backend type: pluto, owon (overrides config)")
	flag.StringVar(&opts.BackendAddr, "addr", "", "Backend address (IP or URL, overrides config)")
	flag.StringVar(&opts.ConfigFile, "config", "", "Config file path (optional)")
	flag.Parse()

	// Load config with options (handles env vars and applies overrides)
	cfg, configPath, err := config.LoadWithOptions(opts)
	if err != nil {
		log.Fatalf("Failed to load config from %s: %v", configPath, err)
	}
	if configPath != "" {
		log.Printf("Loaded configuration from %s", configPath)
	} else {
		log.Println("Using default configuration")
	}

	// Environment variable overrides for identity
	if id := os.Getenv("SCANNER_ID"); id != "" {
		cfg.DeviceID = id
	}
	if name := os.Getenv("SCANNER_NAME"); name != "" {
		cfg.Name = name
	}
	if desc := os.Getenv("SCANNER_DESCRIPTION"); desc != "" {
		cfg.Description = desc
	}

	log.Printf("Spectrum Scanner: %s (%s)", cfg.Name, cfg.DeviceID)
	log.Printf("  Description: %s", cfg.Description)
	log.Printf("  Dwell time: %d ms", cfg.DwellTimeMs)
	log.Printf("  Bands configured: %d", len(cfg.Bands))
	for _, band := range cfg.Bands {
		status := "disabled"
		if band.Enabled {
			status = "enabled"
		}
		log.Printf("    - %s: %.1f - %.1f MHz [%s]",
			band.Name,
			float64(band.StartHz)/1e6,
			float64(band.StopHz)/1e6,
			status)
	}

	// Create runner with all components
	r, err := runner.New(cfg, runner.DefaultOptions())
	if err != nil {
		log.Fatalf("Failed to initialize: %v", err)
	}
	defer r.Close()

	// Always auto-start scanning
	cfg.AutoStart = true
	if err := r.AutoStart(); err != nil {
		log.Printf("Warning: Failed to auto-start scanner: %v", err)
	}

	// Initialize SQLite store for scan history (timeline scrubber)
	var store *db.Store
	dbPath := config.AppConfigDir() + "/scans.db"
	store, err = db.NewStore(dbPath)
	if err != nil {
		log.Printf("Warning: Failed to initialize scan history database: %v", err)
	} else {
		log.Printf("Scan history database: %s", dbPath)
		defer store.Close()
		// Start periodic cleanup (keep 24 hours)
		go func() {
			ticker := time.NewTicker(1 * time.Hour)
			defer ticker.Stop()
			for range ticker.C {
				store.Cleanup(24)
			}
		}()
	}

	// Create and start HTTP server
	server := api.NewServer(r.Engine, cfg, r.MQTTClient)

	// Wire up SQLite store for scan history endpoints
	if store != nil {
		server.SetStore(store)
	}

	// Wire up config save callback if using a config file
	if configPath != "" {
		server.SetConfigSaveFunc(func() error {
			return config.SaveToFile(configPath, cfg)
		})
	}

	// Wire up status change callback to broadcast to WebSocket clients
	r.Engine.SetStatusChangeCallback(func(scanning bool, currentBand string) {
		server.WSHub().BroadcastStatus(scanning, currentBand)
	})

	// Subscribe to scans and store them
	if store != nil {
		go func() {
			ch := r.Engine.Subscribe()
			defer r.Engine.Unsubscribe(ch)
			for scan := range ch {
				if err := store.StoreScan(&scan); err != nil {
					log.Printf("Warning: failed to store scan: %v", err)
				}
			}
		}()
	}

	log.Printf("Starting HTTP server on %s", opts.ListenAddr)
	log.Printf("API endpoints:")
	log.Printf("  GET  /api/status     - Scanner status")
	log.Printf("  GET  /api/config     - Configuration")
	log.Printf("  PUT  /api/config     - Update configuration")
	log.Printf("  GET  /api/bands      - Band list")
	log.Printf("  PUT  /api/bands      - Update bands")
	log.Printf("  POST /api/scan/start - Start scanning")
	log.Printf("  POST /api/scan/stop  - Stop scanning")
	log.Printf("  GET  /ws/stream      - WebSocket for live data")

	if err := server.ListenAndServe(opts.ListenAddr); err != nil {
		log.Fatalf("Server error: %v", err)
	}
}
