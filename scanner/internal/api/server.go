package api

import (
	"embed"
	"io/fs"
	"log"
	"net/http"

	"scanner/internal/models"
	"scanner/internal/mqtt"
	"scanner/internal/scanner"
)

//go:embed web
var webFS embed.FS

// ConfigSaveFunc is called when config changes and should be persisted
type ConfigSaveFunc func() error

// Server handles HTTP requests for the spectrum scanner
type Server struct {
	engine       *scanner.Engine
	config       *models.Config
	mqtt         *mqtt.Client
	mux          *http.ServeMux
	wsHub        *WSHub
	onConfigSave ConfigSaveFunc
}

// NewServer creates a new HTTP server
func NewServer(engine *scanner.Engine, config *models.Config, mqttClient *mqtt.Client) *Server {
	s := &Server{
		engine: engine,
		config: config,
		mqtt:   mqttClient,
		mux:    http.NewServeMux(),
		wsHub:  NewWSHub(),
	}
	s.setupRoutes()
	return s
}

// WSHub returns the WebSocket hub for external status broadcasts
func (s *Server) WSHub() *WSHub {
	return s.wsHub
}

func (s *Server) setupRoutes() {
	// API routes
	s.mux.HandleFunc("GET /api/status", s.handleGetStatus)
	s.mux.HandleFunc("GET /api/config", s.handleGetConfig)
	s.mux.HandleFunc("PUT /api/config", s.handlePutConfig)
	s.mux.HandleFunc("POST /api/scan/start", s.handleStartScan)
	s.mux.HandleFunc("POST /api/scan/stop", s.handleStopScan)
	s.mux.HandleFunc("GET /api/bands", s.handleGetBands)
	s.mux.HandleFunc("PUT /api/bands", s.handlePutBands)
	s.mux.HandleFunc("GET /api/gain", s.handleGetGain)
	s.mux.HandleFunc("PUT /api/gain", s.handlePutGain)
	s.mux.HandleFunc("PUT /api/bandwidth", s.handlePutBandwidth)

	// WebSocket for live scan data
	s.mux.HandleFunc("GET /ws/stream", s.handleWebSocket)

	// RF info from maia/SDR
	s.mux.HandleFunc("GET /api/radio", s.handleGetRadio)

	// Health check
	s.mux.HandleFunc("GET /health", s.handleHealth)

	// Static files (Vue frontend)
	webContent, err := fs.Sub(webFS, "web")
	if err != nil {
		log.Printf("Warning: could not load embedded web files: %v", err)
		// Serve a simple message if no web files embedded
		s.mux.HandleFunc("GET /", func(w http.ResponseWriter, r *http.Request) {
			w.Header().Set("Content-Type", "text/html")
			w.Write([]byte(`<!DOCTYPE html>
<html>
<head><title>Spectrum Scanner</title></head>
<body>
<h1>Spectrum Scanner API</h1>
<p>Frontend not embedded. API endpoints:</p>
<ul>
<li>GET /api/status - Scanner status</li>
<li>GET /api/config - Configuration</li>
<li>POST /api/scan/start - Start scanning</li>
<li>POST /api/scan/stop - Stop scanning</li>
<li>GET /ws/stream - WebSocket for live data</li>
</ul>
</body>
</html>`))
		})
		return
	}
	s.mux.Handle("GET /", http.FileServer(http.FS(webContent)))
}

// ListenAndServe starts the HTTP server
func (s *Server) ListenAndServe(addr string) error {
	log.Printf("Starting HTTP server on %s", addr)
	return http.ListenAndServe(addr, s.mux)
}

// Handler returns the HTTP handler (useful for testing)
func (s *Server) Handler() http.Handler {
	return s.mux
}

// SetConfigSaveFunc sets the callback to persist config changes to disk
func (s *Server) SetConfigSaveFunc(fn ConfigSaveFunc) {
	s.onConfigSave = fn
}

// saveConfig calls the config save callback if set
func (s *Server) saveConfig() {
	if s.onConfigSave != nil {
		if err := s.onConfigSave(); err != nil {
			log.Printf("Warning: failed to save config: %v", err)
		}
	}
}

// SetEngine sets or updates the scanner engine (allows starting server before engine is ready)
func (s *Server) SetEngine(engine *scanner.Engine) {
	s.engine = engine
}

// SetMQTTClient sets or updates the MQTT client
func (s *Server) SetMQTTClient(client *mqtt.Client) {
	s.mqtt = client
}
