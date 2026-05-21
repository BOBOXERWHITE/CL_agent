import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// React Testing Library auto-cleans after each test only when its jest
// preset is loaded; vitest with ``globals: true`` doesn't trigger that
// path, so renders from prior tests leak DOM nodes — which then produce
// "Found multiple elements" failures in unrelated tests within the same
// file. Forcing cleanup() restores the per-test isolation.
afterEach(() => {
  cleanup();
});
