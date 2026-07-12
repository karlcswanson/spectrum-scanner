package mqtt

import (
	"crypto/rand"
	"crypto/rsa"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/pem"
	"math/big"
	"os"
	"path/filepath"
	"testing"
	"time"

	"scanner/internal/models"
)

func TestBrokerUsesTLS(t *testing.T) {
	tls := []string{
		"wss://host/mqtt", "ssl://host:8883", "tls://host:8883",
		"mqtts://host", "mqtt+ssl://host", "tcps://host:8883",
	}
	plain := []string{
		"tcp://host:1883", "ws://host/mqtt", "mqtt://host", "host:1883", "",
	}
	for _, b := range tls {
		if !brokerUsesTLS(b) {
			t.Errorf("brokerUsesTLS(%q) = false, want true", b)
		}
	}
	for _, b := range plain {
		if brokerUsesTLS(b) {
			t.Errorf("brokerUsesTLS(%q) = true, want false", b)
		}
	}
}

func TestBrokerTLSConfig_PlainSchemeIsNil(t *testing.T) {
	cfg := &models.MQTTConfig{Broker: "tcp://host:1883", TLSInsecure: true, CAFile: "/nope"}
	got, err := brokerTLSConfig(cfg)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if got != nil {
		t.Fatalf("plain tcp:// should yield nil TLS config, got %#v", got)
	}
}

func TestBrokerTLSConfig_PublicCertNeedsNoOptions(t *testing.T) {
	cfg := &models.MQTTConfig{Broker: "wss://host/mqtt"}
	got, err := brokerTLSConfig(cfg)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if got == nil {
		t.Fatal("wss:// should yield a TLS config")
	}
	if got.InsecureSkipVerify {
		t.Error("default wss:// must verify certs (InsecureSkipVerify should be false)")
	}
	if got.RootCAs != nil {
		t.Error("no ca_file set: RootCAs should be nil (system roots)")
	}
	if got.MinVersion != tlsVersionTLS12 {
		t.Errorf("MinVersion = %d, want TLS 1.2 (%d)", got.MinVersion, tlsVersionTLS12)
	}
}

func TestBrokerTLSConfig_Insecure(t *testing.T) {
	cfg := &models.MQTTConfig{Broker: "wss://host/mqtt", TLSInsecure: true}
	got, err := brokerTLSConfig(cfg)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if !got.InsecureSkipVerify {
		t.Error("TLSInsecure=true should set InsecureSkipVerify")
	}
}

func TestBrokerTLSConfig_CAFile(t *testing.T) {
	caPath := filepath.Join(t.TempDir(), "ca.pem")
	if err := os.WriteFile(caPath, testCACertPEM(t), 0644); err != nil {
		t.Fatal(err)
	}
	cfg := &models.MQTTConfig{Broker: "ssl://host:8883", CAFile: caPath}
	got, err := brokerTLSConfig(cfg)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if got.RootCAs == nil {
		t.Fatal("ca_file set: RootCAs should be populated")
	}
}

func TestBrokerTLSConfig_CAFileErrors(t *testing.T) {
	// Missing file.
	if _, err := brokerTLSConfig(&models.MQTTConfig{Broker: "wss://h/mqtt", CAFile: "/does/not/exist"}); err == nil {
		t.Error("missing ca_file should error")
	}
	// File with no valid PEM certs.
	bad := filepath.Join(t.TempDir(), "bad.pem")
	if err := os.WriteFile(bad, []byte("not a cert"), 0644); err != nil {
		t.Fatal(err)
	}
	if _, err := brokerTLSConfig(&models.MQTTConfig{Broker: "wss://h/mqtt", CAFile: bad}); err == nil {
		t.Error("ca_file with no PEM certs should error")
	}
}

// tlsVersionTLS12 mirrors tls.VersionTLS12 without importing crypto/tls in the
// assertions above (keeps the test focused on our config values).
const tlsVersionTLS12 = 0x0303

// testCACertPEM generates a throwaway self-signed cert usable as a CA PEM.
func testCACertPEM(t *testing.T) []byte {
	t.Helper()
	key, err := rsa.GenerateKey(rand.Reader, 2048)
	if err != nil {
		t.Fatal(err)
	}
	tmpl := &x509.Certificate{
		SerialNumber:          big.NewInt(1),
		Subject:               pkix.Name{CommonName: "test-ca"},
		NotBefore:             time.Now().Add(-time.Hour),
		NotAfter:              time.Now().Add(time.Hour),
		IsCA:                  true,
		BasicConstraintsValid: true,
		KeyUsage:              x509.KeyUsageCertSign,
	}
	der, err := x509.CreateCertificate(rand.Reader, tmpl, tmpl, &key.PublicKey, key)
	if err != nil {
		t.Fatal(err)
	}
	return pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: der})
}
