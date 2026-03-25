from __future__ import annotations

import re
from dataclasses import dataclass

from bs4 import BeautifulSoup, Tag
from playwright.async_api import Page

ADD_TO_CART_PATTERNS = [
    "add to cart",
    "add to bag",
    "add to basket",
    "buy now",
    "purchase",
]


def _normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "")).strip().lower()


def _tag_text(tag: Tag) -> str:
    return _normalize_space(" ".join(tag.stripped_strings))


def _get_attr(tag: Tag, name: str) -> str:
    value = tag.attrs.get(name)
    if isinstance(value, list):
        return " ".join(str(v) for v in value)
    return str(value or "")


def _safe_literal(value: str) -> str:
    if "'" not in value:
        return f"'{value}'"
    if '"' not in value:
        return f'"{value}"'
    parts = value.split("'")
    return "concat(" + ", \"'\", ".join(f"'{part}'" for part in parts) + ")"


def _build_xpath(tag: Tag) -> str:
    parts: list[str] = [f"//{tag.name}"]

    tag_id = _get_attr(tag, "id").strip()
    if tag_id:
        parts.append(f"[@id={_safe_literal(tag_id)}]")
        return "".join(parts)

    name = _get_attr(tag, "name").strip()
    if name:
        parts.append(f"[@name={_safe_literal(name)}]")

    data_action = _get_attr(tag, "data-action").strip()
    if data_action:
        parts.append(f"[@data-action={_safe_literal(data_action)}]")

    btn_type = _get_attr(tag, "type").strip()
    if btn_type:
        parts.append(f"[@type={_safe_literal(btn_type)}]")

    classes = [cls for cls in _get_attr(tag, "class").split() if cls]
    if classes:
        class_checks = [
            f"contains(concat(' ', normalize-space(@class), ' '), ' {cls} ')" for cls in classes[:2]
        ]
        parts.append("[" + " and ".join(class_checks) + "]")

    text_value = _tag_text(tag)
    if text_value:
        parts.append(
            f"[contains(translate(normalize-space(.), "
            f"'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), "
            f"{_safe_literal(text_value[:40])})]"
        )

    return "".join(parts)


@dataclass
class _Candidate:
    score: int
    xpath: str


def _score_add_to_cart_tag(tag: Tag) -> int:
    score = 0
    text_value = _tag_text(tag)
    attrs_blob = _normalize_space(
        " ".join(
            [
                text_value,
                _get_attr(tag, "id"),
                _get_attr(tag, "name"),
                _get_attr(tag, "class"),
                _get_attr(tag, "value"),
                _get_attr(tag, "aria-label"),
                _get_attr(tag, "data-action"),
                _get_attr(tag, "data-testid"),
            ]
        )
    )

    if tag.name in {"button", "input"}:
        score += 10
    if tag.name == "button":
        score += 8

    if _normalize_space(_get_attr(tag, "type")) == "submit":
        score += 12

    for pattern in ADD_TO_CART_PATTERNS:
        if pattern in text_value:
            score += 30
            break

    if "add" in attrs_blob and "cart" in attrs_blob:
        score += 18

    if "product-form" in attrs_blob or "product-form__submit" in attrs_blob:
        score += 15

    if "shopify-payment-button" in attrs_blob:
        score -= 10

    parent_form = tag.find_parent("form")
    if parent_form:
        form_action = _normalize_space(_get_attr(parent_form, "action"))
        if "/cart/add" in form_action:
            score += 35
        if "product-form" in _normalize_space(_get_attr(parent_form, "class")):
            score += 12

    if tag.has_attr("disabled"):
        score -= 20

    return score


def _collect_add_to_cart_candidates(html_text: str) -> list[_Candidate]:
    soup = BeautifulSoup(html_text, "html.parser")
    candidates: list[_Candidate] = []

    for tag in soup.find_all(["button", "input"]):
        if _normalize_space(_get_attr(tag, "type")) == "hidden":
            continue
        score = _score_add_to_cart_tag(tag)
        if score < 20:
            continue
        candidates.append(_Candidate(score=score, xpath=_build_xpath(tag)))

    deduped: dict[str, _Candidate] = {}
    for candidate in sorted(candidates, key=lambda item: item.score, reverse=True):
        deduped.setdefault(candidate.xpath, candidate)
    return list(deduped.values())


async def discover_add_to_cart_xpaths(page: Page, top: int = 8) -> list[str]:
    html_text = await page.content()
    candidates = _collect_add_to_cart_candidates(html_text)
    return [c.xpath for c in candidates[:top]]


async def discover_checkout_xpaths(page: Page, top: int = 8) -> list[str]:
    html_text = await page.content()
    soup = BeautifulSoup(html_text, "html.parser")
    candidates: list[_Candidate] = []
    for tag in soup.find_all(["button", "input", "a"]):
        if _normalize_space(_get_attr(tag, "type")) == "hidden":
            continue
        text = _tag_text(tag)
        attrs_blob = _normalize_space(
            " ".join(
                [
                    text,
                    _get_attr(tag, "id"),
                    _get_attr(tag, "name"),
                    _get_attr(tag, "class"),
                    _get_attr(tag, "value"),
                    _get_attr(tag, "aria-label"),
                    _get_attr(tag, "data-action"),
                    _get_attr(tag, "data-testid"),
                    _get_attr(tag, "href"),
                ]
            )
        )
        score = 0
        if tag.name in {"button", "input", "a"}:
            score += 8
        if "checkout" in text or "check out" in text:
            score += 35
        if "checkout" in attrs_blob:
            score += 30
        if "/checkout" in _normalize_space(_get_attr(tag, "href")):
            score += 40
        if _normalize_space(_get_attr(tag, "name")) == "checkout":
            score += 25
        if tag.has_attr("disabled"):
            score -= 20
        if score >= 25:
            candidates.append(_Candidate(score=score, xpath=_build_xpath(tag)))
    deduped: dict[str, _Candidate] = {}
    for candidate in sorted(candidates, key=lambda item: item.score, reverse=True):
        deduped.setdefault(candidate.xpath, candidate)
    return [c.xpath for c in list(deduped.values())[:top]]
