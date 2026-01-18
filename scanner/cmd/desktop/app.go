package main

import (
	"context"
	"fmt"
	"log"
	"net/http"
	"os"
	"path/filepath"
	goruntime "runtime"
	"sync"

	wailsRuntime "github.com/wailsapp/wails/v2/pkg/runtime"

	"scanner/internal/api"
	"scanner/internal/backend/pluto"
	"scanner/internal/config"
	"scanner/internal/models"
	"scanner/internal/mqtt"
	"scanner/internal/runner"
	"scanner/internal/scanner"
)

// App struct holds the desktop application state
type App struct {
	ctx    context.Context
	runner *runner.Runner
	config *models.Config

	// Server mode components (web server managed separately for desktop)
	webServer      *api.Server
	httpServer     *http.Server
	standaloneMQTT *mqtt.Client // MQTT client when running without a runner (before Pluto connects)

	mu         sync.RWMutex
	configPath string
}

// ScanEvent is sent to the frontend when new scan data arrives
type ScanEvent struct {
	Band      string    `json:"band"`
	HzLo      float64   `json:"hz_lo"`
	HzHi      float64   `json:"hz_hi"`
	Step      float64   `json:"step"`
	Power     []float64 `json:"power"`
	Timestamp string    `json:"timestamp"`
}

// StatusEvent is sent to the frontend when status changes
type StatusEvent struct {
	Scanning    bool   `json:"scanning"`
	CurrentBand string `json:"current_band"`
	Connected   bool   `json:"connected"`
}

// ServerStatus reports the state of MQTT and web server
type ServerStatus struct {
	MQTTEnabled   bool   `json:"mqtt_enabled"`
	MQTTConnected bool   `json:"mqtt_connected"`
	MQTTBroker    string `json:"mqtt_broker"`
	WebEnabled    bool   `json:"web_enabled"`
	WebPort       int    `json:"web_port"`
	WebRunning    bool   `json:"web_running"`
}

// NewApp creates a new App instance
func NewApp() *App {
	return &App{}
}

// getConfigDir returns the appropriate config directory for the platform
func getConfigDir() string {
	// Try user config directory first
	configDir, err := os.UserConfigDir()
	if err == nil {
		appDir := filepath.Join(configDir, "Spectrum Scanner")
		if err := os.MkdirAll(appDir, 0755); err == nil {
			return appDir
		}
	}

	// Fallback to home directory
	homeDir, err := os.UserHomeDir()
	if err == nil {
		appDir := filepath.Join(homeDir, ".spectrum-scanner")
		if err := os.MkdirAll(appDir, 0755); err == nil {
			return appDir
		}
	}

	// Last resort: current directory
	return "."
}

// startup is called when the app starts
func (a *App) startup(ctx context.Context) {
	a.ctx = ctx

	// Determine config path in user's config directory
	configDir := getConfigDir()
	a.configPath = filepath.Join(configDir, "config.yaml")

	// Load configuration (similar to CLI scanner)
	var err error
	if _, err = os.Stat(a.configPath); err == nil {
		a.config, err = config.LoadFromFile(a.configPath)
		if err != nil {
			log.Printf("Warning: Failed to load config: %v", err)
			a.config = config.DefaultConfig()
		} else {
			log.Printf("Loaded config from %s", a.configPath)
		}
	} else {
		a.config = config.DefaultConfig()
		log.Printf("Using default configuration (will save to %s)", a.configPath)
	}

	log.Printf("Desktop app started - %s (%s)", a.config.Name, a.config.DeviceID)

	// Start MQTT and web server independently of Pluto connection
	// These should run even if the tuner isn't available
	if a.config.MQTT != nil && a.config.MQTT.Enabled {
		go func() {
			a.mu.Lock()
			defer a.mu.Unlock()
			if err := a.startMQTTStandalone(); err != nil {
				log.Printf("Warning: Failed to auto-start MQTT: %v", err)
			} else {
				wailsRuntime.EventsEmit(a.ctx, "server-status", a.getServerStatusLocked())
			}
		}()
	}
	if a.config.Web != nil && a.config.Web.Enabled {
		go func() {
			a.mu.Lock()
			defer a.mu.Unlock()
			if err := a.startWebServer(); err != nil {
				log.Printf("Warning: Failed to auto-start web server: %v", err)
			} else {
				wailsRuntime.EventsEmit(a.ctx, "server-status", a.getServerStatusLocked())
			}
		}()
	}
}

