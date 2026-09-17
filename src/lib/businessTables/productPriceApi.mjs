export function buildProductPriceRowsPath({
  workspaceId,
  startRow,
  endRow,
  search,
  filterModel,
  sortModel,
}) {
  const query = new URLSearchParams({
    workspace_id: String(workspaceId ?? ""),
    offset: String(startRow),
    limit: String(Math.max(0, endRow - startRow)),
  });
  const normalizedSearch = String(search ?? "").trim();
  if (normalizedSearch) query.set("q", normalizedSearch);

  const sort = (sortModel ?? [])
    .filter((item) => item?.colId && (item.sort === "asc" || item.sort === "desc"))
    .map((item) => ({ field: item.colId, direction: item.sort }));
  if (sort.length > 0) query.set("sort", JSON.stringify(sort));

  if (filterModel && Object.keys(filterModel).length > 0) {
    query.set("filters", JSON.stringify(filterModel));
  }

  return `/api/v1/admin/data-tables/ProductPrice/rows?${query.toString()}`;
}
