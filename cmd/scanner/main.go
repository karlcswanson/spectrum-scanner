package main

import (
	"flag"
	"log"
	"os"
	"runtime"

	"spectrum-pluto/internal/api"
	"spectrum-pluto/internal/config"
	"spectrum-pluto/internal/maia"
	"spectrum-pluto/internal/models"
	"spectrum-pluto/internal/mqtt"
	"spectrum-pluto/internal/sweep"
)

func main() {
	// Detect environment and set appropriate defaults
	defaultMaia := "https://192.168.2.1" // Dev: remote Pluto via USB (HTTPS)
	defaultListen := ":8080"             // Dev: unprivileged port

	if runtime.GOARCH == "arm" {
		// Running on the Pluto itself
		// Port 80 = stock Pluto page, Port 443 = maia-httpd HTTPS
		defaultMaia = "https://localhost" // Prod: local maia-httpd (HTTPS)
		defaultListen = ":8080"           // Prod: use 8080 (80 is stock page)
	}

	// Command line flags
	listenAddr := flag.String("listen", defaultListen, "HTTP listen address")
	maiaURL := flag.String("maia", defaultMaia, "maia-httpd base URL")
	configFile := flag.String("config", "", "Config file path (optional)")
	autoStart := flag.Bool("auto-start", false, "Automatically start scanning on startup")
	flag.Parse()

	// Allow environment variable overrides
	if envListen := os.Getenv("SCANNER_LISTEN"); envListen != "" {
		*listenAddr = envListen
	}
	if envMaia := os.Getenv("SCANNER_MAIA_URL"); envMaia != "" {
		*maiaURL = envMaia
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

	// Allow environment variable overrides for identity
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

	// Create maia-httpd client
	maiaClient := maia.NewClient(*maiaURL)

	// Verify maia-httpd is reachable
	log.Printf("Connecting to maia-httpd at %s...", *maiaURL)
	ad9361, err := maiaClient.GetAd9361()
	if err != nil {
		log.Printf("Warning: Cannot connect to maia-httpd at %s: %v", *maiaURL, err)
		log.Println("Continuing anyway - scanning will fail until maia-httpd is available")
	} else {
		log.Printf("Connected to maia-httpd")
		log.Printf("  AD9361 RX LO: %.2f MHz", float64(ad9361.RxLoFrequency)/1e6)
		log.Printf("  Sample rate: %.2f MHz", float64(ad9361.SamplingFrequency)/1e6)
		log.Printf("  RX Gain: %.1f dB (%s)", ad9361.RxGain, ad9361.RxGainMode)
	}

	// Create MQTT client if configured
	var mqttClient *mqtt.Client
	if cfg.MQTT != nil && cfg.MQTT.Enabled {
		log.Printf("MQTT enabled, connecting to %s...", cfg.MQTT.Broker)
		mqttClient, err = mqtt.NewClient(cfg.MQTT, cfg)
		if err != nil {
			log.Printf("Warning: Failed to create MQTT client: %v", err)
		} else if mqttClient != nil {
			if err := mqttClient.Connect(); err != nil {
				log.Printf("Warning: Failed to connect to MQTT broker: %v", err)
			} else {
				defer mqttClient.Disconnect()
			}
		}
	}

	// Create sweep engine
	engine := sweep.NewEngine(maiaClient, cfg, mqttClient)

	// Auto-start scanning if requested (via flag or config)
	if *autoStart || cfg.AutoStart {
		log.Println("Auto-starting scanner...")
		if err := engine.Start(); err != nil {
			log.Printf("Warning: Failed to auto-start scanner: %v", err)
		}
	}

	// Create and start HTTP server
	server := api.NewServer(engine, cfg, mqttClient)
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
