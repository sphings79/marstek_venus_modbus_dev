# Why the battery drops off the network — and why this integration cannot fix it

**Deutsch: [FIRMWARE-DROPOUTS.de.md](FIRMWARE-DROPOUTS.de.md)**

If your Venus disappears from Home Assistant every half hour for a few seconds,
that is not this integration and not your network. It is the battery's own
firmware, and the cause is now understood down to the function that does it.

This document exists because the symptom looks like a Modbus problem, so it lands
in this repo's issues. What the integration *can* do is survive it — see
[What this integration does about it](#what-this-integration-does-about-it).

## The mechanism

On Control firmware **v150** the device buffers telemetry records destined for
Marstek's cloud and counts them. If more than one is still unsent when a
1800-second timer expires, the firmware concludes the network path is broken and
**hardware-resets its own network chip**:

```c
if (((1 < *(ushort *)(DAT_08015fcc + 2)) &&
     (Tick_Timer_Check_Elapsed(DAT_0801600c, 0x708) != 0)) &&
    (*_DAT_08016010 == 0)) {
    CH395_Reset_And_Reinit(0);
    log_printf(3, 1, "[HTTP]ch395 reset!!!!");
}
```

For two to three seconds the device is simply gone — Modbus TCP sessions die,
ping stops answering, then everything returns. On a fixed rhythm, indefinitely.

| | Ethernet (CH395) | WiFi (FC41D) |
|---|---|---|
| timer | 1800 s (30 min) | 900 s (15 min) |
| backlog needed | more than 1 record | any record |

**WiFi is the harsher variant, not the milder one.** Switching the battery to
WiFi is not a way around this.

So this hits you if the battery cannot reach Marstek's cloud — a firewalled IoT
VLAN, a DNS blocklist, an outage on their side. Keep it offline and you get the
resets; that is the trade.

## What this integration does about it

It cannot prevent the reset. What it can do is come back quickly instead of
hanging, and releases 1.2.0 through 1.3.2 are largely about exactly that:

- the read guard no longer expires before pymodbus has finished its own retry
  ladder, which used to freeze the integration for minutes at a time
- reconnects are serialised, so a dozen waiting callers produce one rebuild
  instead of tearing down each other's connections
- a failed connect backs off instead of hammering a device that is still in
  reset
- half-open sockets are detected and recycled

The practical result, measured on a user's Venus E v3: dropouts still happen, but
the integration is back within seconds rather than minutes, and no longer needs a
Home Assistant restart to recover.

## The other v150 symptom: a four-second stall on every upload

Separate from the reset, and it cannot be fixed by anything outside the battery.

v150 moved the telemetry upload from plain HTTP to TLS — v149.2 sent it in the
clear to `hamedata.com`, v150 sends it to `api-eu.marstekcloud.com` over HTTPS,
and the entire TLS session code is new in that release. So every upload now costs
the device a key exchange, and on this MCU that takes about four seconds, during
which it **stops answering Modbus**. It keeps answering ping and ARP throughout,
which is how you tell it apart from a chip reset.

Measured over 11.7 hours on a Venus D with a drained buffer:

| | |
|---|---|
| Modbus gaps longer than 3.5 s | **141** — 12.0 per hour |
| TLS handshakes in the same window | **141** |
| gaps coinciding with a handshake | **141 of 141** |

Twelve an hour is one per telemetry record, which is one per upload.

**Practical consequence: a Modbus response timeout under about 8 seconds will
produce an error every five minutes on v150**, with or without cloud access, with
or without this integration. If you see a warning on a five-minute rhythm and the
battery answers ping throughout, that is this — not a dropout, and not something
the integration can retry its way out of.

## The other symptom: RS485 control mode switching itself off

Register **42000** (`rs485_control_mode`) sometimes flips from `21930` to `21947`
on its own, and the battery stops accepting power setpoints until it is written
back. This has been observed on both Venus E v3 and Venus D, in the same window
as a communication failure, with no write from Home Assistant anywhere in the
log.

Since 1.3.0 the integration notices this and raises a **Repair** entry offering
to switch it back on. The write happens because somebody pressed a button, not
silently in the background — the mechanism behind the reset is still not fully
understood.

Note that 42000 and 43000 are the **same byte** in firmware, reachable at two
addresses.

## Making the dropouts stop

The only way to stop them without patching firmware is to give the battery
something that answers its telemetry upload. A container that does exactly that,
including a step-by-step setup guide in English and German:

**<https://github.com/sphings79/Marstek-offline-endpoint>**

Confirmed on a Venus D on 26 August 2026: seven hours without a single dropout,
against a previous rhythm of one every 1824 s. The telemetry stays on your own
machine as a side effect.

Getting a container the device *accepts* turned out to be harder than expected —
a functionally equivalent reply is rejected, and the difference is in HTTP headers
the firmware never should have cared about. That story, including four wrong
turns, is in
[HOW-WE-FOUND-IT.md](https://github.com/sphings79/Marstek-offline-endpoint/blob/main/docs/HOW-WE-FOUND-IT.md).

## Firmware analysis

Addresses, conditions and the full call chain:
<https://github.com/sphings79/marstek_venus_modbus_dev/issues/2>
