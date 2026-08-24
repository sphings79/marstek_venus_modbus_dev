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

## 1c. Bug fix — a calculated sensor's inputs were fetched even when it was disabled

`fffa643` · general · `coordinator.py`

`dependency_keys_set` was built from the definitions alone, so the source registers of
every calculated sensor were polled whether or not anything consumed them. Upstream this
means `solar_power_total` has always pulled `mppt1..4_power` on every cycle even when
nobody enabled it; in this fork the six per-pack cell voltage deltas added twelve more
registers, spread across all six pack regions — the regions this device is most sensitive
about.

The collection now skips a calculated sensor whose own entity is disabled. A source that
is enabled in its own right keeps being polled, and a source feeding several calculated
sensors keeps being polled while any one of them is enabled.

An entity the registry does not know yet counts as enabled — during the first refresh the
platforms have not added their entities, and treating unknown as disabled would leave
every calculated sensor without a value for one cycle.

Also extracts the registry lookup the poll loop did inline into `_is_entity_disabled`, so
the loop and the dependency collection cannot drift apart.

**Strong upstream candidate** — it saves work on every installation.

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

## 3b. Feature — fault bitfields in plain text

`bcbdc74`, `72037d6`, `f10c1ec` · mechanism general, definitions Venus D · `coordinator.py`,
`sensor.py`, `registers/d.yaml`, all three translations

`bit_descriptions` had been present in the register YAML since before this fork but no
Python ever read it — dead data. It is now rendered by `MarstekBitfieldTextSensor` in a new
`BITFIELD_TEXT_SENSOR_DEFINITIONS` section.

The numeric sensors are untouched: `fault_status` still reports `32`, and a companion
`fault_status_description` reports `32 - BMS reports a fault (check pack firmware
versions)`. Undecoded bits render as `unknown bit N` rather than being dropped. Each
description sensor exposes `raw_value`, `active_bits`, `active_faults` and
`undecoded_bits` as attributes so automations can test a single bit.

An earlier attempt rendered the text on the numeric sensor itself. That changed the state
type of Venus E v1/v2's `fault_status` and `alarm_status` as a side effect and was
replaced by the companion-sensor design.

Also exposes the other three fault registers for Venus D: the device splits each 32-bit
error word across two registers, high word first, and only the high word of `error_code1`
was readable. **36101** carries the backup/off-grid fault bit, confirmed on hardware, and
was previously invisible.

## 3c. Feature — the two values the firmware computes but never publishes

`2b12368`, `8b28363`, `ab2a2e4` · Venus D · `coordinator.py`, `sensor.py`,
`registers/d.yaml`, all three translations

The device computes two power values for its Bluetooth payload and exposes no register for
either. Both are rebuilt from the registers the firmware's own formulas read, decompiled
from the BLE payload builder, and verified against hardware in all three operating states —
discharge, bypass and charge.

- **`grid_power`** — power at the grid connection point. Not a plain subtraction: in bypass
  the backup output is fed straight from the grid, the inverter's own grid sample reads
  zero, and inverter state 4 is the one state where that zero means something else.
- **`battery_power_bms`** — BMS pack voltage times pack current. A *second* battery power
  sensor beside `battery_power` (30001), not a replacement: 30001 is the inverter's
  measurement, this one the BMS side. They agree within half a percent under load and
  differ by the device's own consumption at idle.

`battery_power_bms` deliberately does **not** read register 32101, which is where the
firmware itself gets the current, because of the firmware defect described in section 11.

## 3d. Correctness — entity categories and state classes

`4409fb0`, `c7742d9` · mixed · `registers/d.yaml`

Three measurements were filed as diagnostics, which files them separately on the device
page and leaves them out of auto-generated dashboards: `battery_1..6_cell_voltage_delta`,
`bms_battery_voltage` and `pv_year_capacity`. All three were introduced by this fork.

Two more, from the Venus D branches and upstream:

- `battery_1..6_cycle_count` and `battery_cycle_count_calc` used `state_class: measurement`
  for monotonic counters, so long-term statistics recorded them as gauges. The device-level
  `battery_cycle_count` already used `total_increasing`.
- `wifi_signal_strength` had `device_class: signal_strength` but no `state_class` at all,
  so it produced no long-term statistics.

The per-pack sensors were audited and found internally consistent — all measurements
uncategorised, all status fields diagnostic.

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
- `manifest.json`: semantic versioning (`1.3.1`) instead of upstream's calendar scheme, so
  it is obvious which build is installed. **Do not carry upstream.**

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

## 11. Firmware defect worked around, not fixed here

