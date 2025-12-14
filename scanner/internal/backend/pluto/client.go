// Package pluto implements the scanner backend for ADALM-Pluto via maia-httpd.
package pluto

import (
	"bytes"
	"context"
	"crypto/tls"
	"encoding/binary"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"math"
	"net/http"
	"strings"
	"sync"
	"time"

	"github.com/gorilla/websocket"

	"scanner/internal/models"
	"scanner/internal/scanner"
)

const (
	// FFTSize is the fixed FFT size used by maia-hdl
	FFTSize = 4096

	// SegmentOverlap is the fraction of overlap between segments (50%)
	SegmentOverlap = 0.5

	// SettleTime is the wait time after tuning for PLL to settle
	SettleTime = 20 * time.Millisecond
)

// Client implements scanner.Backend for ADALM-Pluto via maia-httpd.
type Client struct {
	baseURL    string
	httpClient *http.Client
	name       string

	mu        sync.Mutex
	connected bool

	// Current configuration
	currentBand models.Band
	settings    scanner.SweepSettings
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

// NewClient creates a new maia-httpd client for ADALM-Pluto.
func NewClient(baseURL string, name string) *Client {
	if name == "" {
		name = "ADALM-Pluto"
	}

	// Skip TLS verification for self-signed certs on the Pluto
	tlsConfig := &tls.Config{InsecureSkipVerify: true}
	transport := &http.Transport{TLSClientConfig: tlsConfig}

	return &Client{
		baseURL: strings.TrimSuffix(baseURL, "/"),
		httpClient: &http.Client{
			Timeout:   10 * time.Second,
			Transport: transport,
		},
		name: name,
	}
}

// Name returns the scanner name
func (c *Client) Name() string {
	return c.name
}

// Type returns the backend type
func (c *Client) Type() string {
	return "pluto"
}

// FrequencyRange returns the frequency range this scanner supports
func (c *Client) FrequencyRange() (minHz, maxHz int64) {
	// ADALM-Pluto: 325 MHz to 3.8 GHz (with hack: 70 MHz to 6 GHz)
	return 70_000_000, 6_000_000_000
}

// Connect verifies connection to maia-httpd
func (c *Client) Connect() error {
	c.mu.Lock()
	defer c.mu.Unlock()

	log.Printf("Pluto: Connecting to maia-httpd at %s...", c.baseURL)

	ad9361, err := c.getAd9361()
	if err != nil {
		return fmt.Errorf("failed to connect to maia-httpd: %w", err)
	}

	c.connected = true
	log.Printf("Pluto: Connected - RX LO: %.2f MHz, Sample rate: %.2f MHz",
		float64(ad9361.RxLoFrequency)/1e6,
		float64(ad9361.SamplingFrequency)/1e6)

	return nil
}

// Close disconnects from maia-httpd
func (c *Client) Close() error {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.connected = false
	return nil
}

// IsConnected returns whether the client is connected
func (c *Client) IsConnected() bool {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.connected
}

// Configure sets up the Pluto for a specific band
func (c *Client) Configure(band models.Band, settings scanner.SweepSettings) error {
	c.mu.Lock()
	defer c.mu.Unlock()

	c.currentBand = band
	c.settings = settings

	// Apply gain settings
	gainMode := settings.RxGainMode
	if gainMode == "" {
		gainMode = "manual"
	}
	rxGain := settings.RxGain
	if rxGain == 0 {
		rxGain = 40
	}

	log.Printf("Pluto: Configuring for band %s (%.1f - %.1f MHz), gain: %.1f dB",
		band.Name, float64(band.StartHz)/1e6, float64(band.StopHz)/1e6, rxGain)

	if err := c.setGainAndMode(rxGain, gainMode); err != nil {
		log.Printf("Pluto: Warning - failed to set gain: %v", err)
	}

	return nil
}

// Sweep performs a frequency sweep across the configured band
func (c *Client) Sweep(ctx context.Context) (models.ScanLine, error) {
	c.mu.Lock()
	band := c.currentBand
	settings := c.settings
	c.mu.Unlock()

	// Get current settings
	spec, err := c.getSpectrometer()
	if err != nil {
		return models.ScanLine{}, err
	}
	ad9361, err := c.getAd9361()
	if err != nil {
		return models.ScanLine{}, err
	}

	// Calculate segments
	segmentBandwidth := int64(spec.InputSamplingFrequency)
	binHz := spec.InputSamplingFrequency / float64(FFTSize)
	segments := calculateSegments(band, segmentBandwidth)

	log.Printf("Pluto: Sweeping %d segments, %.2f MHz each",
		len(segments), float64(segmentBandwidth)/1e6)

	// Crop bins (25% from each edge for 50% overlap)
	cropBins := int(float64(FFTSize) * SegmentOverlap / 2)

	// Pre-allocate result array
	totalBins := int(float64(band.StopHz-band.StartHz) / binHz)
	allPowers := make([]float64, totalBins)
	for i := range allPowers {
		allPowers[i] = -140 // noise floor
	}

	for _, centerFreq := range segments {
		select {
		case <-ctx.Done():
			return models.ScanLine{}, ctx.Err()
		default:
		}

		// Tune to segment
		if err := c.setFrequency(uint64(centerFreq)); err != nil {
			return models.ScanLine{}, err
		}

		// Re-apply gain after frequency change
		gainMode := settings.RxGainMode
		if gainMode == "" {
			gainMode = "manual"
		}
		rxGain := settings.RxGain
		if rxGain == 0 {
			rxGain = 40
		}
		c.setGainAndMode(rxGain, gainMode)

		// Wait for PLL to settle
		time.Sleep(SettleTime)

		// Collect FFT frames
		powers, err := c.collectSegment(ctx, settings.DwellTimeMs)
		if err != nil {
			return models.ScanLine{}, err
		}

		// Apply calibration offset
		calibrationOffset := -ad9361.RxGain - 90.0
		for i := range powers {
			powers[i] += calibrationOffset
		}

		// Copy cropped segment to output
		cropHz := float64(cropBins) * binHz
		usableStartHz := float64(centerFreq) - float64(segmentBandwidth)/2 + cropHz
		startBin := int((usableStartHz - float64(band.StartHz)) / binHz)

		for i := cropBins; i < FFTSize-cropBins; i++ {
			outIdx := startBin + (i - cropBins)
			if outIdx >= 0 && outIdx < len(allPowers) {
				if powers[i] > allPowers[outIdx] {
					allPowers[outIdx] = powers[i]
				}
			}
		}
	}

	return models.ScanLine{
		Timestamp: time.Now().UTC(),
		HzLo:      float64(band.StartHz),
		HzHi:      float64(band.StopHz),
		Step:      binHz,
		Samples:   float64(len(allPowers)),
		Power:     allPowers,
	}, nil
}

// calculateSegments returns center frequencies for each segment with overlap
func calculateSegments(band models.Band, segmentBandwidth int64) []int64 {
	var centers []int64

	hopSize := int64(float64(segmentBandwidth) * (1 - SegmentOverlap))
	cropHz := int64(float64(segmentBandwidth) * SegmentOverlap / 2)
	freq := band.StartHz + segmentBandwidth/2 - cropHz

	for freq-segmentBandwidth/2+cropHz < band.StopHz {
		centers = append(centers, freq)
		freq += hopSize
	}

	if len(centers) == 0 {
		centers = append(centers, (band.StartHz+band.StopHz)/2)
	}

	return centers
}

func (c *Client) collectSegment(ctx context.Context, dwellMs int) ([]float64, error) {
	conn, err := c.connectWaterfall(ctx)
	if err != nil {
		return nil, err
	}
	defer conn.Close()

	if dwellMs <= 0 {
		dwellMs = 50
	}

	deadline := time.Now().Add(time.Duration(dwellMs) * time.Millisecond)
	var frames [][]float64
	firstRead := true

	for time.Now().Before(deadline) {
		select {
		case <-ctx.Done():
			return nil, ctx.Err()
		default:
		}

		readTimeout := 100 * time.Millisecond
		if firstRead {
			readTimeout = 500 * time.Millisecond
		}
		conn.SetReadDeadline(time.Now().Add(readTimeout))

		powers, err := readFFTFrame(conn)
		if err != nil {
			if firstRead {
				firstRead = false
				continue
			}
			break
		}
		firstRead = false
		frames = append(frames, powers)
	}

	if len(frames) == 0 {
		return make([]float64, FFTSize), nil
	}

	if len(frames) > 1 {
		frames = frames[1:]
	}

	// Average frames
	averaged := make([]float64, FFTSize)
	for i := 0; i < FFTSize; i++ {
		sum := 0.0
		for _, frame := range frames {
			sum += frame[i]
		}
		averaged[i] = sum / float64(len(frames))
	}

	return averaged, nil
}

// HTTP/API methods

func (c *Client) getAd9361() (*Ad9361Settings, error) {
	resp, err := c.httpClient.Get(c.baseURL + "/api/ad9361")
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("status %d: %s", resp.StatusCode, body)
	}

	var settings Ad9361Settings
	if err := json.NewDecoder(resp.Body).Decode(&settings); err != nil {
		return nil, err
	}
	return &settings, nil
}

