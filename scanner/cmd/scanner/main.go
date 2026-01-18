package main

import (
	"flag"
	"log"
	"os"
	"strings"

	"scanner/internal/api"
	"scanner/internal/config"
	"scanner/internal/models"
	"scanner/internal/runner"
)

func main() {
	// Command line flags
	listenAddr := flag.String("listen", ":8080", "HTTP listen address")
	backendType := flag.String("backend", "", "Backend type: pluto, owon (overrides config)")
	backendAddr := flag.String("addr", "", "Backend address (IP or URL, overrides config)")
	configFile := flag.String("config", "", "Config file path (optional)")
	autoStart := flag.Bool("auto-start", false, "Automatically start scanning on startup")
	flag.Parse()

	// Allow environment variable overrides
	if envListen := os.Getenv("SCANNER_LISTEN"); envListen != "" {
		*listenAddr = envListen
	}
	if envBackend := os.Getenv("SCANNER_BACKEND"); envBackend != "" {
		*backendType = envBackend
	}
	if envAddr := os.Getenv("SCANNER_ADDR"); envAddr != "" {
		*backendAddr = envAddr
	}

	// Load configuration
	var cfg *models.Config
	var err error

	if *configFile != "" {
		cfg, err = config.LoadFromFile(*configFile)
		if err != nil {
			log.Fatalf("Failed to load config from %s: %v", *configFile, err)
		}
		log.Printf("Loaded configuration from %s", *configFile)
	} else {
		cfg = config.DefaultConfig()
		log.Println("Using default configuration")
	}

	// Command line overrides for backend
	if *backendType != "" {
		if cfg.Backend == nil {
			cfg.Backend = &models.BackendConfig{}
		}
		cfg.Backend.Type = *backendType
	}
	if *backendAddr != "" {
		if cfg.Backend == nil {
			cfg.Backend = &models.BackendConfig{}
		}
		// Detect if it's a URL or IP address
		if strings.HasPrefix(*backendAddr, "http") {
			cfg.Backend.URL = *backendAddr
		} else {
			cfg.Backend.Address = *backendAddr
		}
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

	// Auto-start scanning if requested (flag overrides config)
	if *autoStart {
		cfg.AutoStart = true
	}
	if err := r.AutoStart(); err != nil {
		log.Printf("Warning: Failed to auto-start scanner: %v", err)
	}

	// Create and start HTTP server
	server := api.NewServer(r.Engine, cfg, r.MQTTClient)

	// Wire up config save callback if using a config file
	if *configFile != "" {
		cfgPath := *configFile
		server.SetConfigSaveFunc(func() error {
			return config.SaveToFile(cfgPath, cfg)
		})
	}

	// Wire up status change callback to broadcast to WebSocket clients
	r.Engine.SetStatusChangeCallback(func(scanning bool, currentBand string) {
		server.WSHub().BroadcastStatus(scanning, currentBand)
	})

	log.Printf("Starting HTTP server on %s", *listenAddr)
	log.Printf("API endpoints:")
	log.Printf("  GET  /api/status     - Scanner status")
	log.Printf("  GET  /api/config     - Configuration")
	log.Printf("  PUT  /api/config     - Update configuration")
	log.Printf("  GET  /api/bands      - Band list")
	log.Printf("  PUT  /api/bands      - Update bands")
	log.Printf("  POST /api/scan/start - Start scanning")
	log.Printf("  POST /api/scan/stop  - Stop scanning")
	log.Printf("  GET  /ws/stream      - WebSocket for live data")

	if err := server.ListenAndServe(*listenAddr); err != nil {
		log.Fatalf("Server error: %v", err)
	}
}
