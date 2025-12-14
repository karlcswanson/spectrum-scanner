package api

import (
	"log"
	"net/http"

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

func (s *Server) handleWebSocket(w http.ResponseWriter, r *http.Request) {
	conn, err := upgrader.Upgrade(w, r, nil)
	if err != nil {
		log.Printf("WebSocket upgrade error: %v", err)
		return
	}
	defer conn.Close()

	// Subscribe to scan results from the sweep engine
	ch := s.engine.Subscribe()
	defer s.engine.Unsubscribe(ch)

	clientAddr := r.RemoteAddr
	log.Printf("WebSocket client connected: %s", clientAddr)

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
		if err := conn.WriteJSON(scan); err != nil {
			log.Printf("WebSocket write error for %s: %v", clientAddr, err)
			return
		}
	}

	log.Printf("WebSocket client disconnected: %s", clientAddr)
}
