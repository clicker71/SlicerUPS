"""SlicerUPS core package - CLI-first, UI-agnostic UPS-RS client."""

from .catalog import Catalog, Procedure
from .client import UPSClient
from .dicomweb import DicomwebClient, DicomwebError
from .models import (
    Code,
    Workitem,
    WorkitemEvent,
    WorkitemParameter,
    TERMINAL_STATES,
)
from .parameters import encode_parameters, decode_parameters
from .watcher import Watcher, Subscription, parse_event

__version__ = "0.1.0"

__all__ = [
    "UPSClient",
    "DicomwebClient",
    "DicomwebError",
    "Catalog",
    "Procedure",
    "Code",
    "Workitem",
    "WorkitemEvent",
    "WorkitemParameter",
    "Watcher",
    "Subscription",
    "parse_event",
    "encode_parameters",
    "decode_parameters",
    "TERMINAL_STATES",
    "__version__",
]
