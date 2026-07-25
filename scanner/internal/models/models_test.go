package models

import (
	"math"
	"testing"
)

func approx(a, b float64) bool {
	return math.Abs(a-b) < 1e-9
}

func TestCorrectionAt_NilAndEmpty(t *testing.T) {
	var nilCal *Calibration
	if got := nilCal.CorrectionAt(500e6); got != 0 {
		t.Errorf("nil calibration: got %v, want 0", got)
	}
	empty := &Calibration{ReferenceDBm: -28}
	if got := empty.CorrectionAt(500e6); got != 0 {
		t.Errorf("empty points: got %v, want 0", got)
	}
}

func TestCorrectionAt_SinglePoint(t *testing.T) {
	// Correction = reference - measured, applied everywhere (both clamp sides).
	cal := &Calibration{
		ReferenceDBm: -28,
		Points:       []CalibrationPoint{{FrequencyMHz: 500, MeasuredDBm: -30}},
	}
	want := 2.0 // -28 - (-30)
	for _, freqHz := range []float64{100e6, 500e6, 6000e6} {
		if got := cal.CorrectionAt(freqHz); !approx(got, want) {
			t.Errorf("single point @ %.0f Hz: got %v, want %v", freqHz, got, want)
		}
	}
}

func TestCorrectionAt_InterpolationAndClamp(t *testing.T) {
	cal := &Calibration{
		ReferenceDBm: -28,
		Points: []CalibrationPoint{
			{FrequencyMHz: 470, MeasuredDBm: -27.5}, // correction -0.5
			{FrequencyMHz: 500, MeasuredDBm: -26.0}, // correction -2.0
		},
	}
	cases := []struct {
		name   string
		freqHz float64
		want   float64
	}{
		{"below range clamps to first", 400e6, -0.5},
		{"lower endpoint", 470e6, -0.5},
		{"midpoint interpolates", 485e6, -1.25},
		{"upper endpoint", 500e6, -2.0},
		{"above range clamps to last", 600e6, -2.0},
	}
	for _, tc := range cases {
		if got := cal.CorrectionAt(tc.freqHz); !approx(got, tc.want) {
			t.Errorf("%s: got %v, want %v", tc.name, got, tc.want)
		}
	}
}

func TestCorrectionAt_UnsortedPointsAreSorted(t *testing.T) {
	// Same data as above but out of order; result must be identical.
	cal := &Calibration{
		ReferenceDBm: -28,
		Points: []CalibrationPoint{
			{FrequencyMHz: 500, MeasuredDBm: -26.0},
			{FrequencyMHz: 470, MeasuredDBm: -27.5},
		},
	}
	if got := cal.CorrectionAt(485e6); !approx(got, -1.25) {
		t.Errorf("unsorted midpoint: got %v, want -1.25", got)
	}
}

func TestIsValid(t *testing.T) {
	var nilCal *Calibration
	if nilCal.IsValid() {
		t.Error("nil calibration should not be valid")
	}
	if (&Calibration{}).IsValid() {
		t.Error("calibration with no points should not be valid")
	}
	cal := &Calibration{Points: []CalibrationPoint{{FrequencyMHz: 470, MeasuredDBm: -27}}}
	if !cal.IsValid() {
		t.Error("calibration with points should be valid")
	}
}
