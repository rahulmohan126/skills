def format_duration(seconds: int) -> str:
    """Format a number of seconds as e.g. '1h30m', '45s', '2h'."""
    if seconds < 0:
        raise ValueError("seconds must be non-negative")
    if seconds == 0:
        return "0s"
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    out = ""
    if h:
        out += f"{h}h"
    if m:
        out += f"{m}m"
    if s:
        out += f"{s}s"
    return out
