# Makefile
# See https://docs.cocotb.org/en/stable/quickstart.html for more info

# defaults
SIM ?= icarus
FST ?= -fst # Use more efficient FST format
TOPLEVEL_LANG ?= verilog
THIS_DIR := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))
SRC_DIR = $(THIS_DIR)../../src
PROJECT_SOURCES = host_fifo.sv tick_imem.sv tick_cfg.sv tick_timer.sv tick_events.sv tick_queue.sv tick_issue.sv tick_core.sv host_spi.sv tt_um_larsnitschke_tick.sv

ifneq ($(GATES),yes)

# RTL simulation:
SIM_BUILD				= sim_build/rtl
VERILOG_SOURCES += $(addprefix $(SRC_DIR)/,$(PROJECT_SOURCES))

else

# Gate level simulation:
SIM_BUILD				= sim_build/gl
COMPILE_ARGS    += -DGL_TEST
COMPILE_ARGS    += -DFUNCTIONAL
COMPILE_ARGS    += -DSIM
VERILOG_SOURCES += $(PDK_ROOT)/ihp-sg13cmos5l/libs.ref/sg13cmos5l_io/verilog/sg13cmos5l_io.v
VERILOG_SOURCES += $(PDK_ROOT)/ihp-sg13cmos5l/libs.ref/sg13cmos5l_stdcell/verilog/sg13cmos5l_stdcell.v
VERILOG_SOURCES += $(PDK_ROOT)/ihp-sg13cmos5l/libs.ref/sg13cmos5l_stdcell/verilog/sg13cmos5l_udp.v

# this gets copied in by the GDS action workflow
VERILOG_SOURCES += $(THIS_DIR)gate_level_netlist.v

endif

# Allow sharing configuration between design and testbench via `include`:
COMPILE_ARGS 		+= -I$(SRC_DIR)

# Include the testbench sources:
VERILOG_SOURCES += $(THIS_DIR)tb.v
TOPLEVEL = tb

# Same list for RTL and gate-level (tt-gds-action gl_test uses this dir).
# Pin-only modules (safe at GL): test_uart_tx, test_stage2a, test_uart_tx_pin3, …
COCOTB_TEST_MODULES = test_host_link,test_uart_tx,test_queue_order,test_lockstep,test_wait_tick_timer,test_iss_rtl_fuzz,test_stage2a,test_stage2b,test_cmd_dispatch,test_uart_tx_pin3,test_repro_mts_ecfg_clk_en,test_repro_trial1,test_repro_trial177,test_rtl_events_traps_miss,test_uart_rx,test_idle_drive_before_run_no_false_edge,test_miss_send_default_lsb,test_pin_input_latency,test_repro_trap_stretch_oe,test_repro_trial24_oe,test_repro_set_e_after_miss_od,test_repro_host_trap_on_run_rise,test_repro_pin_trap_suppress_run_rise,test_repro_trap_sett_timer_restart,test_repro_trial83,test_repro_no_phantom_qual_after_run_rise,test_repro_sett_e_clears_oe,test_repro_sett_e_timed_clears_oe,test_repro_mfs_pc_on_miss_trap,test_spi_i2c_milestones,test_i2c_target_read_data_byte_nack_stop,test_repro_trial475_pin7_oe,test_wait_stop_then_timed_rearms_timer,test_stalled_sett_does_not_arm_timer,test_spi_target_miso_timing

# Assembler / ISS live in sw/tick
export PYTHONPATH := $(THIS_DIR)../../sw:$(PYTHONPATH)

# Prefer project venv cocotb (CI and local).
REPO_ROOT := $(THIS_DIR)../..
COCOTB_CONFIG := $(shell \
	if [ -x "$(REPO_ROOT)/.venv/bin/cocotb-config" ]; then \
		echo "$(REPO_ROOT)/.venv/bin/cocotb-config"; \
	else echo cocotb-config; fi)

# include cocotb's make rules to take care of the simulator setup
include $(shell $(COCOTB_CONFIG) --makefiles)/Makefile.sim
