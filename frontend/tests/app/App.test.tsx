import { render, screen } from "@testing-library/react";

import App from "../../src/app/App";

test("renders app shell title", () => {
  render(<App />);
  expect(screen.getByText("Travel Ops Copilot")).toBeInTheDocument();
});
