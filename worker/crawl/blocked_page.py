"""
Blocked-page detection for last-resort overlay hide fallback (TECH_SPEC_V1.1.md §5 v1.23).

Detection is deterministic, does not mutate the DOM, and has no network or external
dependencies. Returns True only when both overlay heuristic and blocking signal are satisfied.
"""

from __future__ import annotations

from typing import TypedDict

from playwright.async_api import Page

from worker.crawl.constants import (
    BLOCKED_PAGE_OVERLAY_HIDE_EXCLUDE_TAGS,
    BLOCKED_PAGE_OVERLAY_MIN_VIEWPORT_RATIO,
    BLOCKED_PAGE_OVERLAY_MIN_Z_INDEX,
)

# Injected into the page; runs in one pass, DOM order, read-only.
_BLOCKED_PAGE_DETECT_JS = """
(options) => {
  const minRatio = options.minViewportRatio;
  const minZIndex = options.minZIndex;
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  const viewportArea = vw * vh;
  const cx = vw / 2;
  const cy = vh / 2;

  const overlayCandidates = [];
  const all = document.getElementsByTagName('*');
  for (let i = 0; i < all.length; i++) {
    const el = all[i];
    const style = window.getComputedStyle(el);
    const position = style.position;
    if (position !== 'fixed' && position !== 'absolute') continue;
    let z = 0;
    const zStr = style.zIndex;
    if (zStr !== 'auto' && zStr !== '') {
      const parsed = parseInt(zStr, 10);
      if (!isNaN(parsed)) z = parsed;
    }
    if (z < minZIndex) continue;
    const rect = el.getBoundingClientRect();
    const left = Math.max(0, rect.left);
    const right = Math.min(vw, rect.right);
    const top = Math.max(0, rect.top);
    const bottom = Math.min(vh, rect.bottom);
    const area = (right - left) * (bottom - top);
    if (area <= 0) continue;
    const ratio = area / viewportArea;
    if (ratio >= minRatio) overlayCandidates.push(el);
  }

  let scrollLocked = false;
  const htmlStyle = window.getComputedStyle(document.documentElement);
  const bodyStyle = window.getComputedStyle(document.body);
  if (htmlStyle.overflow === 'hidden' || htmlStyle.overflowY === 'hidden' ||
      bodyStyle.overflow === 'hidden' || bodyStyle.overflowY === 'hidden') {
    scrollLocked = true;
  }
  const bodyPos = document.body.style.position;
  const htmlPos = document.documentElement.style.position;
  if (!scrollLocked && (bodyPos === 'fixed' || htmlPos === 'fixed')) {
    scrollLocked = true;
  }

  let clickBlocked = false;
  const centerEl = document.elementFromPoint(cx, cy);
  if (centerEl && overlayCandidates.length > 0) {
    clickBlocked = overlayCandidates.some(oc => oc === centerEl || oc.contains(centerEl));
  }

  const hasOverlayCandidate = overlayCandidates.length > 0;
  const isBlocked = hasOverlayCandidate && (scrollLocked || clickBlocked);
  return {
    hasOverlayCandidate,
    scrollLocked,
    clickBlocked,
    isBlocked,
    overlayCandidateCount: overlayCandidates.length,
  };
}
"""

# One pass per frame: hide overlay candidates (same heuristic as detection),
# exclude structural nodes. Mutates DOM (visibility only); run when blocked.
_OVERLAY_HIDE_JS = """
(options) => {
  const minRatio = options.minViewportRatio;
  const minZIndex = options.minZIndex;
  const structuralTags = options.structuralTags || [];
  const vw = document.documentElement.clientWidth || window.innerWidth;
  const vh = document.documentElement.clientHeight || window.innerHeight;
  const viewportArea = vw * vh;
  let hiddenCount = 0;
  const all = document.getElementsByTagName('*');
  for (let i = 0; i < all.length; i++) {
    const el = all[i];
    const tag = (el.tagName || '').toLowerCase();
    if (structuralTags.indexOf(tag) >= 0) continue;
    const style = window.getComputedStyle(el);
    const position = style.position;
    if (position !== 'fixed' && position !== 'absolute') continue;
    let z = 0;
    const zStr = style.zIndex;
    if (zStr !== 'auto' && zStr !== '') {
      const parsed = parseInt(zStr, 10);
      if (!isNaN(parsed)) z = parsed;
    }
    if (z < minZIndex) continue;
    const rect = el.getBoundingClientRect();
    const left = Math.max(0, rect.left);
    const right = Math.min(vw, rect.right);
    const top = Math.max(0, rect.top);
    const bottom = Math.min(vh, rect.bottom);
    const area = (right - left) * (bottom - top);
    if (area <= 0) continue;
    const ratio = area / viewportArea;
    if (ratio >= minRatio) {
      el.style.setProperty('visibility', 'hidden');
      hiddenCount++;
    }
  }
  return { hiddenCount };
}
"""


