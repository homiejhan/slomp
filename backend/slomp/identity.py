"""Product identity: which listings on different sites are the same product.

Two listings are the same product only if their GTINs match, or their brand and normalized model match exactly, and
no size-like attribute disagrees (screen inches, GB/TB, ounces, pack count) and neither is an accessory or a different
condition. When that can't be established there is no comparison: a missing comparison beats a wrong one.
"""
from __future__ import annotations

import re
from typing import Optional

from .models import Identity

BRANDS = """
Apple Samsung Sony LG Bose JBL Beats Anker Logitech Razer Corsair HP Dell Lenovo Asus Acer MSI Microsoft Google
Amazon Roku TCL Hisense Vizio Insignia Toshiba Panasonic Philips Canon Nikon Fujifilm GoPro DJI Insta360 Garmin
Fitbit WD Seagate SanDisk Crucial Kingston Netgear TP-Link Eero Ring Arlo Blink Wyze Nintendo PlayStation Xbox Meta
Skullcandy Sennheiser Audio-Technica Shure Sonos Marshall Belkin Mophie OtterBox Nvidia AMD Intel Gigabyte ASRock
Zotac Sapphire XFX Thermaltake NZXT Elgato HyperX SteelSeries Epson Brother Soundcore Ugreen Baseus EcoFlow Jackery
Pioneer Klipsch Polk Yamaha Denon Onkyo Ultimate-Ears Tile Chromecast Kindle Echo Motorola OnePlus Nothing Xiaomi
Nike Adidas Puma Reebok Asics Brooks Hoka Saucony On New-Balance Under-Armour Columbia The-North-Face Patagonia
Yeti Stanley Coleman Igloo Wilson Spalding Rawlings Callaway TaylorMade Titleist Bowflex NordicTrack Peloton
Hydro-Flask CamelBak Shimano Penn Bushnell Vortex Leupold Ozark-Trail Owala Contigo Solo-Stove Traeger Weber
Levi's Carhartt Calvin-Klein Tommy-Hilfiger Ralph-Lauren Michael-Kors Coach Kate-Spade Fossil Timex Ray-Ban Oakley
Crocs UGG Converse Vans Skechers Clarks Timberland Wrangler Hanes Champion Lululemon Gap Dockers Sperry Merrell
KEEN Teva Birkenstock Dr.-Martens Steve-Madden Sam-Edelman Cole-Haan Kenneth-Cole Guess Lacoste
Dyson Shark iRobot Roomba Bissell Hoover Ninja KitchenAid Cuisinart Instant-Pot Keurig Nespresso Breville
Le-Creuset Lodge Calphalon T-fal Pyrex Rubbermaid OXO Char-Broil DeWalt Milwaukee Makita Ryobi Craftsman Bosch
Black+Decker Kobalt Worx EGO Greenworks Husky Vevor Hamilton-Beach Crock-Pot Chefman Cosori Vitamix Nutribullet
Corelle Tramontina Henckels Lasko Honeywell Levoit Govee Philips-Hue Kasa Eufy Roborock Ecovacs Tineco
Olay CeraVe Neutrogena L'Oreal Maybelline Revlon Dove Gillette Oral-B Colgate Crest Braun Remington Conair
Clinique Estee-Lauder Lancome Tarte Urban-Decay NYX e.l.f. Olaplex Dyson-Airwrap Native Cetaphil La-Roche-Posay
Advil Tylenol Centrum Nature-Made Vitafusion Theragun Omron
LEGO Hasbro Mattel Barbie Hot-Wheels Nerf Funko Melissa-&-Doug Fisher-Price VTech Crayola Play-Doh Squishmallows
Purina Blue-Buffalo Pedigree Iams Hill's Greenies Kong Frisco
Mobil-1 Castrol Pennzoil Michelin Goodyear Armor-All Meguiar's Chemical-Guys NOCO Viair Rain-X Bosch
Pampers Huggies Graco Chicco Evenflo Similac Enfamil
Tide Bounty Charmin Lysol Clorox Febreze Swiffer Cascade Dawn
""".split()
_BRAND_INDEX = {re.sub(r"[^a-z0-9]", "", b.lower().replace("-", " ")): b.replace("-", " ") for b in BRANDS}

