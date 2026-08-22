# Integration domain name
DOMAIN = "marstek_modbus"

# Manufacturer and model information for the Marstek Venus battery
MANUFACTURER = "Marstek"
MODEL = "Venus"

# Default network configuration for Modbus connection
DEFAULT_PORT = 502
DEFAULT_MESSAGE_WAIT_MS = 80  # Default wait time for Modbus messages in milliseconds
DEFAULT_UNIT_ID = 1  # Default Modbus Unit ID (unit ID)

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
