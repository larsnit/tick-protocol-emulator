# Tick — top-level build / verification targets
REPO := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
export PYTHONPATH := $(REPO)/sw:$(REPO)/verification/model:$(PYTHONPATH)
# Prefer project venv when present (CI / local).
PYTHON ?= $(shell if [ -x "$(REPO)/.venv/bin/python" ]; then echo "$(REPO)/.venv/bin/python"; else echo python3; fi)

# Must match info.yaml project.source_files (order preserved).
SRC_SV := \
	$(REPO)/src/host_fifo.sv \
	$(REPO)/src/tick_imem.sv \
	$(REPO)/src/tick_cfg.sv \
	$(REPO)/src/tick_timer.sv \
	$(REPO)/src/tick_queue.sv \
	$(REPO)/src/tick_issue.sv \
	$(REPO)/src/tick_core.sv \
	$(REPO)/src/tt_um_larsnitschke_tick.sv

.PHONY: help test test-model test-rtl test-gl formal synth lint clean

help:
	@echo "Targets:"
	@echo "  make test          lint + ISS pytest + cocotb RTL"
	@echo "  make lint          Yosys check -assert + verilator -Wall (pre-flatten)"
	@echo "  make test-model    pytest verification/model"
	@echo "  make test-rtl      cocotb RTL (verification/rtl)"
	@echo "  make test-gl       gate-level cocotb (needs PDK_ROOT, netlist)"
	@echo "  make formal        SymbiYosys queue invariant"
	@echo "  make synth         Yosys synth; print cell count"
	@echo "  make clean         remove sim / formal / synth build products"

test: lint test-model test-rtl

# LibreLane-style pre-flatten check on every info.yaml source file.
lint:
	@echo "=== yosys check -assert (before flatten) ==="
	@yosys -p "read_verilog -sv $(SRC_SV); \
		hierarchy -check -top tt_um_larsnitschke_tick; \
		proc; check -assert"
	@echo "=== verilator --lint-only -Wall ==="
	@verilator --lint-only -Wall -Wno-DECLFILENAME \
		--top-module tt_um_larsnitschke_tick \
		$(SRC_SV)

test-model:
	cd $(REPO) && $(PYTHON) -m pytest verification/model -q

test-rtl:
	cd $(REPO)/verification/rtl && PATH="$(REPO)/.venv/bin:$$PATH" $(MAKE)

test-gl:
	@test -n "$(PDK_ROOT)" || (echo "PDK_ROOT not set"; exit 1)
	cd $(REPO)/verification/rtl && $(MAKE) GATES=yes

formal:
	cd $(REPO)/verification/formal && sby -f tick.sby

synth:
	@mkdir -p $(REPO)/synth
	@yosys -p "read_verilog -sv $(SRC_SV); \
		hierarchy -top tt_um_larsnitschke_tick; proc; opt; \
		synth -top tt_um_larsnitschke_tick; \
		tee -o $(REPO)/synth/tick_yosys_stat.txt stat" \
		> $(REPO)/synth/tick_yosys.log 2>&1; \
	echo "--- cell count ---"; \
	grep -E 'Number of cells|Chip area|^[[:space:]]+[0-9]+ cells$$' $(REPO)/synth/tick_yosys_stat.txt | head -20

clean:
	cd $(REPO)/verification/rtl && $(MAKE) clean || true
	rm -rf $(REPO)/verification/formal/tick_prove $(REPO)/verification/formal/tick
	rm -rf $(REPO)/synth
	find $(REPO) -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find $(REPO) -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
