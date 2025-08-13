# -*- coding: utf-8 -*-
"""
Wczytuje template.html, pobiera dane z Google Sheets (zakładka 'www'),
buduje fragmenty HTML i wstrzykuje je do placeholderów.
Nie pobiera obrazów - używa URL z arkusza.
Zapisuje wynik do index.html.
"""

import os
import math
import time
import re
from typing import Dict, List, Any

# Google Sheets
from oauth2client.service_account import ServiceAccountCredentials
import gspread

# === ŚCIEŻKI ===
TEMPLATE_PATH = r"c:\Users\Jakub\Downloads\__Eprojekty\www\template.html"
OUTPUT_INDEX = r"c:\Users\Jakub\Downloads\__Eprojekty\www\index.html"
ROOT_DIR = os.path.dirname(OUTPUT_INDEX)  # do audytu ścieżek

# === GOOGLE SHEETS ===
SPREADSHEET_ID = "1GKT-rZSvkoqyAde7NuLKx8s4QzfH97Awee4Fvz-OvpU"
SHEET_NAME = "www"

# Twoje stałe do Google - jak wymagałeś
SCOPE = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
CREDENTIALS = ServiceAccountCredentials.from_json_keyfile_name(
    "e:/Mirror/EUBRAND/2. dane i analizy/Python/phrasal-client-392117-584fd6576209.json",
    scopes=SCOPE
)

def rating_to_percent_str(val: str) -> str:
    s = (val or "").strip().replace(",", ".")
    try:
        f = max(0.0, min(5.0, float(s)))
    except ValueError:
        f = 4.5
    return f"{round(f/5*100, 2)}%"

def rating_to_class(val: str) -> str:
    """Zamienia '4.5' -> 'rating-4-5'. Puste -> 'rating-4-5' (domyślnie)."""
    s = (val or "").strip()
    if not s:
        return "rating-4-5"
    s = s.replace(",", ".")
    try:
        f = max(0.0, min(5.0, float(s)))
    except ValueError:
        return "rating-4-5"
    whole = int(f)
    half = abs(f - whole) >= 0.5 - 1e-6 and abs(f - whole) < 0.75
    if f >= 4.75:  # zaokrąglamy 4.8..5 -> 5
        return "rating-5"
    return f"rating-{whole}-5" if half and whole < 5 else f"rating-{whole}"


# === RETRY WRAPPER ===
def retry(max_tries=5, base_delay=1.0, max_delay=8.0, exceptions=(Exception,)):
    def decorator(fn):
        def wrapped(*args, **kwargs):
            tries = 0
            while True:
                try:
                    return fn(*args, **kwargs)
                except exceptions:
                    tries += 1
                    if tries >= max_tries:
                        raise
                    delay = min(max_delay, base_delay * (2 ** (tries - 1)))
                    time.sleep(delay)
        return wrapped
    return decorator

# === UTILS ===
def clean(val: Any) -> str:
    """Konwersja NaN/null/None do pustego stringa + trim + usunięcie niewidocznych znaków."""
    if val is None:
        return ""
    if isinstance(val, float) and math.isnan(val):
        return ""
    s = str(val).strip()
    # usuń zero-width chars itp.
    s = s.replace("\u200b", "").replace("\ufeff", "")
    if s.lower() in ("nan", "null", "none"):
        return ""
    return s

@retry()
def gs_open():
    gc = gspread.authorize(CREDENTIALS)
    return gc.open_by_key(SPREADSHEET_ID)

@retry()
def gs_fetch_records() -> List[Dict[str, Any]]:
    sh = gs_open()
    ws = sh.worksheet(SHEET_NAME)
    # Oczekiwane nagłówki: type | key | field | value
    return ws.get_all_records()

