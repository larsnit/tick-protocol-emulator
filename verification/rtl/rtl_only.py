"""Gate-level skip helper.

Tests that probe ``dut.user_project.core`` (or other flattened hierarchy) cannot
run when ``GATES=yes``. Prefer rewriting to pins + HostLink; otherwise decorate
with ``@cocotb.test(skip=RTL_ONLY)``.
"""

from __future__ import annotations

import os

RTL_ONLY = os.environ.get("GATES") == "yes"
