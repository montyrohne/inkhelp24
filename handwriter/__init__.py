"""Text-to-Handwriting Modul.

Wandelt normalen Text in ein Bild/PDF um, das wie eine
handgeschriebene Notiz aussieht.
"""

try:
    from .renderer import Handwriter
except ImportError:  # pragma: no cover - direct script execution fallback
    from renderer import Handwriter

__all__ = ["Handwriter"]

if __name__ == "__main__":
    print(f"Handwriter loaded: {Handwriter.__module__}")
