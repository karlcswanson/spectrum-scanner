package mqtt

import (
	"encoding/json"
	"fmt"
	"log"
	"time"

	pahomqtt "github.com/eclipse/paho.mqtt.golang"

	"spectrum-pluto/internal/models"
)

// Client handles MQTT publishing for scan data
type Client struct {
	client        pahomqtt.Client
	config        *models.MQTTConfig
	scannerConfig *models.Config
	topicPrefix   string
	scannerID     string
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
	ID          string       `json:"id"`
	Name        string       `json:"name"`
	Type        string       `json:"type"`
	Location    string       `json:"location,omitempty"`
	Description string       `json:"description,omitempty"`
	Bands       []BandConfig `json:"bands"`
	Settings    Settings     `json:"settings"`
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
	if mqttConfig == nil || !mqttConfig.Enabled {
		return nil, nil
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
		}).
		SetConnectionLostHandler(func(client pahomqtt.Client, err error) {
			log.Printf("MQTT connection lost: %v", err)
		})

	if mqttConfig.Username != "" {
		opts.SetUsername(mqttConfig.Username)
		opts.SetPassword(mqttConfig.Password)
	}

	// Set last will to mark scanner offline
	willTopic := fmt.Sprintf("%s/scanners/%s/status", topicPrefix, scannerID)
	willPayload, _ := json.Marshal(StatusMessage{Online: false, Scanning: false})
	opts.SetWill(willTopic, string(willPayload), 1, true)

	c.client = pahomqtt.NewClient(opts)

	return c, nil
}

// Connect establishes the MQTT connection
func (c *Client) Connect() error {
	log.Printf("Connecting to MQTT broker at %s...", c.config.Broker)

	token := c.client.Connect()
	if token.Wait() && token.Error() != nil {
		return fmt.Errorf("MQTT connect failed: %w", token.Error())
	}

	// Publish online status
	c.PublishStatus(true, false, "")

	return nil
}

// Disconnect cleanly disconnects from the broker
func (c *Client) Disconnect() {
	c.PublishStatus(false, false, "")
	c.client.Disconnect(1000)
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

	// Use name/location from MQTT config, fall back to scanner config
	name := c.config.Name
	if name == "" {
		name = c.scannerConfig.Name
	}
	if name == "" {
		name = c.scannerID
	}

	msg := ConfigMessage{
		ID:          c.scannerID,
		Name:        name,
		Type:        "pluto", // ADALM-Pluto scanner
		Location:    c.config.Location,
		Description: c.scannerConfig.Description,
		Bands:       bands,
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