Register **32101** (BMS battery current) cannot be read as documented. The device's FC03
serializer sign-extends an `int16` into an unsigned word and then applies the descriptor's
divide-by-ten scale to it, so negative values come back corrupted — `-122` arrives as
`39309`. Positive values pass through correctly, so the defect only bites on discharge.

Reproduced exactly against three hardware states and reported to the manufacturer. In
firmware v150 exactly one of 246 descriptor entries combines a signed type with a divide
scale, so 32101 is the only register affected today; the defect lives in the shared
serializer.

Nothing in this repository reads 32101. `battery_power_bms` sums the per-pack current
registers instead, which carry no scale code.

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
| 1c | calculated-sensor inputs only when enabled | **yes** | saves work everywhere |
| 3b | bitfield description sensors | **yes** | mechanism is model-agnostic |
| 3c | grid_power / battery_power_bms | Venus D | formulas are device-specific |
| 3d | categories and state classes | **partly** | the two state_class fixes apply to all models |
| 9 | version scheme | **no** | fork-specific |
| 13 | setup time, client timeout, block guard | **yes** | fixes a live defect on every UI-created entry |
| 14 | `message_wait_ms` reachable in the options | **yes** | the value was unwritable before |
| 15 | `precision` on calculated sensors | **yes** | affects every model |
| 16 | one retry ladder, half-open recovery, request logging | **yes** | model-agnostic, verified against a silent server |
| 17 | repair issue for the RS485 control mode reset | verify first | needs 42000 confirmed on a second model |
| 18 | serialised reconnect + connect backoff | **yes** | belongs with 16; without it 16 can storm |

Removals in 4 and 5 leave orphaned entities behind in existing installations. Home
Assistant keeps them in the registry as `unavailable` until deleted by hand. Any upstream
release carrying them needs that in its release notes.

## 12. DEV-Register (Optionsschalter)

**Dateien:** `const.py`, `config_flow.py`, `coordinator.py`, `sensor.py`,
`registers/d.yaml`, `translations/{de,en,nl}.json`

Ein Schalter in den Integrations-Optionen (`Optionen → DEV-Register`) blendet
131 zusaetzliche Diagnose-Sensoren ein. Standardmaessig aus.

**Zwei getrennt schaltbare Gruppen** (`DEV_UNKNOWN_SENSOR_DEFINITIONS` und
`DEV_DUPLICATE_SENSOR_DEFINITIONS`):

| Option | Anzahl | Inhalt |
|---|---|---|
| `dev_registers_unknown` | 119 | Register ohne geklaerte Bedeutung: Konfidenz `niedrig`/`mittel` aus der Firmware-Analyse, plus Register >= 40000, die im Live-Scan vom 2026-08-22 nachweislich auf einen FC03-Read geantwortet haben |
| `dev_registers_duplicate` | 13 | Register mit demselben Wert wie ein bereits integrierter Sensor: Aliase auf dieselbe SRAM-Quelle, Spiegelregister, Folgeregister eines mehrteiligen Blocks |

Die Trennung erlaubt es, die Doppelungen einzeln einzuschalten — etwa um zu
pruefen, ob zwei Register wirklich synchron laufen — ohne 117 unbekannte
Sensoren mitzuschleppen.

**Migration:** Der Sammelschalter `dev_registers` aus 1.1.5-beta.1 wird noch
gelesen. War er an, gelten beide neuen Optionen als an, solange die neuen
Schluessel fehlen. Beim naechsten Speichern wird der alte Schluessel entfernt.

**Namensschema:** `DEV <register> (<verdacht>?)`. Alle beginnen mit `DEV` und
stehen dadurch in der Oberflaeche beieinander; das Fragezeichen macht deutlich,
dass der Name eine Vermutung ist. Kategorie `diagnostic`, `scan_interval: low`.

**Eigene Entity-Klasse `MarstekDevSensor`:** setzt `_attr_name` direkt statt
`translation_key`. Mit einem Uebersetzungsschluessel ohne hinterlegte
Uebersetzung blieben die Entitaeten namenlos — genau der Fehler, der schon
einmal auftrat.

**Bewusst ausgeschlossen:**

- `41500`–`41515`: WLAN-Zugangsdaten-Puffer (SRAM `0x20014DCC`, referenziert von
  `WiFi_Set_Credentials`). Ein Sensorwert landet sonst in Datenbank, Backups und
  moeglicherweise Logs.
- `40000`, `41000`, `45000`–`45031`, `46000`: Diese Register liessen im Scan die
  Modbus-Verbindung abreissen — dasselbe Verhalten, das die urspruenglichen
  Haenger verursacht hat.

