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
	"time"

	wailsRuntime "github.com/wailsapp/wails/v2/pkg/runtime"

	"scanner/internal/api"
	"scanner/internal/backend/pluto"
	"scanner/internal/backend/tinysa"
	"scanner/internal/config"
	"scanner/internal/db"
	"scanner/internal/models"
	"scanner/internal/mqtt"
	"scanner/internal/runner"
	"scanner/internal/scanner"
)

// Default device addresses
const (
	defaultPlutoAddress  = "https://192.168.2.1"
	defaultTinySAPort    = "/dev/tty.usbmodem4001"
	defaultWebServerPort = 8080
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
	mqttStatus     string       // "connected", "disconnected", "error", or "" for unknown

	// SQLite store for scan history (timeline scrubber)
	store *db.Store

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
	MQTTConnected bool   `json:"mqtt_connected"` // Kept for backwards compatibility
	MQTTStatus    string `json:"mqtt_status"`    // "connected", "disconnected", "error"
	MQTTBroker    string `json:"mqtt_broker"`
	WebEnabled    bool   `json:"web_enabled"`
	WebPort       int    `json:"web_port"`
	WebRunning    bool   `json:"web_running"`
}

// NewApp creates a new App instance
func NewApp() *App {
	return &App{}
}

// startup is called when the app starts
func (a *App) startup(ctx context.Context) {
	a.ctx = ctx

	// Load configuration (checks env vars, ./config.yaml > system config > defaults)
	opts := config.DefaultOptions()
	var err error
	a.config, a.configPath, err = config.LoadWithOptions(opts)
	if err != nil {
		log.Printf("Warning: Failed to load config: %v", err)
		a.config = config.DefaultConfig()
	} else if a.configPath != "" {
		log.Printf("Loaded config from %s", a.configPath)
	} else {
		log.Printf("Using default configuration")
	}

	log.Printf("Desktop app started - %s (%s)", a.config.Name, a.config.DeviceID)

	// Initialize SQLite store for scan history
	dbPath := config.AppConfigDir() + "/scans.db"
	a.store, err = db.NewStore(dbPath)
	if err != nil {
		log.Printf("Warning: Failed to initialize scan history database: %v", err)
	} else {
		log.Printf("Scan history database: %s", dbPath)
		// Start periodic cleanup (keep 24 hours by default)
		go a.runCleanupLoop(24)
	}

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
	// Auto-connect to backend on startup
	go a.autoConnect()
}

