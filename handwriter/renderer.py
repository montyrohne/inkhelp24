"""Bild- und PDF-Rendering für Handschrift-Notizen.

Bietet viele Einstellungen, um eine möglichst natürliche, echte
Handschrift zu simulieren (Variation, Papier-Optik, Datum, Korrekturen).
"""

import random
import tempfile
import os
import math
from datetime import date

from PIL import Image, ImageDraw, ImageFont, ImageFilter


class Handwriter:
    """Wandelt Text in ein handschriftliches Bild/PDF um."""

    A4 = (8.27, 11.69)
    LETTER = (8.5, 11.0)

    DEFAULTS = {
        "neigung": 0.0,         # Schräglage (-1..+1): 0=gerade, -1=links, +1=rechts
        "wortabstand": 0.5,     # Wortabstand (0..1)
        "durchstreichung": 0.0, # Häufigkeit von Korrekturen (0..1)
        "fehlende": 0.0,        # Anteil verschluckter Buchstaben (0..1)
        "rechtschreibfehler": 0.0,  # Natürliche Tippfehler wie vertauschte/wegfallende Zeichen
        "datum": False,
        "randlinien": False,
        "papier": "weiss",
        # Feste Linienanzahl pro Papier-Typ
        "linien_liniert": 32,      # horizontale Linien
        "linien_kariert_h": 59,    # horizontale Linien
        "linien_kariert_v": 41,    # vertikale Linien
        # Seitenränder (cm)
        "rand_links_cm": 2.5,
        "rand_rechts_cm": 2.5,
        # Bei kariert: nur in jede zweite Zeile schreiben
        "kariert_jede_zweite": False,
    }

    def __init__(self, font_path, font_size=42, line_spacing=1.5,
                 dpi=200, paper="A4", seed=None, **opts):
        self.font_path = font_path
        self.font_size = font_size
        self.line_spacing = line_spacing
        self.dpi = dpi
        self.paper = paper
        self.opts = dict(self.DEFAULTS)
        self.opts.update(opts)
        self._rng = random.Random(seed)

        # Seitenränder: links/rechts aus cm-Regler, oben/unten fest (cm -> px)
        # Oberer/unterer Rand klein halten, damit möglichst viele Zeilen
        # genutzt werden (kein Platzverschwendung). 0.6 cm oben/unten.
        self._margin_top = int(0.6 * dpi / 2.54)
        self._margin_bottom = int(0.6 * dpi / 2.54)
        self._rand_links = int(
            max(0.0, float(self.opts.get("rand_links_cm", 2.5))) * dpi / 2.54)
        self._rand_rechts = int(
            max(0.0, float(self.opts.get("rand_rechts_cm", 2.5))) * dpi / 2.54)
        # Bequemer Alias für vertikale Ränder (oben/unten)
        self._margin = self._margin_top

    def _page_size_px(self):
        w_inch, h_inch = self.A4 if self.paper == "A4" else self.LETTER
        return int(w_inch * self.dpi), int(h_inch * self.dpi)

    def _metrics(self, font):
        ascent, descent = font.getmetrics()
        line_height = (ascent + descent) * self.line_spacing
        return ascent, descent, line_height

    def _raster(self, height, width, font):
        """Grundlinien-Raster über die ganze Seite.

        Die Anzahl der Linien ist pro Papier-Typ fest vorgegeben:
        - liniert: 32 horizontale Linien
        - kariert: 59 horizontale + 41 vertikale Linien
        - sonst (weiss/alt/punkte): Raster aus der Schriftgröße

        Gibt (h_lines, v_lines, line_height) zurück, wobei h_lines die
        y-Koordinaten der Grundlinien und v_lines die x-Koordinaten sind.
        """
        ascent, descent, _ = self._metrics(font)
        mode = self.opts.get("papier", "weiss")

        if mode in ("liniert", "randliniert"):
            n = int(self.opts.get("linien_liniert", 32))
            step = (height - 1) / (n - 1)
            h_lines = [int(round(i * step)) for i in range(n)]
            v_lines = []
            line_height = step
        elif mode == "kariert":
            n_h = int(self.opts.get("linien_kariert_h", 59))
            n_v = int(self.opts.get("linien_kariert_v", 41))
            step_h = (height - 1) / (n_h - 1)
            step_v = (width - 1) / (n_v - 1)
            h_lines = [int(round(i * step_h)) for i in range(n_h)]
            v_lines = [int(round(i * step_v)) for i in range(n_v)]
            line_height = step_h
        else:
            # weiss/alt/punkte: Raster aus Schriftgröße
            line_height = (ascent + descent) * 1.7
            start = line_height * 0.35
            h_lines = []
            y = start
            while y < height:
                h_lines.append(int(round(y)))
                y += line_height
            v_lines = []
        return h_lines, v_lines, line_height, ascent

    # ------------------------------------------------------------------
    # Papier-Hintergrund
    # ------------------------------------------------------------------
    def _make_paper(self, width, height, color, font):
        img = Image.new("RGB", (width, height), color)
        draw = ImageDraw.Draw(img, "RGBA")

        mode = self.opts.get("papier", "weiss")
        line_color = (120, 160, 220, 150)

        h_lines, v_lines, line_height, ascent = self._raster(height, width, font)

        if mode in ("liniert", "randliniert"):
            for y in h_lines:
                draw.line([(0, y), (width, y)],
                          fill=line_color, width=max(1, int(2)))

        if mode == "kariert":
            for x in v_lines:
                draw.line([(x, 0), (x, height)],
                          fill=line_color, width=1)
            for y in h_lines:
                draw.line([(0, y), (width, y)],
                          fill=line_color, width=1)

        if mode == "punkte":
            for y in h_lines:
                x = 0
                while x < width:
                    draw.ellipse([x - 2, y - 2, x + 2, y + 2],
                                 fill=(150, 150, 150))
                    x += line_height

        if self.opts.get("randlinien"):
            red = (220, 80, 80, 180)
            lw = max(2, int(self.dpi * 4 / 200))
            # Bei kariert müssen die Randlinien auf einer genauen Längszeile
            # (vertikalen Gitterlinie) liegen; sonst am freien Textrand.
            if mode == "kariert" and v_lines:
                left_line = min(v_lines, key=lambda x: abs(x - self._rand_links))
                right_line = min(v_lines, key=lambda x: abs(x - (width - self._rand_rechts)))
            else:
                left_line = self._rand_links
                right_line = width - self._rand_rechts
            # eine Randlinie links, eine rechts
            draw.line([(left_line, 0), (left_line, height)],
                      fill=red, width=lw)
            draw.line([(right_line, 0), (right_line, height)],
                      fill=red, width=lw)

        if mode == "alt":
            img = img.convert("RGBA")
            w, h = img.size
            tone = Image.new("RGBA", (w, h), (255, 244, 214, 80))
            img = Image.alpha_composite(img, tone)
            overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            od = ImageDraw.Draw(overlay)
            for _ in range(40):
                rx = self._rng.randint(0, w)
                ry = self._rng.randint(0, h)
                r = self._rng.randint(20, 160)
                od.ellipse([rx - r, ry - r, rx + r, ry + r],
                           fill=(200, 170, 120,
                                 self._rng.randint(6, 22)))
            img = Image.alpha_composite(img, overlay)
            img = img.convert("RGB")

        return img

    # ------------------------------------------------------------------
    # Wort-Zerlegung + Hilfen
    # ------------------------------------------------------------------
    def _word_step(self, font, draw):
        """Der tatsächliche Schritt zwischen zwei Wörtern (wie beim Rendern)."""
        space = self._advance(" ", font, draw)
        factor = 0.5 + self.opts.get("wortabstand", 0.5) * 1.4
        return space * factor

    def _wrapped_words(self, text, width, font, draw):
        # Sicherheitspuffer: Ränder nie überlaufen lassen (Schräglage/Rundung)
        width = width - self.font_size * 0.7
        word_step = self._word_step(font, draw)
        # Buchstabenschritt wie beim Rendern (inkl. Ausgangsschwung-Glyphenbreite)
        pad = self.font_size * 0.06
        paragraphs = text.replace("\r\n", "\n").split("\n")
        word_lines = []
        for para in paragraphs:
            if not para.strip():
                word_lines.append([""])
                continue
            words = para.split(" ")
            current = []
            cur_w = 0.0
            for word in words:
                wt = 0.0
                for ch in word:
                    if ch in (" ", "\t"):
                        wt += draw.textlength(" ", font=font) * 0.8
                    else:
                        adv = draw.textlength(ch, font=font)
                        gb = draw.textbbox((0, 0), ch, font=font)
                        wt += max(adv, gb[2] - gb[0]) + pad
                add = wt if not current else word_step + wt
                if cur_w + add <= width or not current:
                    current.append(word)
                    cur_w += add
                else:
                    word_lines.append(current)
                    current = [word]
                    cur_w = wt
            word_lines.append(current)
        return word_lines

    def _advance(self, ch, font, draw):
        try:
            return draw.textlength(ch, font=font)
        except Exception:
            return self.font_size * 0.5

    def _colorize(self, rgba, color):
        r, g, b, a = rgba.split()
        r = r.point(lambda p: color[0])
        g = g.point(lambda p: color[1])
        b = b.point(lambda p: color[2])
        return Image.merge("RGBA", (r, g, b, a))

    def _apply_fehlende(self, word):
        rate = self.opts.get("fehlende", 0.0)
        if rate <= 0 or len(word) <= 2:
            return [(ch, False) for ch in word]

        out = []
        for i, ch in enumerate(word):
            missing = 2 <= i <= len(word) - 2 and self._rng.random() < rate
            out.append((ch, missing))

        if all(missing for _, missing in out):
            out[0] = (out[0][0], False)
        return out

    def _apply_rechtschreibfehler(self, word):
        rate = self.opts.get("rechtschreibfehler", 0.0)
        if rate <= 0 or len(word) <= 2:
            return [(ch, False) for ch in word]

        chars = list(word)
        out = []
        i = 0
        while i < len(chars):
            if self._rng.random() < rate:
                if i + 1 < len(chars) and self._rng.random() < 0.45:
                    # Natürlicher Vertauschungsfehler: zwei Buchstaben werden
                    # in der Folge kurz vertauscht, ohne dass dabei eine Lücke entsteht.
                    out.append((chars[i + 1], False))
                    out.append((chars[i], False))
                    i += 2
                    continue
                if self._rng.random() < 0.7:
                    # Ein kurzer Übersehensfehler: Buchstabe fällt aus, aber der
                    # Text fließt ohne sichtbaren Hohlraum weiter.
                    out.append((chars[i], True))
                    i += 1
                    continue
            out.append((chars[i], False))
            i += 1
        return out

    def _clock_t(self):
        """Entscheidet anhand der 'Handlichkeit', wie sehr zu variieren."""
        # kombiniert Höhen-/Dreh-/Neigungswerte zu einem 0..1 Wert
        h = self.opts.get("hoehen", 0.5)
        d = self.opts.get("drehung", 0.5)
        n = self.opts.get("neigung", 0.15)
        return max(0.0, min(1.0, (h * 0.5 + d * 0.3 + n * 0.2)))

    # ------------------------------------------------------------------
    # Linien zeichnen
    # ------------------------------------------------------------------
    def _draw_line(self, page_img, word_line, base_x, baseline_y, font,
                   ink, ink_variation, max_x=None):
        opts = self.opts
        # Schräglage: konstanter Winkel für alle Buchstaben.
        # neigung liegt in -1..+1 (UI: -50..+50), 0 = gerade,
        # -1 = nach links geneigt, +1 = nach rechts geneigt.
        n_deg = -opts.get("neigung", 0.0) * 40
        strike_rate = opts.get("durchstreichung", 0.0)

        draw = ImageDraw.Draw(page_img)
        x_cursor = float(base_x)

        # Tempel-Dimensionen: großzügig, damit Ober-/Unterlängen + Rotation
        # keinen Rand abschneiden. TMP_B = y der Baseline im Tempel.
        TMP_W, TMP_H = 240, 300
        TMP_X, TMP_B = 120, 250

        is_last_word = len(word_line) - 1
        for wi, word in enumerate(word_line):
            if word == "":
                continue

            wfont = ImageFont.truetype(
                self.font_path, max(8, int(self.font_size)))
            ascent_w = wfont.getmetrics()[0]

            if self.opts.get("rechtschreibfehler", 0.0) > 0:
                processed = self._apply_rechtschreibfehler(word)
            else:
                processed = self._apply_fehlende(word)
            word_start_x = x_cursor
            for ch, missing in processed:
                if ch in (" ", "\t"):
                    x_cursor += self._advance(" ", wfont, draw) * 0.8
                    continue

                adv = self._advance(ch, wfont, draw)
                try:
                    gb = ImageDraw.Draw(Image.new("RGBA", (1, 1))).textbbox((0, 0), ch, font=wfont)
                    glyph_w = gb[2] - gb[0]
                except Exception:
                    glyph_w = adv
                step = max(adv, glyph_w) + self.font_size * 0.06

                if missing:
                    # Kein sichtbarer Hohlraum: Der Text fließt weiter, als wäre
                    # der Buchstabe nur kurz übersehen worden. Dadurch entsteht
                    # keine Unterbrechung im Schriftbild und die Zeile wird nicht
                    # künstlich kürzer.
                    x_cursor += max(step * 0.2, self.font_size * 0.08)
                    continue

                tmp = Image.new("RGBA", (TMP_W, TMP_H), (0, 0, 0, 0))
                td = ImageDraw.Draw(tmp)
                gb = td.textbbox((0, 0), ch, font=wfont)

                # So zeichnen, dass die BASELINE (Buchstabenfuß) bei TMP_B liegt:
                # Pillow setzt die glyphen-Oberkante bei y, Baseline bei y+ascent.
                td.text((TMP_X - gb[0], TMP_B - ascent_w), ch,
                        fill=(255, 255, 255), font=wfont)

                # Schräglage um den Baselinemittelpunkt, ohne expand, damit
                # der Punkt (TMP_X, TMP_B) die Position im Bild behält.
                if abs(n_deg) > 0.1:
                    tmp = tmp.rotate(n_deg, resample=Image.BICUBIC,
                                     center=(TMP_X, TMP_B), expand=False)

                color = (ink, ink, ink, 255)

                # Baseline-Mittelpunkt des Tempels auf die Grundlinie setzen
                dest_x = int(x_cursor) - TMP_X
                dest_y = int(baseline_y) - TMP_B

                # Niemals über den rechten Rand hinaus zeichnen
                if max_x is not None and dest_x >= max_x:
                    x_cursor = float(max_x)
                    break

                page_img.paste(self._colorize(tmp, color),
                               (dest_x, dest_y), mask=tmp.split()[3])

                # Vorrücken: mindestens die Advance-Breite, aber auch genug
                # Platz für den sichtbaren Ausgangsschwung des Buchstabens
                # (v.a. beim "g" in verbindenden Schriften), sonst hängen
                # aufeinanderfolgende Buchstaben ineinander.
                x_cursor += step

            # Durchstreichung: gelegentlich eine Korrekturlinie übers Wort
            word_end_x = min(x_cursor, max_x) if max_x is not None else x_cursor
            if strike_rate > 0 and self._rng.random() < strike_rate \
                    and (word_end_x - word_start_x) > self.font_size * 1.5:
                self._draw_strikeout(page_img, word_start_x, word_end_x,
                                     baseline_y, wfont)

            # Wortabstand: nur zwischen Wörtern, nie nach dem letzten
            if wi < is_last_word:
                x_cursor += self._word_step(wfont, draw)

    def _draw_date(self, img, base_font, baseline_y):
        if not self.opts.get("datum"):
            return
        d = date.today()
        try:
            label = d.strftime("%d.%m.%Y")
        except Exception:
            label = d.isoformat()
        w, _ = self._page_size_px()
        # Datum in exakt derselben Größe wie die Schrift und auf der Grundlinie
        font = ImageFont.truetype(self.font_path, int(self.font_size))

        # Wie beim Text: Buchstaben mit Baseline bei TMP_B rendern.
        TMP_H = 300
        TMP_X, TMP_B = 120, 250
        ascent_w = font.getmetrics()[0]
        # Tempelbreite großzügig, damit das gesamte Datum nie abgeschnitten wird
        probe = ImageDraw.Draw(Image.new("RGB", (10, 10)))
        glyph_w = int(probe.textlength(label, font=font)) + 4
        TMP_W = glyph_w + 2 * TMP_X
        tmp = Image.new("RGBA", (TMP_W, TMP_H), (0, 0, 0, 0))
        td = ImageDraw.Draw(tmp)
        td.text((TMP_X, TMP_B - ascent_w), label, fill=(255, 255, 255), font=font)
        # rechtsbündig innerhalb der Ränder: Datum endet am rechten Rand
        # (mit kleinem Abstand), beginnt aber nie links vor dem linken Rand.
        right_edge = w - self._rand_rechts
        left_edge = self._rand_links
        pad = max(4, int(self.font_size * 0.15))
        dest_x = int(right_edge - pad - glyph_w) - TMP_X
        if dest_x + TMP_X < left_edge:
            dest_x = left_edge - TMP_X
        dest_y = int(baseline_y) - TMP_B
        tmp = self._colorize(tmp, (30, 30, 30, 255))
        img.paste(tmp, (dest_x, dest_y), mask=tmp.split()[3])

    def _draw_strikeout(self, page_img, x0, x1, baseline_y, wfont):
        """Zeichnet eine unregelmäßige Korrektur-Kratzlinie übers Wort."""
        opts = self.opts
        draw = ImageDraw.Draw(page_img)
        mid_y = baseline_y - self.font_size * 0.45
        # leicht schräg und mit Wellenlinie
        tint = max(0, min(255, int(30 + self._rng.uniform(-10, 10))))
        color = (tint, tint, tint, 255)
        width = int(self.font_size * 0.08) + 1
        segs = max(3, int((x1 - x0) / (self.font_size * 0.5)))
        step = (x1 - x0) / segs
        pts = [(x0, mid_y + self._rng.uniform(-3, 3))]
        for i in range(1, segs + 1):
            px = x0 + step * i
            py = mid_y + self._rng.uniform(-6, 6)
            pts.append((px, py))
        draw.line(pts, fill=color, width=width, joint="curve")

    # ------------------------------------------------------------------
    # Seite rendern
    # ------------------------------------------------------------------
    def _render_page(self, text, bg):
        width, height = self._page_size_px()
        base_font = ImageFont.truetype(self.font_path, self.font_size)
        base = self._make_paper(width, height, bg, base_font).convert("RGBA")
        draw = ImageDraw.Draw(base)

        left = self._rand_links
        right = self._rand_rechts
        # Sicherheitsabstand: Der Text darf die Randlinien NIE berühren.
        # Auch bei Schräglage und Ausgangsschwüngen bleibt so ein Abstand.
        kante_buffer = self.font_size * 0.7
        base_x = left + kante_buffer
        text_width = width - left - right - 2 * kante_buffer
        if text_width < 0:
            text_width = 0
        word_lines = self._wrapped_words(text, text_width, base_font, draw)

        # Rasterlinien (Grundlinien) über die ganze Seite
        h_lines, v_lines, line_height, ascent = self._raster(height, width, base_font)

        # Nutzbare Grundlinien: innerhalb des oberen/unteren Rands
        page_lines = [y for y in h_lines
                      if self._margin_top <= y <= height - self._margin_bottom]

        # Bei kariert: optional nur jede zweite Zeile nutzen
        if self.opts.get("kariert_jede_zweite") and self.opts.get("papier") == "kariert":
            page_lines = page_lines[0::2]

        pages = []
        idx = 0
        is_first = True
        while idx < len(word_lines):
            # Auf der ersten Seite sitzt das Datum allein in Zeile 1,
            # der Text beginnt erst in Zeile 2. Alle Folgeseiten haben
            # kein Datum und nutzen alle Zeilen.
            lines_this = page_lines[1:] if is_first else page_lines
            cap = len(lines_this) or 1
            chunk = word_lines[idx:idx + cap]

            page_rgb = base.convert("RGB")
            if is_first:
                self._draw_date(page_rgb, base_font,
                                page_lines[0] if page_lines else self._margin_top)

            ink = 30
            ink_variation = 0
            for li, line in enumerate(chunk):
                if li >= len(lines_this):
                    break
                baseline = lines_this[li]
                # Jede Zeile beginnt etwas anders (natürlich, nicht maschinell):
                # leichte Einrückung-Unregelmäßigkeit am linken Rand.
                # Die Abweichung geht nur nach rechts, damit nichts links
                # über den linken Rand hinausragt.
                line_x = base_x + self._rng.uniform(0, self.font_size * 0.75)
                self._draw_line(page_rgb, line, line_x, baseline,
                                base_font, ink, ink_variation,
                                max_x=base_x + text_width)

            pages.append(page_rgb)
            idx += cap
            is_first = False
        return pages

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def to_images(self, text, page_color=(255, 255, 255)):
        text = text.strip()
        if not text:
            text = " "
        return self._render_page(text, page_color)

    def to_pdf(self, text, page_color=(255, 255, 255),
               output_path=None, title=None):
        pages = self.to_images(text, page_color)
        if output_path is None:
            fd, output_path = tempfile.mkstemp(suffix=".pdf")
            os.close(fd)
        first, rest = pages[0], pages[1:]
        first.save(output_path, "PDF", resolution=self.dpi,
                   save_all=True, append_images=rest,
                   title=title or "Handschrift")
        return output_path