**Warum das Polling sicher bleibt:** `_build_contiguous_read_groups` gruppiert
nur strikt lueckenlose Register (`register == current_end + 1`). Eine Luecke
bricht die Gruppe, ein Blockread kann also nie ueber ein nicht definiertes
Register laufen. Gegengeprueft: 59 Blockgruppen ueber alle 423 Definitionen,
keine ueberspannt ein Stoerregister, groesste Gruppe 44 Register.

**Umschalten loest ein Reload aus,** weil die Registerdefinitionen nur beim
Setup gelesen werden.

**Fuer einen Upstream-Port:** Die Registerliste in `DEV_SENSOR_DEFINITIONS` gilt
ausschliesslich fuer Venus D. Venus A und E v3 teilen sich zwar die
Firmware-Basis, aber weder die Scan-Ergebnisse noch die Konfidenzeinstufungen
wurden dort geprueft. Venus E v1/v2 hat eine voellig andere Basis — dort darf
nichts davon uebernommen werden.

### Zurueckgezogen: `pv_year_capacity` (37021/37022)

Der Sensor war als Energiezaehler angelegt — `device_class: energy`,
`state_class: total_increasing`, u32 ueber 37021+37022, Einheit kWh. Grundlage
war der Firmware-String `PV_Year_Cap_10Wh` am Inverter-Struct +0x2c.

**Die Messung widerlegt das.** Ueber 70 Minuten an einem Geraet **ohne
angeschlossenes PV** beobachtet: 37021 steht konstant auf 0, 37022 schwankt in
beide Richtungen zwischen 535 und 561. Ein Jahres-Energiezaehler kann nicht
fallen, und mit `total_increasing` haette jeder Ruecksetzer die
Langzeitstatistik verfaelscht. Der Sensor war zwar `enabled_by_default: false`,
die Definition aber trotzdem falsch.

Entfernt aus `SENSOR_DEFINITIONS`. Beide Register laufen jetzt als
eigenstaendige `uint16`-Eintraege in der Unbekannt-Gruppe.

**Zweiter Fehler an derselben Stelle:** `dev_37022` hatte den Datentyp `uint32`
aus der Register-Map uebernommen und las damit 37022 **und 37023** als einen
32-Bit-Wert. 37023 ist `mppt_error`. Der angezeigte Wert war
`register_37022 << 16 | mppt_error` — rund 35 Millionen. Das ist der Grund,
warum der Sensor eine unsinnige Zahl zeigte, die sich bewegte.

**Regel daraus:** Ein DEV-Eintrag uebernimmt nie den Datentyp `u32` aus der
Register-Map, ohne dass geklaert ist, ob das Register der Anfang des Paares ist.
Alle DEV-Eintraege sind jetzt `uint16` oder `int16`; ein automatischer Test
prueft das.

## 13. Startup — warum das Laden des Config Entry so lange dauerte

**Dateien:** `__init__.py`, `select.py`, `coordinator.py`, `const.py`,
`helpers/modbus_client.py`

Home Assistant meldete beim Start `Setup of select platform marstek_modbus is
taking over 10 seconds` — und zwar nur fuer `select`. Vier unabhaengige
Ursachen, alle im Setup-Pfad.

**a) `update_before_add=True` zog einen kompletten Poll in den Plattform-Setup.**
`select.py` war die einzige Plattform, die so addete. Bei einer
`CoordinatorEntity` landet das in `async_device_update()` →
`CoordinatorEntity.async_update()` → `coordinator.async_request_refresh()`.
Dessen Debouncer laeuft mit `REQUEST_REFRESH_DEFAULT_IMMEDIATE = True`
(`helpers/update_coordinator.py`), fuehrt `_async_refresh()` also **sofort aus
und wartet darauf** — ein voller Poll ueber alle faelligen Register, blockierend
im Setup. Die uebrigen Select-Entities liefen ins gesperrte `_execute_lock`,
setzten den Debounce-Timer und loesten ~10 s spaeter einen **zweiten** Voll-Poll
aus. Die Werte kommen ohnehin aus `async_config_entry_first_refresh()`.

**b) `message_wait_ms` wirkte doppelt pro Request.** Nach jedem Request lief ein
Sleep von `message_wait_sec` **innerhalb** des Request-Locks, danach wartete das
Pacing nochmal denselben Betrag ab `_last_request_finished_at` — das aber erst
nach dem ersten Sleep gesetzt wurde, der Abstand war also immer voll. Gemessen
im Log vom 21.08.: 169–173 ms zwischen aufeinanderfolgenden Requests bei ~10 ms
Antwortzeit des Geraets. Jetzt wartet eine Transaktion genau einmal
(`_async_wait_for_request_slot` / `_mark_request_finished`), Writes eingeschlossen
— die hatten vorher gar kein Pacing davor, nur den Sleep danach.

