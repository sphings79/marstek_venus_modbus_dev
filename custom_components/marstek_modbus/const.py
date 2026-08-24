# Integration domain name
DOMAIN = "marstek_modbus"

# Manufacturer and model information for the Marstek Venus battery
MANUFACTURER = "Marstek"
MODEL = "Venus"

# Default network configuration for Modbus connection
DEFAULT_PORT = 502
DEFAULT_MESSAGE_WAIT_MS = 80  # Default wait time for Modbus messages in milliseconds
CONF_MESSAGE_WAIT_MS = "message_wait_milliseconds"
DEFAULT_UNIT_ID = 1  # Default Modbus Unit ID (unit ID)
DEFAULT_TIMEOUT = 3  # Default Modbus request timeout in seconds

# General scan intervals (in seconds)
DEFAULT_SCAN_INTERVALS = {
    "high": 10,      # fast-changing sensors and former medium-priority sensors
    "low": 60,       # slower-changing sensors and former very_low-priority sensors
}

# Supported device versions
SUPPORTED_VERSIONS = [
    "E v1/v2", 
    "E v3",
    "D",
    "A"]

# Note: register loading logic (get_registers) was moved to
# `coordinator.py` to keep `const.py` focused on constants only.

# Optionsschluessel fuer die DEV-Register. Getrennt schaltbar, weil die beiden
# Gruppen unterschiedlichen Zwecken dienen:
#   unknown   - Register ohne geklaerte Bedeutung (117)
#   duplicate - Register, die denselben Wert liefern wie ein bereits
#               integrierter Sensor: Aliase, Spiegel, Folgeregister (14)
CONF_DEV_REGISTERS_UNKNOWN = "dev_registers_unknown"
CONF_DEV_REGISTERS_DUPLICATE = "dev_registers_duplicate"
DEFAULT_DEV_REGISTERS = False

# Alter Sammelschalter aus 1.1.5-beta.1. Wird nur noch gelesen, um bestehende
# Konfigurationen zu migrieren: war er an, gelten beide neuen Optionen als an.
CONF_DEV_REGISTERS_LEGACY = "dev_registers"

# Steuermodus (Register 42000). Der Firmware-Write-Handler zeigt, was dahinter
# steckt: 42000 und 43000 schreiben dieselbe Variable. `42000 = 0x55AA` setzt das
# Modus-Byte auf 0x0A, `0x55BB` holt den gespeicherten Modus aus EEPROM 0x301
# zurueck, und die drei Optionen von 43000 schreiben 0x01/0x00/0x05 — keine davon
# ist 0x0A. Zwei Bedienelemente, ein Zustand.
#
# Faellt das Byte auf einen normalen Betriebsmodus zurueck, ignoriert die
# Regelung `force_mode`. Schreibbefehle werden weiter bestaetigt und Messwerte
# weiter geliefert, das Geraet fuehrt nur nichts mehr aus — am Venus D gemessen:
# laufende Entladung 605 W -> 12 W (Eigenverbrauch des Wechselrichters). Der
# Ausfall ist also unsichtbar, bis jemand merkt, dass die Regelung nichts
# bewirkt. Deshalb ein Reparatur-Eintrag statt einer Logzeile.
RS485_CONTROL_MODE_KEY = "rs485_control_mode"
ISSUE_RS485_CONTROL_MODE_RESET = "rs485_control_mode_reset"

