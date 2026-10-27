"""Pytest configuration for zebra-ioc tests."""


def pytest_addoption(parser):
    """Add command line options for testing."""
    parser.addoption(
        "--port",
        action="store",
        default=None,
        help="Zebra serial port (e.g., /dev/ttyUSB0 or /tmp/vserial0)",
    )
