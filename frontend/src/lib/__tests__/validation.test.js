import { describe, expect, it } from "vitest";
import { eventErrorLines, issueLine, summarizeUpload } from "../validation";

describe("validation messages", () => {
  it("writes each problem as a sentence", () => {
    expect(issueLine({ row: 5, column: "Season", value: "XYZ", message: "Must be one of: …" })).toBe('Invalid value: Season = "XYZ" (row 5)');
    expect(issueLine({ row: 7, column: "Price", value: "-500", message: "Price must be greater than 0" })).toBe("Invalid value: Price = -500 (row 7)");
    expect(issueLine({ row: 2, column: "Target_Category", value: null, message: "Value is missing." })).toBe("Missing value: Target_Category (row 2)");
    expect(issueLine({ field: "bogus", value: "1", message: "Unexpected field." })).toBe("Unexpected field: bogus");
  });
  it("summarises rejected and accepted uploads", () => {
    const rejected = summarizeUpload({ missing_columns: ["Customer_Preference"], column_errors: ["Missing required columns: Customer_Preference"],
      errors: [], valid_rows: 0 }, { accepted: false, message: "Upload rejected: Missing required columns: Customer_Preference." });
    expect(rejected.headline).toBe("Upload rejected");
    expect(rejected.lines).toEqual(["Missing column: Customer_Preference"]);
    expect(rejected.tone).toBe("drift");
    const ok = summarizeUpload({ ok: true, valid_rows: 2100, invalid_rows: 0, duplicate_rows: 0, errors: [] }, { accepted: true });
    expect(ok.headline).toBe("Validation successful");
    expect(ok.detail).toBe(`${new Intl.NumberFormat().format(2100)} records accepted`);
    expect(eventErrorLines([{ field: "price", value: "-500", message: "x" }])[0].text).toBe("Invalid value: price = -500");
  });
});
