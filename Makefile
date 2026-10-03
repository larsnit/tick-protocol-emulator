# Tick — top-level build / verification targets
REPO := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
export PYTHONPATH := $(REPO)/sw:$(REPO)/verification/model:$(PYTHONPATH)

.PHONY: help test test-model test-rtl test-gl formal synth clean

help:
	@echo "Targets:"
	@echo "  make test          ISS pytest + cocotb RTL"
	@echo "  make test-model    pytest verification/model"
	@echo "  make test-rtl      cocotb RTL (verification/rtl)"
	@echo "  make test-gl       gate-level cocotb (needs PDK_ROOT, netlist)"
	@echo "  make formal        SymbiYosys queue invariant"
	@echo "  make synth         Yosys synth; print cell count"
	@echo "  make clean         remove sim / formal / synth build products"

test: test-model test-rtl

test-model:
	cd $(REPO) && python3 -m pytest verification/model -q

test-rtl:
	cd $(REPO)/verification/rtl && $(MAKE)

test-gl:
	@test -n "$(PDK_ROOT)" || (echo "PDK_ROOT not set"; exit 1)
	cd $(REPO)/verification/rtl && $(MAKE) GATES=yes

formal:
	cd $(REPO)/verification/formal && sby -f tick.sby

synth:
	@mkdir -p $(REPO)/synth
	@yosys -p "read_verilog -sv $(REPO)/src/tick_core.sv $(REPO)/src/tt_um_larsnitschke_tick.sv; \
		hierarchy -top tt_um_larsnitschke_tick; proc; opt; \
		synth -top tt_um_larsnitschke_tick; \
		tee -o $(REPO)/synth/tick_yosys_stat.txt stat" \
		> $(REPO)/synth/tick_yosys.log 2>&1; \
	echo "--- cell count ---"; \
	grep -E 'Number of cells|Chip area' $(REPO)/synth/tick_yosys_stat.txt $(REPO)/synth/tick_yosys.log | head -20

clean:
	cd $(REPO)/verification/rtl && $(MAKE) clean || true
	rm -rf $(REPO)/verification/formal/tick_prove $(REPO)/verification/formal/tick
	rm -rf $(REPO)/synth
	find $(REPO) -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find $(REPO) -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
