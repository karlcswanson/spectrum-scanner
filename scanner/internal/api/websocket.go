package api

import (
	"encoding/json"
	"log"
	"net/http"
	"sync"
	"time"

	"github.com/gorilla/websocket"
)

var upgrader = websocket.Upgrader{
	ReadBufferSize:  1024,
	WriteBufferSize: 1024,
	// Allow all origins for embedded device use
	CheckOrigin: func(r *http.Request) bool {
		return true
	},
}

// WSMessage wraps different message types sent over WebSocket
type WSMessage struct {
	Type string      `json:"type"` // "scan" or "status"
	Data interface{} `json:"data"`
}

// WSHub manages WebSocket connections for broadcasting
type WSHub struct {
	mu      sync.RWMutex
	clients map[*websocket.Conn]bool
}

// NewWSHub creates a new WebSocket hub
func NewWSHub() *WSHub {
	return &WSHub{
		clients: make(map[*websocket.Conn]bool),
	}
}

// Add registers a new client
func (h *WSHub) Add(conn *websocket.Conn) {
	h.mu.Lock()
	h.clients[conn] = true
	h.mu.Unlock()
}

// Remove unregisters a client
func (h *WSHub) Remove(conn *websocket.Conn) {
	h.mu.Lock()
	delete(h.clients, conn)
	h.mu.Unlock()
}

// Broadcast sends a message to all connected clients
func (h *WSHub) Broadcast(msg WSMessage) {
	data, err := json.Marshal(msg)
	if err != nil {
		log.Printf("WSHub marshal error: %v", err)
		return
	}

	h.mu.RLock()
	defer h.mu.RUnlock()

	for conn := range h.clients {
		if err := conn.WriteMessage(websocket.TextMessage, data); err != nil {
			log.Printf("WSHub broadcast error: %v", err)
		}
	}
}

// BroadcastStatus sends a status update to all clients
func (h *WSHub) BroadcastStatus(scanning bool, currentBand string) {
	h.Broadcast(WSMessage{
		Type: "status",
		Data: map[string]interface{}{
			"scanning":     scanning,
			"current_band": currentBand,
		},
	})
}

// BroadcastConfig sends a config update to all clients
func (h *WSHub) BroadcastConfig(config interface{}) {
	h.Broadcast(WSMessage{
		Type: "config",
		Data: config,
	})
}

// BroadcastServerStatus sends server status (MQTT/web) to all clients
func (h *WSHub) BroadcastServerStatus(status interface{}) {
	log.Printf("WSHub: broadcasting server-status: %+v", status)
	h.Broadcast(WSMessage{
		Type: "server-status",
		Data: status,
	})
}

func (s *Server) handleWebSocket(w http.ResponseWriter, r *http.Request) {
	conn, err := upgrader.Upgrade(w, r, nil)
	if err != nil {
		log.Printf("WebSocket upgrade error: %v", err)
		return
	}
	defer conn.Close()

	// Register with hub for status broadcasts
	s.wsHub.Add(conn)
	defer s.wsHub.Remove(conn)

	clientAddr := r.RemoteAddr
	log.Printf("WebSocket client connected: %s", clientAddr)

	// Wait for engine to be ready (poll every 500ms)
	for s.engine == nil {
		s.wsHub.BroadcastStatus(false, "")
		time.Sleep(500 * time.Millisecond)
	}

	// Subscribe to scan results from the sweep engine
	ch := s.engine.Subscribe()
	defer s.engine.Unsubscribe(ch)

	// Send initial status
	s.wsHub.BroadcastStatus(s.engine.IsRunning(), s.engine.CurrentBand())

	// Send initial server status (MQTT/web) if available
	log.Printf("WebSocket: checking for server status callback...")
	serverStatus := s.GetServerStatus()
	log.Printf("WebSocket: got server status: %+v", serverStatus)
	if serverStatus != nil {
		s.wsHub.BroadcastServerStatus(serverStatus)
	}

	// Handle incoming messages (for future use - commands from client)
	go func() {
		for {
			_, _, err := conn.ReadMessage()
			if err != nil {
				// Client disconnected or error
				return
			}
			// Could handle client commands here in the future
		}
	}()

	// Send scan results to the client
	for scan := range ch {
		msg := WSMessage{
			Type: "scan",
			Data: scan,
		}
		if err := conn.WriteJSON(msg); err != nil {
			log.Printf("WebSocket write error for %s: %v", clientAddr, err)
			return
		}
	}

	log.Printf("WebSocket client disconnected: %s", clientAddr)
}
