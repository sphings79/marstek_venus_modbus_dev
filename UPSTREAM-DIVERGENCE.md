# Divergence from upstream

Everything in this fork that is **not** in `ViperRNMC/marstek_venus_modbus`, so it can be
carried upstream when wanted, or dropped deliberately.

The baseline is `39554f4`, the last of the three merges that brought the `vnsd_*` Venus D
branches into `main`. Those branches were submitted upstream separately and are not
repeated here. Everything below landed afterwards.

Each entry states whether it is **general** (applies to every model and belongs upstream
as-is) or **Venus D only** (evidence comes from Venus D v150 firmware).

> **Model scope — read before porting any register finding.**
> Venus **A**, **D** and **E v3** share one firmware base. A finding verified on one of
> them is plausible on the other two and needs only confirmation, not fresh research.
>
> Venus **E v1/v2** is built on a **completely different firmware base**. Nothing derived
> from A/D/E3 firmware may be carried into `e_v12.yaml` — not register meanings, not bit
> tables, not scale factors. Matching register numbers there are coincidence until proven
> otherwise on E v1/v2 firmware itself.

Register research itself lives in the companion firmware-debug project, not in this
repository. The pointers quoted here are just enough to justify each change.

---

## 1. Bug fix — `solar_power_total` loses its inputs on a default install

`ca1621a` · general · `coordinator.py`

`all_definitions_for_deps` did not list `SOLAR_POWER_SENSOR_DEFINITIONS`, so the
coordinator never treated `mppt1..4_power` as dependency keys. Those four sensors ship
`enabled_by_default: false` while `solar_power_total` ships enabled, so on a fresh install
the calculated sensor asks for four values the coordinator deliberately skipped and logs
`missing required value(s)` every poll. It only works if the user enabled the MPPT power
sensors by hand.

Affects `a.yaml` and `d.yaml` equally. Five-line fix; the highest-value change in this
list for upstream.

The added comment states the invariant that was silently violated: every section whose
definitions can carry `dependency_keys` must be listed there. All six such sections are
now covered.

## 1b. Bug fix — reading a register the device does not have

`e0c265c` · Venus A and D · `registers/a.yaml`, `registers/d.yaml`

`ac_offgrid_power` declared register 32302 as `int32` with `count: 2`, so every poll asked
for 32302 **and 32303**. The Venus D firmware's descriptor table exposes 32302 as a single
`i16` register and has no entry for 32303 — the read ran past the end of that descriptor
region and stalled the device's Modbus stack.

Confirmed as the trigger behind observed stalls: two independent failure logs name 32302 as
the first failure, and it was the only read sensor whose declared span exceeded its
descriptor entry. The sensor is disabled by default, which is why the fault only surfaces
once someone enables the off-grid sensors.

`e_v3.yaml` already declared it correctly. `e_v12.yaml` still declares `int32` but belongs
to the other firmware family and was left alone.

**Strong upstream candidate** — it is a live defect, not a Venus D nicety.

## 2. Feature — `ipv4` data type

`1529b55` · general · `helpers/modbus_client.py`

New decoder in `_decode_registers`, plus `ipv4` in `_default_count_for_data_type`. Two
registers, two octets each, high byte first. Verified against a hardware dump: `0xC0A8` /
`0xB59A` decodes to `192.168.181.154`.

Self-contained and harmless without a register that uses it.

## 3. Feature — per-pack cell voltage delta sensors

`b50fc12` · Venus D only (mechanism is general) · `coordinator.py`, `sensor.py`,
`registers/d.yaml`, all three translations

Six calculated sensors `battery_1..6_cell_voltage_delta`, the spread between each pack's
own highest and lowest cell voltage. Volts, three decimals, diagnostic, disabled by
default.

Three parts:

- **`MarstekCellVoltageDeltaSensor`** in `sensor.py`, a subclass of
  `MarstekCalculatedSensor` following the existing pattern. Returns `None` rather than a
  negative spread — max and min are read in separate transactions, so a sample taken
  across a BMS update can invert them.
- **`CELL_VOLTAGE_DELTA_SENSOR_DEFINITIONS`**, a new section wired through
  `get_registers`, the coordinator's attribute init and assignment, and
  `all_definitions_for_deps`. The last one matters: it keeps the max/min registers polled
  while their own entities stay disabled, so enabling six deltas does not require
  enabling twelve source sensors.
- **Six definitions** in `d.yaml` plus de/en/nl names.

The class and the section are model-agnostic. Only the definitions are Venus D specific,
and only because the per-pack max/min registers were verified there.

## 4. Register corrections — three registers named for the wrong quantity

`0f2db67` · Venus D only · `registers/d.yaml`

Each shares its SRAM source pointer with a sensor the integration already exposes, so the
value was duplicated under a name claiming a different physical quantity.

| Register | Was called | Actually reads | Already exposed as |
|---|---|---|---|
| 37004 | `ac_current` | `grid_sample_power` (`0x20014EB4`) | `ac_power` (30006) |
| 32301 | `ac_offgrid_current` | `off_grid_volt` (`0x20014EB0`) | `ac_offgrid_voltage` (32300) |
| 35002 | `internal_mos2_temperature` | `radiator_temp` (`0x20014EBE`) | `internal_mos1_temperature` (35001) |

