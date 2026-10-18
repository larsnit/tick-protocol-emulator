"""MISS send-default LSB-first OD must match ISS pin OE."""
import sys
from pathlib import Path
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/"sw"))
from tick import Machine, MissPolicy, PinMode, assemble
from tick.cfg import dict_to_bytes
from tick.host_link import HostLink
from lockstep_harness import start_run, rtl_pads


@cocotb.test()
async def miss_send_default_lsb_od_lockstep(dut):
    cocotb.start_soon(Clock(dut.clk, 20, unit="ns").start())
    img = assemble("SET.T lp0=1\nhang: JMP AL, hang\n")
    cfg = {
        "per": 4.0, "msb_first": False, "dout_lp": 0, "clk_lp": 2,
        "miss_policy": MissPolicy.SEND_DEFAULT, "default_byte": 0xCB,
        "pins": [
            {"physical": 0, "mode": PinMode.OPENDRAIN, "idle": 1},
            {"physical": 1, "mode": PinMode.INPUT, "idle": 1},
            {"physical": 2, "mode": PinMode.OPENDRAIN, "idle": 1},
            {"physical": 3, "mode": PinMode.INPUT, "idle": 1},
        ],
    }
    n=40
    m=Machine(); m.load(img,[cfg])
    iss=[]
    for _ in range(n):
        m.step()
        out=oe=0
        for p in range(8):
            if m.phys_oe[p]:
                oe|=1<<p; out|=(m.phys_drive[p]&1)<<p
        iss.append((out,oe))
    host = HostLink(dut)
    await host.reset()
    await host.cfg_write_map(dict_to_bytes(0,cfg,enable_mask=None))
    await host.cfg_write_map({0x00:0x01})
    await host.load_program(img)
    dut.uio_in.value = 0xFF
    await start_run(host, dut)
    rtl=[]
    for cy in range(n):
        dut.uio_in.value=0xFF
        await RisingEdge(dut.clk)
        rtl.append((int(dut.uio_out.value)&0xFF, int(dut.uio_oe.value)&0xFF))
    for i in range(n):
        io,ie=iss[i]; ro,re=rtl[i]
        assert ie==re and (io&ie)==(ro&re), f"cy={i} ISS=({io:#04x},{ie:#04x}) RTL=({ro:#04x},{re:#04x})"
