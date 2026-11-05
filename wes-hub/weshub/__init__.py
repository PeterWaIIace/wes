"""wes-hub: scheduling server and Actions-like web UI for WES."""

from weshub.config import Settings
from weshub.manager import Hub, HubError

__all__ = ["Hub", "HubError", "Settings", "__version__"]
__version__ = "0.1.0"