// onDomReady is called when the frontend is ready
func (a *App) onDomReady(ctx context.Context) {
	// Auto-connect to Pluto on startup
	go a.autoConnect()
}

// autoConnect attempts to connect to Pluto and optionally start scanning
func (a *App) autoConnect() {
	// Small delay to let MQTT/web server goroutines start first
	// This prevents lock contention at startup
	log.Println("Auto-connect: waiting for services to initialize...")

	a.mu.Lock()
	defer a.mu.Unlock()

	log.Println("Auto-connect: attempting to connect to Pluto...")

	// Don't auto-start MQTT in runner - we handle it separately via standalone client
	opts := runner.Options{
		AutoConnect:   true,
		AutoStartMQTT: false, // We manage MQTT separately
	}

	r, err := runner.New(a.config, opts)
	if err != nil {
		log.Printf("Auto-connect failed: %v (user can connect manually)", err)
		return
	}

	// Check if backend actually connected
	if r.Backend == nil || !r.Backend.IsConnected() {
		log.Printf("Auto-connect: backend not connected (user can connect manually)")
		r.Close()
		return
	}

	a.runner = r

	// Update web server with the engine if it's already running
	if a.webServer != nil {
		a.webServer.SetEngine(r.Engine)
		log.Println("Updated web server with engine")
	}

	// Set up status change callback for Wails frontend
	a.runner.Engine.SetStatusChangeCallback(func(scanning bool, currentBand string) {
		wailsRuntime.EventsEmit(a.ctx, "status", StatusEvent{
			Scanning:    scanning,
			CurrentBand: currentBand,
			Connected:   a.runner != nil && a.runner.Backend != nil && a.runner.Backend.IsConnected(),
		})
		if a.webServer != nil {
			a.webServer.WSHub().BroadcastStatus(scanning, currentBand)
		}
	})

	log.Printf("Auto-connected to %s: %s", r.Backend.Type(), r.Backend.Name())

	// Connect standalone MQTT to the engine so scans get published
	if a.standaloneMQTT != nil && a.standaloneMQTT.IsConnected() {
		log.Println("Connecting standalone MQTT to engine...")
		r.Engine.SetMQTTClient(a.standaloneMQTT)
		a.standaloneMQTT.SetCommandHandler(r.Engine)
	}

	// Emit connected status to frontend
	wailsRuntime.EventsEmit(a.ctx, "status", StatusEvent{
		Scanning:    false,
		CurrentBand: "",
		Connected:   true,
	})

	// Emit server status so frontend shows current state
	wailsRuntime.EventsEmit(a.ctx, "server-status", a.getServerStatusLocked())

	// Auto-start scanning if configured
	if a.config.AutoStart {
		log.Println("Auto-starting scanning...")
		go a.forwardScans()
		if err := a.runner.Engine.Start(); err != nil {
			log.Printf("Auto-start scanning failed: %v", err)
		}
	}
}

// shutdown is called when the app is closing
func (a *App) shutdown(ctx context.Context) {
	a.mu.Lock()
	defer a.mu.Unlock()

	if a.httpServer != nil {
		a.httpServer.Close()
	}
	if a.standaloneMQTT != nil {
		a.standaloneMQTT.Disconnect()
	}
	if a.runner != nil {
		a.runner.Close()
	}
	log.Println("Desktop app shutdown")
}

