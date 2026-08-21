# Venus D Firmware Analysis — Modbus Read Path and Telemetry Structs

Findings from static analysis of `VNSD-0_app_0150_0805_115146.bin` (Venus D main
application v150, ARM Cortex-M, 389120 bytes, 1884 functions) and
`Micro_VNS_116_vd_inv_app_0116_0702_ota_163439.bin` (inverter MCU v116).

This document records what the firmware **proves** and, separately, what is still
only a candidate. The two are never mixed. `README.md` in this folder remains the
register map; this file is the evidence behind the parts of it that came from
firmware rather than from hardware probing.

---

## 1. Confirmed — the FC03 read path

`Modbus_Dispatcher` (`0x0801ea04`) → `FC03_Read_Handler` (`0x0801f06c`) →
`Read_Serializer` (`0x08050c14`). A second entry point, `RS485_FC03_ReadWrite_Handler`
(`0x0802a990`), shares the same serializer.

### Everything at 40000 and above is a write register

`FC03_Read_Handler` branches on the requested address:

```c
if (uVar7 < 40000) {
    /* descriptor table lookup -> Read_Serializer */
} else {
    /* delegate to Write_Handler(buf, reg, 0) in read-back mode */
}
```

There is no readable data block above 40000 — only write registers read back
through the write handler. **Any scan result that reports ASCII strings, SSIDs or
serial-number fragments in the 41500–41631 range is an artefact, not register
content.** The firmware descriptor tables name that range `schedule_time_XX` /
`schedule_power_XX`.

A plausible mechanism for such artefacts: a Modbus client whose read times out but
which does not flush its receive buffer leaves the late response queued under a
stale transaction id, shifting every subsequent response. The result looks like
plausible data at the wrong addresses.

### Descriptor table

246 entries, stride 12 bytes, base SRAM `0x20000354`.

| Offset | Size | Meaning |
|--------|------|---------|
| +0 | u16 | base register of this entry |
| +2 | u16 | (unused by the serializer) |
| +4 | u32 | SRAM pointer to the value |
| +8 | u8 | type code |
| +9 | u8 | element size (low nibble) |
| +10 | u8 | scale code |
| +11 | u8 | element count |

Type codes: `01` u8 · `02` u16 · `04` u32 · `11` i8 · `12` i16 · `14` i32 ·
`24` float (IEEE754) · `31` ASCII (memcpy).

Scale codes, integer path: `0` ×1 · `1` ×10 · `2` ×100 · `3` ÷10 · `4` ÷100 ·
`5` negate. Float path: `0` ×1 · `1` ×10 · `2` ×100 · `3` ×0.1 · `4` ×0.01.

Addressing within an entry:

```
byte offset into the target = (requested register - entry base register) * 2
```

### Register-level confirmations

| Register | Field | How confirmed |
|----------|-------|---------------|
| 37023 | `Mppt_Error` | MPPT array index [1] = byte +0x02; matches the "Inverter struct +0x02" note in `README.md` |
| 37024 | `Mppt_Warning` | MPPT array index [3] = byte +0x06; matches "+0x06" |

These two cross-checks also settle a naming question: the structure referred to as
the "Inverter struct" in `README.md` is the **MPPT array** of section 3, not the
inverter telemetry block of section 2.

---

## 2. Confirmed — inverter telemetry struct

From `Inverter_Telemetry_Debug_Print` (`0x08036bd4`), which prints all 20 fields
with plaintext names. Base SRAM `0x20014E9C`, 48 bytes.

| Offset | Field | Type | Scale |
|--------|-------|------|-------|
| +0x00 | `inv_state` | u8 | — |
| +0x01 | `buz_state` | u8 | — |
| +0x02 | `chrg_flag` | u8 | — |
| +0x03 | `back_func` | u8 | — |
| +0x04 | `warn_code` | u32 | bitfield |
| +0x08 | `error_code1` | u32 | bitfield |
| +0x0C | `error_code2` | u32 | bitfield |
| +0x10 | `grid_volt` | u16 | 0.1 V |
| +0x12 | `grid_pf` | u16 | 0.1 Hz — grid *frequency* despite the name |
| +0x14 | `off_grid_volt` | u16 | 0.1 V |
| +0x16 | `grid_permit` | u16 | — |
| +0x18 | `grid_sample_power` | i16 | 1 W |
| +0x1A | `off_grid_power` | i16 | 1 W |
| +0x1C | `bat_sample_power` | i16 | 1 W |
| +0x1E | `bat_sample_volt` | i16 | 0.1 V |
| +0x20 | `env_temp` | i16 | 0.1 °C |
| +0x22 | `radiator_temp` | i16 | 0.1 °C |
| +0x24 | `max_power` | i16 | — |
| +0x26 | `min_power` | i16 | — |
| +0x28 | `chrg_enery` | u32 | 1 Wh |
| +0x2C | `dischrg_enery` | u32 | 1 Wh |

