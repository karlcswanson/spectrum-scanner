package pluto

import (
	"testing"

	"scanner/internal/models"
)

// segmentBandwidth used by the sweep loop; tests use a representative value.
const testBandwidth = int64(30_000_000) // 30 MHz

func TestCalculateSegments_Coverage(t *testing.T) {
	band := models.Band{StartHz: 470_000_000, StopHz: 608_000_000}
	centers := calculateSegments(band, testBandwidth)
	if len(centers) == 0 {
		t.Fatal("expected at least one segment")
	}

	cropHz := int64(float64(testBandwidth) * SegmentOverlap / 2)
	hopSize := int64(float64(testBandwidth) * (1 - SegmentOverlap))

	// The first segment's usable (post-crop) region must start at the band
	// start so nothing at the low edge is missed.
	wantFirst := band.StartHz + testBandwidth/2 - cropHz
	if centers[0] != wantFirst {
		t.Errorf("first center: got %d, want %d", centers[0], wantFirst)
	}

	// Consecutive centers are spaced by hopSize (50%% overlap).
	for i := 1; i < len(centers); i++ {
		if got := centers[i] - centers[i-1]; got != hopSize {
			t.Errorf("spacing at index %d: got %d, want %d", i, got, hopSize)
		}
	}

	// The last segment's usable region must reach past the band stop so the
	// high edge is covered.
	lastUsableHi := centers[len(centers)-1] + testBandwidth/2 - cropHz
	if lastUsableHi < band.StopHz {
		t.Errorf("coverage gap: last usable high %d < band stop %d", lastUsableHi, band.StopHz)
	}
}

func TestCalculateSegments_NarrowBandSingleSegment(t *testing.T) {
	// A band narrower than one segment yields exactly one segment.
	band := models.Band{StartHz: 470_000_000, StopHz: 475_000_000}
	if centers := calculateSegments(band, testBandwidth); len(centers) != 1 {
		t.Errorf("narrow band: got %d segments, want 1", len(centers))
	}
}

func TestCalculateSegments_DegenerateFallback(t *testing.T) {
	// Zero-width band hits the fallback that centers on the midpoint.
	band := models.Band{StartHz: 500_000_000, StopHz: 500_000_000}
	centers := calculateSegments(band, testBandwidth)
	if len(centers) != 1 {
		t.Fatalf("degenerate band: got %d segments, want 1", len(centers))
	}
	if centers[0] != 500_000_000 {
		t.Errorf("fallback center: got %d, want 500000000", centers[0])
	}
}
