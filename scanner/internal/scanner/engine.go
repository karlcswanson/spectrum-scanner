// Package scanner provides the unified sweep engine for all spectrum analyzer backends.
package scanner

import (
	"context"
	"fmt"
	"log"
	"strings"
	"sync"

	"scanner/internal/models"
	"scanner/internal/mqtt"
)

// StatusChangeFunc is called when scanning status changes
type StatusChangeFunc func(scanning bool, currentBand string)

// ConfigChangeFunc is called when configuration changes (e.g., bands enabled/disabled via MQTT)
type ConfigChangeFunc func(config *models.Config)

// Engine orchestrates frequency sweeping across bands using any Backend.
type Engine struct {
	backend Backend
	config  *models.Config
	mqtt    *mqtt.Client

	mu          sync.RWMutex
	running     bool
	currentBand string
	cancel      context.CancelFunc

	// Subscribers receive scan results via channels
	subscribers   []chan models.ScanLine
	subscribersMu sync.RWMutex

	// Status change callback (for WebSocket broadcasts)
	onStatusChange StatusChangeFunc

	// Config change callback (for notifying frontends of remote config changes)
	onConfigChange ConfigChangeFunc

	// Persists the config after a remote change (e.g. band edits via MQTT).
	// Wired by the caller to config.SaveToFile; nil = no persistence.
	configSaveFunc func() error
}

// NewEngine creates a new sweep engine with the given backend.
func NewEngine(backend Backend, config *models.Config, mqttClient *mqtt.Client) *Engine {
	e := &Engine{
		backend:     backend,
		config:      config,
		mqtt:        mqttClient,
		subscribers: make([]chan models.ScanLine, 0),
	}

	// Apply calibration if backend supports it and config has calibration data
	e.applyCalibration()

	return e
}

// applyCalibration passes calibration data to the backend if it supports it
func (e *Engine) applyCalibration() {
	if e.config.Calibration == nil {
		log.Printf("Engine: No calibration data in config")
		return
	}

	if cal, ok := e.backend.(Calibratable); ok {
		log.Printf("Engine: Passing calibration to backend (%d points)", len(e.config.Calibration.Points))
		cal.SetCalibration(e.config.Calibration)
	} else {
		log.Printf("Engine: Backend does not support calibration")
	}
}

// Subscribe registers a channel to receive scan results
func (e *Engine) Subscribe() chan models.ScanLine {
	ch := make(chan models.ScanLine, 10)
	e.subscribersMu.Lock()
	e.subscribers = append(e.subscribers, ch)
	e.subscribersMu.Unlock()
	return ch
}

// Unsubscribe removes a subscriber channel
func (e *Engine) Unsubscribe(ch chan models.ScanLine) {
	e.subscribersMu.Lock()
	defer e.subscribersMu.Unlock()

	for i, sub := range e.subscribers {
		if sub == ch {
			e.subscribers = append(e.subscribers[:i], e.subscribers[i+1:]...)
			close(ch)
			return
		}
	}
}

// SetMQTTClient updates the MQTT client for the engine
func (e *Engine) SetMQTTClient(client *mqtt.Client) {
	e.mu.Lock()
	defer e.mu.Unlock()
	e.mqtt = client
}

// SetStatusChangeCallback sets a function to be called when scanning status changes
func (e *Engine) SetStatusChangeCallback(fn StatusChangeFunc) {
	e.mu.Lock()
	defer e.mu.Unlock()
	e.onStatusChange = fn
}

// SetConfigChangeCallback sets a function to be called when config changes remotely
func (e *Engine) SetConfigChangeCallback(fn ConfigChangeFunc) {
	e.mu.Lock()
	defer e.mu.Unlock()
	e.onConfigChange = fn
}

// SetConfigSaveFunc sets the function used to persist config after a remote
// change (e.g. band edits over MQTT). Wired by the caller to config.SaveToFile.
func (e *Engine) SetConfigSaveFunc(fn func() error) {
	e.mu.Lock()
	defer e.mu.Unlock()
	e.configSaveFunc = fn
}

// notifyStatusChange calls the status change callback if set
func (e *Engine) notifyStatusChange(scanning bool, currentBand string) {
	if e.onStatusChange != nil {
		e.onStatusChange(scanning, currentBand)
	}
}

// notifyConfigChange calls the config change callback if set
func (e *Engine) notifyConfigChange() {
	if e.onConfigChange != nil {
		e.onConfigChange(e.config)
	}
}

// broadcast sends a scan result to all subscribers and MQTT
func (e *Engine) broadcast(scan models.ScanLine, bandName string) {
	e.subscribersMu.RLock()
	defer e.subscribersMu.RUnlock()

	// Send to local WebSocket subscribers
	for _, ch := range e.subscribers {
		select {
		case ch <- scan:
		default:
			// Drop if subscriber is slow
		}
	}

	// Publish to MQTT if configured
	if e.mqtt != nil && e.mqtt.IsConnected() {
		if err := e.mqtt.PublishScan(scan, bandName); err != nil {
			log.Printf("MQTT publish error: %v", err)
		}
	}
}