Nachgemessen mit einem Fake-Client (6 Reads, 10 ms simulierte Antwortzeit):

| | Abstand je Request | 6 Reads gesamt |
|---|---|---|
| vorher | 173 ms | 957 ms |
| nachher | 92 ms | 471 ms |

**c) Kein Timeout am pymodbus-Client.** Der Config Flow hat kein
`timeout`-Feld, `entry.data.get("timeout")` war fuer jeden ueber die UI
angelegten Eintrag `None`, und `AsyncModbusTcpClient(timeout=None)` wartet
unbegrenzt. Genau deshalb brauchte jeder Aufrufer einen eigenen
`asyncio.wait_for`-Mantel. `MarstekModbusClient` normalisiert den Wert jetzt
gegen `DEFAULT_TIMEOUT = 3` — wie `message_wait_ms` und `unit_id` es schon taten.

**d) Block-Timeout von 10–22 s.** `_block_read_timeout` war frei gegriffen und
stand in keinem Verhaeltnis zum Client-Timeout. Ein Block liest mit
`max_retries=1`; laenger zu warten als der Client selbst haelt nur den
Poll-Zyklus auf — beim ersten Refresh also den Setup des Config Entry. Jetzt
`2 x Client-Timeout + 0.02 je Register`, gedeckelt auf `3 x Client-Timeout`
(bei 3 s: 6,1–6,9 s statt 10–22 s).

**e) Setup schluckte jeden Fehler.** `async_setup_entry` fing alles ab und gab
`False` zurueck: war die Batterie beim HA-Start kurz nicht erreichbar, blieb die
Integration dauerhaft ungeladen. Jetzt `ConfigEntryNotReady` (HA wiederholt mit
Backoff) bzw. `ConfigEntryError` bei fehlendem Host/Port, und der Fehlerpfad
raeumt Plattformen, Socket und `hass.data` wieder ab.

**Nicht geaendert: die strikt lueckenlose Blockbildung.** Naheliegend waere,
`_build_contiguous_read_groups` kleine Luecken ueberspringen zu lassen (Venus D:
52 → 32 Requests). Das verbietet Abschnitt 12: ein Blockread darf nie ueber ein
nicht definiertes Register laufen, sonst sind die Stoerregister wieder im Spiel,
die die Verbindung abreissen liessen. Die sichere Variante — eine Luecke nur
ueberspringen, wenn **jedes** Register darin in der YAML definiert ist — wurde
durchgerechnet und bringt fast nichts: bei den standardmaessig aktiven Entities
0 Requests Ersparnis (D: 15, E v3: 13, A: 15, E v1/v2: 13), mit allen Entities
nur D 52 → 46. Nicht das Risiko wert.

## 14. Die Wartezeit zwischen Modbus-Nachrichten war unerreichbar

**Dateien:** `const.py`, `config_flow.py`, `coordinator.py`, `translations/*.json`

`message_wait_milliseconds` wurde an genau einer Stelle gelesen — im Coordinator
aus `entry.data` — und an keiner Stelle geschrieben. Im Config Flow kam der
Schluessel weder beim Einrichten noch in den Optionen vor. Ein Wert, der einmal
in `entry.data` gelandet war (aus einer frueheren Version), liess sich damit
ueber die Oberflaeche nicht mehr aendern; er blieb ueber jedes Update hinweg
stehen.

**Warum das teuer ist:** die Wartezeit gilt pro Request. Auf dem Testgeraet
stand sie auf 300 ms bei ~10 ms tatsaechlicher Antwortzeit — 97 % der Zykluszeit
war selbst gesetzte Pause. Gemessen an einem Reload mit aktiven DEV-Registern:

```
21:16:41.710  Coordinator initialized
21:16:42.496  erster Poll-Tick     ->  Register laden + Connect + Plattformen:  0,79 s
21:16:58.590  erste Entity-Aktualisierung ->  erstes Refresh:                  16,1 s
```

179 Register-Reads in dem Zyklus, ~300 ms je Request. Bei 80 ms waeren es
ueberschlagen 4-5 s statt 16.

**Behoben:** das Feld steht jetzt im Optionsschritt „Verbindung", vorbelegt mit
dem aktuellen Wert, geclampt auf 0-1000 ms. Der Schritt schreibt ohnehin schon
per `async_update_entry(data=...)` nach `entry.data` und baut den Client neu auf,
die Aenderung greift also ohne Reload. Der Testverbindungs-Client bekommt den
neuen Wert, statt wie vorher den alten vom Coordinator zu erben — sonst wuerde
die Verbindung mit einer anderen Taktung geprueft als der, die anschliessend
gespeichert wird.

