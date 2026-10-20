"""Package-local adapter: only ZoneInfo.from_file is supported."""
def find_tzfile(key):
    raise RuntimeError("Use ZoneInfo.from_file with packaged data")