// Connect connects to the Pluto device
func (a *App) Connect(address string) error {
	a.mu.Lock()
	defer a.mu.Unlock()

	// Close existing runner if any
	if a.runner != nil {
		a.runner.Close()
		a.runner = nil
	}

	// Default address
	if address == "" {
		address = "https://192.168.2.1"
	}

	// Update config with address
	if a.config.Backend == nil {
		a.config.Backend = &models.BackendConfig{}
	}
	a.config.Backend.Type = "pluto"
	a.config.Backend.URL = address

	log.Printf("Connecting to Pluto at %s...", address)

	// Use runner to create and connect (but don't auto-start MQTT here, user controls that)
	opts := runner.Options{
		AutoConnect:   true,
		AutoStartMQTT: false, // User controls MQTT separately in desktop app
	}
	r, err := runner.New(a.config, opts)
	if err != nil {
		return fmt.Errorf("failed to connect: %w", err)
	}

	if !r.Backend.IsConnected() {
		r.Close()
		return fmt.Errorf("failed to connect to Pluto at %s", address)
	}

	a.runner = r
	log.Printf("Connected to %s: %s", r.Backend.Type(), r.Backend.Name())

	// Update web server with the engine if it's already running
	if a.webServer != nil {
		a.webServer.SetEngine(r.Engine)
		log.Println("Updated web server with engine")
	}

	// Connect standalone MQTT to the engine so scans get published
	if a.standaloneMQTT != nil && a.standaloneMQTT.IsConnected() {
		log.Println("Connecting standalone MQTT to engine...")
		r.Engine.SetMQTTClient(a.standaloneMQTT)
		a.standaloneMQTT.SetCommandHandler(r.Engine)
	}

	// Set up status change callback
	a.runner.Engine.SetStatusChangeCallback(func(scanning bool, currentBand string) {
		wailsRuntime.EventsEmit(a.ctx, "status", StatusEvent{
			Scanning:    scanning,
			CurrentBand: currentBand,
			Connected:   a.runner != nil && a.runner.Backend != nil && a.runner.Backend.IsConnected(),
		})
		if a.webServer != nil {
			a.webServer.WSHub().BroadcastStatus(scanning, currentBand)
		}
	})

	// Emit connected status
	wailsRuntime.EventsEmit(a.ctx, "status", StatusEvent{
		Scanning:    false,
		CurrentBand: "",
		Connected:   true,
	})

	return nil
}

// Disconnect disconnects from the Pluto device
func (a *App) Disconnect() {
	a.mu.Lock()
	defer a.mu.Unlock()

	if a.runner != nil {
		a.runner.Close()
		a.runner = nil
	}

	wailsRuntime.EventsEmit(a.ctx, "status", StatusEvent{
		Scanning:    false,
		CurrentBand: "",
		Connected:   false,
	})

	log.Println("Disconnected from Pluto")
}

// StartScanning starts the spectrum scan
func (a *App) StartScanning() error {
	a.mu.RLock()
	r := a.runner
	a.mu.RUnlock()

	if r == nil || r.Engine == nil {
		return fmt.Errorf("not connected to device")
	}

	// Subscribe to scan results and forward to frontend
	go a.forwardScans()

	return r.Engine.Start()
}

// StopScanning stops the spectrum scan
func (a *App) StopScanning() {
	a.mu.RLock()
	r := a.runner
	a.mu.RUnlock()

	if r != nil && r.Engine != nil {
		r.Engine.Stop()
	}
}

// forwardScans subscribes to engine scans and emits them to the frontend
func (a *App) forwardScans() {
	a.mu.RLock()
	r := a.runner
	a.mu.RUnlock()

	if r == nil || r.Engine == nil {
		return
	}

	ch := r.Engine.Subscribe()
	defer r.Engine.Unsubscribe(ch)

	for scan := range ch {
		event := ScanEvent{
			Band:      scan.Band,
			HzLo:      scan.HzLo,
			HzHi:      scan.HzHi,
			Step:      scan.Step,
			Power:     scan.Power,
			Timestamp: scan.Timestamp.Format("2006-01-02T15:04:05Z07:00"),
		}
		wailsRuntime.EventsEmit(a.ctx, "scan", event)
	}
}

// GetConfig returns the current configuration
func (a *App) GetConfig() *models.Config {
	a.mu.RLock()
	defer a.mu.RUnlock()
	return a.config
}