# Spec tokens that look like models but aren't: storage, refresh rate, wattage, resolution, years, chips.
_SPEC = re.compile(r"^(?:\d+(?:\.\d+)?(?:GB|TB|MB|GHZ|MHZ|HZ|W|V|MAH|WH|MM|CM|IN|INCH|FT|OZ|LB|LBS|CT|PK|PC|K|P|NM|"
                   r"QT|L|ML|G|KG|MP|X|FPS|MS|DB|AH|A|AMP|HP|CC|BTU|GAL|PCS|PACK|PIECE|PIECES|COUNT|SERIES|GEN|TH|ND|"
                   r"RD|ST)|(?:19|20)\d\d|WIFI\d*|USB\w*|HDMI\d*|DDR\d|PCIE\d*|LTE|5G|4K|8K|M\d|[A-Z]\d|BT\d*|"
                   r"I[3579]|R[3579]|RTX\d+|GTX\d+|RX\d+|IPX\d|IP\d\d|UHS\w*|V\d+|NVME|QHD|FHD|UHD)$")
_WORDISH = {"IN", "PORT", "PORTS", "PACK", "PK", "PIECE", "PIECES", "PC", "PCS", "WAY", "TIER", "LAYER", "SPEED",
            "BIT", "CORE", "GEN", "SERIES", "INCH", "FT", "OZ", "LB", "COUNT", "CT", "QT", "GAL", "CUP", "CUPS", "SET",
            "SETS", "STAGE", "STEP", "BURNER", "DRAWER", "DOOR", "SEAT", "SEATER", "PERSON", "PLAYER", "SLICE",
            "SPEEDS", "MODE", "MODES", "IN1", "INONE", "HOUR", "HR", "DAY", "YEAR", "YR", "MONTH", "AA", "AAA",
            "LAYERS", "SIDED", "PLY", "GAUGE", "SHELF", "TIERS", "PANEL", "BAY", "BED", "BEDROOM", "LBS", "KG"}
_MODEL_TOKEN = re.compile(r"(?<![\w/])([A-Za-z0-9][A-Za-z0-9\-/.]{2,}[A-Za-z0-9])(?![\w])")
_NIKE_STYLE = re.compile(r"\b([A-Z]{2}\d{4}-\d{3})\b")
_LEGO_SET = re.compile(r"\b(\d{4,6})\b")
_SCREEN = re.compile(r"(\d{2,3}(?:\.\d)?)\s?(?:\"|”|″|''|-inch\b|\s?inch(?:es)?\b|-in\.?\b|\s?in\.?\s?(?:class|screen|display|monitor|tv|laptop))",
                     re.I)
_STORAGE = re.compile(r"\b(\d{2,4})\s?(GB|TB)\b", re.I)
_OUNCES = re.compile(r"\b(\d{1,3}(?:\.\d+)?)\s?-?\s?(?:fl\.?\s?)?oz\b", re.I)
_PACK = re.compile(r"\b(\d{1,3})\s?-?\s?(?:pack|pk|ct|count|pc|pcs|piece)\b", re.I)
_CONDITION = re.compile(r"\b(refurb(?:ished)?|renewed|open[- ]box|pre-?owned|used|certified refurbished|"
                        r"scratch (?:and|&) dent)\b", re.I)
# Product kinds that are usually accessories: a listing of one can't be the same product as a deal that isn't one.
_KIND = re.compile(r"\b(ink|toner|cartridges?|filters?|refills?|straps?|watch ?bands?|remotes?|mounts?|brackets?|"
                   r"sleeves?|skins?|screen protectors?|tips|ear ?pads|replacement heads?|brush heads?|bulbs?|"
                   r"blades?|bags? for|batteries|battery packs?)\b", re.I)
