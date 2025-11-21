from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Tuple

import pygame

WINDOW_WIDTH = 960
WINDOW_HEIGHT = 640
BACKGROUND_COLOR: Tuple[int, int, int] = (14, 17, 24)
TANK_COLOR: Tuple[int, int, int] = (46, 196, 182)
TANK_SIZE = (64, 48)
TANK_SPEED = 280  # pixels per second
TANK_ROTATION_SPEED = 180  # degrees per second


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
        barrel_height = 28
        body_width, body_height = self.size
        tank_surface = pygame.Surface((body_width, body_height + barrel_height), pygame.SRCALPHA)

        body_rect = pygame.Rect(0, barrel_height, body_width, body_height)
        pygame.draw.rect(tank_surface, TANK_COLOR, body_rect, border_radius=8)

        barrel_width = 10
        barrel_rect = pygame.Rect(body_width // 2 - barrel_width // 2, 0, barrel_width, barrel_height)
        pygame.draw.rect(tank_surface, TANK_COLOR, barrel_rect, border_radius=4)

        rotated = pygame.transform.rotate(tank_surface, self.angle)
        center = (self.position.x + body_width / 2, self.position.y + body_height / 2)
        rect = rotated.get_rect(center=center)
        surface.blit(rotated, rect.topleft)


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


def run_game() -> None:
    pygame.init()
    screen = pygame.display.set_mode((WINDOW_WIDTH, WINDOW_HEIGHT))
    pygame.display.set_caption("Tank vs. Aliens (Prototype)")
    clock = pygame.time.Clock()

    tank = Tank(
        position=pygame.Vector2(
            (WINDOW_WIDTH - TANK_SIZE[0]) / 2,
            (WINDOW_HEIGHT - TANK_SIZE[1]) / 2,
        )
    )

    try:
        while True:
            dt = clock.tick(60) / 1000  # seconds
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    raise SystemExit

            controls = handle_input()
            tank.update(controls, dt)

            screen.fill(BACKGROUND_COLOR)
            tank.draw(screen)
            draw_hud(screen)
            pygame.display.flip()
    except SystemExit:
        pygame.quit()
        sys.exit()


def draw_hud(surface: pygame.Surface) -> None:
    font = pygame.font.SysFont("consolas", 20)
    instructions = [
        "Controls:",
        "W / Arrow Up    - Move forward",
        "S / Arrow Down  - Reverse",
        "A / Arrow Left  - Rotate left",
        "D / Arrow Right - Rotate right",
    ]
    padding = 10
    for idx, line in enumerate(instructions):
        text_surface = font.render(line, True, (220, 220, 220))
        surface.blit(text_surface, (padding, padding + idx * 22))


if __name__ == "__main__":
    run_game()

