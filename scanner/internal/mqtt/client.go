package mqtt

import (
	"crypto/tls"
	"crypto/x509"
	"encoding/json"
	"fmt"
	"log"
	"os"
	"strings"
	"time"

	pahomqtt "github.com/eclipse/paho.mqtt.golang"

	"scanner/internal/models"
)

// CommandHandler handles incoming commands from the server
type CommandHandler interface {
	HandleStart() error
	HandleStop()
	HandleBands(bands []BandConfig) error
	HandleGain(gain float64, mode string) error
}

// ConnectionStatus represents MQTT connection state
type ConnectionStatus string

const (
	StatusConnected    ConnectionStatus = "connected"
	StatusDisconnected ConnectionStatus = "disconnected"
	StatusError        ConnectionStatus = "error"
)

// ConnectionCallback is called when MQTT connection state changes
type ConnectionCallback func(status ConnectionStatus)

// Client handles MQTT publishing for scan data
type Client struct {
	client             pahomqtt.Client
	config             *models.MQTTConfig
	scannerConfig      *models.Config
	topicPrefix        string
	scannerID          string
	commandHandler     CommandHandler
	connectionCallback ConnectionCallback
}

// SetConnectionCallback sets a callback for connection state changes
func (c *Client) SetConnectionCallback(cb ConnectionCallback) {
	c.connectionCallback = cb
}

// ScanMessage is the minimal MQTT message format for scan data
type ScanMessage struct {
	Timestamp string    `json:"timestamp"`
	Band      string    `json:"band,omitempty"`
	HzLo      float64   `json:"hz_lo"`
	HzHi      float64   `json:"hz_hi"`
	Step      float64   `json:"step"`
	Power     []float64 `json:"power"`
}

// StatusMessage is the MQTT message format for scanner status
type StatusMessage struct {
	Online      bool   `json:"online"`
	Scanning    bool   `json:"scanning"`
	CurrentBand string `json:"current_band,omitempty"`
}

// ConfigMessage is the MQTT message format for scanner configuration
type ConfigMessage struct {
	ID       string       `json:"id"`
	Type     string       `json:"type"`
	Bands    []BandConfig `json:"bands"`
	Settings Settings     `json:"settings"`
}

// BandConfig represents a band in the config message
type BandConfig struct {
	Name    string `json:"name"`
	StartHz int64  `json:"start_hz"`
	StopHz  int64  `json:"stop_hz"`
	Enabled bool   `json:"enabled"`
}

// Settings contains scanner settings
type Settings struct {
	DwellTimeMs int     `json:"dwell_time_ms"`
	RxGain      float64 `json:"rx_gain"`
	RxGainMode  string  `json:"rx_gain_mode"`
	Mode        string  `json:"mode,omitempty"`
}

// NewClient creates a new MQTT client
func NewClient(mqttConfig *models.MQTTConfig, scannerConfig *models.Config) (*Client, error) {
	if mqttConfig == nil {
		return nil, fmt.Errorf("MQTT config is nil")
	}

	topicPrefix := mqttConfig.TopicPrefix
	if topicPrefix == "" {
		topicPrefix = "spectrum"
	}

	// Use ID from MQTT config, fall back to auto-generated DeviceID
	scannerID := mqttConfig.ID
	if scannerID == "" {
		scannerID = scannerConfig.DeviceID
	}

	clientID := fmt.Sprintf("pluto-%s", scannerID)

	c := &Client{
		config:        mqttConfig,
		scannerConfig: scannerConfig,
		topicPrefix:   topicPrefix,
		scannerID:     scannerID,
	}

	opts := pahomqtt.NewClientOptions().
		AddBroker(mqttConfig.Broker).
		SetClientID(clientID).
		SetAutoReconnect(true).
		SetConnectRetry(true).
		SetConnectRetryInterval(5 * time.Second).
		SetKeepAlive(60 * time.Second).
		SetOnConnectHandler(func(client pahomqtt.Client) {
			log.Printf("MQTT connected to %s", mqttConfig.Broker)
			// Publish config on connect/reconnect
			c.PublishConfig()
			// Subscribe to command topics
			c.subscribeToCommands()
			// Publish online status
			c.PublishStatus(true, false, "")
			// Notify callback (for UI status updates)
			if c.connectionCallback != nil {
				c.connectionCallback(StatusConnected)
			}
		}).
		SetConnectionLostHandler(func(client pahomqtt.Client, err error) {
			log.Printf("MQTT connection lost: %v", err)
			// Notify callback - this is an error (unexpected disconnect)
			if c.connectionCallback != nil {
				c.connectionCallback(StatusError)
			}
		})

	// TLS transport for wss:// / ssl:// brokers (443/8883). Paho passes this
	// config straight to the websocket/TLS dialer, which fills ServerName from
	// the URL host; a valid public cert needs no config, so this is only non-nil
	// when the scheme is TLS-based (and layers on ca_file / tls_insecure).
	tlsCfg, err := brokerTLSConfig(mqttConfig)
	if err != nil {
		return nil, err
	}
	if tlsCfg != nil {
		opts.SetTLSConfig(tlsCfg)
	}

	// Authenticate with scanner ID (UUID) and token
	if mqttConfig.ID != "" && mqttConfig.Token != "" {
		opts.SetUsername(mqttConfig.ID)
		opts.SetPassword(mqttConfig.Token)
	}

	// Set last will to mark scanner offline
	willTopic := fmt.Sprintf("%s/scanners/%s/status", topicPrefix, scannerID)
	willPayload, _ := json.Marshal(StatusMessage{Online: false, Scanning: false})
	opts.SetWill(willTopic, string(willPayload), 1, true)

	c.client = pahomqtt.NewClient(opts)

	return c, nil
}

