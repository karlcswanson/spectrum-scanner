package api

import (
	"embed"
	"io/fs"
	"log"
	"net/http"

	"spectrum-pluto/internal/models"
	"spectrum-pluto/internal/sweep"
)

//go:embed web
var webFS embed.FS

// Server handles HTTP requests for the spectrum scanner
type Server struct {
	engine *sweep.Engine
	config *models.Config
	mux    *http.ServeMux
}

// NewServer creates a new HTTP server
func NewServer(engine *sweep.Engine, config *models.Config) *Server {
	s := &Server{
		engine: engine,
		config: config,
		mux:    http.NewServeMux(),
	}
	s.setupRoutes()
	return s
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

	// WebSocket for live scan data
	s.mux.HandleFunc("GET /ws/stream", s.handleWebSocket)

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