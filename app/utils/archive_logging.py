import json
from datetime import datetime, timezone

def log_archive_debug(message, data=None):
    """Write debug message and optional data to archive_debug.log"""
    timestamp = datetime.now(timezone.utc).isoformat()
    with open('archive_debug.log', 'a') as f:
        f.write(f"\n[{timestamp}] {message}\n")
        if data:
            if isinstance(data, (dict, list)):
                f.write(json.dumps(data, indent=2))
            else:
                f.write(str(data))
            f.write("\n") 