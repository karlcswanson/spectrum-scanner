"""Base spectrum analyzer interface and implementations."""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import pyvisa

logger = logging.getLogger(__name__)


@dataclass
class ScanResult:
    """Result from a spectrum scan."""

    hz_lo: float
    hz_hi: float
    step_hz: float
    power: list[float]  # dBm values
    timestamp: datetime
    band: Optional[str] = None
    rbw_hz: Optional[float] = None


class SpectrumAnalyzer(ABC):
    """Abstract base class for spectrum analyzers."""

    def __init__(self, resource_name: str):
        self.resource_name = resource_name
        self.rm = pyvisa.ResourceManager('@py')
        self.inst = None

    def connect(self) -> None:
        """Connect to the analyzer."""
        logger.info(f"Connecting to {self.resource_name}")
        self.inst = self.rm.open_resource(self.resource_name)
        self.inst.timeout = 30000  # 30 second timeout
        self._identify()

    def disconnect(self) -> None:
        """Disconnect from the analyzer."""
        if self.inst:
            self.inst.close()
            self.inst = None

    def _identify(self) -> str:
        """Query instrument identification."""
        idn = self.inst.query("*IDN?").strip()
        logger.info(f"Connected to: {idn}")
        return idn

    @abstractmethod
    def scan(
        self,
        start_hz: float,
        stop_hz: float,
        rbw_hz: Optional[float] = None,
        band_name: Optional[str] = None,
    ) -> ScanResult:
        """Perform a spectrum scan."""
        pass

    @abstractmethod
    def get_trace(self) -> list[float]:
        """Get current trace data in dBm."""
        pass


class TTiAnalyzer(SpectrumAnalyzer):
    """TTi PSA series spectrum analyzer."""

    def scan(
        self,
        start_hz: float,
        stop_hz: float,
        rbw_hz: Optional[float] = None,
        band_name: Optional[str] = None,
    ) -> ScanResult:
        """Perform a spectrum scan on TTi PSA."""
        # Set frequency range
        self.inst.write(f":FREQ:START {start_hz}")
        self.inst.write(f":FREQ:STOP {stop_hz}")

        # Set RBW if specified
        if rbw_hz:
            self.inst.write(f":BAND:RES {rbw_hz}")

        # Trigger sweep
        self.inst.write(":INIT:IMM")
        self.inst.query("*OPC?")  # Wait for completion

        # Get trace data
        power = self.get_trace()

        # Calculate step
        step_hz = (stop_hz - start_hz) / len(power) if power else 0

        return ScanResult(
            hz_lo=start_hz,
            hz_hi=stop_hz,
            step_hz=step_hz,
            power=power,
            timestamp=datetime.now(timezone.utc),
            band=band_name,
            rbw_hz=rbw_hz,
        )

    def get_trace(self) -> list[float]:
        """Get trace data from TTi PSA."""
        data = self.inst.query(":TRACE:DATA?")
        # Parse comma-separated dBm values
        values = [float(x) for x in data.strip().split(',')]
        return values


class OWONAnalyzer(SpectrumAnalyzer):
    """OWON XSA/HSA series spectrum analyzer."""

    def scan(
        self,
        start_hz: float,
        stop_hz: float,
        rbw_hz: Optional[float] = None,
        band_name: Optional[str] = None,
    ) -> ScanResult:
        """Perform a spectrum scan on OWON."""
        # Set frequency range
        self.inst.write(f":FREQ:START {start_hz}")
        self.inst.write(f":FREQ:STOP {stop_hz}")

        # Set RBW if specified
        if rbw_hz:
            self.inst.write(f":BAND:RES {rbw_hz}")

        # Trigger sweep
        self.inst.write(":INIT:IMM")
        self.inst.query("*OPC?")

        power = self.get_trace()
        step_hz = (stop_hz - start_hz) / len(power) if power else 0

        return ScanResult(
            hz_lo=start_hz,
            hz_hi=stop_hz,
            step_hz=step_hz,
            power=power,
            timestamp=datetime.now(timezone.utc),
            band=band_name,
            rbw_hz=rbw_hz,
        )

    def get_trace(self) -> list[float]:
        """Get trace data from OWON."""
        data = self.inst.query(":TRACE:DATA?")
        values = [float(x) for x in data.strip().split(',')]
        return values


class GenericSCPIAnalyzer(SpectrumAnalyzer):
    """Generic SCPI spectrum analyzer (basic commands)."""

    def scan(
        self,
        start_hz: float,
        stop_hz: float,
        rbw_hz: Optional[float] = None,
        band_name: Optional[str] = None,
    ) -> ScanResult:
        """Perform a basic SCPI scan."""
        self.inst.write(f"FREQ:START {start_hz}")
        self.inst.write(f"FREQ:STOP {stop_hz}")

        if rbw_hz:
            self.inst.write(f"BAND {rbw_hz}")

        self.inst.write("INIT:IMM")
        self.inst.query("*OPC?")

        power = self.get_trace()
        step_hz = (stop_hz - start_hz) / len(power) if power else 0

        return ScanResult(
            hz_lo=start_hz,
            hz_hi=stop_hz,
            step_hz=step_hz,
            power=power,
            timestamp=datetime.now(timezone.utc),
            band=band_name,
            rbw_hz=rbw_hz,
        )

    def get_trace(self) -> list[float]:
        """Get trace data using generic SCPI."""
        data = self.inst.query("TRACE:DATA?")
        values = [float(x) for x in data.strip().split(',')]
        return values


def create_analyzer(resource_name: str, analyzer_type: str = "generic") -> SpectrumAnalyzer:
    """Factory function to create appropriate analyzer instance."""
    analyzers = {
        "tti": TTiAnalyzer,
        "owon": OWONAnalyzer,
        "generic": GenericSCPIAnalyzer,
    }

    cls = analyzers.get(analyzer_type.lower(), GenericSCPIAnalyzer)
    return cls(resource_name)
