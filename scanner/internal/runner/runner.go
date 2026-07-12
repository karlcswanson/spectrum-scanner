// Package runner provides common startup logic for both CLI and desktop scanner apps.
package runner

import (
	"context"
	"fmt"
	"log"
	"runtime"
	"sync"
	"time"

	"scanner/internal/backend/owon"
	"scanner/internal/backend/pluto"
	"scanner/internal/backend/tinysa"
	"scanner/internal/config"
	"scanner/internal/db"
	"scanner/internal/models"
	"scanner/internal/mqtt"
	"scanner/internal/scanner"
)

// Runner holds all the initialized components for a scanner instance.
type Runner struct {
	Config     *models.Config
	Backend    scanner.Backend
	Engine     *scanner.Engine
	MQTTClient *mqtt.Client
	Store      *db.Store

	ctx    context.Context
	cancel context.CancelFunc
	wg     sync.WaitGroup
}

// Options configures the runner behavior
type Options struct {
	// AutoConnect attempts to connect to backend on startup (default: true)
	AutoConnect bool
	// AutoStartMQTT starts MQTT if enabled in config (default: true)
	AutoStartMQTT bool
	// EnableStore initializes SQLite store for scan history (default: true)
	EnableStore bool
	// StoreRetentionHours is how long to keep scans (default: 24)
	StoreRetentionHours int
}

// DefaultOptions returns sensible defaults
func DefaultOptions() Options {
	return Options{
		AutoConnect:         true,
		AutoStartMQTT:       true,
		EnableStore:         true,
		StoreRetentionHours: 24,
	}
}

// New creates a new Runner with all components initialized based on config.
func New(cfg *models.Config, opts Options) (*Runner, error) {
	ctx, cancel := context.WithCancel(context.Background())
	return newRunner(ctx, cancel, cfg, opts)
}

// NewWithContext creates a Runner with an external context for lifecycle management.
// Use this when embedding Runner in another application (e.g., Wails desktop app).
func NewWithContext(ctx context.Context, cfg *models.Config, opts Options) (*Runner, error) {
	childCtx, cancel := context.WithCancel(ctx)
	return newRunner(childCtx, cancel, cfg, opts)
}

// newRunner is the shared implementation for New and NewWithContext
func newRunner(ctx context.Context, cancel context.CancelFunc, cfg *models.Config, opts Options) (*Runner, error) {
	r := &Runner{
		Config: cfg,
		ctx:    ctx,
		cancel: cancel,
	}

	// Create backend
	backend, err := CreateBackend(cfg)
	if err != nil {
		cancel()
		return nil, fmt.Errorf("failed to create backend: %w", err)
	}
	r.Backend = backend

	// Connect to backend if requested
	if opts.AutoConnect {
		log.Printf("Connecting to %s backend...", backend.Type())
		if err := backend.Connect(); err != nil {
			log.Printf("Warning: Cannot connect to backend: %v", err)
			log.Println("Continuing anyway - scanning will fail until hardware is available")
		} else {
			log.Printf("Connected to %s: %s", backend.Type(), backend.Name())
		}
	}

	// Create MQTT client if configured and enabled
	if opts.AutoStartMQTT && cfg.MQTT != nil && cfg.MQTT.Enabled {
		log.Printf("MQTT enabled, connecting to %s...", cfg.MQTT.Broker)
		mqttClient, err := mqtt.NewClient(cfg.MQTT, cfg)
		if err != nil {
			log.Printf("Warning: Failed to create MQTT client: %v", err)
		} else {
			if err := mqttClient.Connect(); err != nil {
				log.Printf("Warning: Failed to connect to MQTT broker: %v", err)
			} else {
				r.MQTTClient = mqttClient
			}
		}
	}

	// Create sweep engine
	r.Engine = scanner.NewEngine(backend, cfg, r.MQTTClient)

	// Connect engine as command handler for MQTT commands
	if r.MQTTClient != nil {
		r.MQTTClient.SetCommandHandler(r.Engine)
	}

	// Initialize SQLite store for scan history
	if opts.EnableStore {
		if err := r.initStore(opts.StoreRetentionHours); err != nil {
			log.Printf("Warning: Failed to initialize scan history: %v", err)
		}
	}

	return r, nil
}

// initStore initializes the SQLite store and starts background goroutines
func (r *Runner) initStore(retentionHours int) error {
	dbPath := config.AppConfigDir() + "/scans.db"
	store, err := db.NewStore(dbPath)
	if err != nil {
		return fmt.Errorf("failed to open database: %w", err)
	}
	r.Store = store
	log.Printf("Scan history database: %s", dbPath)

	// Start cleanup goroutine
	r.wg.Add(1)
	go r.runCleanupLoop(retentionHours)

	// Start scan persistence goroutine
	r.wg.Add(1)
	go r.runScanPersistence()

	return nil
}

