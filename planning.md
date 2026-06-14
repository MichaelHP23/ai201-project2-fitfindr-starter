# FitFindr — Planning Document

Fill this out **before** writing any implementation code. Your agent design lives here.

---

## A Complete Interaction

FitFindr is a multi-tool AI agent that takes a natural language thrift request and orchestrates three tools to return a ranked listing, an outfit suggestion, and a shareable fit card. The agent parses the user's query to extract a description, size filter, and price ceiling, then calls `search_listings` to find matching items. If results come back, the top match flows automatically into `suggest_outfit`, which uses the user's wardrobe to produce styled outfit ideas; that suggestion then flows into `create_fit_card` to produce a social-ready caption — all without the user re-entering anything. If any tool produces empty output or an error, the agent communicates specifically what failed and what the user can try next, then stops rather than passing bad data downstream.

**Example query trace:** `"I'm looking for a vintage graphic tee under $30, size M. I mostly wear baggy jeans and chunky sneakers."`

1. Agent parses query → `description="vintage graphic tee"`, `size="M"`, `max_price=30.0`
2. `search_listings("vintage graphic tee", size="M", max_price=30.0)` → returns 3 matching dicts sorted by relevance score. Top result: `{"title": "Faded Band Tee", "price": 22.0, "platform": "Depop", "condition": "Good", ...}`
3. `session["selected_item"]` = top result dict. Agent checks: results not empty → proceed.
4. `suggest_outfit(selected_item, wardrobe)` → `"Pair this faded band tee with your wide-leg jeans and chunky sneakers for a classic 90s grunge look. Roll the sleeves once and tuck the front corner for shape."`
5. `session["outfit_suggestion"]` = that string. Agent proceeds.
6. `create_fit_card(outfit_suggestion, selected_item)` → `"thrifted this faded band tee off depop for $22 and it was literally made for my wide-legs 🖤 full look dropping soon"`
7. Agent returns session with `fit_card`, `outfit_suggestion`, and `selected_item` populated. `error` is `None`.

**Error path:** If step 2 returns `[]`, agent sets `session["error"] = "No listings found for 'vintage graphic tee' in size M under $30. Try removing the size filter or raising your budget."` and returns immediately — `suggest_outfit` and `create_fit_card` are never called.

---

## Tools

### Tool 1 — `search_listings`

**What it does:** Filters the full mock listings dataset by keyword relevance, optional size, and optional price ceiling. Returns a ranked list of matching listing dicts.

**Inputs:**
- `description` (str): Keywords describing what the user wants (e.g., `"vintage graphic tee"`). Used for scoring by keyword overlap against `title`, `description`, `style_tags`, `category`, and `colors` fields.
- `size` (str | None): Size string to filter by (e.g., `"M"`). Matching is case-insensitive and substring-based so `"M"` matches `"S/M"`. If `None`, no size filter is applied.
- `max_price` (float | None): Maximum price (inclusive). If `None`, no price filter is applied.

**Returns:** `list[dict]` — a list of listing dicts sorted by relevance score (highest first). Each dict contains: `id` (str), `title` (str), `description` (str), `category` (str), `style_tags` (list[str]), `size` (str), `condition` (str), `price` (float), `colors` (list[str]), `brand` (str), `platform` (str). Returns `[]` (empty list) if nothing matches — never raises an exception.

**On failure / empty:** Returns `[]`. The agent checks for this and sets `session["error"]` with a specific message naming what filters were applied and suggesting what to relax (e.g., remove size or raise price). Does not proceed to `suggest_outfit`.

---

### Tool 2 — `suggest_outfit`

**What it does:** Given the selected thrifted item and the user's wardrobe, asks the LLM to suggest 1–2 complete outfit combinations.

**Inputs:**
- `new_item` (dict): A listing dict from `search_listings` — the item the user is considering buying.
- `wardrobe` (dict): A wardrobe dict with an `"items"` key containing a list of wardrobe item dicts. Each wardrobe item has: `name` (str), `category` (str), `colors` (list[str]), `style` (str), `fit` (str).

**Returns:** `str` — a non-empty string with outfit suggestions. If the wardrobe is empty, returns general styling advice (e.g., what category of bottoms, shoes, and accessories would pair well and why) rather than crashing or returning `""`.

**On failure / empty wardrobe:** If `wardrobe["items"]` is empty, the LLM prompt shifts to "general styling advice" mode — it describes what kinds of pieces pair well with the item and what vibe it suits. Never returns an empty string or raises an exception.

---

### Tool 3 — `create_fit_card`

**What it does:** Takes the outfit suggestion and the new item's details and generates a 2–4 sentence social-media-ready caption (think Instagram OOTD, not product copy).

**Inputs:**
- `outfit` (str): The outfit suggestion string returned by `suggest_outfit`.
- `new_item` (dict): The listing dict for the thrifted item (used to pull `title`, `price`, `platform`).

**Returns:** `str` — a casual, authentic caption that mentions the item name, price, and platform naturally (once each), captures the outfit vibe in specific terms, and sounds different each time for different inputs. If `outfit` is empty or whitespace-only, returns a descriptive error message string (e.g., `"Error: cannot generate a fit card without an outfit suggestion."`) — never raises an exception.

