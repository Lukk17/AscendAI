"""Generate the twenty-five page canary PDF used by the long-document e2e spec.

Page geometry is deliberate: 595 x 842 points is A4, and the library renders every PDF page at a fixed scale of 2,
so one page reaches inference at 1190 x 1684 = 2,003,960 pixels, just under the 2,500,000 pixel ceiling the service
refuses above.
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

PAGE_WIDTH = 595
PAGE_HEIGHT = 842
PAGE_COUNT = 25
CANARY_PAGE = 24
CANARY = "Halcyon Ledger Canary"
OUTPUT = Path(__file__).resolve().parent / "halcyon-ledger-25-pages.pdf"

BODY = [
    "The ledger of Halcyon keeps one entry for every crossing of the",
    "Verrant Strait, and the clerks who keep it are sworn to enter",
    "nothing they have not seen with their own eyes. The entries run",
    "in three columns: the hour, the vessel, and the name of whoever",
    "signed for the cargo. Where a signature is missing the clerk",
    "writes a single stroke, and a stroke is worth an inquiry.",
    "",
    "Marisel Vane kept the ledger for eleven years and never once",
    "left a stroke unexplained. Her successor left nine in a single",
    "season, which is how the audit began and how this page came to",
    "be written at all.",
]


FONT_CANDIDATES = (
    "C:/Windows/Fonts/arial.ttf",
    "C:/Windows/Fonts/segoeui.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)


def font(size: int) -> ImageFont.FreeTypeFont:
    for candidate in FONT_CANDIDATES:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size)

    raise RuntimeError("no TrueType font found to render the fixture with")


def render_page(number: int) -> Image.Image:
    page = Image.new("L", (PAGE_WIDTH, PAGE_HEIGHT), color=255)
    draw = ImageDraw.Draw(page)
    draw.text((60, 60), f"Halcyon Ledger, page {number} of {PAGE_COUNT}", font=font(26), fill=0)

    y = 120
    for line in BODY:
        draw.text((60, y), line, font=font(19), fill=0)
        y += 32

    if number == CANARY_PAGE:
        draw.text((60, y + 40), CANARY, font=font(28), fill=0)

    return page.convert("1")


pages = [render_page(number) for number in range(1, PAGE_COUNT + 1)]
OUTPUT.parent.mkdir(parents=True, exist_ok=True)
pages[0].save(OUTPUT, format="PDF", save_all=True, append_images=pages[1:], resolution=72.0)

print(OUTPUT, OUTPUT.stat().st_size, "bytes")
