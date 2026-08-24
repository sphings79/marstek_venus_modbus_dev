"""
Helper module for Modbus TCP communication using pymodbus.
Provides an abstraction for reading and writing registers from
a Marstek Venus battery system asynchronously.
"""

from pymodbus.client.tcp import AsyncModbusTcpClient
from pymodbus.exceptions import ModbusIOException
import asyncio
import socket
from typing import Optional

import logging

from ..const import DEFAULT_MESSAGE_WAIT_MS, DEFAULT_TIMEOUT, DEFAULT_UNIT_ID

_LOGGER = logging.getLogger(__name__)

# pymodbus retries a request internally before it gives up, each attempt against
# the full timeout — with its default of 3 a single call can occupy 4 x timeout.
# That second retry ladder is both invisible from here and weaker than the one in
# this module: it re-sends on the same socket, keeps the transaction id, and a
# late response then fails the id check anyway. Ours reconnects between attempts.
# One ladder, ours: a pymodbus call is one attempt and costs at most one timeout,
# which is what `request_budget` promises its callers.
PYMODBUS_RETRIES = 0

# The device does not accept a new session the instant the old one goes away.
# Measured on a Venus E v3 (EMS 150), five reconnects in one log, every one the
# same shape: a connect started right after the close was refused after ~110 ms,
# and the retry ~100 ms later then succeeded in ~310 ms. Waiting here turns two
# attempts and two warnings into one attempt that works.
RECONNECT_SETTLE_SEC = 0.3