// GetStatus returns the current scanner status
func (a *App) GetStatus() StatusEvent {
	a.mu.RLock()
	defer a.mu.RUnlock()

	status := StatusEvent{
		Scanning:    false,
		CurrentBand: "",
		Connected:   false,
	}

	if a.runner != nil && a.runner.Backend != nil {
		status.Connected = a.runner.Backend.IsConnected()
	}
	if a.runner != nil && a.runner.Engine != nil {
		status.Scanning = a.runner.Engine.IsRunning()
		status.CurrentBand = a.runner.Engine.CurrentBand()
	}

	return status
}

// GetBands returns the configured bands
func (a *App) GetBands() []models.Band {
	a.mu.RLock()
	defer a.mu.RUnlock()
	return a.config.Bands
}

// SetBandEnabled enables or disables a band
func (a *App) SetBandEnabled(bandName string, enabled bool) {
	a.mu.Lock()

	for i := range a.config.Bands {
		if a.config.Bands[i].Name == bandName {
			a.config.Bands[i].Enabled = enabled
			break
		}
	}

	if a.runner != nil && a.runner.Engine != nil {
		a.runner.Engine.UpdateConfig(a.config)
	}

	// Save to YAML so setting persists
	configPath := a.configPath
	cfg := a.config
	a.mu.Unlock()

	if err := config.SaveToFile(configPath, cfg); err != nil {
		log.Printf("Warning: failed to save config after band toggle: %v", err)
	}
}

// SetGain sets the receiver gain
func (a *App) SetGain(gain float64, mode string) error {
	a.mu.Lock()
	a.config.RxGain = gain
	if mode != "" {
		a.config.RxGainMode = mode
	}
	r := a.runner
	a.mu.Unlock()

	if r != nil && r.Engine != nil {
		r.Engine.UpdateConfig(a.config)
	}

	return nil
}

// GetGain returns the current gain settings
func (a *App) GetGain() map[string]interface{} {
	a.mu.RLock()
	defer a.mu.RUnlock()

	return map[string]interface{}{
		"rx_gain":      a.config.RxGain,
		"rx_gain_mode": a.config.RxGainMode,
	}
}

// DetectPluto tries to find a connected Pluto device
func (a *App) DetectPluto() string {
	// Common addresses to try
	addresses := []string{
		"https://192.168.2.1", // Default USB
		"https://pluto.local", // mDNS
		"https://192.168.3.1", // Alternate
	}

	for _, addr := range addresses {
		client := pluto.NewClient(addr, "detect")
		if err := client.Connect(); err == nil {
			client.Close()
			return addr
		}
	}

	return ""
}

// GetPlatform returns the current OS
func (a *App) GetPlatform() string {
	return goruntime.GOOS
}

// SaveCSV opens a save dialog and writes CSV content to the selected file
func (a *App) SaveCSV(content string, defaultFilename string) (string, error) {
	filepath, err := wailsRuntime.SaveFileDialog(a.ctx, wailsRuntime.SaveDialogOptions{
		DefaultFilename: defaultFilename,
		Title:           "Save CSV",
		Filters: []wailsRuntime.FileFilter{
			{
				DisplayName: "CSV Files (*.csv)",
				Pattern:     "*.csv",
			},
		},
	})
	if err != nil {
		return "", err
	}

	// User cancelled
	if filepath == "" {
		return "", nil
	}

	// Write the file
	if err := os.WriteFile(filepath, []byte(content), 0644); err != nil {
		return "", fmt.Errorf("failed to write file: %w", err)
	}

	return filepath, nil
}

// ============================================================================
// Server Mode: MQTT and Web Server
// ============================================================================

// GetServerStatus returns the current server mode status
func (a *App) GetServerStatus() ServerStatus {
	a.mu.RLock()
	defer a.mu.RUnlock()
	return a.getServerStatusLocked()
}

// GetMQTTConfig returns the current MQTT configuration
func (a *App) GetMQTTConfig() *models.MQTTConfig {
	a.mu.RLock()
	defer a.mu.RUnlock()
	if a.config.MQTT == nil {
		return &models.MQTTConfig{
			Enabled:     false,
			TopicPrefix: "spectrum",
		}
	}
	return a.config.MQTT
}