_ACCESSORY = re.compile(r"\b(?:compatible (?:with|for)|works with|fits|designed for|made for|"
                        r"replacement (?:for|parts?)|replacements?\b|for use with|"
                        r"ink cartridges?|toner cartridges?|cartridges? for|refills?|(?:screen|lens) protectors?|"
                        r"remote control for|replacement remote|ear ?pads|ear ?cushions|"
                        r"case for|cover for|protector for|"
                        r"charger for|cable for|stand for|mount for|holder for|skins? for|strap for|band for|"
                        r"ear ?tips for|for (?:use with )?(?:apple |samsung |sony |google )?"
                        r"(?:iphone|ipad|airpods|galaxy|macbook|nintendo switch|switch 2|ps5|xbox|pixel|apple watch))\b",
                        re.I)
_PREFIX_NOISE = re.compile(r"^(?:\[[^\]]*\]\s*|\$\S+\s*\|\s*|prime members?:\s*|refurb(?:ished)?\s+|open-box\s+|"
                           r"(?:\d+-(?:pk|pack|ct|pc|piece|count)|\d+(?:\.\d+)?-?(?:oz|lb|ft|in)\.?|\d+\")\s+)+", re.I)


# Popular products sold under a name rather than a part number: (pattern, brand, model). First match wins.
NAMED: tuple[tuple[re.Pattern, str, str], ...] = tuple((re.compile(rx, re.I), b, m) for rx, b, m in (
    (r"\bairpods pro 3\b", "Apple", "AIRPODSPRO3"),
    (r"\bairpods pro 2\b|\bairpods pro \(2nd gen", "Apple", "AIRPODSPRO2"),
    (r"\bairpods 4\b.*\b(?:anc|active noise)", "Apple", "AIRPODS4ANC"),
    (r"\bairpods 4\b", "Apple", "AIRPODS4"),
    (r"\bairpods max 2\b", "Apple", "AIRPODSMAX2"),
    (r"\bairpods max\b", "Apple", "AIRPODSMAX"),
    (r"\bapple watch ultra 3\b", "Apple", "WATCHULTRA3"),
    (r"\bapple watch ultra 2\b", "Apple", "WATCHULTRA2"),
    (r"\bapple watch series (\d{1,2})\b", "Apple", "WATCHS{0}"),
    (r"\bapple watch se 3\b|\bapple watch se \(3rd gen", "Apple", "WATCHSE3"),
    (r"\bmacbook air\b.*\b(m[1-6])\b", "Apple", "MACBOOKAIR{0}"),
    (r"\bmacbook pro\b.*\b(m[1-6](?: pro| max)?)\b", "Apple", "MACBOOKPRO{0}"),
    (r"\bnintendo switch 2\b", "Nintendo", "SWITCH2"),
    (r"\bnintendo switch oled\b", "Nintendo", "SWITCHOLED"),
    (r"\bmeta quest 3s\b", "Meta", "QUEST3S"),
    (r"\bmeta quest 3\b", "Meta", "QUEST3"),
    (r"\bsteam deck oled\b", "Valve", "STEAMDECKOLED"),
    (r"\bkindle paperwhite\b", "Amazon", "KINDLEPAPERWHITE"),
    (r"\bkindle colorsoft\b", "Amazon", "KINDLECOLORSOFT"),
    (r"\bkindle scribe\b", "Amazon", "KINDLESCRIBE"),
    (r"\bfire tv stick 4k max\b", "Amazon", "FIRETVSTICK4KMAX"),
    (r"\bfire tv stick 4k\b", "Amazon", "FIRETVSTICK4K"),
    (r"\becho dot\b.*\b(\d)(?:st|nd|rd|th) gen", "Amazon", "ECHODOT{0}"),
    (r"\bmx master 3s\b", "Logitech", "MXMASTER3S"),
    (r"\bmx master 4\b", "Logitech", "MXMASTER4"),
    (r"\bgalaxy s(\d{2}) ultra\b", "Samsung", "GALAXYS{0}ULTRA"),
    (r"\bgalaxy s(\d{2})\+", "Samsung", "GALAXYS{0}PLUS"),
    (r"\bgalaxy buds ?(\d) pro\b", "Samsung", "GALAXYBUDS{0}PRO"),
    (r"\bpixel (\d{1,2}) pro xl\b", "Google", "PIXEL{0}PROXL"),
    (r"\bpixel (\d{1,2}) pro\b", "Google", "PIXEL{0}PRO"),
    (r"\bpixel (\d{1,2})a\b", "Google", "PIXEL{0}A"),
    (r"\bpowerbeats pro 2\b", "Beats", "POWERBEATSPRO2"),
    (r"\bbeats studio pro\b", "Beats", "BEATSSTUDIOPRO"),
    (r"\bbeats solo 4\b", "Beats", "BEATSSOLO4"),
))


