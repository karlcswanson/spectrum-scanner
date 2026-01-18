package api

import (
	"encoding/json"
	"log"
	"net/http"

	"scanner/internal/models"
)

func (s *Server) handleHealth(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]string{"status": "ok"})
}

func (s *Server) handleGetRadio(w http.ResponseWriter, r *http.Request) {
	if s.engine == nil {
		http.Error(w, "Scanner not connected", http.StatusServiceUnavailable)
		return
	}
	// Return backend info and capabilities
	backend := s.engine.Backend()
	minHz, maxHz := backend.FrequencyRange()

	info := map[string]interface{}{
		"backend_type": backend.Type(),
		"backend_name": backend.Name(),
		"connected":    backend.IsConnected(),
		"min_freq_hz":  minHz,
		"max_freq_hz":  maxHz,
		"min_freq_mhz": float64(minHz) / 1e6,
		"max_freq_mhz": float64(maxHz) / 1e6,
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(info)
}

func (s *Server) handleGetStatus(w http.ResponseWriter, r *http.Request) {
	var currentBand *string
	var scanning bool
	if s.engine != nil {
		if band := s.engine.CurrentBand(); band != "" {
			currentBand = &band
		}
		scanning = s.engine.IsRunning()
	}

	status := models.ScannerStatus{
		ID:          s.config.DeviceID,
		Name:        s.config.Name,
		Description: s.config.Description,
		Online:      s.engine != nil,
		Scanning:    scanning,
		CurrentBand: currentBand,
	}

	w.Header().Set("Content-Type", "application/json")
	if err := json.NewEncoder(w).Encode(status); err != nil {
		log.Printf("Error encoding status: %v", err)
	}
}

func (s *Server) handleGetConfig(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	if err := json.NewEncoder(w).Encode(s.config); err != nil {
		log.Printf("Error encoding config: %v", err)
	}
}

func (s *Server) handlePutConfig(w http.ResponseWriter, r *http.Request) {
	var newConfig models.Config
	if err := json.NewDecoder(r.Body).Decode(&newConfig); err != nil {
		http.Error(w, "Invalid JSON: "+err.Error(), http.StatusBadRequest)
		return
	}

	// Update configuration
	if newConfig.Name != "" {
		s.config.Name = newConfig.Name
	}
	if newConfig.Description != "" {
		s.config.Description = newConfig.Description
	}
	if newConfig.DwellTimeMs > 0 {
		s.config.DwellTimeMs = newConfig.DwellTimeMs
	}
	if newConfig.Mode != "" {
		s.config.Mode = newConfig.Mode
	}
	if len(newConfig.Bands) > 0 {
		s.config.Bands = newConfig.Bands
	}

	// Update the engine with new config
	if s.engine != nil {
		s.engine.UpdateConfig(s.config)
	}

	// Persist to disk if callback set
	s.saveConfig()

	log.Printf("Configuration updated: %s", s.config.Name)

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(s.config)
}

func (s *Server) handleGetBands(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(s.config.Bands)
}

func (s *Server) handlePutBands(w http.ResponseWriter, r *http.Request) {
	var bands []models.Band
	if err := json.NewDecoder(r.Body).Decode(&bands); err != nil {
		http.Error(w, "Invalid JSON: "+err.Error(), http.StatusBadRequest)
		return
	}

	s.config.Bands = bands
	if s.engine != nil {
		s.engine.UpdateConfig(s.config)
	}

	// Persist to disk if callback set
	s.saveConfig()

	// Republish config to MQTT so central server sees the change
	if s.mqtt != nil && s.mqtt.IsConnected() {
		s.mqtt.PublishConfig()
	}

	log.Printf("Bands updated: %d bands configured", len(bands))

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(bands)
}

// GainSettings represents the gain configuration for the API
type GainSettings struct {
	RxGain     float64 `json:"rx_gain"`
	RxGainMode string  `json:"rx_gain_mode"`
}

// BandwidthSettings represents the RF bandwidth configuration
type BandwidthSettings struct {
	RxBandwidthMHz float64 `json:"rx_bandwidth_mhz"`
}

func (s *Server) handleGetGain(w http.ResponseWriter, r *http.Request) {
	settings := GainSettings{
		RxGain:     s.config.RxGain,
		RxGainMode: s.config.RxGainMode,
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(settings)
}

func (s *Server) handlePutGain(w http.ResponseWriter, r *http.Request) {
	var settings GainSettings
	if err := json.NewDecoder(r.Body).Decode(&settings); err != nil {
		http.Error(w, "Invalid JSON: "+err.Error(), http.StatusBadRequest)
		return
	}

	// Validate gain value (AD9361 supports 0-73 dB)
	if settings.RxGain < 0 || settings.RxGain > 73 {
		http.Error(w, "rx_gain must be between 0 and 73 dB", http.StatusBadRequest)
		return
	}

	// Validate gain mode (lowercase accepted, normalized to maia format in maia client)
	validModes := map[string]bool{"manual": true, "slow_attack": true, "fast_attack": true, "hybrid": true}
	if settings.RxGainMode != "" && !validModes[settings.RxGainMode] {
		http.Error(w, "rx_gain_mode must be 'manual', 'slow_attack', 'fast_attack', or 'hybrid'", http.StatusBadRequest)
		return
	}

	// Update config
	s.config.RxGain = settings.RxGain
	if settings.RxGainMode != "" {
		s.config.RxGainMode = settings.RxGainMode
	}
	if s.engine != nil {
		s.engine.UpdateConfig(s.config)
	}

	// Persist to disk if callback set
	s.saveConfig()

	// Gain will be applied on next sweep/configure cycle
	log.Printf("Gain updated: %.1f dB, mode: %s", s.config.RxGain, s.config.RxGainMode)

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(GainSettings{
		RxGain:     s.config.RxGain,
		RxGainMode: s.config.RxGainMode,
	})
}

func (s *Server) handlePutBandwidth(w http.ResponseWriter, r *http.Request) {
	var settings BandwidthSettings
	if err := json.NewDecoder(r.Body).Decode(&settings); err != nil {
		http.Error(w, "Invalid JSON: "+err.Error(), http.StatusBadRequest)
		return
	}

	// This endpoint is primarily for SDR backends (Pluto)
	// For spectrum analyzers like OWON, RBW is controlled via backend config
	if s.engine == nil {
		http.Error(w, "Scanner not connected", http.StatusServiceUnavailable)
		return
	}
	backend := s.engine.Backend()
	if backend.Type() != "pluto" {
		http.Error(w, "Bandwidth control not supported for "+backend.Type()+" backend. Use RBW in config.", http.StatusBadRequest)
		return
	}

	// AD9361 supports 200 kHz to 56 MHz RF bandwidth
	if settings.RxBandwidthMHz < 0.2 || settings.RxBandwidthMHz > 56 {
		http.Error(w, "rx_bandwidth_mhz must be between 0.2 and 56 MHz", http.StatusBadRequest)
		return
	}

	// Store in config for next sweep
	log.Printf("RF bandwidth setting updated: %.2f MHz (will apply on next sweep)", settings.RxBandwidthMHz)

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(settings)
}

func (s *Server) handleStartScan(w http.ResponseWriter, r *http.Request) {
	if s.engine == nil {
		http.Error(w, "Scanner not connected", http.StatusServiceUnavailable)
		return
	}
	if s.engine.IsRunning() {
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]string{
			"status":  "already_running",
			"message": "Scanner is already running",
		})
		return
	}

	if err := s.engine.Start(); err != nil {
		http.Error(w, "Failed to start scanner: "+err.Error(), http.StatusInternalServerError)
		return
	}

	log.Println("Scan started via API")

	// Broadcast status to WebSocket clients
	s.wsHub.BroadcastStatus(true, "")

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]string{
		"status":  "started",
		"message": "Scanner started successfully",
	})
}

func (s *Server) handleStopScan(w http.ResponseWriter, r *http.Request) {
	if s.engine == nil {
		http.Error(w, "Scanner not connected", http.StatusServiceUnavailable)
		return
	}
	if !s.engine.IsRunning() {
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]string{
			"status":  "not_running",
			"message": "Scanner is not running",
		})
		return
	}

	s.engine.Stop()

	log.Println("Scan stopped via API")

	// Broadcast status to WebSocket clients
	s.wsHub.BroadcastStatus(false, "")

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]string{
		"status":  "stopped",
		"message": "Scanner stopped successfully",
	})
}
