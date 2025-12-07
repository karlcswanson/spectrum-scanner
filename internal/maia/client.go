package maia

import (
	"bytes"
	"context"
	"crypto/tls"
	"encoding/binary"
	"encoding/json"
	"fmt"
	"io"
	"math"
	"net/http"
	"strings"
	"time"

	"github.com/gorilla/websocket"
)

const (
	// FFTSize is the fixed FFT size used by maia-hdl
	FFTSize = 4096
	// MaxSampleRate is the maximum AD9361 sample rate
	MaxSampleRate = 61_440_000
)

// Client communicates with maia-httpd
type Client struct {
	baseURL    string
	httpClient *http.Client
}

// NewClient creates a new maia-httpd client
func NewClient(baseURL string) *Client {
	// Skip TLS verification for self-signed certs on the Pluto
	tlsConfig := &tls.Config{InsecureSkipVerify: true}
	transport := &http.Transport{TLSClientConfig: tlsConfig}

	return &Client{
		baseURL: strings.TrimSuffix(baseURL, "/"),
		httpClient: &http.Client{
			Timeout:   10 * time.Second,
			Transport: transport,
		},
	}
}

// Ad9361Settings represents AD9361 transceiver settings
type Ad9361Settings struct {
	SamplingFrequency uint32  `json:"sampling_frequency"`
	RxRfBandwidth     uint32  `json:"rx_rf_bandwidth"`
	TxRfBandwidth     uint32  `json:"tx_rf_bandwidth"`
	RxLoFrequency     uint64  `json:"rx_lo_frequency"`
	TxLoFrequency     uint64  `json:"tx_lo_frequency"`
	RxGain            float64 `json:"rx_gain"`
	RxGainMode        string  `json:"rx_gain_mode"`
	TxGain            float64 `json:"tx_gain"`
}

// PatchAd9361 is used for PATCH requests to update AD9361 settings
type PatchAd9361 struct {
	SamplingFrequency *uint32  `json:"sampling_frequency,omitempty"`
	RxRfBandwidth     *uint32  `json:"rx_rf_bandwidth,omitempty"`
	RxLoFrequency     *uint64  `json:"rx_lo_frequency,omitempty"`
	RxGain            *float64 `json:"rx_gain,omitempty"`
	RxGainMode        *string  `json:"rx_gain_mode,omitempty"`
}

// SpectrometerSettings represents spectrometer configuration
type SpectrometerSettings struct {
	Input                   string  `json:"input"`
	InputSamplingFrequency  float64 `json:"input_sampling_frequency"`
	OutputSamplingFrequency float64 `json:"output_sampling_frequency"`
	NumberIntegrations      uint32  `json:"number_integrations"`
	FFTSize                 uint32  `json:"fft_size"`
	Mode                    string  `json:"mode"`
}

// PatchSpectrometer is used for PATCH requests to update spectrometer settings
type PatchSpectrometer struct {
	Input              *string `json:"input,omitempty"`
	NumberIntegrations *uint32 `json:"number_integrations,omitempty"`
	Mode               *string `json:"mode,omitempty"`
}

