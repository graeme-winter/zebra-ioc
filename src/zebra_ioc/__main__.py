"""Command line entry point for the Zebra soft IOC."""

import argparse
import asyncio
import logging
import sys
import threading

from softioc import asyncio_dispatcher, builder, softioc

from .device import DEFAULT_CAPTURE_POINTS, ZebraDevice
from .ioc import ZebraIOC

logger = logging.getLogger(__name__)


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="zebra-ioc",
        description="EPICS soft IOC for the Quantum Detectors Zebra",
        epilog=(
            "Examples:\n"
            "  zebra-ioc --port /dev/ttyUSB0 --prefix NECAT:ZEBRA1:\n"
            "  zebra-ioc --port tcp://172.23.241.3:7012 --prefix NECAT:ZEBRA1:\n"
            "  zebra-ioc --port sim://zebra01 --prefix TEST:ZEBRA:\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--port",
        required=True,
        help=(
            "Zebra connection: serial device (/dev/ttyUSB0, COM3), "
            "TCP endpoint (tcp://host:port or host:port), "
            "or simulator (sim://name)"
        ),
    )
    parser.add_argument(
        "--prefix",
        default="ZEBRA:",
        help=(
            "EPICS PV prefix, used verbatim. Include the trailing separator "
            "(default: ZEBRA:)"
        ),
    )
    parser.add_argument(
        "--capture-points",
        type=int,
        default=DEFAULT_CAPTURE_POINTS,
        help=(
            "Capacity of each position compare capture array. Large values "
            "need EPICS_CA_MAX_ARRAY_BYTES raised to match "
            f"(default: {DEFAULT_CAPTURE_POINTS})"
        ),
    )
    parser.add_argument(
        "--poll-period",
        type=float,
        default=0.3,
        help="Seconds between system bus status polls (default: 0.3)",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level (default: INFO)",
    )
    parser.add_argument(
        "--no-interactive",
        action="store_true",
        help=(
            "Run without the interactive console. Use when the IOC is "
            "supervised by systemd or a container rather than procServ"
        ),
    )
    parser.add_argument(
        "--list-pvs",
        action="store_true",
        help="Print the PV names that would be created, then exit",
    )
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )

    dispatcher = asyncio_dispatcher.AsyncioDispatcher()

    builder.SetDeviceName(args.prefix.rstrip(":"))
    device = ZebraDevice(
        args.port,
        capture_points=args.capture_points,
        poll_period=args.poll_period,
    )
    ioc = ZebraIOC(device)

    if args.list_pvs:
        for name in sorted(ioc.record_names()):
            print(name)
        return 0

    builder.LoadDatabase()
    softioc.iocInit(dispatcher)

    async def startup():
        try:
            await ioc.start()
        except Exception:
            logger.exception("Failed to connect to the Zebra")
            ioc.status_msg.set("Connection failed")

    dispatcher(startup)

    if args.no_interactive:
        # AsyncioDispatcher already runs the loop in its own thread, so the
        # main thread just has to stay alive and out of the way
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            pass
    else:
        softioc.interactive_ioc(globals())
    return 0


if __name__ == "__main__":
    sys.exit(main())