class BlockedPageResult(TypedDict):
    """Result of blocked-page detection (for logging)."""

    is_blocked: bool
    has_overlay_candidate: bool
    scroll_locked: bool
    click_blocked: bool
    overlay_candidate_count: int


async def detect_blocked_page(page: Page) -> BlockedPageResult:
    """
    Run blocked-page detection in the page context. Does not mutate DOM.

    Per TECH_SPEC_V1.1.md §5 v1.23:
    - Overlay heuristic: at least one large fixed/absolute element with high z-index
      and viewport coverage >= BLOCKED_PAGE_OVERLAY_MIN_VIEWPORT_RATIO.
    - Blocking signal: scroll locked (overflow hidden or body/html position fixed)
      OR click at viewport center blocked by an overlay candidate (elementFromPoint).

    Returns a result dict with is_blocked (True only when both conditions hold),
    plus fields for logging. Deterministic; no network or external deps.
    """
    options = {
        "minViewportRatio": BLOCKED_PAGE_OVERLAY_MIN_VIEWPORT_RATIO,
        "minZIndex": BLOCKED_PAGE_OVERLAY_MIN_Z_INDEX,
    }
    raw = await page.evaluate(_BLOCKED_PAGE_DETECT_JS, options)
    return BlockedPageResult(
        is_blocked=bool(raw["isBlocked"]),
        has_overlay_candidate=bool(raw["hasOverlayCandidate"]),
        scroll_locked=bool(raw["scrollLocked"]),
        click_blocked=bool(raw["clickBlocked"]),
        overlay_candidate_count=int(raw["overlayCandidateCount"]),
    )


async def is_page_blocked(page: Page) -> bool:
    """
    Return True if the page is considered blocked (overlay heuristic + blocking signal).

    Convenience wrapper around detect_blocked_page. Deterministic; does not mutate DOM.
    """
    result = await detect_blocked_page(page)
    return result["is_blocked"]


def _overlay_hide_options() -> dict:
    """Options for overlay-hide script (main doc + iframes)."""
    return {
        "minViewportRatio": BLOCKED_PAGE_OVERLAY_MIN_VIEWPORT_RATIO,
        "minZIndex": BLOCKED_PAGE_OVERLAY_MIN_Z_INDEX,
        "structuralTags": list(BLOCKED_PAGE_OVERLAY_HIDE_EXCLUDE_TAGS),
    }


async def apply_overlay_hide_in_frames(page: Page) -> tuple[int, int]:
    """
    Apply overlay hide (visibility: hidden) in main document and all iframes, one pass per frame.

    Per TECH_SPEC_V1.1.md §5 v1.23: hide elements matching overlay heuristic only;
    exclude structural nodes (html, body, main, header, nav, footer). Does not remove nodes.
    Call only when blocked-page detection is True.

    Returns (total_hidden_count, frame_count). frame_count counts only frames where
    evaluate succeeded; cross-origin or otherwise failing frames are skipped.
    """
    options = _overlay_hide_options()
    total_hidden = 0
    frame_count = 0
    for frame in page.frames:
        try:
            raw = await frame.evaluate(_OVERLAY_HIDE_JS, options)
            total_hidden += int(raw.get("hiddenCount", 0))
            frame_count += 1
        except Exception:
            continue
    return (total_hidden, frame_count)
