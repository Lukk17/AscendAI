"""Generate the one-page A4 test page that was printed and photographed for the straightening fixtures.

The page is 2480 x 3508 pixels written at 300 dpi, which is A4, and the ground truth file holds its 21 lines exactly
as rendered, the title first.
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

PAGE_WIDTH = 2480
PAGE_HEIGHT = 3508
RESOLUTION = 300
LEFT_MARGIN = 200
RIGHT_MARGIN = 100
TITLE_TOP = 220
BODY_TOP = 390
LINE_PITCH = 125
TITLE_SIZE = 64
BODY_SIZE = 46
OUTPUT_DIR = Path(__file__).resolve().parent
PDF_OUTPUT = OUTPUT_DIR / "straightening-test-page.pdf"
TEXT_OUTPUT = OUTPUT_DIR / "straightening-test-page.txt"

TITLE = "Test page for straightening, ascend-ocr"
LINES = [
    "Invoice 2026-0917 issued on 25 September 2026",
    "Customer: Harbour Lane Bakery, 14 Mill Street",
    "Order reference HLB-4471, delivery window 08:00 to 10:30",
    "Item 1: rye sourdough loaves, 24 pieces, 3.40 EUR each",
    "Item 2: poppy seed rolls, 60 pieces, 0.85 EUR each",
    "Item 3: oat and honey biscuits, 12 boxes, 6.20 EUR each",
    "Subtotal 207.00 EUR, VAT 23 percent 47.61 EUR",
    "Total due 254.61 EUR within 14 days of this invoice",
    "IBAN PL61 1090 1014 0000 0712 1981 2874",
    "Payment title must quote the order reference above",
    "Zażółć gęślą jaźń, pchnąć w tę łódź jeża lub ośm skrzyń fig",
    "Grzegorz Brzęczyszczykiewicz, Chrząszczyżewoszyce, powiat Łękołody",
    "El pingüino Wenceslao hizo kilómetros bajo exhaustiva lluvia",
    "¿Dónde está la señora Muñoz? ¡Llegó ayer a Córdoba!",
    "The quick brown fox jumps over the lazy dog 0123456789",
    "Pack my box with five dozen liquor jugs, then ship by Friday",
    "Serial numbers: QX-5082-77, QX-5082-78, QX-5083-01",
    "Contact: orders@harbourlane.example, phone +48 512 334 906",
    "Notes: keep refrigerated below 6 degrees, do not stack",
    "Signed on behalf of the supplier by Marta Kowalczyk",
]

REGULAR_FONT = "C:/Windows/Fonts/arial.ttf"
BOLD_FONT = "C:/Windows/Fonts/arialbd.ttf"


def font(path: str, size: int) -> ImageFont.FreeTypeFont:
    if not Path(path).exists():
        raise RuntimeError(f"font {path} not found, the printed page was rendered with Arial")

    return ImageFont.truetype(path, size)


def render_page() -> Image.Image:
    page = Image.new("RGB", (PAGE_WIDTH, PAGE_HEIGHT), "white")
    draw = ImageDraw.Draw(page)
    regular = font(REGULAR_FONT, BODY_SIZE)
    draw.text((LEFT_MARGIN, TITLE_TOP), TITLE, font=font(BOLD_FONT, TITLE_SIZE), fill="black")

    for index, line in enumerate(LINES):
        position = (LEFT_MARGIN, BODY_TOP + index * LINE_PITCH)
        draw.text(position, line, font=regular, fill="black")
        right = draw.textbbox(position, line, font=regular)[2]
        if right >= PAGE_WIDTH - RIGHT_MARGIN:
            raise RuntimeError(f"line runs into the right margin: {line}")

    missing = sorted(ch for ch in set("".join(LINES)) if ch.strip() and regular.getmask(ch).getbbox() is None)
    if missing:
        raise RuntimeError(f"glyphs without ink: {missing}")

    return page


Image.init()
render_page().save(PDF_OUTPUT, resolution=RESOLUTION)
TEXT_OUTPUT.write_text("\n".join([TITLE, *LINES]) + "\n", encoding="utf-8", newline="\n")

print(PDF_OUTPUT, PDF_OUTPUT.stat().st_size, "bytes")
print(TEXT_OUTPUT, TEXT_OUTPUT.stat().st_size, "bytes")