func (c *Client) getSpectrometer() (*SpectrometerSettings, error) {
	resp, err := c.httpClient.Get(c.baseURL + "/api/spectrometer")
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("status %d: %s", resp.StatusCode, body)
	}

	var settings SpectrometerSettings
	if err := json.NewDecoder(resp.Body).Decode(&settings); err != nil {
		return nil, err
	}
	return &settings, nil
}

func (c *Client) setFrequency(hz uint64) error {
	patch := PatchAd9361{RxLoFrequency: &hz}
	return c.patch("/api/ad9361", patch)
}

func (c *Client) setGainAndMode(db float64, mode string) error {
	normalized := normalizeGainMode(mode)
	patch := PatchAd9361{RxGain: &db, RxGainMode: &normalized}
	return c.patch("/api/ad9361", patch)
}

func normalizeGainMode(mode string) string {
	switch mode {
	case "manual", "Manual":
		return "Manual"
	case "slow_attack", "SlowAttack":
		return "SlowAttack"
	case "fast_attack", "FastAttack":
		return "FastAttack"
	case "hybrid", "Hybrid":
		return "Hybrid"
	default:
		return "Manual"
	}
}

func (c *Client) patch(path string, body interface{}) error {
	jsonBody, err := json.Marshal(body)
	if err != nil {
		return err
	}

	req, err := http.NewRequest(http.MethodPatch, c.baseURL+path, bytes.NewReader(jsonBody))
	if err != nil {
		return err
	}
	req.Header.Set("Content-Type", "application/json")

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()

	if resp.StatusCode >= 400 {
		body, _ := io.ReadAll(resp.Body)
		return fmt.Errorf("PATCH %s: status %d: %s", path, resp.StatusCode, body)
	}

	return nil
}