// GetWebConfig returns the current web server configuration
func (a *App) GetWebConfig() *models.WebConfig {
	a.mu.RLock()
	defer a.mu.RUnlock()
	if a.config.Web == nil {
		return &models.WebConfig{
			Enabled: false,
			Port:    8080,
		}
	}
	return a.config.Web
}

// SetMQTTConfig updates the MQTT configuration
func (a *App) SetMQTTConfig(enabled bool, broker, id, token, name, location string) error {
	a.mu.Lock()
	defer a.mu.Unlock()

	if a.config.MQTT == nil {
		a.config.MQTT = &models.MQTTConfig{
			TopicPrefix: "spectrum",
		}
	}

	a.config.MQTT.Enabled = enabled
	a.config.MQTT.Broker = broker
	a.config.MQTT.ID = id
	a.config.MQTT.Token = token
	a.config.MQTT.Name = name
	a.config.MQTT.Location = location

	return nil
}

// SetWebConfig updates the web server configuration
func (a *App) SetWebConfig(enabled bool, port int) error {
	a.mu.Lock()
	defer a.mu.Unlock()

	if a.config.Web == nil {
		a.config.Web = &models.WebConfig{}
	}

	a.config.Web.Enabled = enabled
	if port > 0 {
		a.config.Web.Port = port
	} else {
		a.config.Web.Port = 8080
	}

	return nil
}

// EnableMQTT starts the MQTT client
func (a *App) EnableMQTT() error {
	a.mu.Lock()
	defer a.mu.Unlock()

	return a.startMQTT()
}

// startMQTTStandalone starts MQTT without a runner (must be called with lock held)
func (a *App) startMQTTStandalone() error {
	if a.config.MQTT == nil || a.config.MQTT.Broker == "" {
		return fmt.Errorf("MQTT not configured")
	}

	// Disconnect existing standalone client
	if a.standaloneMQTT != nil {
		a.standaloneMQTT.Disconnect()
		a.standaloneMQTT = nil
	}

	log.Printf("MQTT: Connecting to %s...", a.config.MQTT.Broker)

	client, err := mqtt.NewClient(a.config.MQTT, a.config)
	if err != nil {
		return fmt.Errorf("failed to create MQTT client: %w", err)
	}

	if err := client.Connect(); err != nil {
		return fmt.Errorf("failed to connect to MQTT broker: %w", err)
	}

	a.standaloneMQTT = client
	a.config.MQTT.Enabled = true
	log.Printf("MQTT: Connected to %s", a.config.MQTT.Broker)

	return nil
}

// startMQTT starts the MQTT client (must be called with lock held)
func (a *App) startMQTT() error {
	if a.config.MQTT == nil || a.config.MQTT.Broker == "" {
		return fmt.Errorf("MQTT not configured")
	}

	// If we have a runner, use its EnableMQTT method
	if a.runner != nil {
		// Disconnect standalone client if exists
		if a.standaloneMQTT != nil {
			a.standaloneMQTT.Disconnect()
			a.standaloneMQTT = nil
		}
		if err := a.runner.EnableMQTT(); err != nil {
			return err
		}
		a.config.MQTT.Enabled = true
		wailsRuntime.EventsEmit(a.ctx, "server-status", a.getServerStatusLocked())
		return nil
	}

	// No runner - use standalone
	return a.startMQTTStandalone()
}

// DisableMQTT stops the MQTT client
func (a *App) DisableMQTT() {
	a.mu.Lock()
	defer a.mu.Unlock()

	if a.runner != nil {
		a.runner.DisableMQTT()
	}

	if a.standaloneMQTT != nil {
		a.standaloneMQTT.Disconnect()
		a.standaloneMQTT = nil
	}

	if a.config.MQTT != nil {
		a.config.MQTT.Enabled = false
	}

	log.Println("MQTT: Disconnected")

	// Emit event to frontend
	wailsRuntime.EventsEmit(a.ctx, "server-status", a.getServerStatusLocked())
}

// EnableWebServer starts the local web server
func (a *App) EnableWebServer() error {
	a.mu.Lock()
	defer a.mu.Unlock()

	return a.startWebServer()
}