`ac_current` was **enabled by default**, so every Venus D installation showed grid power
scaled by 0.004 and labelled as amperes.

Removed rather than renamed, since the correct sensor for each value already exists. The
translation keys stay because `a.yaml`, `e_v3.yaml` and `e_v12.yaml` still use them.

**Before porting upstream:** check the same pointers on Venus A and Venus E. The register
numbers are shared across models, the firmware evidence is not.

## 5. Register corrections — device-wide cell extremes are pack 1's

`37b2cac` · Venus D only · `registers/d.yaml`, `README.md`, `registers/README.md`

| Register | Source pointer | Firmware field |
|---|---|---|
| 37007 · 34005 | `0x20014FC4` | pack 1 max cell voltage |
| 37008 · 34006 | `0x20014FC6` | pack 1 min cell voltage |

`max_cell_voltage` and `min_cell_voltage` presented themselves as device-wide extremes.
There is no device-wide maximum or minimum anywhere in the register set — both read the
same word as the per-pack registers. Invisible on a single-pack unit; on a six-pack Venus
D the sensor reported pack 1 while looking like a whole-battery figure, which is exactly
the value one consults to find a weak cell.

Replacement is `battery_1_max_cell_voltage` / `battery_1_min_cell_voltage`.

`bms_version` (30204) duplicates `battery_1_bms_version` (34010) the same way but was
**kept**: `firmware_version` uses it as a dependency key.

## 6. New registers

`1529b55`, `0f2db67` · Venus D only · `registers/d.yaml`, all three translations

| Key | Register | Notes |
|---|---|---|
| `device_ip_address` | 30400–30401 | uses the new `ipv4` type |
| `gateway_ip_address` | 30402–30403 | same |
| `pv_year_capacity` | 37021 | u32 in 10 Wh units, scaled 0.01 to kWh, `total_increasing` |

The descriptor table exposes the IP block as one entry at 30400 with `count: 8`; the split
into device and gateway address is this fork's reading of those eight bytes.

The PV daily and monthly counters sit beside the yearly one in the same struct but have no
descriptor entry and are not readable over Modbus.

## 7. Naming — cell NTCs

`dc72ce2` · Venus D only · all three translations, `registers/README.md`

`battery_1..6_cell_temperature_1..4` renamed from "Cell Temperature 1..4" to **"Cell NTC
1..4"** in de/en/nl. Registers 34013–34016 are four thermistors covering sixteen cells;
the number is the sensor's slot in BMS frame 0x41, not a cell number, and the firmware
does not expose where each sits. The old name implied a cell mapping that does not exist.

Display names only — entity ids are untouched.

## 8. Translation gap

`83933e8` · general · `translations/de.json`

`vms_version` had no German name and fell back to the English string. Added as
"VMS-Version", matching `EMS-Version` and `BMS-Version`. Three lines, no risk.

## 9. Documentation and housekeeping

- `registers/README.md`: the backup/UPS question resolved as duplicates, a note on what
  the device does not report about individual cells, the pack-1 finding. Trimmed to short
  pointers — the analysis itself lives in the firmware-debug project.
- `README.md`: `d` column blanked for `max_cell_voltage` / `min_cell_voltage`, with a
  footnote.
- `.gitignore`: `logs/`.
- `manifest.json`: version `1.0.x-dev` instead of upstream's calendar scheme, so it is
  obvious which build is installed. **Do not carry upstream.**

`7849a29` and `4521d0d` added and then corrected a `registers/firmware-analysis.md`
holding the Venus D firmware analysis. `0f2db67` removed it again when that research moved
to the firmware-debug project, so the net effect on the tree is zero and there is nothing
to port. They appear in the history only.

## 10. Reverted, do not resurrect

`1529b55` added `backup_voltage` (30005) and `backup_power` (30007) on the strength of a
register note describing them as a separate backup measurement point. `ba96592` removed
them again: the descriptor table resolves both to the same source as `ac_offgrid_voltage`
(32300) and `ac_offgrid_power` (32302).

The Venus E Gen 3 notes had it right; the Venus D note was wrong. `registers/README.md`
carries the resolution so this does not get re-added.

---

## Porting checklist

| # | Change | Upstream-ready | Note |
|---|---|---|---|
| 1 | `solar_power_total` dependency fix | **yes** | affects all models, fixes a live defect |
| 2 | `ipv4` data type | **yes** | inert without a consumer |
| 3 | delta sensor class + section | **yes** | definitions are Venus D only |
| 8 | German `vms_version` | **yes** | trivial |
| 4 | three mislabelled registers | verify first | check the pointers on A and E |
| 5 | pack-1 cell extremes | verify first | same |
| 6 | new registers | Venus D only | needs #2 for the IP sensors |
| 7 | Cell NTC renaming | Venus D only | display names only |
| 9 | version scheme | **no** | fork-specific |

Removals in 4 and 5 leave orphaned entities behind in existing installations. Home
Assistant keeps them in the registry as `unavailable` until deleted by hand. Any upstream
release carrying them needs that in its release notes.
