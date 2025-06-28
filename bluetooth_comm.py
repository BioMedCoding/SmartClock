"""
BluetoothCommunication
──────────────────────
• Opens /dev/rfcomm0 (115 200 Bd by default)
• Receives framed sensor packets and pushes dicts into the GUI queue
• Can transmit ON / OFF / PWM commands to actuator nodes

Copy into the same folder as main.py and import normally.
"""

from __future__ import annotations
import serial, queue, struct, time, logging
from typing import Optional

# ────────────── Config – tweak here ─────────────────────────────────────────
BT_PORT          = "/dev/rfcomm0"
BT_BAUD          = 115200
START_BYTE       = 0x55
CRC_POLY         = 0x31        # Dallas/Maxim
ACK_TIMEOUT_S    = 0.3
# ────────────────────────────────────────────────────────────────────────────

def crc8(data: bytes, poly: int = CRC_POLY, init: int = 0) -> int:
    crc = init
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = ((crc << 1) ^ poly) & 0xFF if (crc & 0x80) else (crc << 1) & 0xFF
    return crc

class BluetoothCommunication:
    def __init__(self, data_queue: "queue.Queue[dict]",
                 port: str = BT_PORT, baud: int = BT_BAUD):
        self.port, self.baud = port, baud
        self._ser: Optional[serial.Serial] = None
        self._q   = data_queue
        self._buf = bytearray()
        self._running = False

    # ───────── Public API ───────────────────────────────────────────────────
    def start_communication(self):
        self._open()
        self._running = True
        logging.info("BluetoothCommunication started on %s.", self.port)
        while self._running:
            self._rx_loop()

    def stop(self):
        self._running = False
        if self._ser:
            self._ser.close()

    # Actuator helpers -------------------------------------------------------
    def send_actuator(self, node_id: int, act_id: int,
                      mode: str = "ON", pwm_val: int = 0):
        """mode: 'ON', 'OFF', 'PWM'  (PWM uses pwm_val 0-255)"""
        modes = {"ON": 0x01, "OFF": 0x00, "PWM": 0x02}
        if mode not in modes: raise ValueError("mode must be ON/OFF/PWM")
        payload = struct.pack("BBB", modes[mode], act_id & 0x0F, pwm_val & 0xFF)
        frame   = self._encode_frame(cmd=0x20, node_id=node_id, payload=payload)
        self._ser.write(frame)
        self._ser.flush()
        time.sleep(ACK_TIMEOUT_S)        # give node time to act

    # ───────── Internal ─────────────────────────────────────────────────────
    # framing
    def _open(self):
        self._ser = serial.Serial(self.port, self.baud, timeout=0.2)

    def _rx_loop(self):
        self._buf.extend(self._ser.read(64))
        while len(self._buf) >= 5:                       # header + CRC
            if self._buf[0] != START_BYTE:
                self._buf.pop(0);   continue
            length = self._buf[1]
            if len(self._buf) < length + 3:              # wait for full frame
                return
            frame = bytes(self._buf[:length + 3])
            del self._buf[:length + 3]
            if crc8(frame[1:-1]) != frame[-1]:
                continue                                 # bad CRC → drop
            self._handle(frame[2:-1])                    # strip START & CRC

    def _handle(self, payload: bytes):
        cmd, node_id, rest = payload[0], payload[1], payload[2:]
        if cmd == 0x01:                                  # sensor report
            self._decode_sensor_report(node_id, rest)

    # sensor decoding --------------------------------------------------------
    def _decode_sensor_report(self, node_id: int, data: bytes):
        if not data: return
        n_tlvs, idx = data[0], 1
        type_names = {0: "TEMP", 1: "HUM", 2: "PRESS"}
        for _ in range(n_tlvs):
            if idx + 4 > len(data): break
            t_s, hi, lo, age = data[idx:idx+4]; idx += 4
            s_type, s_num    = t_s >> 4, t_s & 0x0F
            raw              = (hi << 8) | lo
            value            = raw / 10.0
            sensor_type      = type_names.get(s_type, "GEN")
            sensor_id        = f"{sensor_type}_{node_id:02d}_{s_num}"
            self._q.put({"sensor_id": sensor_id, "value": value})

    # encoder ----------------------------------------------------------------
    @staticmethod
    def _encode_frame(cmd: int, node_id: int, payload: bytes = b"") -> bytes:
        body  = bytes([cmd & 0xFF, node_id & 0xFF]) + payload
        frame = bytes([START_BYTE, len(body)]) + body
        crc   = crc8(frame[1:])            # over LEN..payload
        return frame + bytes([crc])
