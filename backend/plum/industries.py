"""The fixed industry list, and the rules that put a deal into industries.

Evidence, strongest first:
  1. the source's own taxonomy: Flipp labels ad items with Google Product Taxonomy categories (`_L1`/`_L2`), and
     dealnews files every post under its category tree;
  2. keyword rules on the title and brand;
  3. the merchant's prior (a grocery store's unlabelled item is groceries).
A deal can belong to more than one industry. Every label carries the rule that produced it.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Iterable, Optional

from .reference import DATA, norm


@dataclass(frozen=True)
class Industry:
    id: str
    name: str
    description: str


INDUSTRIES: tuple[Industry, ...] = (
    Industry("tech", "Tech & Electronics", "TVs, computers, phones, audio, cameras, video games, smart home"),
    Industry("sports", "Sports & Outdoors", "Fitness, team sports, camping, hunting & fishing, athletic gear"),
    Industry("fashion", "Fashion & Apparel", "Clothing, shoes, bags, jewelry and accessories"),
    Industry("home", "Home & Garden", "Furniture, decor, kitchen, appliances, tools, lawn & garden"),
    Industry("beauty", "Beauty & Personal Care", "Makeup, skin and hair care, fragrance, grooming"),
    Industry("health", "Health & Wellness", "Pharmacy, vitamins, medicine, first aid, health devices"),
    Industry("grocery", "Grocery & Household", "Food, drinks, cleaning, paper and laundry supplies"),
    Industry("toys", "Toys, Games & Hobbies", "Toys, LEGO, board games, crafts, party supplies"),
    Industry("baby", "Baby & Kids", "Diapers, baby gear, nursery, kids' clothing"),
    Industry("pets", "Pets", "Pet food, treats, toys and supplies"),
    Industry("auto", "Automotive", "Car parts, tools, accessories, tires, car care"),
    Industry("office", "Office & School", "Office supplies, school supplies, printers, office furniture"),
    Industry("dining", "Restaurants & Dining", "Restaurant chain promotions at locations near you"),
)
IDS = tuple(i.id for i in INDUSTRIES)
BY_ID = {i.id: i for i in INDUSTRIES}


def parse_ids(raw: str | Iterable[str]) -> tuple[list[str], list[str]]:
    """'tech,sports' -> (valid ids, invalid ids)."""
    items = raw.split(",") if isinstance(raw, str) else list(raw)
    ids = [i.strip().lower() for i in items if i and i.strip()]
    return [i for i in ids if i in BY_ID], [i for i in ids if i not in BY_ID]


# --- Google Product Taxonomy (what Flipp labels ad items with) ---------------------------------------------------
TAXONOMY_L1: dict[str, list[str]] = {
    "Electronics": ["tech"], "Cameras & Optics": ["tech"], "Software": ["tech"],
    "Sporting Goods": ["sports"],
    "Apparel & Accessories": ["fashion"], "Luggage & Bags": ["fashion"],
    "Home & Garden": ["home"], "Furniture": ["home"], "Hardware": ["home"], "Religious & Ceremonial": ["home"],
    "Food, Beverages & Tobacco": ["grocery"],
    "Toys & Games": ["toys"], "Arts & Entertainment": ["toys"],
    "Baby & Toddler": ["baby"],
    "Animals & Pet Supplies": ["pets"],
    "Vehicles & Parts": ["auto"],
    "Office Supplies": ["office"], "Business & Industrial": ["office"],
    "Health & Beauty": [],        # decided by L2 or keywords: personal care vs health care
    "Media": [],                  # books and magazines fit no industry; DVDs and music go to tech below
    "Mature": [],
}
TAXONOMY_L2: dict[tuple[str, str], list[str]] = {
    ("Home & Garden", "Household Supplies"): ["grocery"],
    ("Home & Garden", "Home Security"): ["tech", "home"],
    ("Home & Garden", "Business & Home Security"): ["tech", "home"],
    ("Health & Beauty", "Personal Care"): ["beauty"],
    ("Health & Beauty", "Health Care"): ["health"],
    ("Health & Beauty", "Jewelry Cleaning & Care"): ["fashion"],
    ("Furniture", "Baby & Toddler Furniture"): ["baby", "home"],
    ("Furniture", "Office Furniture"): ["home", "office"],
    ("Furniture", "Office Furniture Accessories"): ["home", "office"],
    ("Electronics", "Print, Copy, Scan & Fax"): ["tech", "office"],
    ("Luggage & Bags", "Diaper Bags"): ["baby"],
    ("Baby & Toddler", "Baby Toys"): ["baby", "toys"],
    ("Baby & Toddler", "Baby Toys & Activity Equipment"): ["baby", "toys"],
    ("Business & Industrial", "Food Service"): ["grocery"],
    ("Business & Industrial", "Medical"): ["health"],
    ("Business & Industrial", "Hairdressing & Cosmetology"): ["beauty"],
    ("Business & Industrial", "Work Safety Protective Gear"): ["home"],
    ("Business & Industrial", "Agriculture"): ["home"],
    ("Business & Industrial", "Construction"): ["home"],
    ("Business & Industrial", "Material Handling"): ["home"],
    ("Business & Industrial", "Signage"): [],          # Flipp files store promo banners here; the words decide
    ("Arts & Entertainment", "Event Tickets"): [],
    ("Media", "DVDs & Videos"): ["tech"],
    ("Media", "Music & Sound Recordings"): ["tech"],
    ("Mature", "Weapons"): ["sports"],
    ("Sporting Goods", "Indoor Games"): ["sports", "toys"],
    ("Cameras & Optics", "Optics"): ["sports", "tech"],
}


# --- keyword rules -----------------------------------------------------------------------------------------------
def _rx(*words: str) -> re.Pattern:
    """Whole words or phrases, each also matching its plural ('cereal' finds 'Cereals')."""
    return re.compile(r"\b(?:" + "|".join(f"(?:{w})(?:e?s)?" for w in words) + r")\b", re.I)


# Ordered: specific phrases that would otherwise be misread come first. Each rule adds its industries.
KEYWORD_RULES: tuple[tuple[str, re.Pattern, list[str]], ...] = (
    ("pets", _rx(r"(?:dog|cat|pet|puppy|kitten)s? (?:food|treats?|beds?|toys?|crates?|carriers?|bowls?|collars?|"
                 r"harness(?:es)?|shampoo|chews?|litter|tree|gates?|kennels?|houses?|doors?|wipes|pads|supplements?|"
                 r"grooming|clippers|brush(?:es)?|fountains?|feeders?|leash(?:es)?)", r"kibble", r"cat litter", r"litter box",
                 r"bird ?seed", r"aquarium", r"leash(?:es)?", r"dog bed", r"chew toys?", r"flea", r"heartgard",
                 r"nexgard", r"reptiles?", r"reptile terrariums?", r"aquariums?", r"fish tanks?", r"hamsters?", r"guinea pigs?", r"bird cages?", r"(?:pet|dog) gates?", r"purina", r"pedigree", r"blue buffalo", r"meow mix", r"friskies", r"milk-bone",
                 r"greenies", r"temptations"), ["pets"]),
    ("baby", _rx(r"itzy ritzy", r"(?:baby|safety|mesh|walk-?thru|pressure[- ]mounted|stair) gates?", r"diapers?", r"baby", r"babies", r"infants?", r"toddlers?", r"newborn", r"strollers?",
                 r"car seats?", r"cribs?", r"pacifiers?", r"infant formula", r"baby formula", r"onesies?",
                 r"sippy", r"pampers", r"huggies", r"luvs", r"similac", r"enfamil", r"gerber", r"kids'? clothing",
                 r"carter's", r"nursery"), ["baby"]),
    ("home-goods", _rx(r"night lights?", r"wine glass", r"glass(?:es)? sets?", r"stemware", r"drinkware", r"glassware",
                       r"barware", r"decanters?", r"carpet cleaners?", r"spot cleaners?", r"steam (?:mops?|cleaners?)",
                       r"bissell", r"(?:ice cream|frozen treat|waffle|bread|pasta|rice|yogurt|popcorn|soda|sandwich|pizza) makers?",
                       r"sheet sets?", r"(?:bath|beach|hand|kitchen) towels?", r"towel sets?", r"bedding(?: sets?)?",
                       r"comforter(?: sets?)?", r"duvet(?: covers?)?", r"quilts?", r"pillowcases?", r"throw pillows?",
                       r"throw blankets?", r"(?:espresso|coffee|cold brew) (?:machines?|makers?)", r"espresso", r"brewers?",
                       r"(?:stand|hand) mixers?", r"air fryers?", r"slow cookers?", r"pressure cookers?"), ["home"]),
    ("tech-brand", _rx(r"verizon", r"t-mobile", r"straight talk", r"tracfone", r"cricket wireless", r"boost mobile", r"total wireless", r"energizer", r"duracell", r"apple (?:airpods|ipad|iphone|macbook|imac|watch|tv|pencil)", r"airpods", r"ipad",
                       r"iphone", r"macbook", r"nintendo", r"playstation", r"ps5", r"xbox", r"switch 2",
                       r"galaxy (?:s\d+|z|tab|watch|buds)", r"pixel (?:\d+|buds|watch)", r"ring (?:video )?doorbell",
                       r"echo (?:dot|show|pop)", r"kindle", r"fire tv", r"roku", r"chromecast", r"fitbit",
                       r"garmin", r"gopro", r"meta quest"), ["tech"]),
    ("tech", _rx(r"tvs?", r"television", r"oled", r"qled", r"4k", r"uhd", r"laptops?", r"notebook pc",
                 r"chromebooks?", r"tablet(?!s)", r"smartphones?", r"cell phones?", r"headphones?", r"earbuds?",
                 r"soundbars?", r"(?:bluetooth|smart|portable|bookshelf) speakers?", r"monitors?", r"keyboards?",
                 r"mouse(?! ?trap)", r"routers? (?:wi-?fi|mesh)|wi-?fi (?:\d+ )?router|mesh wi-?fi", r"ssd",
                 r"hard drive", r"flash drive", r"micro ?sd", r"memory card", r"usb-?c? (?:cable|hub|adapter|charger|dock)", r"hdmi", r"webcams?",
                 r"(?:digital|instant|security|dash|action) cam(?:era)?s?", r"drones?", r"smart ?watch(?:es)?",
                 r"video games?", r"gaming", r"consoles?", r"controllers?", r"printers?", r"projectors?",
                 r"(?:wall|car|wireless|phone|laptop|gan|usb-?c) chargers?", r"charging (?:station|dock|pad|stand)", r"power banks?", r"graphics cards?", r"gpu", r"processors?", r"cpu",
                 r"motherboards?", r"desktop(?: pc| computer)?", r"computers?", r"streaming (?:stick|device)",
                 r"smart (?:plug|bulb|home|display|lock)", r"camera"), ["tech"]),
    ("toys", _rx(r"scrapbook(?:ing)?s?", r"photo albums?", r"fuse beads?", r"perler", r"bead kits?", r"craft kits?", r"sticker books?", r"coloring books?", r"creativity for kids", r"kids'? (?:craft|activity|science) (?:kits?|sets?)", r"party favors?", r"board books?", r"picture books?", r"kids\' books?", r"slime", r"stickers?", r"activity kits?", r"coloring", r"pumpkin (?:decorating|carving)", r"trick or treat", r"halloween (?:craft\w*|activity)", r"lego", r"toys?", r"dolls?", r"action figures?", r"puzzles?", r"board games?", r"card games?",
                 r"playsets?", r"nerf", r"barbie", r"hot wheels", r"plush (?:toys?|animals?|dolls?|pals?|characters?)", r"stuffed animals?", r"squishmallows?", r"funko",
                 r"play-doh", r"crayola", r"crafts?", r"craft supplies", r"yarn", r"party supplies", r"balloons?",
                 r"halloween decor", r"costumes?"), ["toys"]),
    ("sports", _rx(r"fishing", r"hunting", r"camping", r"tents?", r"sleeping bags?", r"kayaks?", r"golf",
                   r"basketballs?", r"footballs?", r"baseball", r"softball", r"soccer", r"tennis", r"pickleball",
                   r"volleyball", r"bikes?", r"bicycles?", r"cycling", r"treadmills?", r"dumbbells?", r"kettlebells?",
                   r"yoga", r"fitness", r"exercise", r"workout", r"cleats", r"running shoes?", r"athletic",
                   r"ammo", r"ammunition", r"rifles?", r"shotguns?", r"handguns?", r"archery", r"crossbows?",
                   r"hiking", r"trail", r"coolers?", r"binoculars", r"scopes?", r"jerseys?", r"nfl", r"nba", r"mlb",
                   r"nhl", r"ncaa", r"skateboards?", r"scooters?", r"paddle ?boards?", r"swim(?:wear|suits?)?",
                   r"yeti", r"stanley quencher"), ["sports"]),
    ("health", _rx(r"bladder control", r"incontinence", r"male guards?", r"guards for men", r"composure", r"tena", r"prevail", r"(?:incontinence|bladder|maxi|panty|heating|sanitary|bed) pads", r"pads (?:or|&|and) (?:liners|underwear)", r"kinesiology", r"therapy tape", r"(?:knee|back|wrist|ankle) (?:brace|support)s?", r"braces?", r"compression (?:sleeves?|socks)", r"heating pads?", r"massagers?", r"tens unit", r"hydrogen peroxide", r"rubbing alcohol", r"isopropyl", r"cotton swabs", r"q-?tips", r"liners", r"poise", r"always discreet", r"laxative", r"miralax", r"acid reducer", r"omeprazole", r"famotidine", r"antacids?", r"epsom salt", r"hand sanitizer", r"sanitizer", r"allergy", r"sleep aid", r"zzzquil", r"vicks", r"theraflu", r"emergen-c", r"airborne", r"\w+ health", r"vitamins?", r"supplements?", r"multivitamin", r"probiotics?", r"melatonin", r"tablets",
                   r"caplets", r"capsules", r"softgels", r"gummies", r"pain relie(?:f|ver)", r"allergy",
                   r"cold (?:&|and) flu", r"cough", r"antacid", r"first aid", r"bandages?", r"thermometers?",
                   r"blood pressure", r"covid", r"test kits?", r"pharmacy", r"prescriptions?", r"advil", r"tylenol",
                   r"motrin", r"aleve", r"claritin", r"zyrtec", r"mucinex", r"nyquil", r"dayquil", r"centrum",
                   r"nature made", r"protein powder", r"electrolytes?", r"contact lens(?:es)?", r"reading glasses",
                   r"incontinence", r"depend", r"\d+ ?mg"), ["health"]),
    ("beauty", _rx(r"(?:hair|face|facial|body|hand|eye|night|day|shave|shaving|curl|styling) (?:cream|mask|oil|gel|serum|treatment|butter|scrub|mist|mousse)", r"sheamoisture", r"leave-in", r"edge control", r"toner pads", r"cotton pads", r"makeup remover(?: pads| wipes)?", r"(?:exfoliating|cleansing) pads", r"manscaped", r"body groomers?", r"(?:beard|hair|nose|body) trimmers?", r"groomers?", r"balms?", r"lip balm", r"smashbox", r"glass skin", r"hand soap", r"bar soap", r"body lotion", r"jergens", r"suave", r"pantene", r"head (?:&|and) shoulders", r"herbal essences", r"secret", r"degree", r"old spice", r"axe", r"essential oils?", r"makeup", r"cosmetics?", r"lipsticks?", r"lip gloss", r"mascara", r"eyeliner", r"foundation",
                   r"concealer", r"nail polish", r"nails", r"shampoos?", r"conditioners?", r"hair (?:care|dryer|color|spray)",
                   r"skin ?care", r"serums?", r"moisturi[sz]ers?", r"lotions?", r"body wash", r"cleansers?",
                   r"fragrances?", r"perfumes?", r"cologne", r"eau de (?:parfum|toilette)", r"deodorants?",
                   r"antiperspirants?", r"razors?", r"shav(?:e|ing)", r"toothpaste", r"toothbrush(?:es)?",
                   r"mouthwash", r"sunscreen", r"olay", r"cerave", r"neutrogena", r"l'or[eé]al", r"maybelline",
                   r"revlon", r"dove", r"gillette", r"colgate", r"crest", r"sephora", r"ulta"), ["beauty"]),
    ("fashion", _rx(r"drawstring bags?", r"crossbody(?: bags?)?", r"duffel(?: bags?)?", r"shoulder bags?", r"belt bags?", r"tote bags?", r"(?:gold|silver|figaro|rope|box|cuban|curb|snake|sparkle) chains?", r"chains", r"bangles?", r"halo rings?", r"platinum", r"ctw", r"diamond (?:rings?|necklaces?|earrings?|pendants?|studs?|bands?|bracelets?|jewelry)", r"lab-grown diamonds?", r"\d+mm bangle", r"denim", r"panties", r"briefs", r"boxers?", r"lingerie", r"flats", r"loafers", r"fleece", r"flannels?", r"outfits?", r"lab-(?:grown|created) (?:diamonds?|gemstones?)", r"gemstones?", r"sterling silver", r"1[04]k (?:gold|white gold|yellow gold|rose gold)", r"ct\.? t\.?w\.?", r"solitaire", r"pendants?", r"charms?", r"pajama sets?", r"sleepwear", r"activewear", r"swimwear", r"t-?shirts?", r"tees?", r"shirts?", r"jeans", r"pants", r"shorts", r"dress(?:es)?", r"skirts?",
                    r"sweaters?", r"hoodies?", r"sweatshirts?", r"jackets?", r"coats?", r"vests?", r"socks",
                    r"underwear", r"bras?", r"leggings", r"pajamas?", r"boots", r"sneakers", r"shoes", r"sandals",
                    r"heels", r"slippers", r"handbags?", r"purses?", r"wallets?", r"backpacks?", r"jewelry",
                    r"necklaces?", r"earrings?", r"bracelets?", r"(?:diamond|gold|silver) (?:ring|band)s?",
                    r"(?<!smart )(?<!apple )(?<!galaxy )(?<!pixel )watch(?:es)?(?! ?(?:bands?|party|straps?|chargers?))", r"sunglasses", r"hats?", r"caps?", r"scarf|scarves", r"belts?",
                    r"totes?", r"luggage", r"suitcases?", r"apparel", r"clothing", r"outerwear", r"blazers?",
                    r"suits?", r"polos?", r"flannel", r"cardigans?", r"joggers?", r"crocs", r"levi'?s", r"nike",
                    r"adidas", r"under armour", r"new balance", r"skechers", r"hoka", r"asics"), ["fashion"]),
    ("auto", _rx(r"motor oil", r"car (?:battery|wash|wax|seat covers?|charger|mount|vacuum|care)", r"tires?",
                 r"wiper blades?", r"windshield", r"brake", r"spark plugs?", r"jump starter", r"headlights?",
                 r"automotive", r"vehicle", r"truck bed", r"trailer hitch", r"floor mats", r"antifreeze",
                 r"mobil 1", r"castrol", r"pennzoil", r"armor ?all", r"meguiar'?s", r"obd"), ["auto"]),
    ("office", _rx(r"office", r"school supplies", r"notebooks?(?! pc)", r"binders?", r"pens?", r"pencils?",
                   r"markers?", r"highlighters?", r"staplers?", r"paper (?:ream|case)", r"copy paper", r"ink",
                   r"toner", r"envelopes?", r"desk organizers?", r"filing (?:cabinets?|folders?|boxes|supplies|systems?|trays?)", r"file folders?", r"labels?", r"calculators?",
                   r"backpacks? for school", r"post-it", r"sharpie", r"shredders?", r"desks?", r"office chairs?"),
     ["office"]),
    ("home", _rx(r"ornaments?", r"ornament storage", r"animated", r"holiday (?:decor\w*|lights?)", r"christmas (?:trees?|lights?|decor\w*)", r"sheet sets?", r"light-?up", r"inflatables?", r"pumpkins?", r"wreaths?", r"garlands?", r"halloween (?:decor\w*|inflatable\w*)", r"shades", r"blinds", r"drapes", r"window (?:panels?|treatments?)", r"bedding", r"quilts?", r"duvets?", r"bath mats?", r"shower curtains?", r"dinnerware", r"glassware", r"mugs?", r"furniture", r"sofas?", r"couch(?:es)?", r"chairs?", r"tables?", r"beds?", r"mattress(?:es)?",
                 r"pillows?", r"sheets", r"comforters?", r"blankets?", r"towels?", r"rugs?", r"curtains?", r"lamps?",
                 r"lighting", r"decor", r"candles?", r"frames?", r"mirrors?", r"cookware", r"pots?", r"pans?",
                 r"skillets?", r"knives", r"knife set", r"dinnerware", r"bakeware", r"blenders?", r"air fryers?",
                 r"coffee makers?", r"microwaves?", r"toasters?", r"mixers?", r"instant pot", r"ninja",
                 r"keurig", r"vacuums?", r"dyson", r"shark", r"roomba", r"appliances?", r"refrigerators?",
                 r"washers?", r"dryers?", r"dishwashers?", r"grills?", r"smokers?", r"patio", r"garden", r"lawn",
                 r"mowers?", r"trimmers?", r"leaf blowers?", r"plants?", r"mulch", r"soil", r"fertilizer",
                 r"tools?", r"drills?", r"saws?", r"wrench(?:es)?", r"screwdrivers?", r"ladders?", r"paint",
                 r"storage bins?", r"organizers?", r"shelv(?:es|ing)", r"faucets?", r"ceiling fans?", r"fans?",
                 r"heaters?", r"air purifiers?", r"humidifiers?", r"generators?", r"tumblers?", r"water bottles?",
                 r"dewalt", r"milwaukee", r"ryobi", r"craftsman", r"kobalt", r"black\+decker"), ["home"]),
    ("grocery", _rx(r"(?:red|white|rosé|rose|sparkling) (?:wine|blend)", r"cabernet(?: sauvignon)?", r"merlot", r"pinot (?:noir|grigio|gris)", r"chardonnay", r"sauvignon blanc", r"moscato", r"riesling", r"zinfandel", r"malbec", r"prosecco", r"champagne", r"apothic", r"barefoot", r"sutter home", r"yellow tail", r"la marca", r"meiomi", r"kendall[- ]jackson", r"josh cellars", r"19 crimes", r"seltzers?", r"hard cider", r"emergency food", r"food supply", r"salad dressing", r"dressing", r"pepperoni", r"extract", r"juices?", r"kool-aid", r"capri sun", r"gumm(?:y|ies)", r"lunchables?", r"kellogg\'?s", r"general mills", r"kraft", r"oscar mayer", r"hormel", r"armour", r"campbell\'?s", r"progresso", r"ragu", r"prego", r"barilla", r"velveeta", r"jell-?o", r"pudding", r"popcorn", r"pretzels", r"granola", r"bars", r"syrup", r"honey", r"peanut butter", r"jelly", r"spices?", r"seasonings?", r"flour", r"sugar", r"oil", r"budweiser", r"bud light", r"coors", r"miller lite", r"michelob", r"modelo", r"corona", r"dr ?pepper", r"sprite", r"fanta", r"7 ?up", r"canada dry", r"schweppes", r"mountain dew", r"gatorade", r"powerade", r"red bull", r"monster energy", r"celsius", r"hershey\'?s?", r"reese\'?s", r"kit ?kat", r"m&m\'?s", r"snickers", r"skittles", r"twix", r"blow pops?", r"tootsie", r"ferrero", r"nestle", r"mars", r"cake mix", r"brownie mix", r"frosting", r"morsels", r"meals?", r"dinners?", r"taco kit", r"fabric softener", r"downy", r"gain", r"suavitel", r"dish (?:liquid|soap|detergent)", r"palmolive", r"dawn", r"contractor bags", r"(?:trash|garbage|kitchen) bags", r"multi-purpose bags", r"air fresheners?", r"glade", r"plates", r"bowls", r"cups", r"utensils", r"foil", r"plastic wrap", r"zip ?loc\w*", r"hefty", r"glad", r"stain remover", r"spot remover", r"wrinkle releaser", r"chicken", r"beef", r"pork", r"steaks?", r"ground (?:beef|turkey)", r"bacon", r"sausages?",
                    r"ham", r"turkey", r"fish", r"salmon", r"shrimp", r"seafood", r"eggs", r"milk", r"cheese",
                    r"butter", r"yogurt", r"cream", r"bread", r"tortillas?", r"cereal", r"oatmeal", r"pasta",
                    r"rice", r"beans", r"soups?", r"sauce", r"salsa", r"chips", r"crackers", r"cookies", r"candy",
                    r"chocolate", r"snacks?", r"nuts", r"coffee", r"tea", r"soda", r"water", r"juice",
                    r"sparkling", r"beer", r"wine", r"spirits", r"vodka", r"tequila", r"whiskey", r"fruits?",
                    r"apples", r"bananas", r"berries", r"strawberries", r"grapes", r"avocados?", r"tomatoes",
                    r"potatoes", r"onions", r"lettuce", r"vegetables?", r"produce", r"frozen", r"pizza",
                    r"ice cream", r"paper towels?", r"toilet paper", r"bath tissue", r"napkins", r"trash bags?",
                    r"laundry detergent", r"detergent", r"dish soap", r"cleaner", r"cleaning", r"disinfect\w*",
                    r"bleach", r"tide", r"bounty", r"charmin", r"lysol", r"clorox", r"febreze", r"swiffer",
                    r"coca-cola|coke", r"pepsi", r"doritos", r"oreo"), ["grocery"]),
)
HOUSEHOLD_ESSENTIALS = re.compile(
    r"\b(?:clean(?:er|ers|ing)|disinfect\w*|detergents?|laundry|fabric softeners?|dryer sheets?|bleach|dish(?:washer)?|"
    r"sponges?|paper towels?|toilet paper|bath tissue|tissues?|napkins|trash bags?|garbage bags?|kitchen bags?|"
    r"(?:aluminum )?foil|plastic wrap|zip ?loc\w*|storage bags?|sandwich bags?|plates|cups|utensils|air fresheners?|"
    r"wipes|mops?|swiffer|tide|gain|downy|bounty|charmin|cottonelle|scott|lysol|clorox|febreze|glad|hefty|cascade|"
    r"dawn|finish|lemi shine|pine-?sol|mr\.? clean|scrubbing bubbles|kleenex|puffs)\b", re.I)

BABY_WORDS = re.compile(r"\b(?:baby|babies|infants?|toddlers?|newborns?|\d+\s?(?:-\s?\d+\s?)?(?:mo|months?)\b|teethers?|"
                        r"rattles?|stroller|crib|nursery|itzy ritzy|fisher-?price|baby einstein|vtech baby)", re.I)

# Bare pet words count only when no other rule names the product ("Cat Christmas Tees" are clothing).
PET_WORD = re.compile(r"\b(?:dogs?|cats?|pupp(?:y|ies)|kittens?|pets?)\b", re.I)

# Applied only when no other rule matched: "Men's ...", "Juniors' ..." in a department-store ad is clothing.
APPAREL_CUE = re.compile(r"\b(?:men'?s|women'?s|juniors'?|misses'?|girls'?|boys'?|toddler'?s?|plus size|big (?:&|and) tall)\b",
                         re.I)
TEXT_RULE_ORDER = tuple(r[0] for r in KEYWORD_RULES)

# A health word next to a tech word ("smart watch blood pressure") is ambiguous; these words win outright.
_DOMINANT = {"tech-brand": "tech"}


@dataclass
class Classification:
    industries: list[str]
    rule: str                  # "taxonomy:Electronics>Audio", "dealnews:TVs", "keywords:tech", "merchant:H-E-B"
    category: str = ""

    def __bool__(self) -> bool:
        return bool(self.industries)


def _dedupe(seq: Iterable[str]) -> list[str]:
    out: list[str] = []
    for s in seq:
        if s and s not in out:
            out.append(s)
    return out


# Items the taxonomy files under apparel but shoppers look for elsewhere: gardening gloves are garden gear.
TAXONOMY_OVERRIDES: tuple[tuple[re.Pattern, list[str]], ...] = (
    (re.compile(r"\b(?:garden(?:ing)?|work|leather work|nitrile|latex|cleaning|dish(?:washing)?) gloves?\b|"
                r"\bmiracle-?gro\b.*\bgloves?\b", re.I), ["home"]),
    (re.compile(r"\bsafety glasses\b|\bear (?:plugs|muffs)\b|\bhard hats?\b|\bknee pads\b", re.I), ["home"]),
    (re.compile(r"\b(?:bottle|floor|trolley|scissor|transmission) jacks?\b|\bjack stands?\b|\btire (?:repair|plug)s?\b|"
                r"\btire inflators?\b", re.I), ["auto"]),
    (re.compile(r"\bthrows\b|\bthrow blankets?\b|\bphoto (?:coasters?|magnets?|prints?|books?|canvas(?:es)?)\b", re.I),
     ["home"]),
    (re.compile(r"\bschool glue\b|\bglue sticks?\b", re.I), ["office"]),
    (re.compile(r"\b(?:v?\d{2}v|v\d{2}|m18|m12|max\*?)\b.*\bbatter(?:y|ies)\b|\bbatter(?:y|ies) (?:starter )?kits?\b|"
                r"\bpower tool batter(?:y|ies)\b", re.I), ["home"]),
    # towing gear the taxonomy files under hardware
    (re.compile(r"\bpintle hooks?\b|\btrailer (?:hitch|jack|lights?|wiring|coupler)s?\b|\bhitch (?:balls?|pins?|locks?|"
                r"receivers?)\b|\bball mounts?\b|\breceiver hitch\b|\btow (?:straps?|ropes?|hooks?)\b|\bwinch(?:es)?\b", re.I),
     ["auto"]),
)


def from_taxonomy(l1: Optional[str], l2: Optional[str]) -> Classification:
    l1, l2 = (l1 or "").strip(), (l2 or "").strip()
    if not l1:
        return Classification([], "")
    label = f"{l1} > {l2}" if l2 else l1
    if (l1, l2) in TAXONOMY_L2:
        return Classification(list(TAXONOMY_L2[(l1, l2)]), f"taxonomy:{label}", label)
    if l1 == "Baby & Toddler" and l2.startswith("Baby Toys"):
        return Classification(["toys", "baby"], f"taxonomy:{label}", label)
    return Classification(list(TAXONOMY_L1.get(l1, [])), f"taxonomy:{label}", label)


_INGREDIENTS = re.compile(r"\s+(?:with|w/|infused with|enriched with|made with|featuring)\s+", re.I)


def head_of(text: str) -> str:
    """The product phrase before its ingredients or extras: "Body Wash with Vitamin B3" -> "Body Wash"."""
    return _INGREDIENTS.split(text, maxsplit=1)[0]


def from_text(*texts: str) -> Classification:
    text = " ".join(t for t in texts if t)
    if not text:
        return Classification([], "")
    # What the product is comes before "with ...": a body wash with vitamin B3 is not a vitamin.
    hits: list[tuple[str, list[str]]] = [(name, inds) for name, rx, inds in KEYWORD_RULES if rx.search(head_of(text))]
    if not hits:
        hits = [(name, inds) for name, rx, inds in KEYWORD_RULES if rx.search(text)]
    if not hits:
        if PET_WORD.search(text):
            return Classification(["pets"], "keywords:pet-word")
        if APPAREL_CUE.search(text):
            return Classification(["fashion"], "keywords:apparel-cue")
        return Classification([], "")
    for name, inds in hits:
        if name in _DOMINANT:
            return Classification(list(inds), f"keywords:{name}")
    # The first matching rule is the primary industry; a second rule adds a label only for well-known pairings
    # (athletic apparel, kids' clothing, kids' toys, personal care that is also health care).
    primary = hits[0][1]
    found = {i for _, inds in hits for i in inds}
    extra = [b for a, b in PAIRINGS if a in primary and b in found] + [a for a, b in PAIRINGS if b in primary and a in found]
    names = [h[0] for h in hits]
    return Classification(_dedupe(primary + extra), "keywords:" + "+".join(names[:2]))


PAIRINGS = (("sports", "fashion"), ("baby", "fashion"), ("baby", "toys"), ("health", "beauty"))


@lru_cache(maxsize=1)
def _dealnews_leaves() -> dict[str, list[str]]:
    data = json.loads((DATA / "dealnews_categories.json").read_text())["categories"]
    leaves: dict[str, list[str]] = {}
    for v in data.values():
        leaves.setdefault(norm(v["leaf"]), [])
        leaves[norm(v["leaf"])] = _dedupe(leaves[norm(v["leaf"])] + v["industries"])
    return leaves


def dealnews_category_ids() -> dict[str, list[str]]:
    data = json.loads((DATA / "dealnews_categories.json").read_text())["categories"]
    return {cid: v["industries"] for cid, v in data.items()}


def from_dealnews(category: str, feed_industries: Iterable[str] = ()) -> Classification:
    """dealnews' own leaf category ('Portable Speakers'), disambiguated by the feed the post came from."""
    feed = [i for i in feed_industries if i]
    leaf = _dealnews_leaves().get(norm(category))
    if leaf is None:
        return Classification(feed, f"dealnews-feed:{','.join(feed)}" if feed else "", category)
    if len(leaf) > 1 and feed and set(leaf) & set(feed):
        leaf = [i for i in leaf if i in feed]
    return Classification(list(leaf), f"dealnews:{category}", category)


