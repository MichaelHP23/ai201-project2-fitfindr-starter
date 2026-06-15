"""
tools.py

The FitFindr tools. Each tool is a standalone function that can be called
and tested independently before being wired into the agent loop.

Tools:
    search_listings(description, size, max_price) → list[dict]
    suggest_outfit(new_item, wardrobe) → str
    create_fit_card(outfit, new_item) → str
    compare_price(item) → str  [stretch]
"""

import os
import statistics
from dotenv import load_dotenv, dotenv_values
from groq import Groq
from utils.data_loader import load_listings

_ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
load_dotenv(_ENV_PATH)

# ── Groq client ───────────────────────────────────────────────────────────────

def _get_groq_client() -> Groq:
    """Initialize and return a Groq client using GROQ_API_KEY from .env."""
    api_key = os.environ.get("GROQ_API_KEY") or dotenv_values(_ENV_PATH).get("GROQ_API_KEY")
    if not api_key:
        raise ValueError(
            "GROQ_API_KEY not set. Add it to a .env file in the project root."
        )
    return Groq(api_key=api_key)


# ── Tool 1: search_listings ───────────────────────────────────────────────────

def search_listings(
    description: str,
    size: str | None = None,
    max_price: float | None = None,
) -> list[dict]:
    """
    Search the mock listings dataset for items matching the description,
    optional size, and optional price ceiling.

    Args:
        description: Keywords describing what the user is looking for
                     (e.g., "vintage graphic tee").
        size:        Size string to filter by, or None to skip size filtering.
                     Matching is case-insensitive substring (e.g., "M" matches "S/M").
        max_price:   Maximum price (inclusive), or None to skip price filtering.

    Returns:
        A list of matching listing dicts sorted by relevance score (highest first).
        Returns [] if nothing matches — never raises an exception.
        Each dict has: id, title, description, category, style_tags (list),
        size, condition, price (float), colors (list), brand, platform.
    """
    try:
        listings = load_listings()
    except Exception:
        return []

    # Step 1: Filter by price
    if max_price is not None:
        listings = [l for l in listings if l.get("price", float("inf")) <= max_price]

    # Step 2: Filter by size (case-insensitive substring match)
    if size is not None:
        size_lower = size.lower()
        listings = [
            l for l in listings
            if size_lower in l.get("size", "").lower()
        ]

    # Step 3: Score each listing by keyword overlap with description
    keywords = set(description.lower().split())

    def score(listing: dict) -> int:
        searchable = " ".join([
            listing.get("title") or "",
            listing.get("description") or "",
            listing.get("category") or "",
            listing.get("brand") or "",
            " ".join(listing.get("style_tags") or []),
            " ".join(listing.get("colors") or []),
        ]).lower()
        return sum(1 for kw in keywords if kw in searchable)


    # Step 4: Drop listings with 0 keyword matches
    scored = [(l, score(l)) for l in listings]
    scored = [(l, s) for l, s in scored if s > 0]

    # Step 5: Sort by score descending
    scored.sort(key=lambda x: x[1], reverse=True)

    return [l for l, _ in scored]


# ── Tool 2: suggest_outfit ────────────────────────────────────────────────────

def suggest_outfit(new_item: dict, wardrobe: dict) -> str:
    """
    Given a thrifted item and the user's wardrobe, suggest 1-2 complete outfits.

    Args:
        new_item: A listing dict (the item the user is considering buying).
        wardrobe: A wardrobe dict with an 'items' key containing a list of
                  wardrobe item dicts. May be empty — handled gracefully.

    Returns:
        A non-empty string with outfit suggestions.
        If wardrobe is empty, returns general styling advice rather than crashing.
    """
    item_summary = (
        f"Title: {new_item.get('title', 'Unknown')}\n"
        f"Category: {new_item.get('category', 'Unknown')}\n"
        f"Style tags: {', '.join(new_item.get('style_tags', []))}\n"
        f"Colors: {', '.join(new_item.get('colors', []))}\n"
        f"Condition: {new_item.get('condition', 'Unknown')}\n"
        f"Description: {new_item.get('description', '')}"
    )

    wardrobe_items = wardrobe.get("items", [])

    if not wardrobe_items:
        # Empty wardrobe: general styling advice mode
        prompt = (
            f"A user just found this secondhand item:\n\n{item_summary}\n\n"
            "They don't have a wardrobe on file yet. Give them 1-2 general outfit ideas: "
            "what categories of clothing (bottoms, shoes, outerwear, accessories) pair well "
            "with this item, what vibe or aesthetic it suits, and any specific styling tips "
            "(e.g., how to wear it, what to tuck/roll/layer). Be specific and helpful, "
            "not generic. Sound like a friend who knows fashion."
        )
    else:
        # Format wardrobe items for the prompt
        wardrobe_summary = "\n".join(
            f"- {item.get('name', 'Unknown')}: {item.get('category', '')}, "
            f"{', '.join(item.get('colors', []))}, {item.get('style', '')} style, "
            f"{item.get('fit', '')} fit"
            for item in wardrobe_items
        )
        prompt = (
            f"A user just found this secondhand item:\n\n{item_summary}\n\n"
            f"Their current wardrobe includes:\n{wardrobe_summary}\n\n"
            "Suggest 1-2 complete outfit combinations using the new item with specific pieces "
            "from their wardrobe. Name the exact wardrobe pieces by name. Include any styling "
            "tips (how to layer, tuck, accessorize). Keep it conversational and specific — "
            "sound like a friend who knows their closet."
        )

    try:
        client = _get_groq_client()
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=400,
            temperature=0.8,
        )
        result = response.choices[0].message.content.strip()
        return result if result else "Try pairing this piece with neutral basics to let it stand out."
    except Exception as e:
        return f"Unable to generate outfit suggestion right now. Try again in a moment. (Error: {e})"


