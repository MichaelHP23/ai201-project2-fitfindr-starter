# FitFindr

A multi-tool AI agent that helps you find secondhand pieces and figure out how to wear them. Describe what you're looking for, and FitFindr searches mock thrift listings, suggests outfit combinations using your wardrobe, and generates a shareable caption — all in one flow.

---

## Setup

```bash
git clone https://github.com/MichaelHP23/ai201-project2-fitfindr-starter
cd ai201-project2-fitfindr-starter
python -m venv .venv
source .venv/bin/activate  # Mac/Linux
# or: source .venv/Scripts/activate  (Windows Git Bash)
pip install -r requirements.txt
```

Create a `.env` file in the project root:

```
GROQ_API_KEY=your_key_here
```

Get a free key at [console.groq.com](https://console.groq.com) — no credit card required.

Run the app:

```bash
python app.py
```

Run tests:

```bash
pytest tests/
```

---

## Tool Inventory

### `search_listings(description, size, max_price)`

Filters the 40-item mock listings dataset by keyword relevance, optional size, and optional price ceiling.

| Parameter | Type | Description |
|-----------|------|-------------|
| `description` | `str` | Keywords describing the item (e.g., `"vintage graphic tee"`) |
| `size` | `str \| None` | Size to filter by (case-insensitive substring); `None` skips filter |
| `max_price` | `float \| None` | Maximum price inclusive; `None` skips filter |

**Returns:** `list[dict]` — listing dicts sorted by relevance score (highest first). Each dict contains `id` (str), `title` (str), `description` (str), `category` (str), `style_tags` (list[str]), `size` (str), `condition` (str), `price` (float), `colors` (list[str]), `brand` (str), `platform` (str). Returns `[]` on no matches — never raises.

---

### `suggest_outfit(new_item, wardrobe)`

Uses Groq (llama-3.3-70b-versatile) to suggest 1–2 complete outfits combining the thrifted item with the user's wardrobe.

| Parameter | Type | Description |
|-----------|------|-------------|
| `new_item` | `dict` | A listing dict from `search_listings` |
| `wardrobe` | `dict` | Wardrobe dict with `"items"` key (list of wardrobe item dicts) |

**Returns:** `str` — non-empty outfit suggestion. If `wardrobe["items"]` is empty, returns general styling advice instead of crashing.

---

### `create_fit_card(outfit, new_item)`

Uses Groq (llama-3.3-70b-versatile, temperature=1.2) to generate a 2–4 sentence Instagram/TikTok-style caption.

| Parameter | Type | Description |
|-----------|------|-------------|
| `outfit` | `str` | Outfit suggestion string from `suggest_outfit` |
| `new_item` | `dict` | Listing dict for the thrifted item |

**Returns:** `str` — casual social caption mentioning item name, price, and platform. If `outfit` is empty/whitespace, returns a descriptive error string instead of crashing.

---

### `compare_price(item)` — Stretch Feature

Compares an item's price to comparable listings in the dataset by category and style tags.

| Parameter | Type | Description |
|-----------|------|-------------|
| `item` | `dict` | A listing dict to evaluate |

**Returns:** `str` — plain-language price assessment with verdict (steal / fairly priced / pricey) and supporting data (median price, number of comparables). Returns fallback message if no comparables found.

---

## How the Planning Loop Works

The loop in `run_agent()` makes decisions based on what each tool returns — it does not call all tools unconditionally.

**Step 1:** Initialize session dict with `_new_session()`.

**Step 2:** Call LLM to parse the natural language query into `description` (str), `size` (str or None), and `max_price` (float or None). Falls back to regex parsing if LLM call fails.

**Step 3:** Call `search_listings(description, size, max_price)`.
- If results are empty AND size was specified: automatically retry with `size=None` (retry logic). If retry succeeds, set `session["retry_message"]` to inform the user. If retry also fails, set `session["error"]` and return early — no downstream tools are called.
- If results are empty AND no size was specified: set `session["error"]` and return early.
- If results are found: set `session["selected_item"] = results[0]` and proceed.

**Step 4:** Call `suggest_outfit(selected_item, wardrobe)`. Store result in `session["outfit_suggestion"]`. Empty wardrobe is handled gracefully by the tool itself.

**Step 5:** Call `create_fit_card(outfit_suggestion, selected_item)`. Store result in `session["fit_card"]`.

**Step 6:** Call `compare_price(selected_item)`. Store result in `session["price_assessment"]`.

**Step 7:** Return session.

The agent behaves differently for a non-standard input: if `search_listings` returns no results (e.g., "designer ballgown size XXS under $5"), the agent sets an error and stops — `suggest_outfit` and `create_fit_card` are never called. The demo shows this contrast explicitly.

---

## State Management

All state lives in the session dict initialized by `_new_session()` and passed through the planning loop. No global variables are used.

| Key | Set when | Used by |
|-----|----------|---------|
| `query` | Init | Step 2 (parsing) |
| `parsed` | Step 2 | Step 3 |
| `search_results` | Step 3 | Step 3 (branch check) |
| `selected_item` | Step 3 (top result) | Steps 4, 5, 6 |
| `wardrobe` | Init | Step 4 |
| `outfit_suggestion` | Step 4 | Step 5 |
| `fit_card` | Step 5 | UI output |
| `price_assessment` | Step 6 | UI output |
| `error` | Step 3 (on failure) | Early return check |
| `retry` | Step 3 | Tracks fallback attempt |
| `retry_message` | Step 3 (on successful retry) | UI listing panel |

The item returned by `search_listings` is stored as `session["selected_item"]` and flows directly into `suggest_outfit` and `create_fit_card` without any re-entry from the user.

---

## Error Handling

| Tool | Failure Mode | Agent Response |
|------|-------------|----------------|
| `search_listings` | Returns `[]` with size specified | Retries automatically with size filter removed. If retry succeeds, shows results with a notice. If retry also fails, returns: `"No listings found for '[description]' even after removing the size filter. Try a broader description or a higher price."` |
| `search_listings` | Returns `[]` with no size filter | Returns: `"No listings found matching '[description]' under $[max_price]. Try a broader description or a higher budget."` |
| `suggest_outfit` | Empty wardrobe | Switches LLM prompt to general styling advice mode. Returns styling suggestions without referencing specific wardrobe pieces. Never crashes. |
| `suggest_outfit` | Groq API error | Returns: `"Unable to generate outfit suggestion right now. Try again in a moment."` |
| `create_fit_card` | Empty/whitespace `outfit` | Returns: `"Error: cannot generate a fit card without an outfit suggestion."` — checked before any LLM call. |
| `create_fit_card` | Groq API error | Returns: `"Unable to generate fit card right now. Try again in a moment."` |
| `compare_price` | No comparable listings | Returns: `"No comparable listings found for this [category]. It may be a niche item."` |

**Concrete example from testing:** Running `search_listings("designer ballgown", size="XXS", max_price=5)` directly returns `[]` without raising any exception. When run through `run_agent()` with this query, the agent first retries without the XXS filter — which also returns `[]` — and the agent surfaces: `"No listings found for "designer ballgown" under $5 even after removing the size filter. Try a broader description or a higher price."` The Gradio UI shows this in the listing panel; the outfit and fit card panels remain blank.

---

## Stretch Features

### Price Comparison Tool (+2 pts)
`compare_price(item)` in `tools.py` finds comparable listings by matching `category` and `style_tags`, computes the median and mean price, and returns a plain-language verdict. No LLM is used — pure statistics. Result is displayed in a dedicated Gradio panel. Falls back gracefully to category-only matching if style-tag comparables are fewer than 2.

### Style Profile Memory (+2 pts)
`app.py` includes `load_profile()` and `save_profile()` functions that read/write `profile.json` (gitignored). The Gradio UI adds a "My saved profile" wardrobe option (shown if a profile file exists) and a "Save wardrobe to my profile" checkbox. This lets users skip re-entering their wardrobe across sessions. Storage approach: local JSON file, written only when the checkbox is checked.

### Retry Logic with Fallback (+1 pt)
When `search_listings` returns no results and a size filter was applied, the agent automatically retries without the size constraint. If the retry finds results, `session["retry_message"]` is set and displayed in the listing panel so the user knows their size filter was dropped. If the retry also fails, a specific error message explains both attempts.

---

## Spec Reflection

**One way the spec helped:** Writing out the planning loop as conditional logic in `planning.md` before touching code made the branch structure in `run_agent()` straightforward to implement. The explicit instruction to not call `suggest_outfit` when `search_results` is empty eliminated a whole class of potential bugs where bad data would flow to the LLM.

**One way implementation diverged from the spec:** The spec describes query parsing as a separate option — "use regex, string splitting, or ask the LLM." I initially planned regex-only parsing, but during implementation I realized LLM parsing handles edge cases like "something cozy and warm, not too expensive" far better than regex. I added regex as a fallback for when the LLM parse fails, keeping the spec's intent (robust parsing) while improving reliability.

---

## AI Usage

**Instance 1 — `search_listings` implementation:**
I gave Claude the Tool 1 section of `planning.md` (inputs with types, return value description listing all fields, failure mode) and the `load_listings()` function signature. I asked it to implement keyword scoring as overlap between lowercased description words and a concatenated searchable string built from `title`, `description`, `style_tags`, `category`, `colors`. Before using the output, I verified that the price filter used `<=` (inclusive) as specified, that size matching was substring-based (so `"M"` matches `"S/M"`), and that the function returned `[]` without raising on no matches. I revised the scoring loop to include `brand` in the searchable fields, which the generated code had omitted.

**Instance 2 — planning loop / retry logic:**
I gave Claude the Architecture diagram from `planning.md` and the Planning Loop section describing the retry branch (loosen size filter if results are empty). The generated code initially placed the retry inside the `if results:` branch (wrong — it should only trigger when `results` is empty). I restructured it to match the spec: retry only fires on empty results with a size filter present, sets `session["retry"] = True`, and proceeds only if the second search returns something. I also added the `session["retry_message"]` key that the generated code had omitted.

---

## Project Structure

```
ai201-project2-fitfindr-starter/
├── data/
│   ├── listings.json
│   └── wardrobe_schema.json
├── utils/
│   └── data_loader.py
├── tests/
│   └── test_tools.py
├── planning.md
├── tools.py
├── agent.py
├── app.py
├── requirements.txt
└── README.md
```