def text_industries(*texts: str) -> list[str]:
    """Every industry whose keywords appear in the text, in rule order (from_text gives only the first)."""
    text = " ".join(t for t in texts if t)
    return _dedupe(i for _, rx, inds in KEYWORD_RULES if rx.search(text) for i in inds)


def classify_ad_item(l1: Optional[str], l2: Optional[str], title: str, brand: str,
                     merchant_industries: Iterable[str], exclusive: bool = False,
                     sells: Iterable[str] = (), food: bool = True) -> Classification:
    """Industries for a weekly-ad item, kept to what the store plausibly sells.

    The source's category labels are machine-made and sometimes absurd (a diamond ring at JCPenney filed under
    Food, razor blades at Lowe's under Beverages). `sells` lists the industries a store carries; a label outside
    it is replaced by what the item's words say, or else by the store's own line of business."""
    prior = list(merchant_industries)
    c = _classify_ad_item(l1, l2, title, brand, prior, exclusive, food)
    allowed = set(sells)
    if not allowed or not c.industries:
        return c
    keep = [i for i in c.industries if i in allowed]
    if keep:
        return Classification(keep, c.rule, c.category)
    words = [i for i in text_industries(title, brand) if i in allowed][:1]
    if words:
        return Classification(words, c.rule + "+not sold here, so keywords", c.category)
    fallback = [i for i in prior if i in allowed]
    return Classification(fallback, c.rule + "+not sold here" + (", so the store's line" if fallback else ""), c.category)