// brokerUsesTLS reports whether the broker URL uses a TLS-based transport, i.e.
// the connection must be TLS-terminated (wss/ssl/tls/mqtts/tcps).
func brokerUsesTLS(broker string) bool {
	for _, scheme := range []string{"wss://", "ssl://", "tls://", "mqtts://", "mqtt+ssl://", "tcps://"} {
		if strings.HasPrefix(broker, scheme) {
			return true
		}
	}
	return false
}

// brokerTLSConfig returns the TLS config for a TLS-based broker scheme, or nil
// for plain tcp:// / ws:// (where Paho ignores TLS settings). A valid public
// cert (Let's Encrypt via Caddy) verifies against the system roots with no
// config; CAFile trusts a private CA; TLSInsecure skips verification for a
// self-signed broker on a trusted LAN (event appliance).
func brokerTLSConfig(cfg *models.MQTTConfig) (*tls.Config, error) {
	if !brokerUsesTLS(cfg.Broker) {
		return nil, nil
	}
	tlsCfg := &tls.Config{MinVersion: tls.VersionTLS12}
	if cfg.TLSInsecure {
		tlsCfg.InsecureSkipVerify = true
	}
	if cfg.CAFile != "" {
		pem, err := os.ReadFile(cfg.CAFile)
		if err != nil {
			return nil, fmt.Errorf("mqtt ca_file: %w", err)
		}
		pool := x509.NewCertPool()
		if !pool.AppendCertsFromPEM(pem) {
			return nil, fmt.Errorf("mqtt ca_file %q: no PEM certificates found", cfg.CAFile)
		}
		tlsCfg.RootCAs = pool
	}
	return tlsCfg, nil
}

// Connect establishes the MQTT connection asynchronously.
// The scanner will work locally even if MQTT is unavailable.
// Status updates are sent via the connectionCallback from the Paho event handlers.
func (c *Client) Connect() error {
	log.Printf("Connecting to MQTT broker at %s (async)...", c.config.Broker)

	// Connect asynchronously - don't block scanner startup
	// The OnConnectHandler and ConnectionLostHandler will handle status notifications
	go func() {
		token := c.client.Connect()
		// Wait with a reasonable timeout for initial connection attempt
		if token.WaitTimeout(10 * time.Second) {
			if token.Error() != nil {
				log.Printf("MQTT initial connection failed: %v (will retry in background)", token.Error())
				// Notify callback of failure (OnConnect won't fire if connection failed)
				if c.connectionCallback != nil {
					c.connectionCallback(StatusError)
				}
			}
			// Success case: OnConnectHandler will fire and notify callback
		} else {
			log.Printf("MQTT connection timeout (will retry in background)")
			// Notify callback of timeout
			if c.connectionCallback != nil {
				c.connectionCallback(StatusError)
			}
		}
	}()

	return nil
}

// Disconnect cleanly disconnects from the broker
func (c *Client) Disconnect() {
	c.PublishStatus(false, false, "")
	c.client.Disconnect(1000)
	// Notify callback of intentional disconnect (not an error)
	if c.connectionCallback != nil {
		c.connectionCallback(StatusDisconnected)
	}
}

// IsConnected returns whether the client is connected
func (c *Client) IsConnected() bool {
	return c.client.IsConnected()
}

// PublishScan publishes a scan result to MQTT (minimal payload, not retained)
func (c *Client) PublishScan(scan models.ScanLine, bandName string) error {
	topic := fmt.Sprintf("%s/scanners/%s/scan", c.topicPrefix, c.scannerID)

	msg := ScanMessage{
		Timestamp: scan.Timestamp.UTC().Format(time.RFC3339),
		Band:      bandName,
		HzLo:      scan.HzLo,
		HzHi:      scan.HzHi,
		Step:      scan.Step,
		Power:     scan.Power,
	}

	payload, err := json.Marshal(msg)
	if err != nil {
		return fmt.Errorf("failed to marshal scan: %w", err)
	}

	// QoS 0, not retained - scan data is transient
	token := c.client.Publish(topic, 0, false, payload)
	go func() {
		if token.Wait() && token.Error() != nil {
			log.Printf("MQTT publish error: %v", token.Error())
		}
	}()

	return nil
}