**Bewusst nicht im Einrichtungsformular.** Der Default von 80 ms hat auf allen
getesteten Geraeten funktioniert; das Feld gehoert zur Fehlersuche, nicht zum
ersten Kontakt. Neue Installationen schreiben den Schluessel gar nicht erst und
laufen auf `DEFAULT_MESSAGE_WAIT_MS`.

**Der Schluessel heisst jetzt `CONF_MESSAGE_WAIT_MS`** statt als Stringliteral im
Coordinator zu stehen, und der Coordinator faellt sichtbar auf den Default
zurueck, statt `None` weiterzureichen — dieselbe Klasse Fehler wie beim Timeout
in Abschnitt 13c.

## 15. Bug fix — berechnete Sensoren ignorierten ihre `precision`

**Datei:** `sensor.py`

Die Zellspannungs-Differenz zeigte `0` statt `0,000`. Ursache: `precision`
steht in den Definitionen (bei Venus D an allen sechs Delta-Sensoren, dazu
`grid_power` und `battery_power_bms`), gelesen wurde der Schluessel aber nur von
`MarstekSensor` ueber die Property `suggested_display_precision`.
`MarstekCalculatedSensor` setzt Einheit, Device-Class, State-Class, Kategorie
und Icon aus der Definition — die Nachkommastellen fehlten.

Home Assistant liest `_attr_suggested_display_precision` ueber eine
`cached_property`, die Zuweisung im Konstruktor genuegt also. Betroffen waren
alle berechneten Sensoren gleichermassen; die Textsensoren (Version,
Bitfield-Klartext) tragen keinen `precision`-Schluessel und bleiben unberuehrt.

**Warum das mehr ist als Kosmetik:** ein Delta von `0` liest sich wie ein
fehlender Wert, `0,000` wie ein perfekt balanciertes Pack. Genau bei dem Sensor,
dessen Zweck es ist, eine schwaechelnde Zelle fruehzeitig sichtbar zu machen.

**Hinweis fuer bestehende Installationen:** Home Assistant uebernimmt die
vorgeschlagene Genauigkeit beim naechsten Laden — es sei denn, die Anzeige wurde
fuer die Entitaet einmal von Hand eingestellt. Dann gewinnt die manuelle
Einstellung und muss in den Entitaetsoptionen zurueckgesetzt werden.

**Starker Upstream-Kandidat** — der Fehler betrifft jedes Modell, das
berechnete Sensoren mit Nachkommastellen hat.

## 16. Ein stummes Geraet legte das Polling minutenlang lahm

**Dateien:** `helpers/modbus_client.py`, `coordinator.py`

Gemeldet an der Upstream-Integration, Venus E v3, Firmware 150. Das Debug-Log
zeigt den Ablauf lueckenlos:

```
09:39:17.909  letzte Antwort des Geraets (42021)      <- ab hier: 0 Antworten
09:39:18.06   Read 43000 raus ................ nie beantwortet
09:39:25.375  Automation schreibt force_mode + set_charge_power
09:39:28.000  wait_for(10 s) bricht den 43000-Read ab
...           28 Reads + 7 Bloecke, jeder volle 10 s
09:46:04.543  "All read attempts failed (0/28)"  -> sofortiger Reconnect
09:46:04.859  verbunden — alles laeuft wieder, inklusive 43000
```

Dazwischen: keine einzige Antwort, kein einziger Client-Fehler, ein einziger
Poll-Zyklus (`Finished fetching MarstekCoordinator data in 356.622 seconds`).
Das Geraet war nicht defekt — der frische Socket lieferte nach 316 ms wieder
Daten. Der alte Socket war halboffen, und niemand hat ihn ersetzt.

**a) Der aeussere Guard lag unter dem Retry-Budget des Clients.** Der
Coordinator umgibt jeden Aufruf mit `asyncio.wait_for`, upstream fest auf 10 s.
pymodbus wiederholt eine Anfrage aber selbst, `retries=3` per Default, jeder
Versuch gegen den vollen Timeout. Gemessen gegen einen stummen Server:

| pymodbus `retries` | Dauer **eines** Aufrufs bei `timeout=3` |
|---|---|
| 3 (Default) | 12,01 s |
| 0 | 3,00 s |

Ein Aufruf brauchte also laenger als der Guard, der ihn bewachen sollte. Der
Guard hat **immer** zuerst gefeuert und die Transaktion mittendrin abgebrochen —
und eine abgebrochene Transaktion liest ihre Antwort nie, was den Socket genau in
den Zustand bringt, den die Meldung „connection may be half-open" beschreibt.
Das war auch mit dem Timeout-Fix aus Abschnitt 13c noch so: 12 s > 10 s.

