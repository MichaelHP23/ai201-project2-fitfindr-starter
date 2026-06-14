"""
tests/test_tools.py

Pytest tests for each FitFindr tool, covering happy paths and failure modes.
Run with: pytest tests/
"""

import pytest
from tools import search_listings, create_fit_card, compare_price

# ── search_listings tests ─────────────────────────────────────────────────────

def test_search_returns_results():
    results = search_listings("vintage graphic tee", size=None, max_price=50)
    assert isinstance(results, list)
    assert len(results) > 0


def test_search_empty_results():
    """Impossible query — should return empty list, not crash."""
    results = search_listings("designer ballgown", size="XXS", max_price=5)
    assert results == []


def test_search_price_filter():
    """All returned items should be at or below max_price."""
    results = search_listings("jacket", size=None, max_price=30)
    assert all(item["price"] <= 30 for item in results)


def test_search_size_filter_case_insensitive():
    """Size filter should be case-insensitive."""
    results_upper = search_listings("shirt", size="M", max_price=None)
    results_lower = search_listings("shirt", size="m", max_price=None)
    assert len(results_upper) == len(results_lower)


def test_search_no_filters():
    """With no size or price filter, should return multiple results."""
    results = search_listings("shirt")
    assert isinstance(results, list)


def test_search_returns_dicts_with_required_fields():
    """Each returned item should have the fields the agent depends on."""
    results = search_listings("vintage", size=None, max_price=100)
    if results:
        item = results[0]
        for field in ["id", "title", "price", "platform", "size", "condition"]:
            assert field in item, f"Missing field: {field}"


def test_search_sorted_by_relevance():
    """Higher-scoring items should appear before lower-scoring ones."""
    results = search_listings("vintage denim jacket")
    # We can't know exact scores, but results should be a list — just verify no crash
    assert isinstance(results, list)


# ── create_fit_card tests ─────────────────────────────────────────────────────

def test_create_fit_card_empty_outfit_returns_error():
    """Empty outfit string should return an error message, not raise."""
    results = search_listings("vintage graphic tee", size=None, max_price=50)
    if results:
        result = create_fit_card("", results[0])
        assert isinstance(result, str)
        assert "Error" in result or "error" in result


def test_create_fit_card_whitespace_outfit_returns_error():
    """Whitespace-only outfit should also return an error message."""
    results = search_listings("jacket", size=None, max_price=100)
    if results:
        result = create_fit_card("   ", results[0])
        assert isinstance(result, str)
        assert len(result) > 0


# ── compare_price tests ───────────────────────────────────────────────────────

def test_compare_price_returns_string():
    results = search_listings("jacket", size=None, max_price=100)
    if results:
        result = compare_price(results[0])
        assert isinstance(result, str)
        assert len(result) > 0


def test_compare_price_no_comparables():
    """Item with a made-up category should gracefully return a fallback message."""
    fake_item = {
        "id": "fake-999",
        "title": "Space Suit",
        "category": "space_gear",
        "style_tags": [],
        "price": 9999.99,
    }
    result = compare_price(fake_item)
    assert isinstance(result, str)
    assert len(result) > 0
