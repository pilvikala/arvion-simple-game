from __future__ import annotations

import json
import socket
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple


def _encode(data: dict) -> bytes:
    return (json.dumps(data) + "\n").encode("utf-8")


def _decode(line: str) -> dict:
    return json.loads(line)


@dataclass
class TankSnapshot:
    player_id: str
    position: Tuple[float, float]
    angle: float
    color: Tuple[int, int, int]


@dataclass
class ClientRecord:
    socket: socket.socket
    color: Tuple[int, int, int]
    buffer: str = ""


class ServerNetwork:
    def __init__(self, host: str, port: int, palette: Iterable[Tuple[int, int, int]]):
        self.host = host
        self.port = port
        self._palette_cache: List[Tuple[int, int, int]] = list(palette)
        if not self._palette_cache:
            raise ValueError("Palette must contain at least one color")

        self._color_index = 0
        self._lock = threading.Lock()
        self._connections: Dict[str, ClientRecord] = {}
        self._remote_states: Dict[str, TankSnapshot] = {}
        self._local_state: Optional[TankSnapshot] = None
        self._running = False
        self._accept_thread: Optional[threading.Thread] = None
        self._broadcast_thread: Optional[threading.Thread] = None
        self._socket: Optional[socket.socket] = None

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._socket.bind((self.host, self.port))
        self._socket.listen(5)
        self._accept_thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._accept_thread.start()
        self._broadcast_thread = threading.Thread(target=self._broadcast_loop, daemon=True)
        self._broadcast_thread.start()

    def shutdown(self) -> None:
        self._running = False
        if self._socket:
            try:
                self._socket.close()
            except OSError:
                pass
        with self._lock:
            for record in list(self._connections.values()):
                try:
                    record.socket.close()
                except OSError:
                    pass
            self._connections.clear()

    def update_local_state(
        self,
        player_id: str,
        position: Tuple[float, float],
        angle: float,
        color: Tuple[int, int, int],
    ) -> None:
        snapshot = TankSnapshot(player_id=player_id, position=position, angle=angle, color=color)
        with self._lock:
            self._local_state = snapshot

    def get_remote_states(self, exclude_id: Optional[str] = None) -> Dict[str, TankSnapshot]:
        with self._lock:
            states = dict(self._remote_states)
        if exclude_id and exclude_id in states:
            states.pop(exclude_id, None)
        return states

    def _next_color(self) -> Tuple[int, int, int]:
        color = self._palette_cache[self._color_index % len(self._palette_cache)]
        self._color_index += 1
        return color

    def _accept_loop(self) -> None:
        assert self._socket is not None
        while self._running:
            try:
                client_sock, _addr = self._socket.accept()
            except OSError:
                if not self._running:
                    break
                continue
            client_sock.setblocking(True)
            player_id = uuid.uuid4().hex[:8]
            color = self._next_color()
            record = ClientRecord(socket=client_sock, color=color, buffer="")
            with self._lock:
                self._connections[player_id] = record
                self._remote_states[player_id] = TankSnapshot(
                    player_id=player_id,
                    position=(0.0, 0.0),
                    angle=0.0,
                    color=color,
                )
            assign_msg = {"type": "assign", "player_id": player_id, "color": color}
            try:
                client_sock.sendall(_encode(assign_msg))
            except OSError:
                self._remove_client(player_id)
                continue
            threading.Thread(
                target=self._client_loop, args=(player_id,), daemon=True
            ).start()

    def _client_loop(self, player_id: str) -> None:
        client = self._connections.get(player_id)
        if not client:
            return
        sock = client.socket
        buffer = client.buffer
        try:
            while self._running:
                data = sock.recv(4096)
                if not data:
                    break
                buffer += data.decode("utf-8")
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    if not line.strip():
                        continue
                    self._handle_message(player_id, line)
        except OSError:
            pass
        finally:
            self._remove_client(player_id)

    def _handle_message(self, player_id: str, line: str) -> None:
        try:
            payload = _decode(line)
        except json.JSONDecodeError:
            return
        if payload.get("type") != "update":
            return
        position = payload.get("position")
        angle = payload.get("angle")
        if not isinstance(position, list) or len(position) != 2:
            return
        if not isinstance(angle, (int, float)):
            return
        with self._lock:
            snapshot = self._remote_states.get(player_id)
            if not snapshot:
                color = self._next_color()
            else:
                color = snapshot.color
            self._remote_states[player_id] = TankSnapshot(
                player_id=player_id,
                position=(float(position[0]), float(position[1])),
                angle=float(angle),
                color=color,
            )

    def _broadcast_loop(self) -> None:
        while self._running:
            message = self._build_state_message()
            if message:
                encoded = _encode(message)
                with self._lock:
                    dead_clients: List[str] = []
                    for player_id, record in self._connections.items():
                        try:
                            record.socket.sendall(encoded)
                        except OSError:
                            dead_clients.append(player_id)
                    for player_id in dead_clients:
                        self._remove_client(player_id)
            time.sleep(1 / 20)

    def _build_state_message(self) -> Optional[dict]:
        with self._lock:
            states = list(self._remote_states.values())
            if self._local_state:
                states.append(self._local_state)
        if not states:
            return None
        tanks_payload = []
        for snapshot in states:
            tanks_payload.append(
                {
                    "player_id": snapshot.player_id,
                    "position": [snapshot.position[0], snapshot.position[1]],
                    "angle": snapshot.angle,
                    "color": list(snapshot.color),
                }
            )
        return {"type": "state", "tanks": tanks_payload}

    def _remove_client(self, player_id: str) -> None:
        with self._lock:
            record = self._connections.pop(player_id, None)
            self._remote_states.pop(player_id, None)
        if record:
            try:
                record.socket.close()
            except OSError:
                pass


