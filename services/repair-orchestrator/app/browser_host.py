"""Trusted Linux browser exec: cap each output file before any helper starts.

The caller supplies a verified cgroup and a quota-limited private tmpfs. This
per-file backstop also covers Playwright's temporary trace resources and archive.
"""

import os
import resource
import sys

TRACE_FILE_LIMIT = 25 * 1024 * 1024


def main() -> None:
    resource.setrlimit(resource.RLIMIT_FSIZE, (TRACE_FILE_LIMIT, TRACE_FILE_LIMIT))
    os.execv(sys.argv[1], sys.argv[1:])


if __name__ == "__main__":
    main()
