from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import Dict, Tuple

import pygame

from networking import ClientNetwork, ServerNetwork, TankSnapshot

WINDOW_WIDTH = 960
WINDOW_HEIGHT = 640
BACKGROUND_COLOR: Tuple[int, int, int] = (14, 17, 24)
TANK_COLOR: Tuple[int, int, int] = (46, 196, 182)
TANK_SIZE = (64, 48)
TANK_SPEED = 280  # pixels per second
TANK_ROTATION_SPEED = 180  # degrees per second
DEFAULT_LISTEN_HOST = "0.0.0.0"
DEFAULT_SERVER_HOST = "127.0.0.1"
DEFAULT_PORT = 5000
PLAYER_COLORS = [
    (46, 196, 182),
    (255, 159, 67),
    (255, 107, 129),
    (84, 160, 255),
    (129, 236, 236),
    (255, 234, 167),
]


def draw_tank_sprite(
    surface: pygame.Surface,
    position: Tuple[float, float],
    angle: float,
    color: Tuple[int, int, int],
    size: Tuple[int, int] = TANK_SIZE,
) -> None:
    barrel_height = 28
    body_width, body_height = size
    tank_surface = pygame.Surface((body_width, body_height + barrel_height), pygame.SRCALPHA)

    body_rect = pygame.Rect(0, barrel_height, body_width, body_height)
    pygame.draw.rect(tank_surface, color, body_rect, border_radius=8)

    barrel_width = 10
    barrel_rect = pygame.Rect(body_width // 2 - barrel_width // 2, 0, barrel_width, barrel_height)
    pygame.draw.rect(tank_surface, color, barrel_rect, border_radius=4)

    rotated = pygame.transform.rotate(tank_surface, angle)
    center = (position[0] + body_width / 2, position[1] + body_height / 2)
    rect = rotated.get_rect(center=center)
    surface.blit(rotated, rect.topleft)


@dataclass
class ControlInput:
    forward: float = 0.0
    rotation: float = 0.0


@dataclass
class Tank:
    position: pygame.Vector2
    angle: float = 0.0
    speed: float = TANK_SPEED
    rotation_speed: float = TANK_ROTATION_SPEED
    size: Tuple[int, int] = TANK_SIZE
    color: Tuple[int, int, int] = TANK_COLOR

    def update(self, controls: ControlInput, dt: float) -> None:
        if controls.rotation != 0:
            self.angle = (self.angle - controls.rotation * self.rotation_speed * dt) % 360

        if controls.forward != 0:
            forward_vector = pygame.Vector2(0, -1).rotate(-self.angle)
            displacement = forward_vector * controls.forward * self.speed * dt
            self.position += displacement
            self._clamp_to_window()

    def _clamp_to_window(self) -> None:
        width, height = self.size
        self.position.x = max(0, min(self.position.x, WINDOW_WIDTH - width))
        self.position.y = max(0, min(self.position.y, WINDOW_HEIGHT - height))

    def draw(self, surface: pygame.Surface) -> None:
        draw_tank_sprite(
            surface,
            (self.position.x, self.position.y),
            self.angle,
            self.color,
            self.size,
        )


def handle_input() -> ControlInput:
    keys = pygame.key.get_pressed()
    controls = ControlInput()
    if keys[pygame.K_w] or keys[pygame.K_UP]:
        controls.forward += 1
    if keys[pygame.K_s] or keys[pygame.K_DOWN]:
        controls.forward -= 1
    if keys[pygame.K_a] or keys[pygame.K_LEFT]:
        controls.rotation -= 1
    if keys[pygame.K_d] or keys[pygame.K_RIGHT]:
        controls.rotation += 1
    return controls


def run_game(args: argparse.Namespace) -> None:
    pygame.init()
    screen = pygame.display.set_mode((WINDOW_WIDTH, WINDOW_HEIGHT))
    pygame.display.set_caption("Tank vs. Aliens (Prototype)")
    clock = pygame.time.Clock()

    server_network: ServerNetwork | None = None
    client_network: ClientNetwork | None = None
    remote_tanks: Dict[str, TankSnapshot] = {}
    local_player_id = "local"
    local_color = TANK_COLOR
    connection_hint = ""

    if args.mode == "server":
        server_network = ServerNetwork(args.listen_host, args.listen_port, PLAYER_COLORS)
        server_network.start()
        local_player_id = "server-host"
        local_color = PLAYER_COLORS[0]
        connection_hint = f"Listening on {args.listen_host}:{args.listen_port}"
    elif args.mode == "client":
        client_network = ClientNetwork(args.server_host, args.server_port)
        client_network.connect()
        local_player_id = client_network.player_id or "client"
        local_color = client_network.assigned_color or PLAYER_COLORS[0]
        connection_hint = f"Connected to {args.server_host}:{args.server_port}"
    else:
        connection_hint = "Solo mode"

    tank = Tank(
        position=pygame.Vector2(
            (WINDOW_WIDTH - TANK_SIZE[0]) / 2,
            (WINDOW_HEIGHT - TANK_SIZE[1]) / 2,
        ),
        color=local_color,
    )

    try:
        while True:
            dt = clock.tick(60) / 1000  # seconds
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    raise SystemExit

            controls = handle_input()
            tank.update(controls, dt)

            if server_network:
                server_network.update_local_state(
                    player_id=local_player_id,
                    position=(tank.position.x, tank.position.y),
                    angle=tank.angle,
                    color=tank.color,
                )
                remote_tanks = server_network.get_remote_states(exclude_id=local_player_id)
            elif client_network:
                client_network.send_snapshot((tank.position.x, tank.position.y), tank.angle)
                remote_tanks = client_network.get_remote_states(exclude_id=local_player_id)
            else:
                remote_tanks = {}

            screen.fill(BACKGROUND_COLOR)
            tank.draw(screen)
            for snapshot in remote_tanks.values():
                draw_tank_sprite(screen, snapshot.position, snapshot.angle, snapshot.color)
            draw_hud(screen, args.mode, connection_hint)
            pygame.display.flip()
    finally:
        if server_network:
            server_network.shutdown()
        if client_network:
            client_network.close()
        pygame.quit()


def draw_hud(surface: pygame.Surface, mode: str, status_line: str) -> None:
    font = pygame.font.SysFont("consolas", 20)
    instructions = [
        "Controls:",
        "W / Arrow Up    - Move forward",
        "S / Arrow Down  - Reverse",
        "A / Arrow Left  - Rotate left",
        "D / Arrow Right - Rotate right",
        f"Mode: {mode}",
        status_line,
    ]
    padding = 10
    for idx, line in enumerate(instructions):
        text_surface = font.render(line, True, (220, 220, 220))
        surface.blit(text_surface, (padding, padding + idx * 22))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Tank vs. Aliens Prototype with networking")
    parser.add_argument(
        "--mode",
        choices=["solo", "server", "client"],
        default="solo",
        help="Choose solo, server, or client mode.",
    )
    parser.add_argument(
        "--listen-host",
        default=DEFAULT_LISTEN_HOST,
        help="Host/interface for server mode.",
    )
    parser.add_argument(
        "--listen-port",
        type=int,
        default=DEFAULT_PORT,
        help="Port for server mode.",
    )
    parser.add_argument(
        "--server-host",
        default=DEFAULT_SERVER_HOST,
        help="Server IP or hostname for client mode.",
    )
    parser.add_argument(
        "--server-port",
        type=int,
        default=DEFAULT_PORT,
        help="Server port for client mode.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    run_game(parse_args())