class ClientNetwork:
    def __init__(self, server_host: str, server_port: int):
        self.server_host = server_host
        self.server_port = server_port
        self.socket: Optional[socket.socket] = None
        self.player_id: Optional[str] = None
        self.assigned_color: Optional[Tuple[int, int, int]] = None
        self._remote_states: Dict[str, TankSnapshot] = {}
        self._lock = threading.Lock()
        self._buffer = ""
        self._running = False
        self._receiver_thread: Optional[threading.Thread] = None

    def connect(self, timeout: float = 5.0) -> None:
        if self.socket:
            return
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect((self.server_host, self.server_port))
        self.socket = sock
        self._running = True
        assign_payload = self._read_message_blocking()
        if not assign_payload or assign_payload.get("type") != "assign":
            raise RuntimeError("Failed to receive assignment from server")
        self.player_id = assign_payload["player_id"]
        color_payload = assign_payload.get("color", [46, 196, 182])
        self.assigned_color = (int(color_payload[0]), int(color_payload[1]), int(color_payload[2]))
        self._receiver_thread = threading.Thread(target=self._receiver_loop, daemon=True)
        self._receiver_thread.start()

    def close(self) -> None:
        self._running = False
        if self.socket:
            try:
                self.socket.close()
            except OSError:
                pass
            self.socket = None

    def send_snapshot(self, position: Tuple[float, float], angle: float) -> None:
        if not self.socket or not self._running:
            return
        payload = {"type": "update", "position": [position[0], position[1]], "angle": angle}
        try:
            self.socket.sendall(_encode(payload))
        except OSError:
            self.close()

    def get_remote_states(self, exclude_id: Optional[str] = None) -> Dict[str, TankSnapshot]:
        with self._lock:
            states = dict(self._remote_states)
        if exclude_id and exclude_id in states:
            states.pop(exclude_id, None)
        return states

    def _receiver_loop(self) -> None:
        while self._running and self.socket:
            payload = self._read_message_blocking(non_blocking=True)
            if payload is None:
                continue
            if payload.get("type") != "state":
                continue
            tanks = payload.get("tanks", [])
            with self._lock:
                updated: Dict[str, TankSnapshot] = {}
                for tank in tanks:
                    player_id = tank.get("player_id")
                    position = tank.get("position") or [0, 0]
                    angle = tank.get("angle", 0.0)
                    color = tank.get("color") or [46, 196, 182]
                    if not player_id:
                        continue
                    updated[player_id] = TankSnapshot(
                        player_id=player_id,
                        position=(float(position[0]), float(position[1])),
                        angle=float(angle),
                        color=(int(color[0]), int(color[1]), int(color[2])),
                    )
                self._remote_states = updated

    def _read_message_blocking(self, non_blocking: bool = False) -> Optional[dict]:
        if not self.socket:
            return None
        sock = self.socket
        sock.settimeout(0.1 if non_blocking else None)
        try:
            while True:
                if "\n" in self._buffer:
                    line, self._buffer = self._buffer.split("\n", 1)
                    if line.strip():
                        return _decode(line)
                data = sock.recv(4096)
                if not data:
                    self.close()
                    return None
                self._buffer += data.decode("utf-8")
        except socket.timeout:
            return None
        except OSError:
            self.close()
            return None