// runCleanupLoop periodically removes old scans
func (r *Runner) runCleanupLoop(retentionHours int) {
	defer r.wg.Done()
	ticker := time.NewTicker(1 * time.Hour)
	defer ticker.Stop()

	for {
		select {
		case <-ticker.C:
			if r.Store != nil {
				r.Store.Cleanup(retentionHours)
			}
		case <-r.ctx.Done():
			return
		}
	}
}

// runScanPersistence subscribes to engine scans and stores them
func (r *Runner) runScanPersistence() {
	defer r.wg.Done()

	ch := r.Engine.Subscribe()
	defer r.Engine.Unsubscribe(ch)

	for {
		select {
		case scan, ok := <-ch:
			if !ok {
				return
			}
			if r.Store != nil {
				if err := r.Store.StoreScan(&scan); err != nil {
					log.Printf("Warning: failed to store scan: %v", err)
				}
			}
		case <-r.ctx.Done():
			return
		}
	}
}

// AutoStart starts scanning if config.AutoStart is true
func (r *Runner) AutoStart() error {
	if r.Config.AutoStart {
		log.Println("Auto-starting scanner...")
		return r.Engine.Start()
	}
	return nil
}

// Close shuts down all components and waits for goroutines to finish
func (r *Runner) Close() {
	// Cancel context to signal goroutines to stop
	if r.cancel != nil {
		r.cancel()
	}

	// Stop scanning
	if r.Engine != nil && r.Engine.IsRunning() {
		r.Engine.Stop()
	}

	// Wait for background goroutines
	r.wg.Wait()

	// Close components
	if r.MQTTClient != nil {
		r.MQTTClient.Disconnect()
	}
	if r.Backend != nil {
		r.Backend.Close()
	}
	if r.Store != nil {
		r.Store.Close()
	}
}

// CreateBackend creates the appropriate scanner backend based on configuration.
func CreateBackend(cfg *models.Config) (scanner.Backend, error) {
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
		return pluto.NewClient(url, cfg.DeviceID), nil
	}

	switch backendType {
	case "pluto":
		// ADALM-Pluto via maia-httpd
		url := "https://192.168.2.1" // default USB network
		if cfg.Backend != nil && cfg.Backend.URL != "" {
			url = cfg.Backend.URL
		}
		return pluto.NewClient(url, cfg.DeviceID), nil

	case "owon":
		// OWON HSA1000 series via SCPI/TCP
		if cfg.Backend == nil || cfg.Backend.Address == "" {
			return nil, fmt.Errorf("OWON backend requires address (IP) in config or via --addr flag")
		}
		port := cfg.Backend.Port
		if port == 0 {
			port = owon.DefaultPort
		}
		return owon.NewClient(cfg.Backend.Address, port, cfg.DeviceID), nil

	case "tinysa":
		// tinySA Ultra via serial
		tinysaCfg := tinysa.DefaultConfig()
		if cfg.Backend != nil && cfg.Backend.Port != 0 {
			tinysaCfg.Port = fmt.Sprintf("/dev/ttyUSB%d", cfg.Backend.Port)
		}
		if cfg.Backend != nil && cfg.Backend.Address != "" {
			// Allow specifying full serial port path via address
			tinysaCfg.Port = cfg.Backend.Address
		}
		return tinysa.NewBackend(tinysaCfg), nil

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

// EnableMQTT connects to MQTT broker (for runtime enable)
func (r *Runner) EnableMQTT() error {
	return r.EnableMQTTWithCallback(nil)
}

// EnableMQTTWithCallback connects to MQTT broker with an optional connection callback
func (r *Runner) EnableMQTTWithCallback(callback mqtt.ConnectionCallback) error {
	if r.Config.MQTT == nil || r.Config.MQTT.Broker == "" {
		return fmt.Errorf("MQTT not configured")
	}

	// Disconnect existing client
	if r.MQTTClient != nil {
		r.MQTTClient.Disconnect()
		r.MQTTClient = nil
	}

	log.Printf("MQTT: Connecting to %s...", r.Config.MQTT.Broker)

	client, err := mqtt.NewClient(r.Config.MQTT, r.Config)
	if err != nil {
		return fmt.Errorf("failed to create MQTT client: %w", err)
	}

	// Set callback before connecting
	if callback != nil {
		client.SetConnectionCallback(callback)
	}

	if err := client.Connect(); err != nil {
		return fmt.Errorf("failed to connect to MQTT broker: %w", err)
	}

	r.MQTTClient = client
	r.Config.MQTT.Enabled = true

	// Connect engine as command handler
	if r.Engine != nil {
		client.SetCommandHandler(r.Engine)
		r.Engine.SetMQTTClient(client)
	}

	// Note: Connect() is async, actual connection status comes via callback
	return nil
}

// DisableMQTT disconnects from MQTT broker
func (r *Runner) DisableMQTT() {
	if r.MQTTClient != nil {
		r.MQTTClient.Disconnect()
		r.MQTTClient = nil
	}
	if r.Config.MQTT != nil {
		r.Config.MQTT.Enabled = false
	}
	if r.Engine != nil {
		r.Engine.SetMQTTClient(nil)
	}
	log.Println("MQTT: Disconnected")
}
