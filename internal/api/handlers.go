package api

import (
	"encoding/json"
	"log"
	"net/http"

	"spectrum-pluto/internal/models"
)

func (s *Server) handleHealth(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]string{"status": "ok"})
}

func (s *Server) handleGetRadio(w http.ResponseWriter, r *http.Request) {
	info, err := s.engine.GetRFInfo()
	if err != nil {
		http.Error(w, "Cannot connect to radio: "+err.Error(), http.StatusServiceUnavailable)
		return
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(info)
}

func (s *Server) handleGetStatus(w http.ResponseWriter, r *http.Request) {
	var currentBand *string
	if band := s.engine.CurrentBand(); band != "" {
		currentBand = &band
	}

	status := models.ScannerStatus{
		ID:          s.config.DeviceID,
		Name:        s.config.Name,
		Description: s.config.Description,
		Online:      true,
		Scanning:    s.engine.IsRunning(),
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
	s.engine.UpdateConfig(s.config)

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
	s.engine.UpdateConfig(s.config)

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
	s.engine.UpdateConfig(s.config)

	// Apply gain to radio immediately
	if err := s.engine.ApplyGain(s.config.RxGain, s.config.RxGainMode); err != nil {
		log.Printf("Warning: failed to apply gain to radio: %v", err)
		// Continue anyway - config is updated, gain will be applied on next scan start
	}

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

	// AD9361 supports 200 kHz to 56 MHz RF bandwidth
	if settings.RxBandwidthMHz < 0.2 || settings.RxBandwidthMHz > 56 {
		http.Error(w, "rx_bandwidth_mhz must be between 0.2 and 56 MHz", http.StatusBadRequest)
		return
	}

	// Convert to Hz and apply
	bwHz := uint32(settings.RxBandwidthMHz * 1e6)
	if err := s.engine.SetRxBandwidth(bwHz); err != nil {
		http.Error(w, "Failed to set bandwidth: "+err.Error(), http.StatusInternalServerError)
		return
	}

	log.Printf("RF bandwidth updated: %.2f MHz", settings.RxBandwidthMHz)

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(settings)
}

func (s *Server) handleStartScan(w http.ResponseWriter, r *http.Request) {
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

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]string{
		"status":  "started",
		"message": "Scanner started successfully",
	})
}

func (s *Server) handleStopScan(w http.ResponseWriter, r *http.Request) {
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

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]string{
		"status":  "stopped",
		"message": "Scanner stopped successfully",
	})
}