// GetAd9361 retrieves current AD9361 settings
func (c *Client) GetAd9361() (*Ad9361Settings, error) {
	resp, err := c.httpClient.Get(c.baseURL + "/api/ad9361")
	if err != nil {
		return nil, fmt.Errorf("GET /api/ad9361: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("GET /api/ad9361: status %d: %s", resp.StatusCode, body)
	}

	var settings Ad9361Settings
	if err := json.NewDecoder(resp.Body).Decode(&settings); err != nil {
		return nil, fmt.Errorf("decode ad9361 settings: %w", err)
	}
	return &settings, nil
}

// SetFrequency sets the AD9361 RX LO frequency in Hz
func (c *Client) SetFrequency(hz uint64) error {
	patch := PatchAd9361{RxLoFrequency: &hz}
	return c.patch("/api/ad9361", patch)
}

// SetGain sets the AD9361 RX gain in dB
func (c *Client) SetGain(db float64) error {
	patch := PatchAd9361{RxGain: &db}
	return c.patch("/api/ad9361", patch)
}

// SetSampleRate sets the AD9361 sampling frequency in Hz
func (c *Client) SetSampleRate(hz uint32) error {
	patch := PatchAd9361{SamplingFrequency: &hz}
	return c.patch("/api/ad9361", patch)
}

// GetSpectrometer retrieves current spectrometer settings
func (c *Client) GetSpectrometer() (*SpectrometerSettings, error) {
	resp, err := c.httpClient.Get(c.baseURL + "/api/spectrometer")
	if err != nil {
		return nil, fmt.Errorf("GET /api/spectrometer: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("GET /api/spectrometer: status %d: %s", resp.StatusCode, body)
	}

	var settings SpectrometerSettings
	if err := json.NewDecoder(resp.Body).Decode(&settings); err != nil {
		return nil, fmt.Errorf("decode spectrometer settings: %w", err)
	}
	return &settings, nil
}

// SetSpectrometerMode configures the spectrometer mode and integration count
func (c *Client) SetSpectrometerMode(mode string, integrations uint32) error {
	patch := PatchSpectrometer{
		Mode:               &mode,
		NumberIntegrations: &integrations,
	}
	return c.patch("/api/spectrometer", patch)
}

// ConnectWaterfall opens a WebSocket connection to the FFT data stream
func (c *Client) ConnectWaterfall(ctx context.Context) (*websocket.Conn, error) {
	wsURL := strings.Replace(c.baseURL, "http://", "ws://", 1)
	wsURL = strings.Replace(wsURL, "https://", "wss://", 1)
	wsURL += "/waterfall"

	// Skip TLS verification for self-signed certs on the Pluto
	dialer := websocket.Dialer{
		HandshakeTimeout: 10 * time.Second,
		TLSClientConfig:  &tls.Config{InsecureSkipVerify: true},
	}

	conn, _, err := dialer.DialContext(ctx, wsURL, nil)
	if err != nil {
		return nil, fmt.Errorf("connect to waterfall: %w", err)
	}
	return conn, nil
}

// ReadFFTFrame reads one FFT frame from the waterfall WebSocket
// Returns FFTSize (4096) float64 power values in dB
func ReadFFTFrame(conn *websocket.Conn) ([]float64, error) {
	_, data, err := conn.ReadMessage()
	if err != nil {
		return nil, err
	}

	// maia-httpd sends 4096 x float32 as binary (little-endian)
	expectedSize := FFTSize * 4
	if len(data) != expectedSize {
		return nil, fmt.Errorf("unexpected frame size: got %d, want %d", len(data), expectedSize)
	}

	powers := make([]float64, FFTSize)
	reader := bytes.NewReader(data)

	for i := 0; i < FFTSize; i++ {
		var val float32
		if err := binary.Read(reader, binary.LittleEndian, &val); err != nil {
			return nil, fmt.Errorf("read float32 at index %d: %w", i, err)
		}
		// Convert to dB (maia sends linear power values)
		if val > 0 {
			powers[i] = 10 * math.Log10(float64(val))
		} else {
			powers[i] = -120 // noise floor
		}
	}

	return powers, nil
}

// patch sends a PATCH request with JSON body
func (c *Client) patch(path string, body interface{}) error {
	jsonBody, err := json.Marshal(body)
	if err != nil {
		return fmt.Errorf("marshal body: %w", err)
	}

	req, err := http.NewRequest(http.MethodPatch, c.baseURL+path, bytes.NewReader(jsonBody))
	if err != nil {
		return fmt.Errorf("create request: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return fmt.Errorf("PATCH %s: %w", path, err)
	}
	defer resp.Body.Close()

	if resp.StatusCode >= 400 {
		body, _ := io.ReadAll(resp.Body)
		return fmt.Errorf("PATCH %s: status %d: %s", path, resp.StatusCode, body)
	}

	return nil
}
