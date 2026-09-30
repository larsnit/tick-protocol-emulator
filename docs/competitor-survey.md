# Competitor survey — Jane Street protocol-emulator ASIC

*Written 29 September 2026. One-page recon for Phase 0.*

## Entries surveyed

| Entry | Approach | Status (as of survey) | Differentiator vs ours |
|---|---|---|---|
| [Abagel-coder/protocol-emulator](https://github.com/Abagel-coder/protocol-emulator) | Time-triggered CPU; UART TX warm-up hardened on 6x4 (~252 cells). Spec mentions deadlines + line-coding pin engines + formal timing | Scaffold + UART TX | Closest to our tick/deadline model. We headline **target/impersonation** (SPI/I2C target, trap events, stretch policy) and first-class **MISS** semantics |
| [kdp1965/ihp-um-janestreet-prism](https://github.com/kdp1965/ihp-um-janestreet-prism) | PRISM programmable SM engine driven by TinyQV RISC-V SoC; CFGMEM latch macros; targeting 8x4 with custom PDN straps | Hardening path mature | Split control/timing (RISC-V + engine). Ours is a single tick ISA with no on-chip general CPU |
| Public UART-only warm-ups (various) | Fixed or lightly programmable TX | Early | Not programmable enough for the brief |

## What this changes

- Deadline/tick timing alone is **not** "most novel" — Abagel already frames a close variant.
- Keep the tick model (it is the right answer to PIO weakness #1/#2). Differentiate on:
  1. Target modes + qualified-edge traps (START/STOP, CS rise) as first-class hardware.
  2. Per-context miss policy (flag / trap / default / stretch) instead of PIO's silent stall.
  3. Verification depth: ISS-first, lockstep, SymbiYosys on the headline property.
- Do **not** reopen the ISA for a RISC-V companion unless area and schedule allow after Phase 2.

## Tile note

Competition post: set `tiles: "6x4"`. Stock template comment lists `*x2` only; Abagel reports successful local harden at 6x4. PRISM forks tools for 8x4 — we stay on 6x4 until an organiser email says otherwise.
