# Register Research Notes

This document captures findings from register scanning and testing across Marstek device models.
Registers documented here were investigated but not included in the integration (no added value,
unclear semantics, or duplicate/inferior alternatives exist).

Add a section per model following the structure below.

---

## Venus E Gen 3.0 (e_v3.yaml)

Hardware tested: Marstek Venus E v3, firmware V148.

| Register | Notes |
|----------|-------|
| 30000 | Alternative for `battery_voltage` (32100). scale 0.1 V, uint16. Less precise. |
| 30002 | Alternative for `internal_temperature` (35000). scale 0.1 °C, int16. Duplicate. |
| 30003 | Alternative for `internal_mos1_temperature` (35001). scale 0.1 °C, int16. Duplicate. |
| 30004 | Alternative for `inverter_voltage` (32200). scale 0.1 V, uint16. Duplicate. |
| 30005 | Alternative for `ac_offgrid_voltage` (32300). scale 0.1 V, uint16. Duplicate. |
| 30007 | Alternative for `ac_offgrid_power` (32302). scale 1 W, int16. Duplicate. |
| 30100 | Alternative for `battery_voltage` (32100). scale 0.01 V, uint16. Inferior. |
| 30102 | Alternative for `max_cell_voltage` (37007). scale 0.001 V. Inferior. |
| 30103 | Alternative for `min_cell_voltage` (37008). scale 0.001 V. Inferior. |
| 30104 | Alternative for `max_cell_temperature` (35010). scale 0.01 °C, uint16. Inferior. |
| 30105 | Alternative for `min_cell_temperature` (35011). scale 0.01 °C, uint16. Inferior. |
| 30107 | Alternative for `bms_temperature_1` (34011). scale 0.1 °C, int16. Duplicate. |
| 30108 | Alternative for `bms_temperature_2` (34012). scale 0.1 °C, int16. Duplicate. |
| 30210 | Alternative for `bms_code` (34004). uint16. Duplicate. |
| 30212 | Unknown. Constant value 5 in all tested modes. Static across mode changes. Adjacent to 30210. Possibly another sub-version or config index. |
| 32101 | Unknown. Internal EMS state indicator — does not map to `inverter_state` or `user_work_mode`. Small integers (4–42) = active app-controlled charge/discharge; 0x9999 (39321) = app idle/bypass; 0x9967 (39271) = RS485-controlled discharge. Sentinel values may encode control source. Observed values: UPS 300W=4, Manual 450W=7, Manual 2500W=42, Manual 2500W (SoC>=95%)=30, Manual 500W=8, Manual 300W=4, Bypass/Stop=39321, RS485 discharge 2500W=39271. |
| 32104 | Alternative for `battery_soc_int` (37005). scale 1 %, uint16. Duplicate. |
| 32106 | Possibly alternative for 35111. Unclear semantics. |
| 32107 | Possibly alternative for 35112. Unclear semantics. |
| 32108 | Alternative for `max_cell_temperature` (35010). scale 0.1 °C. Inferior. |
| 32109 | Alternative for `bms_online` (37000). uint16. Duplicate. |
| 32301 | Alternative for `ac_offgrid_current` (calculated). Returns same value as 32300 (voltage, not current) — unusable for current measurement. `ac_offgrid_current` is calculated as `ac_offgrid_power / ac_offgrid_voltage` instead. |
| 34000 | Alternative for `battery_voltage` (32100). scale 0.01 V, uint16. Inferior. |
| 34001 | Alternative for `battery_current` (30101). scale 0.1 A, int16. Duplicate. |
| 34005 | Alternative for `max_cell_voltage` (37007). scale 0.001 V. Inferior. |
| 34006 | Alternative for `min_cell_voltage` (37008). scale 0.001 V. Inferior. |
| 34010 | Alternative for `bms_version` (30204). uint16. Inferior. |
| 34017 | Alternative for `bms_status` (30106). uint16. Duplicate. |
| 35110 | Unknown. Value 576 in active charge modes (UPS/Manual), 0 in initial scan. Did not change between different charge modes. Purpose unclear. |
| 35111 | Unknown. Changes with mode AND SoC — not a live power setpoint (constant within a snapshot while actual power varied). Observed: Charge (all)=330, Discharge 2500W SoC~46%=1000, Discharge 2500W SoC~25%=330. 330x0.1=33A, possibly a BMS current limit. |
| 35112 | Unknown. Same behaviour as 35111. Observed: Charge (all)=1000, Discharge 2500W SoC~46%=750, Discharge 2500W SoC~25%=500. |
| 36000 | Unknown. uint32, count 2. Possibly alarm bitmask. Individual bit semantics unknown. |
| 36100 | Unknown. uint32, count 2. Possibly fault bitmask. Individual bit semantics unknown. |
| 37006 | Alternative for `cell_temperature_1` (34013). scale 0.1 °C, int16. Duplicate. |
| 37012 | Alternative for `bms_version` (30204). uint16. Inferior. |
| 37016 | Alternative for `ac_voltage` (36103). scale 0.1 V, uint16. Duplicate. |
| 45603 | Unknown. Value 9985 (0x2701). Adjacent to 45604/45605. Possibly WiFi channel, frequency, or AP info. Not confirmed. |
| 45604 | Unknown. Value 20599 (0x5077). Adjacent to 45603/45605. Possibly WiFi channel, frequency, or AP info. Not confirmed. |
| 45605 | Unknown. Constant value 74 in V148 scan. Adjacent to 45603/45604. |
| 47400 | Unknown. Value 43707 (0xAABB) in V148 scan. Alternating-nibble sentinel — same class as 0x9999, likely "not configured" / undefined. |