Jetzt gibt es nur noch **eine** Retry-Ebene, die dieses Moduls
(`PYMODBUS_RETRIES = 0`). Sie ist die staerkere: pymodbus sendet auf demselben
Socket erneut und behaelt die Transaktions-ID, sodass eine spaet eintreffende
Antwort ohnehin an der ID-Pruefung scheitert — dieser Client baut zwischen zwei
Versuchen die Verbindung neu auf. `request_budget()` gibt an, was ein Aufruf
kosten darf, `_call_guard_timeout()` legt den Guard darueber (plus einen
Connect). Bei 3 s Timeout: Read 15,4 s Budget → 18,4 s Guard, Block 3,0 s →
6,0–6,9 s. Die Blockwerte entsprechen damit weiter Abschnitt 13d.

Die Zahl der pymodbus-internen Versuche liest `_pymodbus_call_cost()` am
lebenden Client ab (`client.ctx.retries`) statt sie aus `PYMODBUS_RETRIES`
anzunehmen: das Attribut ist zwischen pymodbus-Versionen umgezogen, und eine
Version, die das Argument ignoriert, wuerde sonst jedes darauf aufgebaute Budget
zu klein machen — also genau den Fehler wieder herstellen, den dieser Abschnitt
behebt. Gegengeprueft: bei ignoriertem Argument waechst das Read-Budget von 15,4
auf 42,4 s mit.

Gegengemessen an einem Server, der wie im Log stumm bleibt:

| | Ergebnis |
|---|---|
| vorher (`retries=3`, Guard 10 s) | Guard bricht nach 10,00 s ab, **1** Socket — kein Reconnect |
| nachher (`retries=0`, Guard 18,4 s) | Client gibt nach 9,82 s sauber auf, **3** Sockets — zwei Reconnects |

Und antwortet das Geraet auf einer frischen Verbindung wieder, ist der Read nach
**3,41 s** durch statt nach 356 s.

**b) „Half-open" sagen und nichts tun.** Feuert der Guard doch, raeumt
`_async_recover_half_open()` den Socket jetzt an Ort und Stelle ab, statt auf die
Zyklus-Auswertung zu warten. Die greift naemlich erst, wenn ein Zyklus zu Ende
ist — im Log waren das 356 Sekunden — und ihre Quote (≥50 % Timeouts in drei
Zyklen in Folge) wurde dabei kein einziges Mal ausgewertet. Der Reconnect ist auf
einen pro `max(5 s, 2 x Timeout)` gedrosselt, damit ein haengender Zyklus mit
dutzenden Registern keinen Reconnect-Sturm ausloest. Angeschlossen sind alle drei
Stellen, die vorher nur protokolliert haben: Einzelread, Blockread (der laeuft mit
`max_retries=1` und reconnectet nie von selbst) und Write. Der Write-Pfad im
Client baut zwischen zwei Versuchen jetzt ebenfalls neu auf, wie der Read-Pfad es
schon tat; FC06 ist idempotent, ein Wiederholungsschreiben desselben Werts ist
harmlos.

Zaehler `half_open_reconnects` in den Verbindungsattributen.

**c) Der Request, der haengt, stand nicht im Log.** `Requesting single register
…` wurde im Erfolgszweig protokolliert — ausgerechnet die unbeantwortete Anfrage
tauchte also nie auf. Dass es 43000 war, liess sich nur ueber den Zeitstempel des
Timeouts rekonstruieren. Die Zeile steht jetzt vor dem Request, mitsamt
Versuchsnummer; beim Write steht sie innerhalb des Locks, damit der Zeitstempel
den Moment auf der Leitung meint und nicht den Moment des Einreihens.

Dazu: eine unbeantwortete Anfrage ist kein Ausnahmefall. `ModbusIOException`
bekommt eine lesbare Warnung statt eines Tracebacks — bei einem Ausfall waere das
sonst ein Traceback pro Register. Aufgepasst: pymodbus verpackt ein
`CancelledError` in genau diese Exception, der Zweig muss sie also durchlassen,
sonst kann kein Guard die Retry-Schleife mehr stoppen.

**Alle drei Teile sind starke Upstream-Kandidaten** — sie haengen an keinem
Modell und an keinem Register.

### Nachtrag 1.2.1 — der Reconnect kam zu frueh

Ein zweites Log desselben Melders, diesmal mit 1.2.0, zeigt die Erholung wie
gebaut: drei Ausfaelle in 18 Minuten, jeder nach 1–4 Sekunden vorbei, kein
Blackout. Es zeigt aber auch, dass jeder Reconnect zweimal ansetzen musste:

