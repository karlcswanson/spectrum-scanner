// Package scanner provides the unified sweep engine for all spectrum analyzer backends.
package scanner

import (
	"context"
	"log"
	"sync"

	"spectrum-pluto/internal/models"
	"spectrum-pluto/internal/mqtt"
)

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
}

// NewEngine creates a new sweep engine with the given backend.
func NewEngine(backend Backend, config *models.Config, mqttClient *mqtt.Client) *Engine {
	return &Engine{
		backend:     backend,
		config:      config,
		mqtt:        mqttClient,
		subscribers: make([]chan models.ScanLine, 0),
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
}

// UpdateConfig updates the engine configuration
func (e *Engine) UpdateConfig(config *models.Config) {
	e.mu.Lock()
	defer e.mu.Unlock()
	e.config = config
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

			// Set scanner ID
			scan.ID = config.DeviceID

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

	if err := e.backend.Configure(band, settings); err != nil {
		return models.ScanLine{}, err
	}

	scan, err := e.backend.Sweep(ctx)
	if err != nil {
		return models.ScanLine{}, err
	}

	scan.ID = config.DeviceID
	return scan, nil
}