def _classify_ad_item(l1: Optional[str], l2: Optional[str], title: str, brand: str, prior: list[str],
                      exclusive: bool, food: bool) -> Classification:
    """Taxonomy, then keywords, then the merchant's prior. A store that sells one kind of thing (PetSmart, Ulta,
    AutoZone) decides outright: a terrarium at PetSmart is a pet supply, whatever the taxonomy calls it."""
    tax = from_taxonomy(l1, l2)
    if exclusive and prior:
        return Classification(prior, "merchant:specialty store", tax.category)
    for rx, inds in TAXONOMY_OVERRIDES:
        if rx.search(f"{brand} {title}"):
            return Classification(list(inds), f"override:{inds[0]}", tax.category)
    if l1 == "Food, Beverages & Tobacco" and not food:
        # This store sells no food, so the label is the source's mistake unless the item's own words agree
        # (a hardware store's barbecue sauce is real).
        if "grocery" in from_text(title, brand).industries:
            return Classification(["grocery"], tax.rule + "+keywords agree", tax.category)
        l1, l2, tax = None, None, Classification([], "source label ignored: the store sells no food", tax.category)
    if l1 == "Baby & Toddler" and (l2 or "").startswith("Baby Toys") and not BABY_WORDS.search(f"{brand} {title}"):
        return Classification(["toys"], tax.rule + "+no baby words", tax.category)
    if (l1, l2) == ("Home & Garden", "Household Supplies"):
        # Cleaning, laundry, paper and trash bags are household essentials (Grocery & Household); storage,
        # organization and albums are home goods.
        words = from_text(title, brand).industries
        if words and words[0] in ("toys", "office", "home"):
            return Classification(words, tax.rule + f"+keywords:{words[0]}", tax.category)
        if not HOUSEHOLD_ESSENTIALS.search(f"{brand} {title}"):
            return Classification(["home"], tax.rule + "+not an essential", tax.category)
    if (l1, l2) == ("Health & Beauty", "Personal Care"):
        # Google's Personal Care includes back care, braces, sleep aids and therapy products, not just beauty.
        words = from_text(title, brand).industries
        if "health" in words and "beauty" not in words:
            return Classification(["health"], tax.rule + "+keywords:health", tax.category)
        if "health" in words:
            return Classification(["beauty", "health"], tax.rule + "+keywords:health", tax.category)
    if tax.industries:
        inds = list(tax.industries)
        # Athletic apparel, shoes and bags at a sporting-goods store belong to sports as well as fashion.
        if "sports" in prior and set(inds) <= {"fashion"}:
            inds.append("sports")
        return Classification(_dedupe(inds), tax.rule, tax.category)
    text = from_text(title, brand)
    if l1 == "Health & Beauty":
        words = head_of(f"{brand} {title}")
        hb = [i for name, rx, inds in KEYWORD_RULES if name in ("health", "beauty") and rx.search(words) for i in inds]
        hb = _dedupe(sorted(hb, key=lambda x: x != "beauty")) or ["health", "beauty"]
        return Classification(hb, tax.rule + (f"+{text.rule}" if text.rule else ""), tax.category)
    if text.industries:
        return Classification(text.industries, text.rule, tax.category)
    if prior:
        return Classification(prior, "merchant", tax.category)
    return Classification([], tax.rule or "unclassified", tax.category)
