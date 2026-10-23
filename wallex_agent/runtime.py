"""Local process exclusion and conservative observation/clock checks."""
import fcntl
import math
from pathlib import Path
from email.utils import parsedate_to_datetime


class ProcessLock:
    """Kernel lock on persistent state; stale files do not prevent restart.

    Excludes processes sharing the same volume. Does not fence multiple hosts.
    """
    def __init__(self, path):
        self.path = Path(path)
        self.handle = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open('a+')
        try:
            fcntl.flock(self.handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.handle.close()
            self.handle = None
            raise PermissionError('another process holds this state lock') from None
        return self

    def __exit__(self, *args):
        if self.handle:
            fcntl.flock(self.handle, fcntl.LOCK_UN)
            self.handle.close()
            self.handle = None


def clock_observation(server_date, sent, received, max_skew=5, max_rtt=5):
    """HTTP Date is a sanity check, not an NTP synchronization guarantee."""
    if not all(math.isfinite(v) for v in (sent, received)) or received < sent:
        raise ValueError('invalid clock observation')
    try:
        server = parsedate_to_datetime(server_date)
        if server.tzinfo is None:
            raise ValueError('naive server date')
        offset = server.timestamp()-(sent+received)/2
    except (ValueError, TypeError, AttributeError, OverflowError):
        return {'accepted': False, 'reason': 'missing/invalid server Date'}
    rtt = received-sent
    return {'accepted': abs(offset)+rtt/2+1 <= max_skew and rtt <= max_rtt,
            'estimated_offset_seconds': offset, 'rtt_seconds': rtt,
            'uncertainty_seconds': rtt/2+1, 'ntp_synchronized': False}


def depth_capacity(levels, reference, max_impact_bps, participation=.01):
    """Conservative fraction of visible size inside a bounded execution band."""
    if not 0 < participation <= 1 or not 0 < reference or not 0 <= max_impact_bps <= 1000:
        raise ValueError('invalid depth limits')
    capacity = 0
    for row in levels:
        price, quantity = float(row['price']), float(row['quantity'])
        if not all(math.isfinite(v) for v in (price, quantity)) or price <= 0 or quantity < 0:
            raise ValueError('invalid depth level')
        if abs(price/reference-1)*10000 <= max_impact_bps+1e-8:
            capacity += quantity*participation
    return capacity