Two adjacent blocks are printed by the same function:

- `0x2000015C`: `hard_ver`, `soft_ver`, `boot_ver`, `dev_state`
- `0x20000144`: `work_mode`, `sleep_flag`, one unnamed field

### Bearing on the 30005 / 30007 question

The struct contains **exactly one** `off_grid_volt` and **exactly one**
`off_grid_power`. That is evidence that 30005/32300 and 30007/32302 are two
register addresses onto the same measurement, i.e. the Venus E Gen 3 notes are
right and these are duplicates rather than a separate backup measurement point.
Not conclusive on its own — two descriptor entries can point at one field — but it
shifts the balance. The hardware comparison described in `README.md` still decides.

---

## 3. Confirmed — MPPT array

From `MPPT_Debug_Print` (`0x08036884`). Addressed as a u16 array; byte offset is
`index * 2`.

| Index | Byte | Field | Type | Scale |
|-------|------|-------|------|-------|
| [0] | +0x00 | `Mppt_State` | u16 | — |
| [1] | +0x02 | `Mppt_Error` | u16 | — |
| [2] | +0x04 | `Mppt_Temp` | i16 | 0.1 °C |
| [3] | +0x06 | `Mppt_Warning` | u16 | — |
| [4][5][6] | +0x08 | `PV1_Vol` / `PV1_Cur` / `PV1_Power` | u16 | 0.1 V / 0.1 A / — |
| [7][8][9] | +0x0E | `PV2_Vol` / `PV2_Cur` / `PV2_Power` | u16 | " |
| [10][11][12] | +0x14 | `PV3_Vol` / `PV3_Cur` / `PV3_Power` | u16 | " |
| [13][14][15] | +0x1A | `PV4_Vol` / `PV4_Cur` / `PV4_Power` | u16 | " |
| [16-17] | +0x20 | `PV_Day_Cap` | u32 | 10 Wh |
| — | +0x24 | `PV_err` | u8 | — |
| — | +0x25 | `PV_state` | u8 | — |
| [19] | +0x26 | `cmd_power` | u16 | 0.1 W |
| [20-21] | +0x28 | `PV_Mon_Cap` | u32 | 10 Wh |
| [22-23] | +0x2C | `PV_Year_Cap` | u32 | 10 Wh |
| [24] | +0x30 | `bat_vol` | i16 | 0.1 V |
| [25] | +0x32 | `bat_cur` | i16 | 0.1 A |
| [26] | +0x34 | `base_vol` | i16 | 0.01 V |
| [27] | +0x36 | `pe_vol` | i16 | 0.01 V |

---

## 4. Candidates for the still-unmapped registers

These registers appear in hardware scans but have no confirmed meaning:

```
30036  30212  32106  32107  32201  35111  35112
37000  37001  37009  37010  37011  37013  37014  37015  37021  37022
45603  45604  45605  47400
```

The 37xxx group must draw from the fields in sections 2 and 3 that carry no known
register yet. Listed by how useful they would be as entities:

**Would add genuinely new data**

| Field | Type | Scale | Would become |
|-------|------|-------|--------------|
| `PV_Day_Cap` | u32 | 10 Wh | daily PV yield — expose with `scale: 0.01` as kWh, `device_class: energy`, `state_class: total_increasing` |
| `PV_Mon_Cap` | u32 | 10 Wh | monthly PV yield, same treatment |
| `PV_Year_Cap` | u32 | 10 Wh | yearly PV yield, same treatment |
| `Mppt_Temp` | i16 | 0.1 °C | MPPT temperature |
| `Mppt_State` | u16 | — | MPPT state |
| `env_temp` / `radiator_temp` | i16 | 0.1 °C | inverter ambient / heatsink temperature |
| `chrg_enery` / `dischrg_enery` | u32 | 1 Wh | inverter-side energy counters |
| `warn_code` / `error_code1` / `error_code2` | u32 | bitfield | fault detail beyond the existing `fault_status` |

`total_increasing` is the correct state class for the PV counters: it tolerates the
reset at each day and month boundary. One count unit is 10 Wh = 0.01 kWh, so
`scale: 0.01` yields kWh directly. The u32 range covers roughly 43 GWh.

**Likely duplicates of already-integrated sensors**