def named_model(title: str) -> tuple[str, str, str]:
    """(brand, model, the words as written) for products known by name ("AirPods Pro 3"), or ('', '', '')."""
    for rx, brand, model in NAMED:
        m = rx.search(title or "")
        if m:
            words = re.sub(r"\s*\(.*$", "", m.group(0)).strip()
            return brand, model.format(*(g.upper().replace(" ", "") for g in m.groups())), words
    return "", "", ""


def surface_model(title: str, model: str) -> str:
    """The model as the title writes it ("WH-1000XM6" for WH1000XM6): what other sites' search boxes understand."""
    for m in _MODEL_TOKEN.finditer(title or ""):
        tok = m.group(1).strip(".-/")
        if norm_model(tok) == model:
            return tok
    return model


def norm_model(token: str) -> str:
    """'WH-1000XM5/B' -> 'WH1000XM5' (the part before '/' is the model; after it, color or region)."""
    return re.sub(r"[^A-Z0-9]", "", token.upper().split("/")[0])


def brand_of(title: str, hint: str = "") -> str:
    if hint:
        known = _BRAND_INDEX.get(re.sub(r"[^a-z0-9]", "", hint.lower()))
        return known or hint.strip()
    head = _PREFIX_NOISE.sub("", title or "").strip()
    head = re.split(r"\s+-\s+", head)[0] if " - " in head[:40] else head      # "Samsung - 48\" Class ..." (Best Buy)
    words = re.findall(r"[\w'+&.!-]+", head)
    for n in (3, 2, 1):
        if len(words) >= n:
            key = re.sub(r"[^a-z0-9]", "", " ".join(words[:n]).lower())
            if key in _BRAND_INDEX:
                return _BRAND_INDEX[key]
    return ""


def models_of(title: str, brand: str = "") -> list[str]:
    """Model-number candidates in a title, best first. Spec tokens (128GB, 120Hz, 2026, i5) are not models."""
    out: list[str] = []
    for m in _NIKE_STYLE.finditer(title):
        out.append(norm_model(m.group(1)))
    if brand.lower() == "lego":
        # A LEGO set's identity is its set number; "FW14B" or "A524" in a title is the model car, not the set.
        return [m.group(1) for m in _LEGO_SET.finditer(title) if not re.fullmatch(r"(?:19|20)\d\d", m.group(1))]
    for m in _MODEL_TOKEN.finditer(title):
        tok = m.group(1).strip(".-/")
        up = tok.upper()
        n = norm_model(tok)
        if len(n) < 4 or not re.search(r"\d", n) or not re.search(r"[A-Z]", n):
            continue
        if _SPEC.match(n) or _SPEC.match(up.replace("-", "")):
            continue
        if re.fullmatch(r"\d+[A-Z]{1,2}", n) and not re.fullmatch(r"\d{3,}[A-Z]{2}", n):
            continue                                   # 65IN, 12V, 3PK: sizes, not models
        if len(re.sub(r"\D", "", n)) < 2:
            continue                                   # 3PORT, USBC3: one digit isn't a model code
        letters = re.sub(r"[^A-Z]", "", n)
        if letters in _WORDISH or re.fullmatch(r"\d+[A-Z]+\d*", n) and letters in _WORDISH:
            continue                                   # 3IN1, 10PIECE, 2PACK, 4WAY
        if brand and n == norm_model(brand):
            continue                                   # "Insta360" is the brand, not a model
        if re.fullmatch(r"[A-Z]{5,}\d{1,3}", n):
            continue                                   # ULTIMATE365, SUPERNOVA2: a product line, not a model code
        if n not in out:
            out.append(n)
    out.sort(key=lambda s: (-(len(s) >= 6), -len(s)))
    return out


