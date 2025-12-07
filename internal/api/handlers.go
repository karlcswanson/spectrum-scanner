package api

import (
	"encoding/json"
	"log"
	"net/http"

	"spectrum-scanner/internal/models"
)

func (s *Server) handleHealth(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]string{"status": "ok"})
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

	log.Printf("Bands updated: %d bands configured", len(bands))

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(bands)
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