// IsRunning returns whether the engine is currently scanning
func (e *Engine) IsRunning() bool {
	e.mu.RLock()
	defer e.mu.RUnlock()
	return e.running
}

// CurrentBand returns the name of the band currently being scanned
func (e *Engine) CurrentBand() string {
	e.mu.RLock()
	defer e.mu.RUnlock()
	return e.currentBand
}

// Backend returns the underlying scanner backend
func (e *Engine) Backend() Backend {
	return e.backend
}

// Start begins the sweep loop
func (e *Engine) Start() error {
	e.mu.Lock()
	if e.running {
		e.mu.Unlock()
		return nil
	}
	e.running = true
	ctx, cancel := context.WithCancel(context.Background())
	e.cancel = cancel
	e.mu.Unlock()

	// Publish scanning status
	if e.mqtt != nil && e.mqtt.IsConnected() {
		e.mqtt.PublishStatus(true, true, "")
	}

	// Notify local WebSocket clients
	e.notifyStatusChange(true, "")

	go e.runLoop(ctx)
	return nil
}

// Stop halts the sweep loop
func (e *Engine) Stop() {
	e.mu.Lock()
	defer e.mu.Unlock()

	if !e.running {
		return
	}

	e.running = false
	if e.cancel != nil {
		e.cancel()
		e.cancel = nil
	}

	// Publish stopped status
	if e.mqtt != nil && e.mqtt.IsConnected() {
		e.mqtt.PublishStatus(true, false, "")
	}

	// Notify local WebSocket clients
	e.notifyStatusChange(false, "")
}

// UpdateConfig updates the engine configuration and notifies all frontends
func (e *Engine) UpdateConfig(config *models.Config) {
	e.mu.Lock()
	e.config = config
	e.mu.Unlock()

	// Reapply calibration in case it changed
	e.applyCalibration()

	// Publish updated config to MQTT so central server sees the change
	if e.mqtt != nil && e.mqtt.IsConnected() {
		e.mqtt.PublishConfig()
	}

	// Notify local frontends (Wails, WebSocket)
	e.notifyConfigChange()
}

// GetConfig returns the current configuration
func (e *Engine) GetConfig() *models.Config {
	e.mu.RLock()
	defer e.mu.RUnlock()
	return e.config
}

func (e *Engine) runLoop(ctx context.Context) {
	log.Printf("Sweep engine started (backend: %s)", e.backend.Type())
	defer func() {
		log.Println("Sweep engine stopped")
		e.mu.Lock()
		e.currentBand = ""
		e.mu.Unlock()
	}()

	for {
		select {
		case <-ctx.Done():
			return
		default:
		}

		e.mu.RLock()
		config := e.config
		e.mu.RUnlock()

		for _, band := range config.Bands {
			select {
			case <-ctx.Done():
				return
			default:
			}

			if !band.Enabled {
				continue
			}

			e.mu.Lock()
			e.currentBand = band.Name
			e.mu.Unlock()

			// Publish current band to MQTT
			if e.mqtt != nil && e.mqtt.IsConnected() {
				e.mqtt.PublishStatus(true, true, band.Name)
			}

			log.Printf("Sweeping band: %s (%.1f - %.1f MHz)",
				band.Name,
				float64(band.StartHz)/1e6,
				float64(band.StopHz)/1e6)

			// Configure backend for this band
			settings := SweepSettings{
				DwellTimeMs: config.DwellTimeMs,
				RxGain:      config.RxGain,
				RxGainMode:  config.RxGainMode,
			}
			if config.Backend != nil {
				settings.RBW = config.Backend.RBW
				settings.VBW = config.Backend.VBW
				settings.AttenuationDB = config.Backend.AttenuationDB
			}

			if err := e.backend.Configure(band, settings); err != nil {
				log.Printf("Error configuring band %s: %v", band.Name, err)
				continue
			}

			// Perform sweep
			scan, err := e.backend.Sweep(ctx)
			if err != nil {
				if ctx.Err() != nil {
					return
				}
				log.Printf("Error sweeping band %s: %v", band.Name, err)
				continue
			}

			scan.Band = band.Name

			e.broadcast(scan, band.Name)
		}
	}
}

// ScanOnce performs a single scan of a specific band (for on-demand requests)
func (e *Engine) ScanOnce(ctx context.Context, band models.Band) (models.ScanLine, error) {
	e.mu.RLock()
	config := e.config
	e.mu.RUnlock()

	settings := SweepSettings{
		DwellTimeMs: config.DwellTimeMs,
		RxGain:      config.RxGain,
		RxGainMode:  config.RxGainMode,
	}
	if config.Backend != nil {
		settings.RBW = config.Backend.RBW
		settings.VBW = config.Backend.VBW
		settings.AttenuationDB = config.Backend.AttenuationDB
	}

	if err := e.backend.Configure(band, settings); err != nil {
		return models.ScanLine{}, err
	}

	scan, err := e.backend.Sweep(ctx)
	if err != nil {
		return models.ScanLine{}, err
	}

	return scan, nil
}