**On failure:** Guards against empty `outfit` string with an explicit check before calling the LLM. Returns an error string, not an exception.

---

### Tool 4 (Stretch) — `compare_price`

**What it does:** Given a listing, finds comparable items in the dataset (same category, similar style tags) and assesses whether the price is fair, high, or a steal based on the median price of comparables.

**Inputs:**
- `item` (dict): A listing dict to evaluate.

**Returns:** `str` — a plain-language price assessment with reasoning, e.g., `"This $22 band tee is a solid deal — comparable graphic tees in the dataset average $31. You're saving about 30%."` Returns a fallback message if no comparables are found.

**On failure / no comparables:** Returns a message stating no comparable listings were found rather than crashing.

---

## Planning Loop

The planning loop in `run_agent()` follows this conditional logic:

```
Step 1: Initialize session with _new_session(query, wardrobe).

Step 2: Parse the query using the LLM (Groq llama-3.3-70b-versatile).
        Prompt asks for JSON with keys: description (str), size (str|null), max_price (float|null).
        Store result in session["parsed"].
        If parsing fails, fall back to using the full query string as description with no filters.

Step 3: Call search_listings(description, size, max_price).
        Store result in session["search_results"].

        IF session["search_results"] == []:
            → IF this is first attempt (session["retry"] is False):
                  Loosen constraints: set size=None, keep max_price.
                  Retry search_listings with loosened params.
                  Set session["retry"] = True.
                  IF still empty:
                      Set session["error"] = specific message naming original filters
                                              and telling user what was tried.
                      RETURN session early.
                  ELSE:
                      Set session["retry_message"] noting size filter was removed.
                      Proceed with loosened results.
            → IF this is a retry that already failed:
                  Set session["error"] and RETURN early.

        IF session["search_results"] is not empty:
            → Set session["selected_item"] = session["search_results"][0].
            → Proceed.

Step 4: Call suggest_outfit(session["selected_item"], session["wardrobe"]).
        Store result in session["outfit_suggestion"].

Step 5: Call create_fit_card(session["outfit_suggestion"], session["selected_item"]).
        Store result in session["fit_card"].

Step 6: (Stretch) Call compare_price(session["selected_item"]).
        Store result in session["price_assessment"].

Step 7: Return session.
```

