import "@testing-library/jest-dom/vitest";

// jsdom does not implement Element.scrollTo — components that auto-scroll
// (ChatInterface) call it on mount, which crashes the render.
if (typeof Element !== "undefined" && !Element.prototype.scrollTo) {
  Element.prototype.scrollTo = () => {};
}