// ============== CommandHandler Interface Implementation ==============

// HandleStart implements mqtt.CommandHandler - starts scanning
func (e *Engine) HandleStart() error {
	return e.Start()
}

// HandleStop implements mqtt.CommandHandler - stops scanning
func (e *Engine) HandleStop() {
	e.Stop()
}

// HandleBands implements mqtt.CommandHandler - updates band configuration
// HandleBands applies a remote band update. The payload is the *complete*
// desired band set (declarative): the engine validates it, replaces its band
// list, persists to the config file, and republishes the retained config so the
// server and browsers reconcile. An invalid update is rejected and the current
// config is left untouched. See docs/remote-band-editing.md.
func (e *Engine) HandleBands(bands []mqtt.BandConfig) error {
	// Validate before mutating so a bad command can't corrupt the config.
	var minHz, maxHz int64
	if e.backend != nil {
		minHz, maxHz = e.backend.FrequencyRange()
	}
	if err := validateBands(bands, minHz, maxHz); err != nil {
		log.Printf("HandleBands: rejecting invalid band update: %v", err)
		return fmt.Errorf("invalid band update: %w", err)
	}

	e.mu.Lock()

	// Authoritative replace: match/add/remove all happen by taking the desired
	// list wholesale.
	newBands := make([]models.Band, len(bands))
	for i, b := range bands {
		newBands[i] = models.Band{
			Name:    strings.TrimSpace(b.Name),
			StartHz: b.StartHz,
			StopHz:  b.StopHz,
			Enabled: b.Enabled,
		}
	}
	e.config.Bands = newBands

	// Persist (under the lock so a concurrent update can't interleave the file
	// write). Band commands are rare and user-driven, so the brief hold is fine.
	if e.configSaveFunc != nil {
		if err := e.configSaveFunc(); err != nil {
			log.Printf("HandleBands: applied %d band(s) but failed to persist: %v", len(newBands), err)
		} else {
			log.Printf("HandleBands: applied and persisted %d band(s)", len(newBands))
		}
	} else {
		log.Printf("HandleBands: applied %d band(s) (persistence not configured)", len(newBands))
	}

	// Re-publish config (retained) so the server + browsers reconcile.
	if e.mqtt != nil && e.mqtt.IsConnected() {
		e.mqtt.PublishConfig()
	}

	e.mu.Unlock()

	// Notify frontends of config change (outside lock to avoid deadlock)
	e.notifyConfigChange()

	return nil
}

// validateBands checks a desired band set before it is applied. minHz/maxHz are
// the backend's supported range; pass 0 to skip the hardware-range check.
func validateBands(bands []mqtt.BandConfig, minHz, maxHz int64) error {
	if len(bands) == 0 {
		return fmt.Errorf("band list is empty")
	}
	seen := make(map[string]bool, len(bands))
	for _, b := range bands {
		name := strings.TrimSpace(b.Name)
		if name == "" {
			return fmt.Errorf("band has an empty name")
		}
		key := strings.ToLower(name)
		if seen[key] {
			return fmt.Errorf("duplicate band name %q", name)
		}
		seen[key] = true

		if b.StartHz <= 0 || b.StopHz <= 0 {
			return fmt.Errorf("band %q: frequencies must be positive", name)
		}
		if b.StartHz >= b.StopHz {
			return fmt.Errorf("band %q: start (%d Hz) must be below stop (%d Hz)", name, b.StartHz, b.StopHz)
		}
		if minHz > 0 && b.StartHz < minHz {
			return fmt.Errorf("band %q: start %d Hz is below the hardware minimum %d Hz", name, b.StartHz, minHz)
		}
		if maxHz > 0 && b.StopHz > maxHz {
			return fmt.Errorf("band %q: stop %d Hz is above the hardware maximum %d Hz", name, b.StopHz, maxHz)
		}
	}
	return nil
}

// HandleGain implements mqtt.CommandHandler - updates gain settings
func (e *Engine) HandleGain(gain float64, mode string) error {
	e.mu.Lock()
	e.config.RxGain = gain
	if mode != "" {
		e.config.RxGainMode = mode
	}
	e.mu.Unlock()

	// Apply gain to backend if it supports it
	if setter, ok := e.backend.(GainSetter); ok {
		if err := setter.SetGain(gain, mode); err != nil {
			log.Printf("Failed to set gain on backend: %v", err)
			return err
		}
	}

	// Re-publish config
	if e.mqtt != nil && e.mqtt.IsConnected() {
		e.mqtt.PublishConfig()
	}

	// Notify frontends of config change
	e.notifyConfigChange()

	return nil
}

// GainSetter is an optional interface for backends that support gain control
type GainSetter interface {
	SetGain(gain float64, mode string) error
}
