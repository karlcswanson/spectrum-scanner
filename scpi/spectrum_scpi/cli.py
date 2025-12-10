"""Command-line interface for SCPI spectrum scanner."""

import logging
import sys
import time

import click

from .analyzer import create_analyzer, ScanResult
from .mqtt_publisher import MQTTPublisher

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@click.group()
@click.option("--debug", is_flag=True, help="Enable debug logging")
def main(debug: bool):
    """SCPI Spectrum Analyzer CLI for Spectrum Server."""
    if debug:
        logging.getLogger().setLevel(logging.DEBUG)


@main.command()
@click.option("--resource", "-r", required=True, help="VISA resource name (e.g., TCPIP::192.168.1.100::INSTR)")
@click.option("--type", "-t", "analyzer_type", default="generic", type=click.Choice(["tti", "owon", "generic"]))
def list_resources(resource: str, analyzer_type: str):
    """List available VISA resources."""
    import pyvisa
    rm = pyvisa.ResourceManager('@py')
    resources = rm.list_resources()

    if resources:
        click.echo("Available VISA resources:")
        for r in resources:
            click.echo(f"  {r}")
    else:
        click.echo("No VISA resources found.")


@main.command()
@click.option("--resource", "-r", required=True, help="VISA resource name")
@click.option("--type", "-t", "analyzer_type", default="generic", type=click.Choice(["tti", "owon", "generic"]))
@click.option("--start", "-s", required=True, type=float, help="Start frequency in MHz")
@click.option("--stop", "-e", required=True, type=float, help="Stop frequency in MHz")
@click.option("--rbw", type=float, help="Resolution bandwidth in kHz")
@click.option("--band", "-b", help="Band name (e.g., UHF)")
def scan(resource: str, analyzer_type: str, start: float, stop: float, rbw: float, band: str):
    """Perform a single scan and print results."""
    analyzer = create_analyzer(resource, analyzer_type)

    try:
        analyzer.connect()

        start_hz = start * 1e6
        stop_hz = stop * 1e6
        rbw_hz = rbw * 1e3 if rbw else None

        click.echo(f"Scanning {start:.1f} - {stop:.1f} MHz...")
        result = analyzer.scan(start_hz, stop_hz, rbw_hz, band)

        click.echo(f"Received {len(result.power)} points")
        click.echo(f"Min: {min(result.power):.1f} dBm, Max: {max(result.power):.1f} dBm")

    finally:
        analyzer.disconnect()


@main.command()
@click.option("--resource", "-r", required=True, help="VISA resource name")
@click.option("--type", "-t", "analyzer_type", default="generic", type=click.Choice(["tti", "owon", "generic"]))
@click.option("--start", "-s", required=True, type=float, help="Start frequency in MHz")
@click.option("--stop", "-e", required=True, type=float, help="Stop frequency in MHz")
@click.option("--rbw", type=float, help="Resolution bandwidth in kHz")
@click.option("--band", "-b", help="Band name")
@click.option("--interval", "-i", default=5.0, type=float, help="Scan interval in seconds")
@click.option("--mqtt-host", default="localhost", help="MQTT broker host")
@click.option("--mqtt-port", default=1883, type=int, help="MQTT broker port")
@click.option("--scanner-id", required=True, help="Unique scanner ID")
@click.option("--scanner-name", default="SCPI Scanner", help="Human-readable name")
@click.option("--location", default="", help="Scanner location")
def continuous(
    resource: str,
    analyzer_type: str,
    start: float,
    stop: float,
    rbw: float,
    band: str,
    interval: float,
    mqtt_host: str,
    mqtt_port: int,
    scanner_id: str,
    scanner_name: str,
    location: str,
):
    """Continuously scan and publish to MQTT."""
    analyzer = create_analyzer(resource, analyzer_type)
    publisher = MQTTPublisher(
        broker_host=mqtt_host,
        broker_port=mqtt_port,
        scanner_id=scanner_id,
        scanner_name=scanner_name,
        scanner_type=f"scpi-{analyzer_type}",
        location=location,
    )

    try:
        analyzer.connect()
        publisher.connect()

        # Wait for MQTT connection
        time.sleep(1)

        start_hz = start * 1e6
        stop_hz = stop * 1e6
        rbw_hz = rbw * 1e3 if rbw else None

        click.echo(f"Starting continuous scan: {start:.1f} - {stop:.1f} MHz")
        click.echo(f"Publishing to MQTT at {mqtt_host}:{mqtt_port}")
        click.echo("Press Ctrl+C to stop")

        publisher.set_scanning(True, band or "")

        while True:
            try:
                result = analyzer.scan(start_hz, stop_hz, rbw_hz, band)
                publisher.publish_scan(result)
                logger.info(f"Scan complete: {len(result.power)} points, max {max(result.power):.1f} dBm")
                time.sleep(interval)

            except KeyboardInterrupt:
                break
            except Exception as e:
                logger.error(f"Scan error: {e}")
                time.sleep(interval)

    finally:
        publisher.set_scanning(False)
        publisher.disconnect()
        analyzer.disconnect()
        click.echo("Stopped.")


@main.command()
@click.option("--resource", "-r", required=True, help="VISA resource name")
@click.option("--type", "-t", "analyzer_type", default="generic", type=click.Choice(["tti", "owon", "generic"]))
def identify(resource: str, analyzer_type: str):
    """Connect to analyzer and print identification."""
    analyzer = create_analyzer(resource, analyzer_type)

    try:
        analyzer.connect()
        click.echo("Successfully connected!")
    except Exception as e:
        click.echo(f"Connection failed: {e}", err=True)
        sys.exit(1)
    finally:
        analyzer.disconnect()


if __name__ == "__main__":
    main()
