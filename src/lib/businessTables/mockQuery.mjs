function toComparable(value) {
  if (value === null || value === undefined) return "";
  if (typeof value === "number") return value;

  return String(value).trim().toLocaleLowerCase();
}

function matchesText(value, model) {
  const source = String(value ?? "").toLocaleLowerCase();
  const filter = String(model.filter ?? "").toLocaleLowerCase();

  switch (model.type) {
    case "equals":
      return source === filter;
    case "notEqual":
      return source !== filter;
    case "startsWith":
      return source.startsWith(filter);
    case "endsWith":
      return source.endsWith(filter);
    case "notContains":
      return !source.includes(filter);
    case "blank":
      return source.length === 0;
    case "notBlank":
      return source.length > 0;
    case "contains":
    default:
      return source.includes(filter);
  }
}

function matchesNumber(value, model) {
  const actual = Number(value);
  if (!Number.isFinite(actual)) {
    return model.type === "blank" && (value === null || value === undefined || value === "");
  }

  const target = Number(model.filter);
  const rangeEnd = Number(model.filterTo);
  switch (model.type) {
    case "equals":
      return actual === target;
    case "notEqual":
      return actual !== target;
    case "lessThan":
      return actual < target;
    case "lessThanOrEqual":
      return actual <= target;
    case "greaterThan":
      return actual > target;
    case "greaterThanOrEqual":
      return actual >= target;
    case "inRange":
      return actual >= target && actual <= rangeEnd;
    case "notBlank":
      return true;
    case "blank":
      return false;
    default:
      return actual === target;
  }
}

function matchesCondition(value, model) {
  if (!model) return true;
  if (Array.isArray(model.conditions)) {
    const results = model.conditions.map((condition) => matchesCondition(value, condition));
    return model.operator === "OR" ? results.some(Boolean) : results.every(Boolean);
  }

  if (model.type === "blank" || model.type === "notBlank") {
    const isBlank = value === null || value === undefined || value === "";
    return model.type === "blank" ? isBlank : !isBlank;
  }

  if (model.filterType === "number" || model.filterType === "date") {
    return matchesNumber(value, model);
  }
  return matchesText(value, model);
}

function matchesFilter(row, filterModel) {
  return Object.entries(filterModel ?? {}).every(([field, model]) =>
    matchesCondition(row[field], model)
  );
}

function matchesSearch(row, search) {
  const query = String(search ?? "").trim().toLocaleLowerCase();
  if (!query) return true;

  return Object.values(row).some((value) => {
    const text = typeof value === "object" && value !== null
      ? JSON.stringify(value)
      : String(value ?? "");
    return text.toLocaleLowerCase().includes(query);
  });
}

function compareRows(left, right, sortModel) {
  for (const sort of sortModel ?? []) {
    if (!sort.colId || (sort.sort !== "asc" && sort.sort !== "desc")) continue;
    const a = toComparable(left.row[sort.colId]);
    const b = toComparable(right.row[sort.colId]);
    const comparison = typeof a === "number" && typeof b === "number"
      ? a - b
      : String(a).localeCompare(String(b), undefined, { numeric: true, sensitivity: "base" });

    if (comparison !== 0) return sort.sort === "desc" ? -comparison : comparison;
  }

  return left.index - right.index;
}

export function queryMockRows(rows, options = {}) {
  const {
    endRow = rows.length,
    filterModel = {},
    search = "",
    sortModel = [],
    startRow = 0,
  } = options;

  const filteredRows = rows
    .filter((row) => matchesSearch(row, search) && matchesFilter(row, filterModel))
    .map((row, index) => ({ row, index }));

  if (sortModel.length > 0) filteredRows.sort((left, right) => compareRows(left, right, sortModel));

  return {
    rows: filteredRows.slice(Math.max(0, startRow), Math.max(startRow, endRow)).map(({ row }) => row),
    total: filteredRows.length,
  };
}