| Abstand zum Schliessen des alten Sockets | Ergebnis |
|---|---|
| ~0 ms | abgelehnt nach ~110 ms |
| ~210 ms | verbunden nach ~310 ms |

Fuenf von fuenf Reconnects liefen so. Das Geraet gibt die alte Sitzung nicht
sofort frei. `RECONNECT_SETTLE_SEC = 0.3` wartet jetzt zwischen Schliessen und
Neuverbinden — nicht beim allererste Connect, dort gibt es nichts freizugeben.
Das spart je Vorfall einen vergeblichen Versuch und zwei Warnungen
(`Failed to connect` / `Reconnect failed`) plus, wenn der Coordinator den
Reconnect angestossen hat, dessen `did not succeed`. Die Wartezeit steckt im
`request_budget`, damit der Guard weiter darueber liegt.

Ausserdem: `Failed to read register … after 1 attempt(s)` ist keine Fehlermeldung
mehr, sondern eine Warnung. Ein Read mit `max_retries=1` ist ein Blockversuch,
fuer den der Coordinator den Einzelread-Fallback schon in der Hand haelt.

**Was bleibt und nicht uns gehoert:** pymodbus protokolliert jede unbeantwortete
Anfrage selbst mit `No response received after 0 retries` auf ERROR. Mit
`retries=0` ist das eine Zeile je Vorfall statt einer je vier. Der Logger
`pymodbus.logging` ist geteilt — auch die eingebaute `modbus`-Integration von
Home Assistant haengt daran —, ein Filter von hier aus wuerde also fremde
Integrationen mit stummschalten. Bleibt stehen.

## 17. Reparatur-Eintrag: das Geraet verlaesst den RS485-Steuermodus von selbst

**Dateien:** `const.py`, `coordinator.py`, `repairs.py` (neu), `__init__.py`,
`translations/{de,en,nl}.json`

Register 42000 schaltet sich auf Firmware 150 selbst ab. Dreimal in drei Logs
desselben Venus E v3 belegt, jedes Mal im selben Moment wie eine
Kommunikationsstoerung und nie nach einem Write der Integration:

```
15:59:49  21930 (an)
16:26:24  Leseausfall 30001
16:26:29  Leseausfall 37004
16:26:33  21947 (aus)      <- ohne dass jemand geschrieben haette
```

Zwischen „an" und „aus" lagen mindestens 26 min 44 s — nah genug an den 30
Minuten, in denen ein zweiter Melder per Ping Verbindungsabrisse ueber
LAN-Kabel misst, um beides als dasselbe Ereignis zu behandeln.

**Warum ein Reparatur-Eintrag und keine Logzeile.** Lesen funktioniert nach dem
Rueckstellen weiter, nur Steuerbefehle laufen ins Leere. Von aussen sieht also
nichts kaputt aus, waehrend die Regelung nichts mehr bewirkt. Der Melder hat
sich das Wiedereinschalten in sein eigenes Steuerskript geschrieben — genau das,
was ein normaler Nutzer nicht kann. Eine Warnung im Log erreicht ihn nicht.

Der Eintrag steht in Einstellungen → System → Reparaturen, ist `is_fixable` und
schreibt nach Bestaetigung 21930 zurueck. **Nicht automatisch**: das ist ein
Schreibzugriff auf ein Steuerregister als Reaktion auf einen Zustand, dessen
Mechanismus noch nicht geklaert ist. Ein Klick ist die Zustimmung.

**Die Erkennung unterscheidet drei Faelle.** Nur ein Wechsel von „an" nach „aus"
zaehlt — ein Modus, der beim Start schon aus ist, ist jemandes Einstellung und
kein Fehler. Ob wir selbst geschaltet haben, entscheidet der **zuletzt von uns
geschriebene Wert**, nicht ein Zeitfenster: nach einem „an" der Reparatur ist
ein zurueckkommendes „aus" das Geraet, das den Befehl verweigert, und muss den
Eintrag erneut ausloesen statt als eigener Write durchzugehen. Dafuer merkt sich
`async_write_value` neben dem Zeitpunkt jetzt auch den Wert
(`_last_write_values`). Der Eintrag verschwindet von selbst, sobald der Modus
wieder an ist, und beim Entladen des Config Entry.

Zehn Faelle sind gegen die echte Coordinator-Methode geprueft (Rueckstellung,
Ruecknahme, Nutzer schaltet selbst aus, aus seit Start, verweigerte Reparatur,
Register nicht im Zyklus, Modell ohne das Register), dazu sechs gegen den
Reparatur-Flow.

