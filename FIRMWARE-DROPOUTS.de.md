# Warum die Batterie aus dem Netz fällt — und warum diese Integration das nicht beheben kann

**English: [FIRMWARE-DROPOUTS.md](FIRMWARE-DROPOUTS.md)**

Wenn dein Venus alle halbe Stunde für ein paar Sekunden aus Home Assistant
verschwindet, liegt das weder an dieser Integration noch an deinem Netz. Es ist
die Firmware der Batterie, und die Ursache ist inzwischen bis auf die Funktion
genau bekannt.

Dieses Dokument gibt es, weil das Symptom nach einem Modbus-Problem aussieht und
deshalb in den Issues dieses Repos landet. Was die Integration leisten kann, ist
das Überstehen — siehe [Was diese Integration tut](#was-diese-integration-tut).

## Der Mechanismus

Ab Control-Firmware **v150** puffert das Gerät Telemetrie-Datensätze für die
Marstek-Cloud und zählt sie mit. Ist mehr als einer unversendet, wenn ein
1800-Sekunden-Timer abläuft, schließt die Firmware auf einen defekten Netzwerkweg
und **setzt ihren eigenen Netzwerkchip per Hardware zurück**:

```c
if (((1 < *(ushort *)(DAT_08015fcc + 2)) &&
     (Tick_Timer_Check_Elapsed(DAT_0801600c, 0x708) != 0)) &&
    (*_DAT_08016010 == 0)) {
    CH395_Reset_And_Reinit(0);
    log_printf(3, 1, "[HTTP]ch395 reset!!!!");
}
```

Zwei bis drei Sekunden lang ist das Gerät schlicht weg — Modbus-TCP-Sitzungen
sterben, Ping antwortet nicht, danach ist alles wieder da. In festem Takt,
dauerhaft.

| | Ethernet (CH395) | WLAN (FC41D) |
|---|---|---|
| Timer | 1800 s (30 min) | 900 s (15 min) |
| nötiger Rückstau | mehr als 1 Datensatz | jeder Datensatz |

**WLAN ist die härtere Variante, nicht die mildere.** Ein Wechsel des Anschlusses
umgeht das Problem also nicht.

Betroffen ist, wessen Batterie die Marstek-Cloud nicht erreicht — abgeschottetes
IoT-VLAN, DNS-Sperrliste, Störung auf deren Seite. Wer sie offline hält, bekommt
die Resets; das ist der Handel.

## Was diese Integration tut

Den Reset verhindern kann sie nicht. Sie kann schnell zurückkommen, statt hängen
zu bleiben — und genau darum ging es in den Versionen 1.2.0 bis 1.3.2:

- Der Lese-Wächter läuft nicht mehr ab, bevor pymodbus seine eigene
  Wiederholungskette beendet hat. Das hat die Integration früher minutenlang
  eingefroren.
- Reconnects laufen serialisiert: Ein Dutzend wartender Aufrufer erzeugt einen
  Neuaufbau statt sich gegenseitig die Verbindung abzureißen.
- Ein fehlgeschlagener Verbindungsversuch wartet, statt ein Gerät zu bombardieren,
  das noch im Reset steckt.
- Halboffene Sockets werden erkannt und ersetzt.

Gemessen am Venus E v3 eines Nutzers: Die Ausfälle kommen weiterhin, aber die
Integration ist nach Sekunden statt Minuten zurück und braucht dafür keinen
Neustart von Home Assistant mehr.

## Das zweite v150-Symptom: vier Sekunden Pause bei jedem Upload

Vom Reset unabhängig — und von außerhalb der Batterie nicht behebbar.

v150 hat den Telemetrie-Upload von Klartext-HTTP auf TLS umgestellt: v149.2
schickte ihn offen an `hamedata.com`, v150 per HTTPS an
`api-eu.marstekcloud.com`, und der gesamte TLS-Code ist neu in dieser Version.
Jeder Upload kostet das Gerät damit einen Schlüsselaustausch, der auf diesem
Mikrocontroller rund vier Sekunden dauert — und in dieser Zeit **beantwortet es
keinen Modbus**. Ping und ARP laufen weiter, daran erkennt man den Unterschied zu
einem Chip-Reset.

Gemessen über 11,7 Stunden an einem Venus D mit leerem Puffer:

| | |
|---|---|
| Modbus-Lücken länger als 3,5 s | **141** — 12,0 pro Stunde |
| TLS-Handshakes im selben Zeitraum | **141** |
| Lücken, die mit einem Handshake zusammenfallen | **141 von 141** |

Zwölf pro Stunde ist einer pro Telemetrie-Datensatz, also einer pro Upload.

**Praktische Folge: Ein Antwort-Timeout unter etwa 8 Sekunden erzeugt auf v150
alle fünf Minuten einen Fehler** — mit oder ohne Cloud-Zugang, mit oder ohne diese
Integration. Wer eine Warnung im Fünf-Minuten-Takt sieht, während die Batterie
durchgehend auf Ping antwortet, hat genau das: keinen Ausfall, und nichts, das
sich durch Wiederholen lösen ließe.

## Das zweite Symptom: der RS485-Steuermodus schaltet sich ab

Register **42000** (`rs485_control_mode`) springt gelegentlich von `21930` auf
`21947`, und die Batterie nimmt danach keine Leistungssollwerte mehr an, bis der
Wert zurückgeschrieben wird. Beobachtet an Venus E v3 **und** Venus D, jeweils im
selben Zeitfenster wie eine Kommunikationsstörung, ohne dass im Log ein Schreiben
aus Home Assistant zu finden wäre.

Seit 1.3.0 erkennt die Integration das und legt einen **Reparatur**-Eintrag an,
der anbietet, den Modus wieder einzuschalten. Geschrieben wird, weil jemand einen
Knopf gedrückt hat — nicht still im Hintergrund, denn der Mechanismus hinter dem
Rücksprung ist noch nicht vollständig verstanden.

Zu wissen wäre außerdem: 42000 und 43000 sind in der Firmware **dasselbe Byte**,
nur über zwei Adressen erreichbar.

## Wie die Ausfälle aufhören

Ohne Firmware-Eingriff gibt es genau einen Weg: der Batterie etwas geben, das
ihren Telemetrie-Upload beantwortet. Ein Container, der genau das tut, samt
Schritt-für-Schritt-Anleitung auf Deutsch und Englisch:

**<https://github.com/sphings79/Marstek-offline-endpoint>**

Bestätigt an einem Venus D am 26. August 2026: sieben Stunden ohne einen einzigen
Ausfall, gegen einen vorherigen Takt von einem alle 1824 Sekunden. Die Telemetrie
bleibt als Nebeneffekt auf dem eigenen Rechner.

Einen Container zu bauen, den das Gerät **akzeptiert**, war schwieriger als
gedacht: Eine funktional gleichwertige Antwort wird abgelehnt, und der Unterschied
liegt in HTTP-Kopfzeilen, die der Firmware eigentlich egal sein müssten. Diese
Geschichte, samt vier Irrwegen, steht in
[HOW-WE-FOUND-IT.md](https://github.com/sphings79/Marstek-offline-endpoint/blob/main/docs/HOW-WE-FOUND-IT.md).

## Firmware-Analyse

Adressen, Bedingungen und die vollständige Aufrufkette:
<https://github.com/sphings79/marstek_venus_modbus_dev/issues/2>