def attrs_of(title: str) -> dict[str, str]:
    a: dict[str, str] = {}
    m = _SCREEN.search(title)
    if m:
        a["screen"] = m.group(1)
    st = sorted({f"{n}{u.upper()}" for n, u in _STORAGE.findall(title)})
    if st:
        a["storage"] = ",".join(st)
    m = _OUNCES.search(title)
    if m:
        a["oz"] = m.group(1)
    m = _PACK.search(title)
    if m and int(m.group(1)) > 1:
        a["pack"] = m.group(1)
    m = _CONDITION.search(title)
    a["condition"] = "refurbished" if m and m.group(1).lower() not in ("open-box", "open box") else (
        "open-box" if m else "new")
    if re.search(r"\bbundle\b|\bcombo\b|\bw/ (?:game|case|charger)|\bwith (?:\w+ )?(?:game|case)\b", title, re.I):
        a["bundle"] = "yes"
    return a


def identify(title: str, brand_hint: str = "", gtin: str = "") -> Identity:
    nb, nm, words = named_model(title)
    brand = brand_of(title, brand_hint) or nb
    models = ([nm] if nm else []) + [m for m in models_of(title, brand) if m != nm]
    query = words or (surface_model(title, models[0]) if models else "")
    kinds = sorted({re.sub(r"s$", "", k.lower().replace(" ", "")) for k in _KIND.findall(title or "")})
    return Identity(brand=brand, model=models[0] if models else "", gtin=re.sub(r"\D", "", gtin or ""),
                    attrs={**attrs_of(title), **({"models": ",".join(models)} if len(models) > 1 else {}),
                           **({"kinds": ",".join(kinds)} if kinds else {}), **({"q": query} if query else {})},
                    # A title naming 3+ model numbers is a compatibility list: a part, ink or case for those models.
                    accessory=bool(_ACCESSORY.search(title or "")) or len(models) >= 3)


def same_product(a: Identity, b: Identity) -> tuple[bool, str]:
    """(same?, why). Conservative by design."""
    if a.gtin and b.gtin:
        return (a.gtin.lstrip("0") == b.gtin.lstrip("0")), "gtin"
    if a.accessory != b.accessory:
        return False, "accessory"
    if a.attrs.get("kinds", "") != b.attrs.get("kinds", ""):
        return False, "different kind of product"
    am = {a.model, *a.attrs.get("models", "").split(",")} - {""}
    bm = {b.model, *b.attrs.get("models", "").split(",")} - {""}
    if not (am & bm):
        return False, "different model"
    if a.brand and b.brand and a.brand.lower() != b.brand.lower():
        return False, "different brand"
    for k in ("screen", "storage", "oz", "pack"):
        if a.attrs.get(k) and b.attrs.get(k) and a.attrs[k] != b.attrs[k]:
            return False, f"different {k}"
    if a.attrs.get("bundle") != b.attrs.get("bundle"):
        return False, "bundle vs single item"
    if a.attrs.get("condition", "new") != b.attrs.get("condition", "new"):
        return False, "different condition"
    return True, "model"


def model_query(ident: Identity) -> Optional[str]:
    """What to type into another site's search box to find this product, or None if it isn't identifiable.
    Accessories aren't compared: "case for Switch 2" names the console, not the case."""
    if not ident.model or ident.accessory:
        return None
    q = ident.attrs.get("q") or ident.model
    if ident.brand and ident.brand.lower() not in q.lower():
        q = f"{ident.brand} {q}"
    return q