class MarstekModbusClient:
    """
    Wrapper for pymodbus AsyncModbusTcpClient with helper methods
    for async reading/writing and interpreting common data types.
    """

    def __init__(self, host: str, port: int, message_wait_ms: int = DEFAULT_MESSAGE_WAIT_MS, timeout: int = DEFAULT_TIMEOUT, unit_id: int = DEFAULT_UNIT_ID):
        """
        Initialize Modbus client with host, port, message wait time, timeout, and unit ID.

        Args:
            host (str): IP address or hostname of Modbus server.
            port (int): TCP port number.
            message_wait_ms (int): Delay in ms between Modbus messages.
            timeout (int): Connection timeout in seconds (default 3 for faster failure).
            unit_id (int): Modbus Unit ID (slave ID), default is 1.
        """
        self.host = host
        self.port = port

        # Normalize and guard the timeout. The config flow has no timeout field,
        # so entry.data.get("timeout") is None for every entry created through
        # the UI — and pymodbus reads None as "wait forever", which turns a
        # single unanswered request into a hanging poll cycle.
        try:
            self.timeout = float(timeout) if timeout is not None else float(DEFAULT_TIMEOUT)
            if self.timeout <= 0:
                raise ValueError
        except (TypeError, ValueError):
            self.timeout = float(DEFAULT_TIMEOUT)

        # Normalize and guard message_wait_ms so it is never None
        self.message_wait_ms = int(message_wait_ms) if message_wait_ms is not None else DEFAULT_MESSAGE_WAIT_MS

        # Precompute seconds sleep to avoid repeated float(None) errors
        try:
            self.message_wait_sec = max(0.0, float(self.message_wait_ms) / 1000.0)
        except (TypeError, ValueError):
            self.message_wait_sec = float(DEFAULT_MESSAGE_WAIT_MS) / 1000.0

        # Create pymodbus async TCP client instance
        self.client = AsyncModbusTcpClient(
            host=host,
            port=port,
            timeout=self.timeout,
            retries=PYMODBUS_RETRIES,
        )

        # set message wait on client if supported
        try:
            self.client.message_wait_milliseconds = self.message_wait_ms
        except AttributeError:
            pass

        # Normalize and guard unit_id so it is never None
        try:
            self.unit_id = int(unit_id)
        except (TypeError, ValueError):
            self.unit_id = DEFAULT_UNIT_ID

        # Lock to serialize outgoing Modbus requests to avoid transaction id collisions
        self._request_lock = asyncio.Lock()

        # Smart transport state for request pacing and diagnostics
        self.wait_between_requests = self.message_wait_sec
        self._last_request_finished_at: float | None = None
        self._last_request_duration: float | None = None
        # True once a connection has succeeded, so the settle delay before a
        # reconnect is not paid on the very first connect.
        self._connected_once = False

    def _pymodbus_call_cost(self) -> float:
        """Return the worst-case duration of one call into pymodbus.

        Read back off the live client rather than assumed from
        `PYMODBUS_RETRIES`: the attribute moved between pymodbus releases, and a
        version that ignores or clamps the argument would otherwise make every
        budget built on top of this too small. pymodbus keeps the count on the
        transaction manager (`client.ctx.retries`) and spends the full timeout on
        each of its `retries + 1` attempts.
        """
        retries = None
        for holder in (getattr(self.client, "ctx", None), self.client):
            candidate = getattr(holder, "retries", None)
            if candidate is not None:
                retries = candidate
                break
        try:
            attempts = 1 + max(0, int(retries if retries is not None else PYMODBUS_RETRIES))
        except (TypeError, ValueError):
            attempts = 1 + max(0, PYMODBUS_RETRIES)
        return attempts * self.timeout

    def request_budget(self, max_retries: int = 3, retry_delay: float = 0.0) -> float:
        """Return how long one read or write call may legitimately take.

        Counts every attempt against the client timeout and, between two
        attempts, the retry delay, the pacing gap and one reconnect — a
        reconnect is a connect and runs against the same timeout.

        Callers guard these calls with their own `asyncio.wait_for`. That guard
        has to sit *above* this value: a guard that fires first cancels a
        transaction the client is still working on, and the request whose
        response never gets read is exactly what leaves the socket half-open.
        """
        attempts = max(1, int(max_retries or 1))
        try:
            delay = max(0.0, float(retry_delay))
        except (TypeError, ValueError):
            delay = 0.0

        per_call = self._pymodbus_call_cost()

        # Between two attempts: the retry delay, the pacing gap, and a reconnect —
        # which is the settle wait plus a connect against the same timeout.
        between_attempts = delay + self.message_wait_sec + RECONNECT_SETTLE_SEC + self.timeout
        return attempts * per_call + (attempts - 1) * between_attempts

    async def _async_wait_for_request_slot(self) -> None:
        """Keep at least `message_wait_ms` between two Modbus transactions.

        The gap is measured from the end of the previous request, so a single
        wait per transaction is enough — an extra sleep after the response
        would only double the pause without giving the device more time.
        """
        if self.wait_between_requests <= 0 or self._last_request_finished_at is None:
            return
        wait_time = self.wait_between_requests - (
            asyncio.get_running_loop().time() - self._last_request_finished_at
        )
        if wait_time > 0:
            await asyncio.sleep(wait_time)

    def _mark_request_finished(self, request_start: float | None = None) -> None:
        """Record when the current transaction finished, for request pacing."""
        self._last_request_finished_at = asyncio.get_running_loop().time()
        if request_start is not None:
            self._last_request_duration = self._last_request_finished_at - request_start

    async def async_connect(self) -> bool:
        """
        Connect asynchronously to the Modbus TCP server.

        Returns:
            bool: True if connection succeeded, False otherwise.
        """
        # Always create a fresh client instance to avoid reusing internal
        # buffers/state that may be left in an inconsistent state after
        # network interruptions. This reduces "extra data" / parse errors
        # and stale transaction id problems.
        try:
            # Close and discard any existing client first
            replacing_a_session = self._connected_once
            if self.client:
                try:
                    result = self.client.close()
                    if asyncio.iscoroutine(result):
                        await result
                except Exception:
                    pass

            if replacing_a_session:
                # Give the device a moment to let go of the old session before
                # asking for a new one; see RECONNECT_SETTLE_SEC. Skipped on the
                # very first connect, where there is nothing to let go of.
                await asyncio.sleep(RECONNECT_SETTLE_SEC)

            # Create a new client instance
            self.client = AsyncModbusTcpClient(
                host=self.host,
                port=self.port,
                timeout=self.timeout,
                retries=PYMODBUS_RETRIES,
            )
            # restore configured properties where supported
            try:
                self.client.message_wait_milliseconds = self.message_wait_ms
            except Exception:
                pass

            connected = await self.client.connect()

            if connected:
                self._connected_once = True
                # Small settle time so the device has time to flush and be ready
                await asyncio.sleep(max(0.2, self.message_wait_sec))
                # Enable TCP keepalive so the OS probes dead connections quickly
                # rather than waiting hours for the default kernel timeout.
                try:
                    transport = getattr(self.client, "transport", None)
                    if transport is not None:
                        sock = transport.get_extra_info("socket")
                        if sock is not None:
                            sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
                            if hasattr(socket, "TCP_KEEPIDLE"):
                                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 60)
                            if hasattr(socket, "TCP_KEEPINTVL"):
                                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 10)
                            if hasattr(socket, "TCP_KEEPCNT"):
                                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 3)
                            _LOGGER.debug("TCP keepalive enabled on Modbus socket")
                except Exception as ke:
                    _LOGGER.debug("Could not set TCP keepalive: %s", ke)
                _LOGGER.info(
                    "Connected to Modbus server at %s:%s with unit %s",
                    self.host,
                    self.port,
                    self.unit_id,
                )
            else:
                _LOGGER.warning(
                    "Failed to connect to Modbus server at %s:%s with unit %s",
                    self.host,
                    self.port,
                    self.unit_id,
                )

            return bool(connected)
        except Exception as e:
            _LOGGER.exception("Exception while connecting to Modbus server: %s", e)
            return False

    async def async_close(self) -> None:
        """
        Close the Modbus TCP connection safely (sync or async)
        and reset client reference.
        """
        if not self.client:
            return

        try:
            result = self.client.close()
            if asyncio.iscoroutine(result):
                await result
            _LOGGER.debug("Modbus client closed successfully")
        except Exception as e:
            _LOGGER.debug("Error closing Modbus client: %s", e)
        finally:
            # Ensure client reference is cleared so future connect creates fresh instance
            self.client = None

    async def _reset_client(self) -> None:
        """Close the current client and clear the reference."""
        if self.client:
            try:
                result = self.client.close()
                if asyncio.iscoroutine(result):
                    await result
            except Exception as err:
                _LOGGER.debug("Error closing stale Modbus client: %s", err)
        self.client = None

    async def _ensure_connected(self) -> bool:
        """Ensure there is an active Modbus connection, reconnecting if needed."""
        if self.is_connected:
            return True
        return await self.async_reconnect()

    @property
    def is_connected(self) -> bool:
        """Return True when the wrapped pymodbus client is currently connected."""
        try:
            return bool(self.client and getattr(self.client, "connected", False))
        except Exception:
            return False

    async def async_reconnect(self) -> bool:
        """Reconnect to the Modbus TCP server by closing and re-opening the connection."""
        async with self._request_lock:
            _LOGGER.info("Reconnecting to Modbus server at %s:%s", self.host, self.port)

            try:
                try:
                    await self.async_close()
                except Exception as e:
                    _LOGGER.debug("Error closing Modbus client during reconnect: %s", e)

                try:
                    connected = await self.async_connect()
                except Exception as e:
                    _LOGGER.warning(
                        "Exception while reconnecting to Modbus server at %s:%s: %s",
                        self.host,
                        self.port,
                        e,
                    )
                    return False

                if connected:
                    _LOGGER.info("Reconnected to Modbus server at %s:%s", self.host, self.port)
                else:
                    _LOGGER.warning("Reconnect failed to Modbus server at %s:%s", self.host, self.port)

                return connected
            except Exception as e:
                _LOGGER.warning("Unhandled exception during reconnect: %s", e)
                return False

    @staticmethod
    def _default_count_for_data_type(data_type: str) -> int:
        """Return the default register count for a given data type."""
        if data_type in {"int32", "uint32", "ipv4"}:
            return 2
        if data_type == "schedule":
            return 5
        return 1

    def _decode_registers(
        self,
        register: int,
        regs: list[int],
        data_type: str = "uint16",
        bit_index: Optional[int] = None,
    ):
        """Decode raw holding registers into the requested data type."""
        if data_type == "int16":
            val = regs[0]
            return val - 0x10000 if val >= 0x8000 else val

        if data_type == "uint16":
            return regs[0]

        if data_type == "int32":
            if len(regs) < 2:
                _LOGGER.warning(
                    "Expected 2 registers for int32 at register %d (0x%04X), got %s",
                    register,
                    register,
                    len(regs),
                )
                return None
            val = (regs[0] << 16) | regs[1]
            return val - 0x100000000 if val >= 0x80000000 else val

        if data_type == "uint32":
            if len(regs) < 2:
                _LOGGER.warning(
                    "Expected 2 registers for uint32 at register %d (0x%04X), got %s",
                    register,
                    register,
                    len(regs),
                )
                return None
            return (regs[0] << 16) | regs[1]

        if data_type == "char":
            byte_array = bytearray()
            for reg in regs:
                byte_array.append((reg >> 8) & 0xFF)
                byte_array.append(reg & 0xFF)
            null_pos = byte_array.find(0)
            if null_pos >= 0:
                byte_array = byte_array[:null_pos]
            return byte_array.decode("ascii", errors="ignore")

        if data_type == "mac":
            byte_array = bytearray()
            for reg in regs:
                byte_array.append((reg >> 8) & 0xFF)
                byte_array.append(reg & 0xFF)

            null_pos = byte_array.find(0)
            if null_pos >= 0:
                byte_array = byte_array[:null_pos]

            try:
                ascii_value = byte_array.decode("ascii", errors="strict").strip()
            except UnicodeDecodeError:
                ascii_value = ""

            if len(ascii_value) == 12 and all(ch in "0123456789abcdefABCDEF" for ch in ascii_value):
                return ":".join(
                    ascii_value[index:index + 2].upper()
                    for index in range(0, 12, 2)
                )

            return ":".join(f"{byte:02X}" for byte in byte_array)

        if data_type == "ipv4":
            if len(regs) < 2:
                _LOGGER.warning(
                    "Expected 2 registers for ipv4 at register %d (0x%04X), got %s",
                    register,
                    register,
                    len(regs),
                )
                return None
            # Each register carries two octets, high byte first:
            # 30400 = 192.168 -> 0xC0A8, 30401 = 181.154 -> 0xB59A
            octets = (
                (regs[0] >> 8) & 0xFF,
                regs[0] & 0xFF,
                (regs[1] >> 8) & 0xFF,
                regs[1] & 0xFF,
            )
            return ".".join(str(octet) for octet in octets)

        if data_type == "schedule":
            if len(regs) < 5:
                _LOGGER.warning(
                    "Expected 5 registers for schedule at %d (0x%04X), got %s",
                    register,
                    register,
                    len(regs),
                )
                return None
            mode_raw = int(regs[3])
            mode_signed = mode_raw - 0x10000 if mode_raw >= 0x8000 else mode_raw
            return {
                "days": int(regs[0]),
                "start": int(regs[1]),
                "end": int(regs[2]),
                "mode": mode_signed,
                "enabled": int(regs[4]),
            }

        if data_type == "bit":
            if bit_index is None or not (0 <= bit_index < 16):
                raise ValueError("bit_index must be between 0 and 15 for bit data_type")
            reg_val = regs[0]
            return bool((reg_val >> bit_index) & 1)

        raise ValueError(f"Unsupported data_type: {data_type}")

    async def async_read_holding_registers(
        self,
        register: int,
        count: int,
        sensor_key: Optional[str] = None,
        max_retries: int = 3,
        retry_delay: float = 0.1,
    ) -> list[int] | None:
        """Read raw holding registers asynchronously with retries."""
        if not (0 <= register <= 0xFFFF):
            _LOGGER.error(
                "Invalid register address: %d (0x%04X). Must be 0-65535.",
                register,
                register,
            )
            return None

        if not (1 <= count <= 125):
            _LOGGER.error(
                "Invalid register count: %d. Must be between 1 and 125.",
                count,
            )
            return None

        attempt = 0
        while attempt < max_retries:
            client_connected = False
            try:
                client_connected = bool(self.client and getattr(self.client, "connected", False))
            except Exception:
                client_connected = False

            if not await self._ensure_connected():
                _LOGGER.error(
                    "Modbus client not connected, skipping register %d (0x%04X)",
                    register,
                    register,
                )
                return None

            request_start = asyncio.get_running_loop().time()
            try:
                result = None
                async with self._request_lock:
                    # Pace requests to avoid overwhelming the device.
                    await self._async_wait_for_request_slot()

                    # Log the request before it goes out, not after it came back.
                    # A request that is never answered is the one worth naming,
                    # and logging it from the success branch hides exactly that.
                    if count == 1:
                        _LOGGER.debug(
                            "Requesting single register %d (0x%04X) from '%s' for key '%s' (attempt %d)",
                            register,
                            register,
                            self.host,
                            sensor_key or "unknown",
                            attempt + 1,
                        )
                    else:
                        _LOGGER.debug(
                            "Requesting register block %d-%d (0x%04X-0x%04X) from '%s' for keys '%s' (count: %s, attempt %d)",
                            register,
                            register + count - 1,
                            register,
                            register + count - 1,
                            self.host,
                            sensor_key or "unknown",
                            count,
                            attempt + 1,
                        )

                    try:
                        read_method = getattr(self.client, "read_holding_registers")
                        for unit_kw in ("device_id", "unit", "slave"):
                            try:
                                result = await read_method(address=register, count=count, **{unit_kw: self.unit_id})
                                break
                            except TypeError:
                                result = None
                                continue
                    finally:
                        self._mark_request_finished(request_start)

                if result is None:
                    _LOGGER.error(
                        "No response object returned for register %d (0x%04X) on attempt %d",
                        register,
                        register,
                        attempt + 1,
                    )
                elif getattr(result, "isError", lambda: False)():
                    _LOGGER.error(
                        "Modbus read error at register %d (0x%04X) on attempt %d",
                        register,
                        register,
                        attempt + 1,
                    )
                    if attempt + 1 < max_retries:
                        _LOGGER.debug(
                            "Attempting reconnect after Modbus error response for register %d (0x%04X)",
                            register,
                            register,
                        )
                        await self.async_reconnect()
                elif not hasattr(result, "registers") or result.registers is None or len(result.registers) < count:
                    _LOGGER.warning(
                        "Incomplete data received at register %d (0x%04X) on attempt %d: expected %d registers, got %s",
                        register,
                        register,
                        attempt + 1,
                        count,
                        len(result.registers) if result.registers else 0,
                    )
                    if attempt + 1 < max_retries:
                        _LOGGER.debug(
                            "Attempting reconnect after incomplete response for register %d (0x%04X)",
                            register,
                            register,
                        )
                        await self.async_reconnect()
                else:
                    regs = list(result.registers)
                    if count == 1:
                        _LOGGER.debug(
                            "Received single register data from '%s' for register %d (0x%04X): %s",
                            self.host,
                            register,
                            register,
                            regs,
                        )
                    else:
                        _LOGGER.debug(
                            "Received block data from '%s' for registers %d-%d (0x%04X-0x%04X): %s",
                            self.host,
                            register,
                            register + count - 1,
                            register,
                            register + count - 1,
                            regs,
                        )
                    return regs
            except asyncio.CancelledError:
                raise
            except ModbusIOException as e:
                # pymodbus turns a cancellation into a ModbusIOException, so this
                # branch has to let it through before treating it as a timeout —
                # otherwise a caller's guard cannot stop the retry loop at all.
                cause = getattr(e, "__cause__", None)
                if isinstance(cause, asyncio.CancelledError):
                    raise cause

                # An unanswered request is the expected shape of a failure here,
                # not something exceptional. It gets a readable line instead of a
                # traceback — during an outage this fires once per register.
                _LOGGER.warning(
                    "No response for register %d (0x%04X) on attempt %d: %s",
                    register,
                    register,
                    attempt + 1,
                    e,
                )
                if attempt + 1 < max_retries:
                    await self.async_reconnect()
            except Exception as e:
                cause = getattr(e, "__cause__", None)
                if isinstance(cause, asyncio.CancelledError):
                    raise cause

                _LOGGER.exception(
                    "Exception during Modbus read at register %d (0x%04X) on attempt %d: %s",
                    register,
                    register,
                    attempt + 1,
                    e,
                )
                if attempt + 1 < max_retries:
                    _LOGGER.debug(
                        "Attempting reconnect after exception for register %d (0x%04X)",
                        register,
                        register,
                    )
                    await self.async_reconnect()
            finally:
                # Covers paths that never reached the request itself (e.g. an
                # exception before the lock); the normal case already stamped.
                self._mark_request_finished(request_start)

            attempt += 1
            if attempt < max_retries:
                await asyncio.sleep(retry_delay)

        # A single-attempt read is the caller probing a block; it has an
        # individual-read fallback ready, so this is not an error on its own.
        log = _LOGGER.warning if max_retries <= 1 else _LOGGER.error
        log(
            "Failed to read register %d (0x%04X) after %d attempt(s)",
            register,
            register,
            max_retries,
        )
        return None

    async def async_read_register(
        self,
        register: int,
        data_type: str = "uint16",
        count: Optional[int] = None,
        bit_index: Optional[int] = None,
        sensor_key: Optional[str] = None,
        max_retries: int = 3,
        retry_delay: float = 0.1,
    ):
        """
        Robustly read registers and interpret the data asynchronously with retries.

        Args:
            register (int): Register address to read from.
            data_type (str): Data type for interpretation, e.g. 'int16', 'int32', 'char', 'bit'.
            count (Optional[int]): Number of registers to read (default depends on data_type).
            bit_index (Optional[int]): Bit position for 'bit' data type (0-15).
            sensor_key (Optional[str]): Sensor key for logging.
            max_retries (int): Maximum number of read attempts.
            retry_delay (float): Delay in seconds between retries.

        Returns:
            int, str, bool, or None: Interpreted value or None on error.
        """
        if count is None:
            count = self._default_count_for_data_type(data_type)

        regs = await self.async_read_holding_registers(
            register=register,
            count=count,
            sensor_key=sensor_key,
            max_retries=max_retries,
            retry_delay=retry_delay,
        )
        if regs is None:
            return None

        return self._decode_registers(
            register=register,
            regs=regs,
            data_type=data_type,
            bit_index=bit_index,
        )

    async def async_write_register(
        self,
        register: int,
        value: int,
        max_retries: int = 3,
        retry_delay: float = 0.2,
    ) -> bool:
        """
        Write a single value to a Modbus holding register asynchronously with retries.

        Args:
            register (int): Register address to write to.
            value (int): Value to write.
            max_retries (int): Maximum number of write attempts.
            retry_delay (float): Delay in seconds between retries.

        Returns:
            bool: True if write was successful, False otherwise.
        """
        # Input validation
        if not (0 <= register <= 0xFFFF):
            _LOGGER.error(
                "Invalid register address for write: %d (0x%04X). Must be 0-65535.",
                register,
                register,
            )
            return False

        # Expect caller to supply an already validated/converted 16-bit unsigned value.
        if not isinstance(value, int):
            _LOGGER.error("Invalid value type for write: %s. Must be int.", type(value))
            return False

        if not (0 <= value <= 0xFFFF):
            _LOGGER.error(
                "Invalid value for write: %d. Must be 0-65535.",
                value,
            )
            return False
        value_to_send = value

        attempt = 0
        while attempt < max_retries:
            # Check client connection
            client_connected = False
            try:
                client_connected = bool(
                    self.client and getattr(self.client, "connected", False)
                )
            except Exception:
                client_connected = False

            if not client_connected:
                _LOGGER.warning(
                    "Modbus client not connected, attempting reconnect before write to register %d (0x%04X)",
                    register,
                    register,
                )
                connected = await self.async_connect()
                if not connected:
                    _LOGGER.error(
                        "Reconnect failed, skipping write to register %d (0x%04X)",
                        register,
                        register,
                    )
                    return False

            # Additional safety check
            if self.client is None:
                _LOGGER.error("Modbus Client became None unexpectedly")
                return False

            try:
                result = None
                request_start = asyncio.get_running_loop().time()
                async with self._request_lock:
                    # Same pacing as for reads, so a write does not jump the queue.
                    await self._async_wait_for_request_slot()

                    # Logged from inside the lock, so the timestamp is the moment
                    # the frame goes out rather than the moment the write was
                    # queued behind whatever request is still running.
                    _LOGGER.debug(
                        "Writing to register %d (0x%04X), value=%d (0x%04X), attempt=%d",
                        register,
                        register,
                        value,
                        value,
                        attempt + 1,
                    )

                    try:
                        # Try multiple kwarg names for compatibility
                        for unit_kw in ("device_id", "unit", "slave"):
                            try:
                                result = await self.client.write_register(
                                    address=register, value=value, **{unit_kw: self.unit_id}
                                )
                                break
                            except TypeError:
                                result = None
                                continue
                    finally:
                        self._mark_request_finished(request_start)

                # Check result
                if result is None:
                    _LOGGER.warning(
                        "No response from write to register %d (0x%04X) on attempt %d",
                        register,
                        register,
                        attempt + 1,
                    )
                elif getattr(result, "isError", lambda: False)():
                    _LOGGER.warning(
                        "Modbus write error at register %d (0x%04X) on attempt %d",
                        register,
                        register,
                        attempt + 1,
                    )
                else:
                    _LOGGER.debug(
                        "Write confirmed for register %d (0x%04X), value=%d",
                        register,
                        register,
                        value,
                    )
                    return True

            except asyncio.CancelledError:
                # Allow cancellation to propagate during shutdown
                raise

            except ModbusIOException as e:
                cause = getattr(e, "__cause__", None)
                if isinstance(cause, asyncio.CancelledError):
                    raise cause

                # Same reasoning as on the read side: no response is a plain
                # failure, not a traceback.
                _LOGGER.warning(
                    "No response for the write to register %d (0x%04X) on attempt %d: %s",
                    register,
                    register,
                    attempt + 1,
                    e,
                )
            except Exception as e:
                # If underlying cause is CancelledError, propagate it
                cause = getattr(e, "__cause__", None)
                if isinstance(cause, asyncio.CancelledError):
                    raise cause

                _LOGGER.exception(
                    "Exception during Modbus write at register %d (0x%04X) on attempt %d: %s",
                    register,
                    register,
                    attempt + 1,
                    e,
                )

            attempt += 1
            if attempt < max_retries:
                # A write that timed out or errored leaves the same doubt about
                # the socket as a failed read does, so it gets the same answer:
                # retry on a fresh connection instead of on the suspect one.
                _LOGGER.debug(
                    "Attempting reconnect before write retry for register %d (0x%04X)",
                    register,
                    register,
                )
                await self.async_reconnect()
                await asyncio.sleep(retry_delay)

        _LOGGER.error(
            "Failed to write to register %d (0x%04X) after %d attempts",
            register,
            register,
            max_retries,
        )
        return False