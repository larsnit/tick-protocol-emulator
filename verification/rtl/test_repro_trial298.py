from __future__ import annotations
import sys
from pathlib import Path
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "sw"))
from tick import EventKind, Machine, MissPolicy, PinMode, TickSource
from tick.cfg import dict_to_bytes
from rtl_bus import load_cfg_bytes, load_program, push_host, reset_dut
ALIGN=1
IMG=[int(x,16) for x in ["0x3d04","0x3e08","0x3f0c","0x7000","0x3b18","0x4000","0x3c20","0x4000","0x7000","0x3b2c","0x3c30","0x7200","0x3e38","0x4000","0x3d40","0x4001","0x2200","0x3d44","0x2020","0x3040","0x3040","0x3544","0x3054","0x480","0xa200","0x8d00","0x7c00","0x7400","0x3c50","0x9340","0x56e0","0x5420","0x3344","0x1600","0x5aa0","0x5420","0x3260","0x7600","0x2020","0x309c"]]
CFG={"per":4.0,"phase":0,"msb_first":True,"clk_en":False,"cpol":False,"cpha":True,"dout_lp":1,"din_lp":3,"clk_lp":0,"tick_source":TickSource.TIMER,"default_byte":151,"miss_policy":MissPolicy.SEND_DEFAULT,"miss_vector":29,
"pins":[{"physical":0,"mode":PinMode.OPENDRAIN,"idle":1,"glitch_filter":True},{"physical":7,"mode":PinMode.PUSHPULL,"idle":1,"glitch_filter":False},{"physical":3,"mode":PinMode.OPENDRAIN,"idle":1,"glitch_filter":True},{"physical":4,"mode":PinMode.PUSHPULL,"idle":1,"glitch_filter":False}],
"events":[{"kind":EventKind.QUAL_RISE_WHILE_HIGH,"pin":0,"qual_pin":1,"latched":False,"trap":True,"vector":19},{"kind":EventKind.EDGE_FALL,"pin":0,"qual_pin":3,"latched":True,"trap":False,"vector":30},{"kind":EventKind.LEVEL_HIGH,"pin":2,"qual_pin":2,"trap":False,"vector":18},{"kind":EventKind.QUAL_FALL_WHILE_HIGH,"pin":0,"qual_pin":0,"latched":False,"trap":False,"vector":32}]}
HOST=[0x3cc,0x8a]
EXT=[55,14,117,41,113,62,71,19,181,124,5,191,123,33,101,127,36,101]

@cocotb.test()
async def t(dut):
    cocotb.start_soon(Clock(dut.clk, 20, unit="ns").start())
    m=Machine(); m.phys_ext=[(EXT[0]>>p)&1 for p in range(8)]; m.load(IMG,[CFG])
    for hw in HOST: m.host_push(hw&0xFF, last=bool(hw&0x100), cmd=bool(hw&0x200))
    iss=[]
    for cy in range(25):
        m.phys_ext=[(EXT[min(cy,len(EXT)-1)]>>p)&1 for p in range(8)]; m.step()
        out=oe=0
        for p in range(8):
            if m.phys_oe[p]: oe|=1<<p; out|=(m.phys_drive[p]&1)<<p
        iss.append((out,oe,m.ctx[0].pc,m.ctx[0].drive_val,m.ctx[0].miss,m.ctx[0].timed_active is not None))
    await reset_dut(dut)
    await load_cfg_bytes(dut, dict_to_bytes(0,CFG,enable_mask=None))
    await load_cfg_bytes(dut,{0x00:0x01})
    await load_program(dut,IMG)
    for hw in HOST: await push_host(dut, hw&0xFF, last=bool(hw&0x100), cmd=bool(hw&0x200))
    dut.ui_in.value=1<<3
    core=dut.user_project.core
    for cy in range(25+ALIGN):
        dut.uio_in.value=EXT[min(cy,len(EXT)-1)]
        await RisingEdge(dut.clk)
        if cy<ALIGN: continue
        i=cy-ALIGN
        io,ie,ipc,dv,miss,tact=iss[i]
        ro=int(dut.uio_out.value)&0xFF; re=int(dut.uio_oe.value)&0xFF; rpc=int(core.dbg_pc.value)
        ak=int(core.dbg_a_kind.value); tick=int(core.dbg_tick.value); trun=int(core.dbg_timer_run.value)
        if i>=10 or ie!=re or (io&ie)!=(ro&re) or ipc!=rpc:
            dut._log.info(f"cy={i} ISS=({io:02x},{ie:02x}) pc={ipc} dv={dv:x} miss={miss} tact={tact} RTL=({ro:02x},{re:02x}) pc={rpc} a={ak} tick={tick} trun={trun}")
        if ie!=re or (io&ie)!=(ro&re) or ipc!=rpc:
            assert False, f"cy={i}"
