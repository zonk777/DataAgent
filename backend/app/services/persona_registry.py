"""Persona Registry — loads YAML persona configs and provides lookup/validation."""

from __future__ import annotations

import functools
from pathlib import Path
from typing import Any

import yaml


PERSONAS_DIR = Path(__file__).resolve().parents[1] / "personas"


class Persona:
    """Immutable persona definition loaded from YAML."""

    def __init__(self, data: dict[str, Any]):
        self.name: str = data["name"]
        self.display_name: str = data.get("display_name", self.name)
        self.description: str = data.get("description", "")
        self.triggers: dict = data.get("triggers", {})
        self.frameworks: list[dict] = data.get("frameworks", [])
        self.tools: dict = data.get("tools", {})
        self.output: dict = data.get("output", {})

    @property
    def is_default(self) -> bool:
        return bool(self.triggers.get("default", False))

    @property
    def summary(self) -> str:
        fw = ", ".join(f.get("display", f.get("name", "")) for f in self.frameworks[:3])
        return f"{self.display_name}: {self.description}（框架: {fw}）"


class PersonaRegistry:
    """Singleton registry for all persona configurations."""

    def __init__(self):
        self._personas: dict[str, Persona] = {}
        self._default: Persona | None = None
        self._load()

    def _load(self) -> None:
        if not PERSONAS_DIR.exists():
            return
        for path in PERSONAS_DIR.glob("*.yaml"):
            if path.name.startswith("_"):
                continue
            try:
                data = yaml.safe_load(path.read_text(encoding="utf-8"))
                if not data or not data.get("name"):
                    continue
                p = Persona(data)
                self._personas[p.name] = p
                if p.is_default:
                    self._default = p
            except (yaml.YAMLError, KeyError, TypeError):
                continue

    def get(self, name: str) -> Persona | None:
        return self._personas.get(name)

    def list_all(self) -> list[Persona]:
        return list(self._personas.values())

    @property
    def default(self) -> Persona | None:
        return self._default

    @property
    def registry_summary(self) -> str:
        return "\n".join(f"- {p.summary}" for p in self.list_all())


@functools.lru_cache(maxsize=1)
def get_persona_registry() -> PersonaRegistry:
    return PersonaRegistry()


def match_persona(task_type: str, question: str) -> Persona | None:
    """Simple keyword-based persona matching."""
    registry = get_persona_registry()
    best = None
    best_score = 0

    for persona in registry.list_all():
        keywords = persona.triggers.get("keywords", [])
        if not keywords:
            continue
        score = sum(1 for kw in keywords if kw in question)
        if score > best_score:
            best_score = score
            best = persona

    return best or registry.default