// PublishStatus publishes scanner status to MQTT (retained)
func (c *Client) PublishStatus(online, scanning bool, currentBand string) {
	topic := fmt.Sprintf("%s/scanners/%s/status", c.topicPrefix, c.scannerID)

	msg := StatusMessage{
		Online:      online,
		Scanning:    scanning,
		CurrentBand: currentBand,
	}

	payload, _ := json.Marshal(msg)

	// QoS 1, retained so new subscribers see current status
	token := c.client.Publish(topic, 1, true, payload)
	go func() {
		if token.Wait() && token.Error() != nil {
			log.Printf("MQTT status publish error: %v", token.Error())
		}
	}()
}

// PublishConfig publishes scanner configuration to MQTT (retained)
func (c *Client) PublishConfig() {
	topic := fmt.Sprintf("%s/scanners/%s/config", c.topicPrefix, c.scannerID)

	// Build band list from config
	bands := make([]BandConfig, len(c.scannerConfig.Bands))
	for i, b := range c.scannerConfig.Bands {
		bands[i] = BandConfig{
			Name:    b.Name,
			StartHz: b.StartHz,
			StopHz:  b.StopHz,
			Enabled: b.Enabled,
		}
	}

	// Identity (name/location/description) is owned by the server's Scanner
	// model; the scanner reports only its UUID and the server labels it.
	msg := ConfigMessage{
		ID:    c.scannerID,
		Type:  "pluto", // ADALM-Pluto scanner
		Bands: bands,
		Settings: Settings{
			DwellTimeMs: c.scannerConfig.DwellTimeMs,
			RxGain:      c.scannerConfig.RxGain,
			RxGainMode:  c.scannerConfig.RxGainMode,
			Mode:        c.scannerConfig.Mode,
		},
	}

	payload, err := json.Marshal(msg)
	if err != nil {
		log.Printf("MQTT config marshal error: %v", err)
		return
	}

	// QoS 1, retained so new subscribers see current config
	token := c.client.Publish(topic, 1, true, payload)
	go func() {
		if token.Wait() && token.Error() != nil {
			log.Printf("MQTT config publish error: %v", token.Error())
		}
	}()

	log.Printf("Published scanner config to %s", topic)
}

// SetCommandHandler sets the handler for incoming commands
func (c *Client) SetCommandHandler(handler CommandHandler) {
	c.commandHandler = handler
}

// subscribeToCommands subscribes to command topics for this scanner
func (c *Client) subscribeToCommands() {
	// Subscribe to all commands for this scanner
	topic := fmt.Sprintf("%s/commands/%s/#", c.topicPrefix, c.scannerID)

	token := c.client.Subscribe(topic, 1, c.handleCommand)
	go func() {
		if token.Wait() && token.Error() != nil {
			log.Printf("MQTT command subscription error: %v", token.Error())
		} else {
			log.Printf("Subscribed to command topic: %s", topic)
		}
	}()
}

// handleCommand processes incoming MQTT commands
func (c *Client) handleCommand(client pahomqtt.Client, msg pahomqtt.Message) {
	if c.commandHandler == nil {
		log.Printf("Received command but no handler set: %s", msg.Topic())
		return
	}

	// Extract command type from topic: spectrum/commands/{id}/{command}
	topic := msg.Topic()
	parts := strings.Split(topic, "/")
	if len(parts) < 4 {
		log.Printf("Invalid command topic: %s", topic)
		return
	}
	command := parts[len(parts)-1]
	payload := msg.Payload()

	log.Printf("Received command: %s", command)

	switch command {
	case "start":
		if err := c.commandHandler.HandleStart(); err != nil {
			log.Printf("Start command failed: %v", err)
		} else {
			log.Printf("Start command executed")
		}

	case "stop":
		c.commandHandler.HandleStop()
		log.Printf("Stop command executed")

	case "bands":
		var bands []BandConfig
		if err := json.Unmarshal(payload, &bands); err != nil {
			log.Printf("Invalid bands payload: %v", err)
			return
		}
		if err := c.commandHandler.HandleBands(bands); err != nil {
			log.Printf("Bands command failed: %v", err)
		} else {
			log.Printf("Bands command executed (%d bands)", len(bands))
		}

	case "gain":
		var gainCmd struct {
			RxGain     float64 `json:"rx_gain"`
			RxGainMode string  `json:"rx_gain_mode"`
		}
		if err := json.Unmarshal(payload, &gainCmd); err != nil {
			log.Printf("Invalid gain payload: %v", err)
			return
		}
		if err := c.commandHandler.HandleGain(gainCmd.RxGain, gainCmd.RxGainMode); err != nil {
			log.Printf("Gain command failed: %v", err)
		} else {
			log.Printf("Gain command executed: %.1f dB, mode=%s", gainCmd.RxGain, gainCmd.RxGainMode)
		}

	default:
		log.Printf("Unknown command: %s", command)
	}
}
