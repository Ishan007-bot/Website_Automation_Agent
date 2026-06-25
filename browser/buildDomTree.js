// buildDomTree.js
//
// Injected into the page on every step. Finds the interactive, visible elements,
// assigns each a stable numeric index, and returns metadata + the viewport-relative
// center coordinates the controller uses for click_on_screen(x, y).
//
// It also draws a numbered highlight box over each element so the screenshot shown
// in the Web-UI matches exactly what the LLM "sees" by index (set-of-marks style).
//
// Returns: { elements: [ {index, tag, type, text, placeholder, ariaLabel,
//                          name, value, x, y, width, height, inViewport} ], scroll: {...} }

(function () {
  const args = arguments[0] || {};
  // Default OFF: only draw the highlight boxes when explicitly asked. The agent
  // always removes any previous overlay below, so leftover boxes get cleaned up.
  const drawHighlights = args.drawHighlights === true;

  // Remove highlights from a previous step.
  const old = document.getElementById("__agent_highlights__");
  if (old) old.remove();

  const overlay = document.createElement("div");
  overlay.id = "__agent_highlights__";
  overlay.style.cssText =
    "position:fixed;top:0;left:0;width:0;height:0;z-index:2147483647;pointer-events:none;";
  if (drawHighlights) document.body.appendChild(overlay);

  const INTERACTIVE_TAGS = new Set([
    "a", "button", "input", "textarea", "select", "summary", "details", "option", "label",
  ]);
  const INTERACTIVE_ROLES = new Set([
    "button", "link", "checkbox", "radio", "menuitem", "tab", "switch",
    "textbox", "combobox", "searchbox", "option", "menuitemcheckbox", "menuitemradio",
  ]);

  function isVisible(el) {
    const style = window.getComputedStyle(el);
    if (style.display === "none" || style.visibility === "hidden" || parseFloat(style.opacity) === 0) {
      return false;
    }
    const rect = el.getBoundingClientRect();
    if (rect.width < 2 || rect.height < 2) return false;
    return true;
  }

  function isInteractive(el) {
    const tag = el.tagName.toLowerCase();
    if (INTERACTIVE_TAGS.has(tag)) {
      // skip disabled/hidden inputs
      if ((tag === "input") && (el.type === "hidden" || el.disabled)) return false;
      return true;
    }
    const role = (el.getAttribute("role") || "").toLowerCase();
    if (INTERACTIVE_ROLES.has(role)) return true;
    if (el.hasAttribute("onclick")) return true;
    if (el.getAttribute("contenteditable") === "true") return true;
    if (el.hasAttribute("tabindex") && el.getAttribute("tabindex") !== "-1") return true;
    // Elements whose CSS marks them clickable.
    if (window.getComputedStyle(el).cursor === "pointer" && el.children.length === 0) return true;
    return false;
  }

  // Find the nearest associated label text for form fields.
  function labelFor(el) {
    if (el.id) {
      const lbl = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
      if (lbl) return lbl.innerText.trim();
    }
    const parentLabel = el.closest("label");
    if (parentLabel) return parentLabel.innerText.trim();
    return "";
  }

  const candidates = Array.from(document.querySelectorAll("*")).filter(
    (el) => isInteractive(el) && isVisible(el)
  );

  const vw = window.innerWidth;
  const vh = window.innerHeight;
  const elements = [];
  let index = 0;

  for (const el of candidates) {
    const rect = el.getBoundingClientRect();
    const cx = rect.left + rect.width / 2;
    const cy = rect.top + rect.height / 2;

    // VIEWPORT-ONLY: only expose elements whose clickable center is actually on
    // screen. This guarantees the (x, y) we hand to click_on_screen always lands
    // on the element. Anything below/above the fold is reached by scrolling first.
    if (cx < 0 || cy < 0 || cx > vw || cy > vh) continue;

    const text = (el.innerText || el.value || "").trim().replace(/\s+/g, " ").slice(0, 120);
    elements.push({
      index,
      tag: el.tagName.toLowerCase(),
      type: el.getAttribute("type") || "",
      text,
      placeholder: el.getAttribute("placeholder") || "",
      ariaLabel: el.getAttribute("aria-label") || "",
      name: el.getAttribute("name") || "",
      value: (el.value || "").slice(0, 120),
      label: labelFor(el),
      x: Math.round(cx),
      y: Math.round(cy),
      width: Math.round(rect.width),
      height: Math.round(rect.height),
      inViewport: cy >= 0 && cy <= vh && cx >= 0 && cx <= vw,
    });

    if (drawHighlights) {
      const box = document.createElement("div");
      box.style.cssText =
        `position:fixed;left:${rect.left}px;top:${rect.top}px;width:${rect.width}px;` +
        `height:${rect.height}px;border:2px solid #ff007f;box-sizing:border-box;` +
        `pointer-events:none;`;
      const tag = document.createElement("div");
      tag.textContent = index;
      tag.style.cssText =
        `position:fixed;left:${rect.left}px;top:${Math.max(0, rect.top - 14)}px;` +
        `background:#ff007f;color:#fff;font:bold 11px monospace;padding:0 3px;` +
        `border-radius:2px;pointer-events:none;`;
      overlay.appendChild(box);
      overlay.appendChild(tag);
    }

    index += 1;
  }

  return {
    elements,
    scroll: {
      x: window.scrollX,
      y: window.scrollY,
      maxY: Math.max(0, document.body.scrollHeight - vh),
      vw,
      vh,
    },
  };
})();
