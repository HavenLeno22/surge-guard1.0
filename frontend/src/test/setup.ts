import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// Testing Library only unmounts between tests on its own when test globals are
// enabled; they are not here, so rendered trees would leak into the next test.
afterEach(() => {
  cleanup();
});