**Was nicht belegt ist:** dass Schreibbefehle bei ausgeschaltetem Modus
tatsaechlich wirkungslos sind. Der Melder handelt danach und `README.md` sagt es
fuer den 42000er-Bereich, aber ein direkter Gegentest — Write bei
ausgeschaltetem Modus, Wirkung pruefen — fehlt. Faellt der anders aus, ist der
Text im Reparatur-Eintrag zu entschaerfen, der Mechanismus bleibt richtig.

**Upstream-Kandidat**, sobald 42000 auf einem zweiten Modell so beobachtet wird.
Auf einem Venus D mit Firmware 150 und altem Kommunikationsmodul tritt das
Ruecksetzen nicht auf.

## 18. Regression aus 1.2.x — nebenlaeufige Reconnects und ein Connect-Sturm

**Datei:** `helpers/modbus_client.py`

Gemeldet nach 1.3.0: die Verbindung ging dauerhaft offline, ein Reload half
nicht („Cannot connect to Modbus device"), nur ein kompletter Neustart von Home
Assistant. Der Fehler kommt nicht aus dem Reparatur-Eintrag, sondern aus der
Reconnect-Arbeit von 1.2.0/1.2.1: die hat die Zahl der Reconnect-Aufrufer stark
erhoeht und damit ein latentes Nebenlaeufigkeitsproblem aktiviert.

**a) Jeder wartende Aufrufer riss die frische Verbindung wieder ab.**
`async_reconnect` haelt zwar das `_request_lock`, aber wer dahinter wartet,
baut nach dem Freiwerden seinerseits neu auf — obwohl die Verbindung laengst
wieder steht. Im Log drei Abrisse in 600 ms:

```
21:30:16.541  Connected ... / Reconnected ... / Reconnecting ...
21:30:17.153  Connected ... / Reconnected ... / Reconnecting ...
21:30:17.764  Failed to connect  (Write-Pfad)
21:30:17.764  Connected          (Poll-Pfad, anderer Client)
21:30:17.765  ConnectionException: Not connected[AsyncModbusTcpClient]
```

Die letzte Zeile ist der Beleg: ein Aufrufer las auf `self.client`, den ein
anderer inzwischen ersetzt hatte. **Der Write-Pfad rief `async_connect` sogar
ganz ohne Lock auf** — eine Automation, die alle 10 s schreibt, und der
Poll-Zyklus bauten also gleichzeitig zwei Verbindungen auf.

Jetzt gibt es ein eigenes `_connect_lock` und einen Generationszaehler: wer
nach dem Warten feststellt, dass ein anderer die Verbindung bereits neu
aufgebaut hat, uebernimmt sie, statt sie abzureissen. Gemessen: sechs parallele
`async_reconnect` → **ein** Neuaufbau. Der Write-Pfad geht ueber dasselbe
`_ensure_connected` wie die Reads.

**b) Ein ablehnendes Geraet wurde in Grund und Boden gefragt.** Sobald das
Geraet `ECONNREFUSED` lieferte, forderte jeder Leseversuch einen neuen Socket
an — 61 Verbindungsversuche in einer Minute, ueber drei Minuten hinweg. Bei
einer Bridge mit kleiner Socket-Tabelle haelt genau das sie belegt: der Sturm
verhindert die Erholung, die er erzwingen soll. Das erklaert auch, warum nur ein
HA-Neustart half — er ist die einzige Pause, die das Geraet bekam.

`CONNECT_BACKOFF_BASE_SEC`/`_MAX_SEC` halten den naechsten Versuch nach einem
Fehlschlag zurueck, verdoppelnd von 1 s bis 30 s, zurueckgesetzt bei jedem
Erfolg. Gemessen gegen einen ablehnenden Port: **4 Versuche in 12 Sekunden statt
15**, und die Erholung dauert trotzdem nur 0,3 s, sobald das Geraet wieder
antwortet.

**c) Nebenbefund, nicht behoben:** viermal im Log steht
`request ask for transaction_id=7 but got id=6, Skipping`. Nach einer verlorenen
Antwort liegt der Strom um eine Transaktion versetzt, jede weitere Anfrage
bekommt die Antwort der vorigen. Der Reconnect raeumt das auf (frischer Socket,
frische IDs), und genau das passiert auch. Mit `PYMODBUS_RETRIES = 0` faellt es
nur schneller auf als vorher.

**Lehre fuer Abschnitt 16:** mehr Reconnect-Stellen sind nur dann eine
Verbesserung, wenn der Reconnect selbst serialisiert und gedeckelt ist.
