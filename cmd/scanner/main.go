package main

import (
	"flag"
	"fmt"
	"log"
	"os"
	"runtime"
	"strings"

	"spectrum-pluto/internal/api"
	"spectrum-pluto/internal/backend/owon"
	"spectrum-pluto/internal/backend/pluto"
	"spectrum-pluto/internal/config"
	"spectrum-pluto/internal/models"
	"spectrum-pluto/internal/mqtt"
	"spectrum-pluto/internal/scanner"
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

	// Create the appropriate backend
	backend, err := createBackend(cfg)
	if err != nil {
		log.Fatalf("Failed to create backend: %v", err)
	}

	// Connect to hardware
	log.Printf("Connecting to %s backend...", backend.Type())
	if err := backend.Connect(); err != nil {
		log.Printf("Warning: Cannot connect to backend: %v", err)
		log.Println("Continuing anyway - scanning will fail until hardware is available")
	} else {
		log.Printf("Connected to %s: %s", backend.Type(), backend.Name())
		defer backend.Close()
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

	// Create sweep engine with the backend
	engine := scanner.NewEngine(backend, cfg, mqttClient)

	// Auto-start scanning if requested
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

// createBackend creates the appropriate scanner backend based on configuration.
func createBackend(cfg *models.Config) (scanner.Backend, error) {
	// Determine backend type
	backendType := "pluto" // default
	if cfg.Backend != nil && cfg.Backend.Type != "" {
		backendType = cfg.Backend.Type
	}

	// Auto-detect Pluto on ARM (running on the device itself)
	if backendType == "pluto" && runtime.GOARCH == "arm" {
		// Running on the Pluto itself
		url := "https://localhost"
		if cfg.Backend != nil && cfg.Backend.URL != "" {
			url = cfg.Backend.URL
		}
		return pluto.NewClient(url, cfg.Name), nil
	}

	switch backendType {
	case "pluto":
		// ADALM-Pluto via maia-httpd
		url := "https://192.168.2.1" // default USB network
		if cfg.Backend != nil && cfg.Backend.URL != "" {
			url = cfg.Backend.URL
		}
		return pluto.NewClient(url, cfg.Name), nil

	case "owon":
		// OWON HSA1000 series via SCPI/TCP
		if cfg.Backend == nil || cfg.Backend.Address == "" {
			return nil, fmt.Errorf("OWON backend requires address (IP) in config or via --addr flag")
		}
		port := cfg.Backend.Port
		if port == 0 {
			port = owon.DefaultPort
		}
		return owon.NewClient(cfg.Backend.Address, port, cfg.Name), nil

	case "rtlsdr":
		return nil, fmt.Errorf("RTL-SDR backend not yet implemented")

	case "rfexplorer":
		return nil, fmt.Errorf("RF Explorer backend not yet implemented")

	case "tti":
		return nil, fmt.Errorf("TTi backend not yet implemented")

	default:
		return nil, fmt.Errorf("unknown backend type: %s", backendType)
	}
}