`bat_vol`, `bat_cur`, `bat_sample_volt`, `bat_sample_power`, `grid_volt`,
`grid_pf`, `grid_sample_power`, `off_grid_volt`, `off_grid_power`,
`PV1..4_Vol/Cur/Power`.

**Unclear purpose**

`inv_state`, `buz_state`, `chrg_flag`, `back_func`, `grid_permit`, `max_power`,
`min_power`, `PV_err`, `PV_state`, `cmd_power`, `base_vol`, `pe_vol`.

Nothing here may be added to the YAML register files until a register number is
actually confirmed. A field list is not a mapping.

---

## 5. Resolved — the descriptor table is decodable

The blocker described in earlier revisions of this document is gone. The table is a
plain `.data` global; the `.data` image is **LZ77-compressed at the end of flash** and
unpacked by the C runtime at boot. That single fact explains every negative finding
listed below, and the table has since been decoded in full — 246 of 246 entries for
both v149.2 and v150 — by the companion firmware-debug project.

Dead ends recorded so they are not repeated:

- **Scanned the full 389120-byte image** for the 12-byte stride pattern with an SRAM
  pointer at +4, at every 4-byte position. Nothing — because the table is compressed.
- **Searched for literals** pointing at `0x20000354`. Exactly two exist, at
  `0x0801F1F8` and `0x0802AAE8`, the literal pools of the two FC03 handlers. Correct,
  and not a gap: there is no builder routine, only readers.
- `RS485_Modbus_RegisterMap_Init` (`0x0802a720`) is unrelated — the eight-entry map of
  the RS485 sub-protocol.
- **Followed the reset vector** at `0x08000004` to `0x08004A71`, which lands in the tail
  of `FUN_080049f4` rather than on a function entry. None of the 42 vector entries
  resolves to a function entry, and no uniform shift fixes it. This is real and expected:
  in this OTA image the vector table does not reach the C startup path at all.

### The load base is confirmed correct

The vector-table anomaly does not indicate a wrong load base. A strict scan of the whole
image finds exactly one Cortex-M vector table, at file offset 0, with reserved slots
7–10 and 13 zero as the architecture requires. More decisively, absolute addresses from
literal pools resolve to exactly the data the surrounding code uses:

| Literal | Resolves to |
|---------|-------------|
| `0x08036D7C` | `"grid_volt(0.1V)=%d\r\n"` |
| `0x080369A4` | `"PV1_Vol(0.1V)=%d\|Cur(0.1A)=%d\|Pow(0.1W)="` |
| `0x08036A98` | `"PV_Day_Cap_10Wh=%d\r\n"` |
| `0x08036EB0` | `"dischrg_enery(1Wh)=%d\r\n"` |

Absolute pointers could not resolve like this under a wrong base. The image is correctly
loaded at `0x08000000` and every address in this document is valid as written.

## 6. Cross-check against the decoded table

The struct layouts in sections 2 and 3 were derived from the debug printers alone, with
no access to the descriptor table. Checking them afterwards against the decoded table:
**all 48 descriptor pointers that fall inside either struct land on a named field.** Both
base addresses are confirmed — inverter telemetry at `0x20014E9C`, MPPT array at
`0x20014F4C`, the latter derived from `PV1_Power` at `0x20014F58` minus its `+0x0C`
offset.

Two corrections to section 4 follow from the decoded table:

- `PV_Year_Cap` **is** reachable, at register **37021** (u32, 10 Wh). `PV_Day_Cap` and
  `PV_Mon_Cap` have no descriptor entry and are therefore *not* readable over Modbus.
  Only the yearly counter can become a kWh sensor.
- `base_vol` is register **30036**, one of the previously open addresses.

### Registers that share one firmware source

Several pairs in the register YAML resolve to the same SRAM pointer, i.e. they are the
same measurement under two names. Confirmed from the descriptor table:

| Source | Registers | Firmware field |
|--------|-----------|----------------|
| `0x20014EB0` | 30005 · 32300 · 32301 | `off_grid_volt` — 32301 is **not** an off-grid current |
| `0x20014EB4` | 30006 · 32202 · 37004 | `grid_sample_power` — 37004 is **not** an AC current |
| `0x20014EB6` | 30007 · 32302 | `off_grid_power` |
| `0x20014EBE` | 35001 · 35002 | `radiator_temp` — MOS1 and MOS2 are one sensor |
| `0x20014FC4` | 34005 · 37007 | pack 1 max cell voltage — the "device-wide" max is pack 1's |
| `0x20014FC6` | 34006 · 37008 | pack 1 min cell voltage |
| `0x20014FD2` | 30204 · 34010 | pack 1 BMS version |