# ── Tool 3: create_fit_card ───────────────────────────────────────────────────

def create_fit_card(outfit: str, new_item: dict) -> str:
    """
    Generate a short, shareable outfit caption for the thrifted find.

    Args:
        outfit:   The outfit suggestion string from suggest_outfit().
        new_item: The listing dict for the thrifted item.

    Returns:
        A 2-4 sentence string usable as an Instagram/TikTok caption.
        If outfit is empty or missing, returns a descriptive error string.
    """
    # Guard against empty outfit
    if not outfit or not outfit.strip():
        return "Error: cannot generate a fit card without an outfit suggestion."

    title = new_item.get("title", "this piece")
    price = new_item.get("price", "")
    platform = new_item.get("platform", "a thrift app")
    style_tags = ", ".join(new_item.get("style_tags", []))

    price_str = f"${price}" if price != "" else "a steal"

    prompt = (
        f"Write a 2-4 sentence Instagram/TikTok OOTD caption for this outfit:\n\n"
        f"Thrifted item: {title} — {price_str} from {platform}\n"
        f"Style vibe: {style_tags}\n"
        f"Outfit idea: {outfit}\n\n"
        "Rules:\n"
        "- Sound like a real person posting their fit, not a product listing\n"
        "- Mention the item name, price, and platform naturally (each once)\n"
        "- Capture the specific outfit vibe\n"
        "- Use casual language, maybe 1-2 relevant emojis\n"
        "- Do NOT use the phrase 'outfit of the day' or 'OOTD'\n"
        "- Keep it under 80 words\n"
        "Return ONLY the caption text, nothing else."
    )

    try:
        client = _get_groq_client()
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=150,
            temperature=1.2,  # Higher temperature for variation
        )
        result = response.choices[0].message.content.strip()
        return result if result else f"just copped this {title} for {price_str} off {platform} and it goes 🔥"
    except Exception as e:
        return f"Unable to generate fit card right now. Try again in a moment. (Error: {e})"


# ── Tool 4 (Stretch): compare_price ──────────────────────────────────────────

def compare_price(item: dict) -> str:
    """
    Assess whether an item's price is fair based on comparable listings.

    Args:
        item: A listing dict to evaluate.

    Returns:
        A plain-language string with price assessment and reasoning.
        Returns a fallback message if no comparables are found.
    """
    try:
        listings = load_listings()
    except Exception:
        return "Unable to load listings for price comparison."

    item_category = item.get("category", "").lower()
    item_style_tags = set(tag.lower() for tag in item.get("style_tags", []))
    item_price = item.get("price")
    item_id = item.get("id")

    if item_price is None:
        return "This item has no price listed, so comparison is not possible."

    # Find comparables: same category, at least one matching style tag, not the item itself
    comparables = [
        l for l in listings
        if l.get("id") != item_id
        and l.get("category", "").lower() == item_category
        and bool(set(tag.lower() for tag in l.get("style_tags", [])) & item_style_tags)
        and l.get("price") is not None
    ]

    # Fallback: same category only (no style tag requirement)
    if len(comparables) < 2:
        comparables = [
            l for l in listings
            if l.get("id") != item_id
            and l.get("category", "").lower() == item_category
            and l.get("price") is not None
        ]

    if not comparables:
        return (
            f"No comparable listings found for this {item_category} to assess the price. "
            "It may be a niche item."
        )

    prices = [l["price"] for l in comparables]
    median_price = statistics.median(prices)
    avg_price = statistics.mean(prices)
    item_name = item.get("title", "This item")

    pct_diff = ((item_price - median_price) / median_price) * 100

    if pct_diff <= -20:
        verdict = "a steal"
        detail = f"it's about {abs(pct_diff):.0f}% below the median"
    elif pct_diff <= 10:
        verdict = "fairly priced"
        detail = f"it's right around the median"
    elif pct_diff <= 30:
        verdict = "slightly above average"
        detail = f"it's about {pct_diff:.0f}% above the median"
    else:
        verdict = "on the pricier side"
        detail = f"it's about {pct_diff:.0f}% above the median"

    return (
        f"Price check: {item_name} at ${item_price:.2f} is {verdict} — "
        f"{detail} for {item_category} in this dataset (median: ${median_price:.2f}, "
        f"avg: ${avg_price:.2f} across {len(comparables)} comparable listings)."
    )
