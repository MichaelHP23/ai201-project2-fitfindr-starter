"""
agent.py

The FitFindr planning loop. Orchestrates the tools in response to a
natural language user query, passing state between them via a session dict.

Usage:
    from agent import run_agent
    from utils.data_loader import get_example_wardrobe

    result = run_agent(
        query="vintage graphic tee under $30, size M",
        wardrobe=get_example_wardrobe(),
    )
    print(result["fit_card"])
    print(result["error"])  # None on success
"""

import json
import os
import re

from dotenv import load_dotenv, dotenv_values
from groq import Groq

from tools import search_listings, suggest_outfit, create_fit_card, compare_price

_ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
load_dotenv(_ENV_PATH)

# ── session state ─────────────────────────────────────────────────────────────

def _new_session(query: str, wardrobe: dict) -> dict:
    """Initialize and return a fresh session dict for one user interaction."""
    return {
        "query": query,
        "parsed": {},
        "search_results": [],
        "selected_item": None,
        "wardrobe": wardrobe,
        "outfit_suggestion": None,
        "fit_card": None,
        "price_assessment": None,
        "error": None,
        "retry": False,
        "retry_message": None,
    }


# ── query parser ──────────────────────────────────────────────────────────────

def _parse_query(query: str) -> dict:
    """
    Use the LLM to extract description, size, and max_price from a natural
    language query. Falls back to safe defaults if parsing fails.

    Returns:
        dict with keys: description (str), size (str|None), max_price (float|None)
    """
    api_key = os.environ.get("GROQ_API_KEY") or dotenv_values(_ENV_PATH).get("GROQ_API_KEY")
    if not api_key:
        return {"description": query, "size": None, "max_price": None}

    client = Groq(api_key=api_key)
    prompt = (
        "Extract search parameters from this thrift shopping query. "
        "Return ONLY a valid JSON object with exactly these keys:\n"
        '  "description": a short keyword description of the item (str),\n'
        '  "size": the size mentioned or null if none (str or null),\n'
        '  "max_price": the maximum price as a number or null if none (float or null).\n\n'
        f"Query: {query}\n\n"
        "Return only the JSON object, no explanation, no markdown."
    )

    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=100,
            temperature=0.1,
        )
        raw = response.choices[0].message.content.strip()
        # Strip any accidental markdown fences
        raw = re.sub(r"```(?:json)?", "", raw).strip().rstrip("```").strip()
        parsed = json.loads(raw)
        return {
            "description": str(parsed.get("description", query)),
            "size": parsed.get("size") or None,
            "max_price": float(parsed["max_price"]) if parsed.get("max_price") is not None else None,
        }
    except Exception:
        # Regex fallback: pull out price and size hints from raw text
        description = query
        size = None
        max_price = None

        price_match = re.search(r"\$(\d+(?:\.\d+)?)", query)
        if price_match:
            max_price = float(price_match.group(1))

        size_match = re.search(
            r"\b(XXS|XS|S/M|M/L|S|M|L|XL|XXL|[0-9]{1,2}W?)\b", query, re.IGNORECASE
        )
        if size_match:
            size = size_match.group(1).upper()

        # Remove price/size tokens from description
        description = re.sub(r"under \$\d+(?:\.\d+)?", "", description, flags=re.IGNORECASE)
        description = re.sub(r"\$\d+(?:\.\d+)?", "", description)
        description = re.sub(
            r"\b(size\s+)?(XXS|XS|S/M|M/L|XS|S|M|L|XL|XXL|[0-9]{1,2}W?)\b",
            "", description, flags=re.IGNORECASE
        )
        description = " ".join(description.split()).strip(" ,.-")

        return {"description": description or query, "size": size, "max_price": max_price}


# ── planning loop ─────────────────────────────────────────────────────────────

def run_agent(query: str, wardrobe: dict) -> dict:
    """
    Main agent entry point. Runs the FitFindr planning loop for a single
    user interaction and returns the completed session dict.

    Args:
        query:    Natural language user request.
        wardrobe: User's wardrobe dict.

    Returns:
        The session dict. Check session["error"] first — if not None,
        the interaction ended early and outfit_suggestion/fit_card will be None.
    """
    # Step 1: Initialize session
    session = _new_session(query, wardrobe)

    # Step 2: Parse the query with LLM
    parsed = _parse_query(query)
    session["parsed"] = parsed

    description = parsed["description"]
    size = parsed["size"]
    max_price = parsed["max_price"]

    # Step 3: Search listings
    results = search_listings(description, size, max_price)
    session["search_results"] = results

    # Step 3a: Handle empty results with retry (stretch: loosen size filter)
    if not results:
        if size is not None:
            # Retry without size filter
            session["retry"] = True
            results = search_listings(description, size=None, max_price=max_price)
            session["search_results"] = results

            if results:
                session["retry_message"] = (
                    f"No results found in size {size} — showing results without size filter."
                )
            else:
                # Build a helpful error message naming what was tried
                filters = [f'"{description}"']
                if max_price is not None:
                    filters.append(f"under ${max_price:.0f}")
                filter_str = " ".join(filters)
                session["error"] = (
                    f"No listings found for {filter_str} even after removing the size filter. "
                    "Try a broader description or a higher price."
                )
                return session
        else:
            # No size to loosen — just report failure
            filters = [f'"{description}"']
            if max_price is not None:
                filters.append(f"under ${max_price:.0f}")
            filter_str = " ".join(filters)
            session["error"] = (
                f"No listings found matching {filter_str}. "
                "Try a broader description or a higher budget."
            )
            return session

    # Step 4: Select top result
    session["selected_item"] = results[0]

    # Step 5: Suggest outfit
    outfit = suggest_outfit(session["selected_item"], session["wardrobe"])
    session["outfit_suggestion"] = outfit

    # Step 6: Create fit card
    fit_card = create_fit_card(outfit, session["selected_item"])
    session["fit_card"] = fit_card

    # Step 7: Price comparison (stretch)
    session["price_assessment"] = compare_price(session["selected_item"])

    return session


# ── CLI test ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from utils.data_loader import get_example_wardrobe, get_empty_wardrobe

    print("=== Happy path: graphic tee ===\n")
    session = run_agent(
        query="looking for a vintage graphic tee under $30",
        wardrobe=get_example_wardrobe(),
    )
    if session["error"]:
        print(f"Error: {session['error']}")
    else:
        item = session["selected_item"]
        print(f"Found: {item['title']} — ${item['price']} on {item['platform']}")
        if session.get("retry_message"):
            print(f"Note: {session['retry_message']}")
        print(f"\nOutfit: {session['outfit_suggestion']}")
        print(f"\nFit card: {session['fit_card']}")
        print(f"\nPrice check: {session['price_assessment']}")

    print("\n\n=== No-results path ===\n")
    session2 = run_agent(
        query="designer ballgown size XXS under $5",
        wardrobe=get_example_wardrobe(),
    )
    print(f"Error message: {session2['error']}")

    print("\n\n=== Empty wardrobe path ===\n")
    session3 = run_agent(
        query="vintage denim jacket under $50",
        wardrobe=get_empty_wardrobe(),
    )
    if session3["error"]:
        print(f"Error: {session3['error']}")
    else:
        print(f"Found: {session3['selected_item']['title']}")
        print(f"\nOutfit (empty wardrobe): {session3['outfit_suggestion']}")
        print(f"\nFit card: {session3['fit_card']}")
