"""Flask Web-App für den Text-to-Handwriting Converter.

Bietet eine Web-Oberfläche mit vielen Einstellungen (Fonts, Papier,
Schrift: Variation, Datum, Korrekturen) zur Erstellung handschriftlich
wirkender Bilder und PDFs.
"""

import base64
import io
import os
import zipfile

from flask import Flask, request, render_template, send_file, jsonify, redirect, url_for, g

from handwriter import Handwriter

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FONTS_DIR = os.path.join(BASE_DIR, "fonts")

FONTS = {
    "NothingYouCouldDo": "NothingYouCouldDo.ttf",
    "Caveat": "Caveat.ttf",
    "Handlee": "Handlee.ttf",
    "PatrickHand": "PatrickHand.ttf",
    "ReenieBeanie": "ReenieBeanie.ttf",
}

SLIDER_KEYS = [
    "neigung", "wortabstand", "durchstreichung", "fehlende",
    "rechtschreibfehler",
]

app = Flask(__name__)
SUPPORTED_LANGS = {"de": "Deutsch", "en": "English"}


def detect_lang():
    lang = request.cookies.get("lang")
    if lang in SUPPORTED_LANGS:
        return lang

    country = (
        request.headers.get("CF-IPCountry")
        or request.headers.get("X-Country-Code")
        or request.headers.get("X-Forwarded-Country")
    )
    if country and country.lower() == "de":
        return "de"

    browser_lang = request.accept_languages.best_match(SUPPORTED_LANGS.keys())
    return browser_lang or "de"


@app.before_request
def set_language_context():
    g.lang = detect_lang()


@app.route("/set_lang/<lang>")
def set_lang(lang):
    if lang not in SUPPORTED_LANGS:
        lang = "de"
    response = redirect(request.referrer or url_for("start"))
    response.set_cookie("lang", lang, max_age=31536000, samesite="Lax")
    return response


def make_writer(font_size, line_spacing, paper, font_name, data):
    font_file = FONTS.get(font_name, FONTS["NothingYouCouldDo"])
    font_path = os.path.join(FONTS_DIR, font_file)
    opts = {}
    for k in SLIDER_KEYS:
        v = data.get(k, Handwriter.DEFAULTS.get(k, 0.5))
        try:
            opts[k] = float(v)
        except (TypeError, ValueError):
            opts[k] = Handwriter.DEFAULTS.get(k, 0.5)
    opts["papier"] = data.get("papier_style", "weiss")
    opts["randlinien"] = bool(data.get("randlinien", False))
    opts["datum"] = bool(data.get("datum", False))
    # Seitenränder in cm + "jede zweite Zeile"
    for k, default in (("rand_links_cm", 2.5), ("rand_rechts_cm", 2.5)):
        try:
            opts[k] = float(data.get(k, default))
        except (TypeError, ValueError):
            opts[k] = default
    opts["kariert_jede_zweite"] = bool(data.get("kariert_jede_zweite", False))
    return Handwriter(
        font_path=font_path,
        font_size=int(font_size),
        line_spacing=float(line_spacing),
        paper=paper,
        **opts,
    )


def _payload_common(data):
    text = (data.get("text") or "").strip()
    if not text:
        return None, {"error": "Bitte gib einen Text ein."}, 400
    font_size = data.get("font_size", 42)
    line_spacing = data.get("line_spacing", 1.5)
    paper = data.get("paper", "A4")
    font_name = data.get("font", "NothingYouCouldDo")
    return (text, font_size, line_spacing, paper, font_name), None, None


@app.route("/")
def start():
    return render_template("start.html", lang=g.lang)


@app.route("/builder")
def index():
    return render_template("index.html", fonts=sorted(FONTS.keys()), lang=g.lang)


@app.route("/impressum")
def impressum():
    return render_template("impressum.html", lang=g.lang)


@app.route("/datenschutz")
def datenschutz():
    return render_template("datenschutz.html", lang=g.lang)


@app.route("/nutzungsbedingungen")
def nutzungsbedingungen():
    return render_template("nutzungsbedingungen.html", lang=g.lang)


@app.route("/api/render", methods=["POST"])
def render():
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"error": "Ungültige Anfrage"}), 400
    common, err, code = _payload_common(data)
    if err:
        return jsonify(err), code
    text, font_size, line_spacing, paper, font_name = common

    writer = make_writer(font_size, line_spacing, paper, font_name, data)
    try:
        pages = writer.to_images(text)
    except Exception as exc:  # pragma: no cover
        return jsonify({"error": f"Fehler beim Rendern: {exc}"}), 500

    # Alle Seiten als Base64 zurückgeben, damit die Vorschau mehrere Seiten zeigt
    imgs = []
    for p in pages:
        buf = io.BytesIO()
        p.save(buf, format="PNG")
        buf.seek(0)
        imgs.append(base64.b64encode(buf.getvalue()).decode("ascii"))
    return jsonify({"pages": imgs})


@app.route("/api/png", methods=["POST"])
def png():
    """Alle Seiten als PNG-Dateien in einem ZIP-Archiv herunterladen."""
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"error": "Ungültige Anfrage"}), 400
    common, err, code = _payload_common(data)
    if err:
        return jsonify(err), code
    text, font_size, line_spacing, paper, font_name = common

    writer = make_writer(font_size, line_spacing, paper, font_name, data)
    try:
        pages = writer.to_images(text)
    except Exception as exc:  # pragma: no cover
        return jsonify({"error": f"Fehler beim Rendern: {exc}"}), 500

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for i, p in enumerate(pages):
            png = io.BytesIO()
            p.save(png, format="PNG")
            png.seek(0)
            zf.writestr(f"seite_{i + 1}.png", png.getvalue())
    buf.seek(0)
    return send_file(buf, mimetype="application/zip", as_attachment=True,
                     download_name="handschrift-seiten.zip")


@app.route("/api/pdf", methods=["POST"])
def pdf():
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"error": "Ungültige Anfrage"}), 400
    common, err, code = _payload_common(data)
    if err:
        return jsonify(err), code
    text, font_size, line_spacing, paper, font_name = common

    writer = make_writer(font_size, line_spacing, paper, font_name, data)
    try:
        pdf_path = writer.to_pdf(text)
    except Exception as exc:  # pragma: no cover
        return jsonify({"error": f"Fehler beim PDF-Erstellen: {exc}"}), 500

    with open(pdf_path, "rb") as f:
        data_buf = f.read()
    try:
        os.remove(pdf_path)
    except OSError:
        pass
    return send_file(io.BytesIO(data_buf), mimetype="application/pdf",
                     as_attachment=True, download_name="handschrift.pdf")


if __name__ == "__main__":
    app.run(debug=True)