// autoConnect attempts to connect to the configured backend and optionally start scanning
func (a *App) autoConnect() {
	// Small delay to let MQTT/web server goroutines start first
	// This prevents lock contention at startup
	log.Println("Auto-connect: waiting for services to initialize...")

	a.mu.Lock()
	defer a.mu.Unlock()

	backendType := "pluto"
	if a.config.Backend != nil && a.config.Backend.Type != "" {
		backendType = a.config.Backend.Type
	}
	log.Printf("Auto-connect: attempting to connect to %s backend...", backendType)

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

	// Set up config change callback for remote config updates (e.g., band enable/disable via MQTT)
	a.runner.Engine.SetConfigChangeCallback(func(cfg *models.Config) {
		wailsRuntime.EventsEmit(a.ctx, "config-changed", cfg)
		if a.webServer != nil {
			a.webServer.WSHub().BroadcastConfig(cfg)
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
	log.Printf("Auto-start config: %v", a.config.AutoStart)
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
	if a.store != nil {
		a.store.Close()
	}
	log.Println("Desktop app shutdown")
}

// runCleanupLoop periodically cleans up old scans
func (a *App) runCleanupLoop(retentionHours int) {
	ticker := time.NewTicker(1 * time.Hour)
	defer ticker.Stop()

	for {
		select {
		case <-ticker.C:
			if a.store != nil {
				a.store.Cleanup(retentionHours)
			}
		case <-a.ctx.Done():
			return
		}
	}
}

// Connect connects to the configured backend device
func (a *App) Connect(address string) error {
	a.mu.Lock()
	defer a.mu.Unlock()

	// Close existing runner if any
	if a.runner != nil {
		a.runner.Close()
		a.runner = nil
	}

	// Initialize backend config if needed
	if a.config.Backend == nil {
		a.config.Backend = &models.BackendConfig{}
	}

	// Use configured backend type, defaulting to pluto
	backendType := a.config.Backend.Type
	if backendType == "" {
		backendType = "pluto"
		a.config.Backend.Type = backendType
	}

	// Set address based on backend type
	switch backendType {
	case "pluto":
		if address == "" {
			address = defaultPlutoAddress
		}
		a.config.Backend.URL = address
	case "tinysa":
		if address == "" {
			address = defaultTinySAPort
		}
		a.config.Backend.Address = address
	case "owon":
		if address != "" {
			a.config.Backend.Address = address
		}
	}

	log.Printf("Connecting to %s backend at %s...", backendType, address)

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
		return fmt.Errorf("failed to connect to %s at %s", backendType, address)
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

	// Set up config change callback for remote config updates
	a.runner.Engine.SetConfigChangeCallback(func(cfg *models.Config) {
		wailsRuntime.EventsEmit(a.ctx, "config-changed", cfg)
		if a.webServer != nil {
			a.webServer.WSHub().BroadcastConfig(cfg)
		}
	})

	// Emit connected status
	wailsRuntime.EventsEmit(a.ctx, "status", StatusEvent{
		Scanning:    false,
		CurrentBand: "",
		Connected:   true,
	})

	// Auto-start scanning if configured
	if a.config.AutoStart {
		log.Println("Auto-starting scanning after connect...")
		go a.forwardScans()
		if err := a.runner.Engine.Start(); err != nil {
			log.Printf("Auto-start scanning failed: %v", err)
		}
	}

	return nil
}

// Disconnect disconnects from the backend device
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

	log.Println("Disconnected from backend")
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
	store := a.store
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

		// Store scan in SQLite for timeline scrubber
		if store != nil {
			if err := store.StoreScan(&scan); err != nil {
				log.Printf("Warning: failed to store scan: %v", err)
			}
		}
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

// SetName sets the scanner name
func (a *App) SetName(name string) error {
	a.mu.Lock()
	a.config.Name = name
	configPath := a.configPath
	cfg := a.config
	a.mu.Unlock()

	// Save to YAML so setting persists
	if err := config.SaveToFile(configPath, cfg); err != nil {
		log.Printf("Warning: failed to save config after name change: %v", err)
		return err
	}

	log.Printf("Scanner name set to: %s", name)
	return nil
}

// Pluto detection addresses (tried in order)
var plutoDetectAddresses = []string{
	defaultPlutoAddress,   // Default USB
	"https://pluto.local", // mDNS
	"https://192.168.3.1", // Alternate
}

// tinySA detection ports (tried in order)
var tinysaDetectPorts = []string{
	defaultTinySAPort,
	"/dev/tty.usbmodem3001",
	"/dev/tty.usbmodem2001",
	"/dev/tty.usbmodem1001",
}

// DetectPluto tries to find a connected Pluto device
func (a *App) DetectPluto() string {
	for _, addr := range plutoDetectAddresses {
		client := pluto.NewClient(addr, "detect")
		if err := client.Connect(); err == nil {
			client.Close()
			return addr
		}
	}

	return ""
}

// DetectTinySA tries to find a connected tinySA device
func (a *App) DetectTinySA() string {
	for _, port := range tinysaDetectPorts {
		cfg := tinysa.Config{Port: port, BaudRate: 576000}
		device, err := tinysa.Open(cfg)
		if err == nil {
			device.Close()
			return port
		}
	}

	return ""
}

// DetectDevice tries to find a connected device based on configured backend type
func (a *App) DetectDevice() string {
	backendType := "pluto"
	if a.config.Backend != nil && a.config.Backend.Type != "" {
		backendType = a.config.Backend.Type
	}

	switch backendType {
	case "pluto":
		return a.DetectPluto()
	case "tinysa":
		return a.DetectTinySA()
	default:
		return ""
	}
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
			Port:    defaultWebServerPort,
		}
	}
	return a.config.Web
}

// SetMQTTConfig updates the MQTT configuration and saves to file
func (a *App) SetMQTTConfig(enabled bool, broker, id, token, location string) error {
	a.mu.Lock()

	if a.config.MQTT == nil {
		a.config.MQTT = &models.MQTTConfig{
			TopicPrefix: "spectrum",
		}
	}

	a.config.MQTT.Enabled = enabled
	a.config.MQTT.Broker = broker
	a.config.MQTT.ID = id
	a.config.MQTT.Token = token
	a.config.MQTT.Location = location

	configPath := a.configPath
	cfg := a.config
	a.mu.Unlock()

	if err := config.SaveToFile(configPath, cfg); err != nil {
		log.Printf("Warning: failed to save MQTT config: %v", err)
		return err
	}
	log.Printf("MQTT config saved to %s", configPath)
	return nil
}

// SetWebConfig updates the web server configuration and saves to file
func (a *App) SetWebConfig(enabled bool, port int) error {
	a.mu.Lock()

	if a.config.Web == nil {
		a.config.Web = &models.WebConfig{}
	}

	a.config.Web.Enabled = enabled
	if port > 0 {
		a.config.Web.Port = port
	} else {
		a.config.Web.Port = defaultWebServerPort
	}

	configPath := a.configPath
	cfg := a.config
	a.mu.Unlock()

	if err := config.SaveToFile(configPath, cfg); err != nil {
		log.Printf("Warning: failed to save web config: %v", err)
		return err
	}
	log.Printf("Web config saved to %s", configPath)
	return nil
}

// EnableMQTT starts the MQTT client
func (a *App) EnableMQTT() {
	// First, disconnect any existing connections (outside of lock to avoid deadlock)
	a.mu.Lock()
	existingStandalone := a.standaloneMQTT
	a.standaloneMQTT = nil
	a.mqttStatus = "" // Clear previous status - connection is now pending
	a.mu.Unlock()

	if existingStandalone != nil {
		existingStandalone.Disconnect()
	}

	// Now start new connection
	a.mu.Lock()
	err := a.startMQTTLocked()
	if err != nil {
		log.Printf("EnableMQTT error: %v", err)
		a.mqttStatus = "error"
	}
	a.mu.Unlock()
	// Don't broadcast here - the async connection callback will broadcast when done
}

// startMQTTStandalone starts MQTT without a runner (must be called with lock held)
// Caller must disconnect any existing client before calling this.
func (a *App) startMQTTStandalone() error {
	if a.config.MQTT == nil || a.config.MQTT.Broker == "" {
		return fmt.Errorf("MQTT not configured")
	}

	log.Printf("MQTT: Connecting to %s...", a.config.MQTT.Broker)

	client, err := mqtt.NewClient(a.config.MQTT, a.config)
	if err != nil {
		return fmt.Errorf("failed to create MQTT client: %w", err)
	}

	// Set up callback to broadcast status when connection state changes
	client.SetConnectionCallback(func(status mqtt.ConnectionStatus) {
		a.mu.Lock()
		a.mqttStatus = string(status)
		webServer := a.webServer
		a.mu.Unlock()
		if webServer != nil {
			a.mu.RLock()
			serverStatus := a.getServerStatusLocked()
			a.mu.RUnlock()
			log.Printf("MQTT connection callback: status=%s, broadcasting", status)
			webServer.WSHub().BroadcastServerStatus(serverStatus)
		}
	})

	if err := client.Connect(); err != nil {
		return fmt.Errorf("failed to connect to MQTT broker: %w", err)
	}

	a.standaloneMQTT = client
	a.config.MQTT.Enabled = true
	// Note: Connect() is async, status updates come via callback

	return nil
}

// startMQTTLocked starts the MQTT client (must be called with lock held)
// Caller must disconnect any existing client before calling this.
func (a *App) startMQTTLocked() error {
	if a.config.MQTT == nil || a.config.MQTT.Broker == "" {
		return fmt.Errorf("MQTT not configured")
	}

	// If we have a runner, use its EnableMQTT method
	if a.runner != nil {
		// Use callback version to broadcast status when connection state changes
		callback := func(status mqtt.ConnectionStatus) {
			a.mu.Lock()
			a.mqttStatus = string(status)
			webServer := a.webServer
			a.mu.Unlock()
			if webServer != nil {
				a.mu.RLock()
				serverStatus := a.getServerStatusLocked()
				a.mu.RUnlock()
				log.Printf("MQTT connection callback (runner): status=%s, broadcasting", status)
				webServer.WSHub().BroadcastServerStatus(serverStatus)
			}
		}
		if err := a.runner.EnableMQTTWithCallback(callback); err != nil {
			return err
		}
		a.config.MQTT.Enabled = true
		return nil
	}

	// No runner - use standalone
	return a.startMQTTStandalone()
}

// DisableMQTT stops the MQTT client
func (a *App) DisableMQTT() {
	a.mu.Lock()
	// Get references before releasing lock
	runner := a.runner
	standaloneMQTT := a.standaloneMQTT
	a.standaloneMQTT = nil
	if a.config.MQTT != nil {
		a.config.MQTT.Enabled = false
	}
	a.mu.Unlock()

	// Disconnect outside of lock (Disconnect calls callback which needs lock)
	if runner != nil {
		runner.DisableMQTT()
	}
	if standaloneMQTT != nil {
		standaloneMQTT.Disconnect()
	}

	// Update status and broadcast
	a.mu.Lock()
	a.mqttStatus = "disconnected"
	webServer := a.webServer
	status := a.getServerStatusLocked()
	a.mu.Unlock()

	log.Println("MQTT: Disconnected")
	if webServer != nil {
		webServer.WSHub().BroadcastServerStatus(status)
	}
}

// EnableWebServer starts the local web server
func (a *App) EnableWebServer() {
	a.mu.Lock()
	defer a.mu.Unlock()

	if err := a.startWebServer(); err != nil {
		log.Printf("EnableWebServer error: %v", err)
	}
	if a.webServer != nil {
		a.webServer.WSHub().BroadcastServerStatus(a.getServerStatusLocked())
	}
}

// startWebServer starts the web server (must be called with lock held)
func (a *App) startWebServer() error {
	if a.config.Web == nil {
		a.config.Web = &models.WebConfig{Port: defaultWebServerPort}
	}

	port := a.config.Web.Port
	if port == 0 {
		port = defaultWebServerPort
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

	// Wire up SQLite store for scan history endpoints
	if a.store != nil {
		a.webServer.SetStore(a.store)
	}

	// Wire up config save callback so API changes persist to YAML
	configPath := a.configPath
	a.webServer.SetConfigSaveFunc(func() error {
		return config.SaveToFile(configPath, a.config)
	})

	// Wire up server status callback so WebSocket clients get initial status
	a.webServer.SetServerStatusFunc(func() interface{} {
		a.mu.RLock()
		defer a.mu.RUnlock()
		return a.getServerStatusLocked()
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

	return nil
}

// DisableWebServer stops the local web server
func (a *App) DisableWebServer() {
	a.mu.Lock()
	defer a.mu.Unlock()

	// Broadcast before stopping so clients get the update
	status := a.getServerStatusLocked()
	status.WebRunning = false
	if a.webServer != nil {
		a.webServer.WSHub().BroadcastServerStatus(status)
	}

	if a.httpServer != nil {
		a.httpServer.Close()
		a.httpServer = nil
		a.webServer = nil
	}

	if a.config.Web != nil {
		a.config.Web.Enabled = false
	}

	log.Println("Web server: Stopped")
}

// getServerStatusLocked returns server status (must be called with lock held)
func (a *App) getServerStatusLocked() ServerStatus {
	status := ServerStatus{}

	if a.config.MQTT != nil {
		status.MQTTEnabled = a.config.MQTT.Enabled
		status.MQTTBroker = a.config.MQTT.Broker

		// Use stored mqttStatus from callbacks (most accurate)
		if a.mqttStatus != "" {
			status.MQTTStatus = a.mqttStatus
			status.MQTTConnected = a.mqttStatus == "connected"
		} else {
			// No callback has fired yet - default to disconnected
			// Don't use IsConnected() as it can be unreliable during async connect
			status.MQTTStatus = "disconnected"
			status.MQTTConnected = false
		}
	} else {
		// MQTT not configured
		status.MQTTStatus = "disconnected"
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

// ============================================================================
// Scan History / Timeline Scrubber (Wails bindings)
// ============================================================================

// TimelineEntry for frontend
type TimelineEntry struct {
	ID        int64  `json:"id"`
	Timestamp string `json:"timestamp"`
	Band      string `json:"band"`
}

// DecimatedScan for scrubber preview
type DecimatedScan struct {
	ID        int64     `json:"id"`
	Timestamp string    `json:"timestamp"`
	Band      string    `json:"band"`
	HzLo      float64   `json:"hz_lo"`
	HzHi      float64   `json:"hz_hi"`
	Step      float64   `json:"step"`
	Power     []float64 `json:"power"`
}

// GetTimeline returns timeline entries for a band
func (a *App) GetTimeline(band string, hours float64) []TimelineEntry {
	a.mu.RLock()
	store := a.store
	a.mu.RUnlock()

	if store == nil {
		return []TimelineEntry{}
	}

	entries, err := store.GetTimeline(band, hours)
	if err != nil {
		log.Printf("Error getting timeline: %v", err)
		return []TimelineEntry{}
	}

	// Convert to frontend format
	result := make([]TimelineEntry, len(entries))
	for i, e := range entries {
		result[i] = TimelineEntry{
			ID:        e.ID,
			Timestamp: e.Timestamp.Format(time.RFC3339),
			Band:      e.Band,
		}
	}
	return result
}

// GetScanAtTime returns the scan closest to the given time
func (a *App) GetScanAtTime(band string, timeStr string) *ScanEvent {
	a.mu.RLock()
	store := a.store
	a.mu.RUnlock()

	if store == nil {
		return nil
	}

	t, err := time.Parse(time.RFC3339, timeStr)
	if err != nil {
		log.Printf("Error parsing time: %v", err)
		return nil
	}

	scan, err := store.GetScanAtTime(band, t)
	if err != nil {
		log.Printf("Error getting scan at time: %v", err)
		return nil
	}
	if scan == nil {
		return nil
	}

	return &ScanEvent{
		Band:      scan.Band,
		HzLo:      scan.HzLo,
		HzHi:      scan.HzHi,
		Step:      scan.Step,
		Power:     scan.Power,
		Timestamp: scan.Timestamp.Format(time.RFC3339),
	}
}

// GetDecimatedScans returns decimated scans for scrubber preview
func (a *App) GetDecimatedScans(band string, hours float64) []DecimatedScan {
	a.mu.RLock()
	store := a.store
	a.mu.RUnlock()

	if store == nil {
		return []DecimatedScan{}
	}

	scans, err := store.GetDecimatedScans(band, hours)
	if err != nil {
		log.Printf("Error getting decimated scans: %v", err)
		return []DecimatedScan{}
	}

	// Convert to frontend format
	result := make([]DecimatedScan, len(scans))
	for i, s := range scans {
		result[i] = DecimatedScan{
			ID:        s.ID,
			Timestamp: s.Timestamp.Format(time.RFC3339),
			Band:      s.Band,
			HzLo:      s.HzLo,
			HzHi:      s.HzHi,
			Step:      s.Step,
			Power:     s.Power,
		}
	}
	return result
}

// GetScanStats returns database statistics
func (a *App) GetScanStats() map[string]interface{} {
	a.mu.RLock()
	store := a.store
	a.mu.RUnlock()

	if store == nil {
		return map[string]interface{}{"error": "store not initialized"}
	}

	stats, err := store.GetStats()
	if err != nil {
		return map[string]interface{}{"error": err.Error()}
	}
	return stats
}