**Key branching decisions:**
- The loop does NOT call `suggest_outfit` if `search_results` is empty — this is the primary branch.
- The retry logic (stretch) automatically loosens the size constraint and informs the user, rather than silently failing.
- `create_fit_card` is only called if `outfit_suggestion` is a non-empty string (guarded by the tool itself, but also implicitly guaranteed by `suggest_outfit`'s contract).

---

## State Management

The session dict is initialized once in `_new_session()` and passed by reference through the loop. Each step writes to it before the next step reads from it. No global state is used.

| Key | Set in Step | Read in Step | Purpose |
|-----|-------------|--------------|---------|
| `query` | init | 2 | Original user input |
| `parsed` | 2 | 3 | Extracted description/size/max_price |
| `search_results` | 3 | 3 (branch check) | All matching listing dicts |
| `selected_item` | 3 | 4, 5 | Top listing dict passed to LLM tools |
| `wardrobe` | init | 4 | User's wardrobe for outfit suggestions |
| `outfit_suggestion` | 4 | 5 | LLM outfit string |
| `fit_card` | 5 | (returned) | Final social caption |
| `price_assessment` | 6 (stretch) | (returned) | Price comparison result |
| `error` | 3 (on failure) | (returned) | Early exit message |
| `retry` | 3 (stretch) | 3 | Tracks whether fallback search was attempted |
| `retry_message` | 3 (stretch) | (returned) | Informs user that size filter was dropped |

---

## Error Handling

| Tool | Failure Mode | Agent Response |
|------|-------------|----------------|
| `search_listings` | Returns `[]` on first attempt | Automatically retries with size filter removed (stretch). If retry also returns `[]`, sets `session["error"]` = `"No listings found for '[description]' under $[max_price]. We also tried removing the size filter. Try a broader description or a higher price."` Returns early without calling downstream tools. |
| `search_listings` | Returns `[]` with no size to loosen | Sets `session["error"]` = `"No listings found matching '[description]' under $[max_price]. Try a broader description or a higher budget."` Returns early. |
| `suggest_outfit` | `wardrobe["items"]` is empty | Switches LLM prompt to general styling mode. Returns string like `"Without a wardrobe on file, here are some general ideas: this piece pairs well with high-waisted jeans and white sneakers for a casual streetwear look..."` Never crashes. |
| `suggest_outfit` | LLM API error | Returns `"Unable to generate outfit suggestion right now. Try again in a moment."` — caught by try/except around Groq call. |
| `create_fit_card` | `outfit` is empty or whitespace | Returns `"Error: cannot generate a fit card without an outfit suggestion."` — checked before any LLM call. |
| `create_fit_card` | LLM API error | Returns `"Unable to generate fit card right now. Try again in a moment."` |
| `compare_price` | No comparable listings found | Returns `"No comparable listings found to assess this price. It may be a niche item."` |

---

## Architecture

```
User query (str) + wardrobe_choice
         │
         ▼
    handle_query()  [app.py]
         │  selects wardrobe, guards empty query
         ▼
    run_agent(query, wardrobe)  [agent.py]
         │
         ▼
    _new_session()  →  session dict initialized
         │
         ▼
    Step 2: LLM Query Parser
         │  session["parsed"] = {description, size, max_price}
         ▼
    Step 3: search_listings(description, size, max_price)
         │  session["search_results"] = [...]
         │
         ├── results == [] AND no retry yet ──► retry with size=None
         │       │
         │       ├── still empty ─────────────► session["error"] set
         │       │                               RETURN session  ◄── early exit
         │       └── results found ────────────► proceed (session["retry_message"] set)
         │
         ├── results == [] AND already retried ► session["error"] set
         │                                        RETURN session  ◄── early exit
         │
         └── results found
                  │  session["selected_item"] = results[0]
                  ▼
         Step 4: suggest_outfit(selected_item, wardrobe)
                  │  session["outfit_suggestion"] = "..."
                  │
                  │  (empty wardrobe → general styling mode, no crash)
                  ▼
         Step 5: create_fit_card(outfit_suggestion, selected_item)
                  │  session["fit_card"] = "..."
                  ▼
         Step 6: compare_price(selected_item)  [stretch]
                  │  session["price_assessment"] = "..."
                  ▼
         RETURN session
                  │
                  ▼
    handle_query() maps session → (listing_text, outfit_text, fit_card_text)
                  │
                  ▼
    Gradio UI: 3 output panels populated
```

---

## AI Tool Plan

### Milestone 3 — Tool Implementation

**Tool 1 (`search_listings`):**
I will give Claude the Tool 1 section of this planning.md (inputs with types, return value description, failure mode) plus the `load_listings()` function signature from `utils/data_loader.py`. I will ask it to implement the keyword scoring as overlap between lowercased description words and the `title + description + style_tags + category + colors` fields. Before using the output, I will verify: (a) all three parameters are used, (b) the empty-list case is returned without exception, (c) price filter is inclusive (`<=`), and (d) size matching is case-insensitive substring. I will test with 3 queries: a happy-path match, an impossible query, and a price-only filter.

**Tool 2 (`suggest_outfit`):**
I will give Claude the Tool 2 section of this planning.md plus the wardrobe schema structure. I will ask it to implement the empty-wardrobe branch explicitly (separate prompt path). Before using the output, I will verify: (a) it calls Groq with `llama-3.3-70b-versatile`, (b) `wardrobe["items"]` empty check is present before formatting items, (c) the function never returns `""` or raises. I will test with example wardrobe and with empty wardrobe.

**Tool 3 (`create_fit_card`):**
I will give Claude the Tool 3 section including the caption style guidelines (casual, authentic, mentions item/price/platform once, different each time). I will ask it to use `temperature=1.2` to ensure variation. Before using the output, I will verify: (a) empty `outfit` guard is before LLM call, (b) prompt instructs the LLM to avoid product-description language, (c) `new_item["price"]` and `new_item["platform"]` are passed into the prompt. I will run it 3 times on the same input to confirm output varies.

**Milestone 4 — Planning Loop:**
I will give Claude the Architecture diagram from this document plus the Planning Loop section (full conditional logic including retry). I will ask it to implement `run_agent()` matching the step-by-step logic exactly. Before using the output, I will verify: (a) `suggest_outfit` is inside an `if search_results:` branch, (b) session dict keys match `_new_session()` exactly, (c) retry logic sets `session["retry"] = True` and attempts a second search before setting `session["error"]`.

---

## Stretch Feature Plans

### Price Comparison Tool
Before starting: I'll add `compare_price(item)` to `tools.py`. It will load all listings, filter to the same `category`, compute median price, and return a string comparing the item's price to the median with a plain-language verdict (steal / fair / pricey). No LLM needed — pure logic. I'll add it to `session` in step 6 of `run_agent()` and display it in a fourth Gradio panel.

### Style Profile Memory
Before starting: I'll add a `profile.json` file (gitignored for privacy) that stores the user's last-used wardrobe items and any style tags they've confirmed. On app load, `load_profile()` checks for this file and pre-populates the wardrobe. After each successful interaction, `save_profile()` writes the updated wardrobe back. The Gradio UI gets a "Remember my wardrobe" checkbox. README will describe this as session persistence via local JSON.

### Retry Logic with Fallback
Before starting: I'll add a `session["retry"]` boolean (False by default) and a `session["retry_message"]` field to `_new_session()`. In step 3 of the planning loop, if `search_results == []` and `session["parsed"]["size"]` is not None and `session["retry"]` is False, I'll set `retry=True`, clear `size`, and call `search_listings` again. If it returns results, I'll set `retry_message` = `"No results found in size {size} — showing results without size filter."` and continue. This message is surfaced in the Gradio listing panel.
