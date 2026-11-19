"""Правило зависимостей: стрелки только внутрь.

  core          -> ничего из src.*, кроме src.core
  adapters      -> только src.core (и не друг друга)
  capabilities  -> только src.core
  app           -> что угодно (composition root)

Запуск: python tests/test_architecture.py  (или pytest)
"""

import ast
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"


def _imports(path: Path):
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            yield from (a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            yield node.module


def _layer(parts: tuple[str, ...]) -> str:
    return parts[0] if parts else ""


def violations() -> list[str]:
    bad = []
    for f in SRC.rglob("*.py"):
        rel = f.relative_to(SRC).parts
        layer = _layer(rel)
        if rel == ("capabilities", "__init__.py"):
            continue  # реестр возможностей: load_all() импортирует их по определению
        own = "/".join(rel[:2])  # adapters/<kind> или capabilities/<name>
        for mod in _imports(f):
            p = mod.split(".")
            if p[0] != "src" or len(p) < 2:
                continue
            target = p[1]
            if layer == "core" and target != "core":
                bad.append(f"{f.relative_to(SRC)}: core не должен импортировать {mod}")
            elif layer in ("adapters", "capabilities") and target not in ("core", layer):
                bad.append(f"{f.relative_to(SRC)}: {layer} может зависеть только от core, а не {mod}")
            elif layer == "adapters" and target == "adapters":
                other = "/".join(p[1:3])
                if other != own:
                    bad.append(f"{f.relative_to(SRC)}: адаптеры не должны знать друг о друге ({mod})")
            elif layer == "capabilities" and target == "capabilities":
                other = "/".join(p[1:3])
                if other != own:
                    bad.append(f"{f.relative_to(SRC)}: возможности не должны знать друг о друге ({mod})")
    return bad


def test_dependency_rule():
    assert not violations(), "\n".join(violations())


if __name__ == "__main__":
    v = violations()
    print("\n".join(v) if v else "architecture ok")
    sys.exit(1 if v else 0)