func (c *Client) connectWaterfall(ctx context.Context) (*websocket.Conn, error) {
	wsURL := strings.Replace(c.baseURL, "http://", "ws://", 1)
	wsURL = strings.Replace(wsURL, "https://", "wss://", 1)
	wsURL += "/waterfall"

	dialer := websocket.Dialer{
		HandshakeTimeout: 10 * time.Second,
		TLSClientConfig:  &tls.Config{InsecureSkipVerify: true},
	}

	conn, _, err := dialer.DialContext(ctx, wsURL, nil)
	if err != nil {
		return nil, err
	}
	return conn, nil
}

func readFFTFrame(conn *websocket.Conn) ([]float64, error) {
	_, data, err := conn.ReadMessage()
	if err != nil {
		return nil, err
	}

	expectedSize := FFTSize * 4
	if len(data) != expectedSize {
		return nil, fmt.Errorf("unexpected frame size: got %d, want %d", len(data), expectedSize)
	}

	powers := make([]float64, FFTSize)
	reader := bytes.NewReader(data)

	for i := 0; i < FFTSize; i++ {
		var val float32
		if err := binary.Read(reader, binary.LittleEndian, &val); err != nil {
			return nil, err
		}
		if val > 0 {
			powers[i] = 10 * math.Log10(float64(val))
		} else {
			powers[i] = -120
		}
	}

	return powers, nil
}

// GetCapabilities returns the capabilities of this scanner
func (c *Client) GetCapabilities() scanner.Capabilities {
	return scanner.Capabilities{
		MinFreqHz:            70_000_000,
		MaxFreqHz:            6_000_000_000,
		RBWOptions:           nil, // Continuous via sample rate
		HasTrackingGenerator: false,
		HasAttenuation:       false,
		HasGainControl:       true,
		MinGainDB:            0,
		MaxGainDB:            73,
		TracePoints:          FFTSize,
	}
}