// startWebServer starts the web server (must be called with lock held)
func (a *App) startWebServer() error {
	if a.config.Web == nil {
		a.config.Web = &models.WebConfig{Port: 8080}
	}

	port := a.config.Web.Port
	if port == 0 {
		port = 8080
	}

	// Stop existing server
	if a.httpServer != nil {
		a.httpServer.Close()
		a.httpServer = nil
		a.webServer = nil
	}

	// Get engine and MQTT client from runner
	var engine *scanner.Engine
	var mqttClient *mqtt.Client
	if a.runner != nil {
		engine = a.runner.Engine
		mqttClient = a.runner.MQTTClient
	}

	// Create API server
	a.webServer = api.NewServer(engine, a.config, mqttClient)

	// Wire up config save callback so API changes persist to YAML
	configPath := a.configPath
	a.webServer.SetConfigSaveFunc(func() error {
		return config.SaveToFile(configPath, a.config)
	})

	// Wire up status change callback to broadcast to WebSocket clients
	if engine != nil {
		engine.SetStatusChangeCallback(func(scanning bool, currentBand string) {
			// Emit to Wails frontend
			connected := a.runner != nil && a.runner.Backend != nil && a.runner.Backend.IsConnected()
			wailsRuntime.EventsEmit(a.ctx, "status", StatusEvent{
				Scanning:    scanning,
				CurrentBand: currentBand,
				Connected:   connected,
			})
			// Broadcast to WebSocket clients
			if a.webServer != nil {
				a.webServer.WSHub().BroadcastStatus(scanning, currentBand)
			}
		})
	}

	addr := fmt.Sprintf("%s:%d", a.config.Web.Host, port)
	a.httpServer = &http.Server{
		Addr:    addr,
		Handler: a.webServer.Handler(),
	}

	a.config.Web.Enabled = true

	log.Printf("Web server: Starting on %s", addr)

	// Start server in goroutine
	go func() {
		if err := a.httpServer.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			log.Printf("Web server error: %v", err)
		}
	}()

	// Emit event to frontend
	wailsRuntime.EventsEmit(a.ctx, "server-status", a.getServerStatusLocked())

	return nil
}

// DisableWebServer stops the local web server
func (a *App) DisableWebServer() {
	a.mu.Lock()
	defer a.mu.Unlock()

	if a.httpServer != nil {
		a.httpServer.Close()
		a.httpServer = nil
		a.webServer = nil
	}

	if a.config.Web != nil {
		a.config.Web.Enabled = false
	}

	log.Println("Web server: Stopped")

	// Emit event to frontend
	wailsRuntime.EventsEmit(a.ctx, "server-status", a.getServerStatusLocked())
}

// getServerStatusLocked returns server status (must be called with lock held)
func (a *App) getServerStatusLocked() ServerStatus {
	status := ServerStatus{}

	if a.config.MQTT != nil {
		status.MQTTEnabled = a.config.MQTT.Enabled
		status.MQTTBroker = a.config.MQTT.Broker
		// Check both runner's MQTT and standalone MQTT
		if a.runner != nil && a.runner.MQTTClient != nil && a.runner.MQTTClient.IsConnected() {
			status.MQTTConnected = true
		} else if a.standaloneMQTT != nil && a.standaloneMQTT.IsConnected() {
			status.MQTTConnected = true
		}
	}

	if a.config.Web != nil {
		status.WebEnabled = a.config.Web.Enabled
		status.WebPort = a.config.Web.Port
		status.WebRunning = a.httpServer != nil
	}

	return status
}

// SaveConfig saves the current configuration to file
func (a *App) SaveConfig() error {
	a.mu.RLock()
	defer a.mu.RUnlock()

	if err := config.SaveToFile(a.configPath, a.config); err != nil {
		return fmt.Errorf("failed to save config: %w", err)
	}

	log.Printf("Configuration saved to %s", a.configPath)
	return nil
}

// GetConfigPath returns the path to the config file
func (a *App) GetConfigPath() string {
	a.mu.RLock()
	defer a.mu.RUnlock()

	absPath, err := filepath.Abs(a.configPath)
	if err != nil {
		return a.configPath
	}
	return absPath
}
