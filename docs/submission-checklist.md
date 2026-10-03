# Submission checklist (target 11 January 2027)

- [x] `info.yaml` tiles `6x4`, top `tt_um_larsnitschke_tick`, SystemVerilog sources listed
- [x] ISA frozen in `docs/isa.md` with golden model
- [x] UART TX ISS-tested and cocotb RTL checked
- [x] Yosys synth cell count recorded
- [x] SymbiYosys queue-invariant PASS; timing properties ISS-tested for now
- [ ] Second context + host SPI shim
- [ ] Local LibreLane harden (`tt_tool --harden`) + slow-corner STA
- [ ] Tiny Tapeout precheck clean
- [ ] `docs/info.md` polish for shuttle datasheet
- [ ] Final verification report signed off
- [ ] Submit via Tiny Tapeout / Jane Street process before 18 January 2027

Pinout and bring-up: see `docs/info.md`.
