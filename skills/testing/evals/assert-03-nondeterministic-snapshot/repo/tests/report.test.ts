import { expect, it } from "vitest";
import { buildReport } from "../src/report";

it("builds the report", () => {
  expect(buildReport()).toMatchSnapshot();
});
