"""
app.py

Gradio interface for FitFindr. Includes style profile memory (stretch feature)
that persists wardrobe across sessions via a local JSON file.

Run with:
    python app.py
"""

import json
import os

import gradio as gr

from agent import run_agent
from utils.data_loader import get_example_wardrobe, get_empty_wardrobe

# ── style profile memory (stretch) ───────────────────────────────────────────

PROFILE_PATH = "profile.json"


def load_profile() -> dict | None:
    """Load saved style profile from disk. Returns None if no profile exists."""
    if os.path.exists(PROFILE_PATH):
        try:
            with open(PROFILE_PATH, "r") as f:
                return json.load(f)
        except Exception:
            return None
    return None


def save_profile(wardrobe: dict) -> None:
    """Persist the current wardrobe to disk for next session."""
    try:
        with open(PROFILE_PATH, "w") as f:
            json.dump(wardrobe, f, indent=2)
    except Exception:
        pass  # Non-fatal — profile saving is best-effort


def get_wardrobe(wardrobe_choice: str) -> dict:
    """Select the appropriate wardrobe based on user choice."""
    if wardrobe_choice == "My saved profile":
        profile = load_profile()
        if profile:
            return profile
        # Fall back to example wardrobe if no profile saved yet
        return get_example_wardrobe()
    elif wardrobe_choice == "Empty wardrobe (new user)":
        return get_empty_wardrobe()
    else:
        return get_example_wardrobe()


# ── query handler ─────────────────────────────────────────────────────────────

def handle_query(
    user_query: str,
    wardrobe_choice: str,
    save_to_profile: bool,
) -> tuple[str, str, str, str]:
    """
    Called by Gradio when the user submits a query.

    Args:
        user_query:      The text the user typed into the search box.
        wardrobe_choice: "Example wardrobe", "My saved profile", or "Empty wardrobe (new user)".
        save_to_profile: Whether to save the wardrobe to disk after this session.

    Returns:
        A tuple of four strings: (listing_text, outfit_suggestion, fit_card, price_assessment)
    """
    # Step 1: Guard against empty query
    if not user_query or not user_query.strip():
        return "Please enter a search query to get started.", "", "", ""

    # Step 2: Select wardrobe
    wardrobe = get_wardrobe(wardrobe_choice)

    # Step 3: Run agent
    session = run_agent(user_query, wardrobe)

    # Step 4: Save profile if requested
    if save_to_profile and wardrobe_choice != "Empty wardrobe (new user)":
        save_profile(wardrobe)

    # Step 5: Handle early exit (error path)
    if session["error"]:
        error_text = f"No results found\n\n{session['error']}"
        return error_text, "", "", ""

    # Step 6: Format listing panel
    item = session["selected_item"]
    retry_note = ""
    if session.get("retry_message"):
        retry_note = f"\n\n⚠️  {session['retry_message']}"

    listing_text = (
        f"🛍️  {item.get('title', 'Unknown')}\n"
        f"💲 ${item.get('price', '?')} — {item.get('condition', 'Unknown')} condition\n"
        f"📦 {item.get('platform', 'Unknown')}\n"
        f"📐 Size: {item.get('size', 'Unknown')}\n"
        f"🏷️  Brand: {item.get('brand', 'Unknown')}\n"
        f"🎨 Colors: {', '.join(item.get('colors', []))}\n"
        f"✨ Tags: {', '.join(item.get('style_tags', []))}\n\n"
        f"{item.get('description', '')}"
        f"{retry_note}"
    )

    outfit_text = session.get("outfit_suggestion") or ""
    fit_card_text = session.get("fit_card") or ""
    price_text = session.get("price_assessment") or ""

    return listing_text, outfit_text, fit_card_text, price_text


# ── interface ─────────────────────────────────────────────────────────────────

EXAMPLE_QUERIES = [
    "vintage graphic tee under $30",
    "90s track jacket in size M",
    "flowy midi skirt under $40",
    "black combat boots size 8",
    "designer ballgown size XXS under $5",  # deliberate no-results test
]


def build_interface():
    profile_exists = os.path.exists(PROFILE_PATH)
    wardrobe_choices = ["Example wardrobe", "Empty wardrobe (new user)"]
    if profile_exists:
        wardrobe_choices.insert(0, "My saved profile")

    with gr.Blocks(title="FitFindr") as demo:
        gr.Markdown("""
# FitFindr 🛍️
Find secondhand pieces and get outfit ideas based on your wardrobe.
Describe what you're looking for — include size and price if you want to filter.
""")

        with gr.Row():
            query_input = gr.Textbox(
                label="What are you looking for?",
                placeholder="e.g. vintage graphic tee under $30, size M",
                lines=2,
                scale=3,
            )
            with gr.Column(scale=1):
                wardrobe_choice = gr.Radio(
                    choices=wardrobe_choices,
                    value=wardrobe_choices[0],
                    label="Wardrobe",
                )
                save_profile_checkbox = gr.Checkbox(
                    label="Save wardrobe to my profile",
                    value=False,
                )

        submit_btn = gr.Button("Find it", variant="primary")

        with gr.Row():
            listing_output = gr.Textbox(
                label="🛍️ Top listing found",
                lines=10,
                interactive=False,
            )
            outfit_output = gr.Textbox(
                label="👗 Outfit idea",
                lines=10,
                interactive=False,
            )

        with gr.Row():
            fitcard_output = gr.Textbox(
                label="✨ Your fit card",
                lines=5,
                interactive=False,
            )
            price_output = gr.Textbox(
                label="💰 Price check",
                lines=5,
                interactive=False,
            )

        gr.Examples(
            examples=[[q, wardrobe_choices[0], False] for q in EXAMPLE_QUERIES],
            inputs=[query_input, wardrobe_choice, save_profile_checkbox],
            label="Try these queries",
        )

        submit_btn.click(
            fn=handle_query,
            inputs=[query_input, wardrobe_choice, save_profile_checkbox],
            outputs=[listing_output, outfit_output, fitcard_output, price_output],
        )

        query_input.submit(
            fn=handle_query,
            inputs=[query_input, wardrobe_choice, save_profile_checkbox],
            outputs=[listing_output, outfit_output, fitcard_output, price_output],
        )

    return demo


if __name__ == "__main__":
    demo = build_interface()
    demo.launch()