def pivot_www(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    texts: Dict[str, str] = {}
    images: Dict[str, str] = {}
    products: Dict[str, Dict[str, str]] = {}
    ingredients: Dict[str, Dict[str, str]] = {}
    reviews: Dict[str, Dict[str, str]] = {}

    for row in records:
        type_ = clean(row.get("type"))
        key = clean(row.get("key"))
        field = clean(row.get("field"))
        value = clean(row.get("value"))
        if not type_ or not key:
            continue

        if type_ == "text":
            texts[key] = value
        elif type_ == "image":
            if field.lower() in ("url", ""):
                images[key] = value
        elif type_ == "product":
            products.setdefault(key, {})
            if field:
                products[key][field] = value
        elif type_ == "ingredient":
            ingredients.setdefault(key, {})
            if field:
                ingredients[key][field] = value
        elif type_ == "review":
            reviews.setdefault(key, {})
            if field:
                reviews[key][field] = value

    return {
        "texts": texts,
        "images": images,
        "products": [v for _, v in sorted(products.items(), key=lambda x: x[0])],
        "ingredients": [v for _, v in sorted(ingredients.items(), key=lambda x: x[0])],
        "reviews": [v for _, v in sorted(reviews.items(), key=lambda x: x[0])],
    }

# === BUDOWANIE FRAGMENTÓW HTML ===
def build_products_html(items: List[Dict[str, str]]) -> str:
    parts = []
    for p in items:
        title = clean(p.get("title"))
        subtitle = clean(p.get("subtitle"))
        img_url = clean(p.get("img_url"))
        amazon_url = clean(p.get("amazon_url"))
        btn = f'<a href="{amazon_url}" target="_blank" rel="noopener">Kup na Amazon</a>' if amazon_url else ""
        parts.append(
            '<div class="product-card">'
            '  <div class="img-frame img-4x5">'
            f'    <img src="{img_url}" alt="{title}" loading="lazy" decoding="async" width="800" height="1000">'
            '  </div>'
            f'  <h3>{title}</h3>'
            f'  <p>{subtitle}</p>'
            f'  {btn}'
            '</div>'
        )
    return "\n".join(parts)

def build_ingredients_html(items: List[Dict[str, str]]) -> str:
    parts = []
    for ing in items:
        name = clean(ing.get("name"))
        blurb = clean(ing.get("blurb"))
        img_url = clean(ing.get("img_url"))
        parts.append(
            '<div class="ingredient">'
            '  <div class="img-frame img-1x1">'
            f'    <img src="{img_url}" alt="{name}" loading="lazy" decoding="async" width="800" height="800">'
            '  </div>'
            f'  <h3>{name}</h3>'
            f'  <p>{blurb}</p>'
            '</div>'
        )
    return "\n".join(parts)

def build_reviews_html(items: List[Dict[str, str]]) -> str:
    parts = []
    for r in items:
        text = clean(r.get("text"))
        author = clean(r.get("author"))
        locale = clean(r.get("locale"))
        rating_val = clean(r.get("rating"))  # z arkusza
        who = " ".join(x for x in [author, "-", locale] if x).strip(" -")

        try:
            percent = round(float(rating_val.replace(",", ".")) / 5 * 100, 2)
        except ValueError:
            percent = 0

        parts.append(f'''
<div class="review" style="--percent:{percent}%">
  <div class="value-with-stars">
    <span class="stars"></span>
    <span class="rating-value">{rating_val}</span>
  </div>
  <p>{text}</p>
  <div class="author">{who}</div>
</div>
''')
    return "\n".join(parts)

def inject_placeholders(template_str: str, mapping: Dict[str, str]) -> str:
    out = template_str
    for k, v in mapping.items():
        out = out.replace("{{" + k + "}}", v)
    return out

def audit_missing_assets(index_path: str, root_dir: str) -> None:
    with open(index_path, "r", encoding="utf-8") as f:
        html = f.read()
    refs = re.findall(r'src="([^"]+)"', html)
    missing = []
    for p in refs:
        if p.startswith("http"):
            continue
        fs = os.path.normpath(os.path.join(root_dir, p))
        if not os.path.exists(fs):
            missing.append((p, fs))
    if missing:
        print("\nBrakujące pliki:")
        for web, fs in missing:
            print("-", web, "->", fs)
    else:
        print("\nBrakujące pliki: brak")

def main():
    # 1) dane
    records = gs_fetch_records()
    if not records:
        raise RuntimeError("Brak danych w arkuszu 'www' - uzupełnij tabelę i uruchom ponownie.")
    model = pivot_www(records)

    # 2) template
    if not os.path.isfile(TEMPLATE_PATH):
        raise FileNotFoundError(f"Brak pliku template: {TEMPLATE_PATH}")
    with open(TEMPLATE_PATH, "r", encoding="utf-8") as f:
        tpl = f.read()

    # 3) fragmenty
    products_html = build_products_html(model["products"])
    ingredients_html = build_ingredients_html(model["ingredients"])
    reviews_html = build_reviews_html(model["reviews"])

    # 4) placeholdery
    texts, images = model["texts"], model["images"]
    rating_val = clean(texts.get("rating_value") or "4.3")
    mapping = {
        "hero_headline": clean(texts.get("hero_headline")),
        "hero_lead": clean(texts.get("hero_lead")),
        "hero_image_url": clean(images.get("hero")),
        "about_text": clean(texts.get("about_text")),
        "about_image_url": clean(images.get("about")),
        "ingredients": ingredients_html,
        "products": products_html,
        "reviews": reviews_html,
        "contact_email": clean(texts.get("contact_email")),
        "contact_www": clean(texts.get("contact_www")),
        "year": time.strftime("%Y"),

        # - NOWE dla gwiazdek w hero
        "rating_value": rating_val,
        "rating_percent": rating_to_percent_str(rating_val),
    }

    # 5) render + zapis
    html = inject_placeholders(tpl, mapping)
    os.makedirs(os.path.dirname(OUTPUT_INDEX), exist_ok=True)
    with open(OUTPUT_INDEX, "w", encoding="utf-8") as f:
        f.write(html)
    print("OK - wygenerowano:", OUTPUT_INDEX)

    # 6) audyt brakujących plików
    audit_missing_assets(OUTPUT_INDEX, ROOT_DIR)

if __name__ == "__main__":
    main()
