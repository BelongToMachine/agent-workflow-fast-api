import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { queryMockRows } from "./mockQuery.mjs";

const rows = [
  { id: "p-01", productName: "Aurora Lamp", category: "Lighting", price: 24 },
  { id: "p-02", productName: "Cedar Chair", category: "Furniture", price: 90 },
  { id: "p-03", productName: "Aurora Strip", category: "Lighting", price: 12 },
  { id: "p-04", productName: "Linen Throw", category: "Home", price: 35 },
];
const mockRegistry = JSON.parse(
  readFileSync(new URL("../../data/businessTables.mock.json", import.meta.url), "utf8")
);

test("global search scans all fields before slicing an infinite block", () => {
  const result = queryMockRows(rows, {
    startRow: 0,
    endRow: 1,
    search: "lighting",
  });

  assert.deepEqual(result.rows.map((row) => row.id), ["p-01"]);
  assert.equal(result.total, 2);
});

test("column text and number filters apply to the whole dataset before pagination", () => {
  const result = queryMockRows(rows, {
    startRow: 0,
    endRow: 10,
    filterModel: {
      category: { filterType: "text", type: "equals", filter: "Lighting" },
      price: { filterType: "number", type: "lessThan", filter: 20 },
    },
  });

  assert.deepEqual(result.rows.map((row) => row.id), ["p-03"]);
  assert.equal(result.total, 1);
});

test("sorting is stable and applied before selecting a requested row block", () => {
  const result = queryMockRows(rows, {
    startRow: 1,
    endRow: 3,
    sortModel: [{ colId: "price", sort: "asc" }],
  });

  assert.deepEqual(result.rows.map((row) => row.id), ["p-01", "p-04"]);
  assert.equal(result.total, 4);
  assert.deepEqual(rows.map((row) => row.id), ["p-01", "p-02", "p-03", "p-04"]);
});

test("mock registry contains the five requested tables with rows matching declared metadata", () => {
  const tableKeys = mockRegistry.tables.map((table) => table.key);

  assert.deepEqual(tableKeys, [
    "RealProductResearch",
    "ProductPrice",
    "ProductOperation",
    "ProductDocument",
    "ContentRecord",
  ]);
  for (const table of mockRegistry.tables) {
    const fields = new Set(table.fields.map((field) => field.field));
    assert.ok(table.rows.length > 30, `${table.key} should contain enough rows to scroll`);
    for (const row of table.rows) {
      assert.ok(Object.keys(row).every((key) => fields.has(key)), `${table.key} has an undeclared field`);
    }
  }
});

test("ProductDocument only exposes its documented relationship fields", () => {
  const table = mockRegistry.tables.find((item) => item.key === "ProductDocument");

  assert.deepEqual(table.fields.map((field) => field.field), ["researchId", "sourceFileId"]);
  assert.equal(table.columnSource, "documented-fields-only");
});