---

## Venus D (d.yaml)

Hardware tested: Marstek Venus D, multi-pack setup (verified with up to 6 packs installed;
address pattern extends to a 7th pack). BMS firmware observed going 116 → 1177 (v117.7) after a BMS update.
All registers below were read back and cross-checked on real hardware, but are **not** added to the
integration — following the same policy applied to Venus A/E, which integrates only per-pack SoC and
per-pack cell voltages, not the remaining per-pack scalars.

Integrated (for reference): `battery_soc_1..6` (34002/34102/34202/34302/34402/34502),
`battery_2..6_cell_1..16_voltage` (34118–34133 / 34218–34233 / 34318–34333 / 34418–34433 / 34518–34533,
16 cells per pack — Venus D packs carry 16 cells vs. 13 on Venus A), `alarm_status` (36000),
`fault_status` (36100). Pack 1 cell voltages (34018–34033) were already present.
Packs 2–4 cell voltages are FW-confirmed; packs 5–6 follow the identical +0x100 register pattern
(pattern-derived, same treatment as Venus A `a.yaml`).

### Mirrors / inferior duplicates of already-integrated sensors

| Register | Notes |
|----------|-------|
| 30002 | Mirror of `internal_temperature` (35000). int16, scale 0.1 °C. |
| 30003 | Mirror of `internal_mos1_temperature` (35001). int16, scale 0.1 °C. |
| 30004 | Mirror of `ac_voltage` (32200). uint16, scale 0.1 V. |
| 37005 | Integer SoC without scale. Inferior to `battery_soc` (32104). |

### Per-pack scalars

Pattern: each pack is offset by +0x100 (pack 1 = 340xx, pack 2 = 341xx, …). Values below confirmed
across packs 1–5 (pack 6 follows the same pattern; populated only when a 6th pack is present).
Layout updated per the 2026-08-16 firmware descriptor-table correction (BMS CAN frames 0x23 / 0x41).

The per-pack health registers are now integrated for packs 1–6 (all disabled by default):
temperatures (34011/34012 → `battery_N_env_temperature` / `battery_N_mos_temperature`), the cell-NTC
block (34013–34016 → `battery_N_cell_temperature_1..4`), the cell-voltage extremes (34005/34006 →
`battery_N_max_cell_voltage` / `battery_N_min_cell_voltage`), and the protection bitmasks (34007/34008 →
`battery_N_protection_1` / `battery_N_protection_2`). The remaining rows stay reference-only.

#### Individual cells: what the device does not report

`max_cell_voltage` / `min_cell_voltage` (37007/37008) and the per-pack 34005/34006 carry
the value only — no register anywhere gives the cell index it came from. The four cell
NTCs (34013–34016) cover sixteen cells with no documented mapping, which is why the
entities are named "Cell NTC 1..4" rather than "Cell Temperature 1..4".

| Register (pack 1 / +0x100 per pack) | Key | Notes |
|----------|-----|-------|
| 34000 | pack battery voltage | uint16, scale 0.01 V. Pack 1 = `battery_voltage`; packs 2–6 **integrated** as `battery_N_voltage`. |
| 34001 | pack battery current | int16, scale 0.1 A. Negative = discharge. Pack 1 = `battery_current`; packs 2–6 **integrated** as `battery_N_current`. |
| 34003 | pack cycle count | int16. Pack 1's value (34003) is `battery_cycle_count`; packs 2–6 **integrated** as `battery_N_cycle_count`. |
| 34004 | pack MOS status | u8. BMS charge/discharge MOSFET state (Chg/Dsg MOS). **Integrated** as `battery_N_mos_status`. |
| 34005 | pack max cell voltage | uint16, scale 0.001 V. **Integrated** as `battery_N_max_cell_voltage`. Value only — no cell index. |
| 34006 | pack min cell voltage | uint16, scale 0.001 V. **Integrated** as `battery_N_min_cell_voltage`. Value only — no cell index. |
| 34007 | pack protection bitmask 1 | int16 bitmask (BMS CAN frame 0x23, protect1). **Integrated** as `battery_N_protection_1`. |
| 34008 | pack protection bitmask 2 | uint16 bitmask (frame 0x23, protect2). A low-SoC/undervoltage bit (0x0002) was observed here during discharge testing (triggers below ~10.7%). **Integrated** as `battery_N_protection_2`. |
| 34009 | pack BMS reserved | uint16. BMS-struct field @+0x5a; not named in the firmware debug print. |
| 34010 | pack BMS version | uint16. 116 → 1177 (v117.7) after BMS firmware update. **Integrated** as `battery_N_bms_version`. |
| 34011 | pack ENV NTC (ambient) | uint16, scale 0.1 °C (BMS frame 0x41). Was previously labelled "cell NTC 0". **Integrated** as `battery_N_env_temperature`. |
| 34012 | pack MOS NTC (MOSFET) | uint16, scale 0.1 °C (BMS frame 0x41). Was previously labelled "cell NTC 1". **Integrated** as `battery_N_mos_temperature`. |
| 34013–34016 | pack cell NTC block | uint16 ×4, scale 0.1 °C (pack struct +0x40). **Integrated** as `battery_N_cell_temperature_1..4`, displayed as "Cell NTC 1..4" — four thermistors for sixteen cells, no cell mapping. |
| 34017 | pack NTC (unused) | uint16, scale 0.1 °C. BMS frame 0x41 bytes 6–7 are not populated. |

### Alternative / redundant sources (firmware-confirmed, intentionally not integrated)

These are valid firmware registers, but each duplicates a value already exposed through a better
source, so they are documented rather than added as extra entities.

| Register | Firmware name | Why not integrated |
|----------|---------------|--------------------|
| 30028 | `inv_bat_voltage` | Inverter-measured battery voltage (0.1 V). Alternative to `battery_voltage` (30100). |
| 30029 | `inv_bat_current` | Inverter-measured battery current (0.1 A). Alternative to `battery_current` (30101). |
| 32100 | `bms_battery_voltage` | BMS/CAN aggregate battery voltage (0.01 V). Alternative to `battery_voltage`. |
| 32101 | `bms_battery_current` | BMS/CAN aggregate battery current (1 A). Coarser alternative to `battery_current`. |
| 32102 | `bat_sample_power` | Battery power as float32. Alternative to `battery_power` (30001, int16 W). |
| 37017–37020 | `mppt1..4_power` | Same source as `mppt1..4_power` (30037–30040), which are already integrated. |
| 37002 / 37003 | `max_charge_power` / `max_discharge_power` | Read-back of the power limits already exposed as the `max_charge_power` / `max_discharge_power` number entities. |

### Backup / UPS output (30005 / 30007) — duplicates, deliberately not integrated

Both resolve to the same firmware source as `ac_offgrid_voltage` (32300) and
`ac_offgrid_power` (32302). Do not add sensors for them.

### Network configuration — integrated

| Register | Key | Notes |
|----------|-----|-------|
| 30400–30401 | `device_ip_address` | Two octets per register, high byte first. 0xC0A8 / 0xB59A → 192.168.181.154. |
| 30402–30403 | `gateway_ip_address` | Same encoding. 0xC0A8 / 0xB501 → 192.168.181.1. |

Decoded by the `ipv4` data type in `helpers/modbus_client.py`. Diagnostic, disabled by default.

### Firmware descriptor-table analysis (v150)

A later pass decoded the device's on-firmware descriptor tables (FC03 read descriptors, plus the
FC06/FC10 write-handler table with their SRAM targets). This is authoritative for register names,
types and layout. Findings folded into the integration and this document:

**Newly integrated diagnostic sensors** (all `category: diagnostic`, disabled by default):

| Register | Sensor | Notes |
|----------|--------|-------|
| 30205 | `mppt_version` | MPPT firmware version (u16, observed 104). |
| 32109 | `bms_pack_count` | Number of packs the BMS reports present (CAN `bat_total_nb`). |
| 32110 | `bms_online_mask` | u16 bitmask: which packs are online (`bat_online_mask`). |
| 32111 | `bms_active_pack_index` | Index of the currently active pack (`work_bat_idx`). |
| 35110 | `bms_charge_voltage_limit` | BMS charge voltage limit, 0.1 V (CAN `chrg_volt`, observed 57.6 V). |
| 37023 | `mppt_error` | MPPT error word (Inverter struct +0x02). |
| 37024 | `mppt_warning` | MPPT warning word (Inverter struct +0x06). |

**Write/control registers — confirmed already integrated.** The firmware write-handler table matches
the existing `number`/`select`/`switch`/`button` definitions (e.g. 42020/42021 charge/discharge power,
44002/44003 max power, 42011 target SoC, 42010 force mode, 43000 work mode, 41200 backup, schedules).
No change needed — the decode simply validates them.

**Write registers intentionally NOT integrated** (decoded from firmware but never write-tested;
some are hazardous to expose as live entities):

| Register | Firmware name | Why excluded |
|----------|---------------|--------------|
| 40000 | `rs485_unlock` | Enables RS485 control; unclear side effects, no display scale. |
| 41100 | `modbus_slave_address` | Changing it silently breaks Modbus communication. |
| 41500–41631 | `schedule_time_XX` / `schedule_power_XX` | Raw schedule arrays; integration already models schedules via 43100+. |

**Note on the earlier `MISSING:` config registers.** The Venus-E-derived addresses (`software_version`
31100, `sn_code` 31200, cutoff 44000/44001, `grid_standard` 44100, `discharge_limit_mode` 41010) do
**not** appear in the Venus D firmware descriptor tables — they likely do not exist on Venus D, or live
at different addresses. They should not be copied over from other models without hardware confirmation.
