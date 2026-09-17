import {
  ColumnApiModule,
  InfiniteRowModelModule,
  NumberFilterModule,
  TextFilterModule,
  themeQuartz,
  type ColDef,
  type ColumnState,
  type GridApi,
  type GridReadyEvent,
  type IDatasource,
  type IGetRowsParams,
  type Theme,
} from "ag-grid-community";
import { AgGridProvider, AgGridReact } from "ag-grid-react";
import {
  ArrowDownIcon,
  ArrowUpIcon,
  CheckIcon,
  ChevronDownIcon,
  Columns3Icon,
  DatabaseIcon,
  ExternalLinkIcon,
  FilterXIcon,
  RefreshCwIcon,
  SearchIcon,
  XIcon,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useApplicationAuth } from "@/lib/auth/applicationAuth";
import { useSession } from "@/lib/auth";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import mockBusinessTables from "@/data/businessTables.mock.json";
import { requestBackend } from "@/lib/backend/request";
import { queryMockRows } from "@/lib/businessTables/mockQuery.mjs";
import { buildProductPriceRowsPath } from "@/lib/businessTables/productPriceApi.mjs";
import "./businessDataTablesPage.css";

type Locale = "zh" | "en";
type BusinessRow = Record<string, unknown>;

type BusinessField = {
  defaultVisible: boolean;
  field: string;
  labelEn: string;
  labelZh: string;
  longText: boolean;
  searchable: boolean;
  sortable: boolean;
  filterable: boolean;
  type: "text" | "number" | "boolean" | "date" | "array";
  width: number;
};

type BusinessTable = {
  category: "product" | "content";
  columnSource?: string;
  descriptionEn: string;
  descriptionZh: string;
  fields: BusinessField[];
  key: string;
  labelEn: string;
  labelZh: string;
  rows: BusinessRow[];
};

type BusinessTableRowsResponse = {
  rows: BusinessRow[];
  total: number;
  hasMore: boolean;
};

type StoredColumnState = ColumnState[];
type OrderedColumn = { field: BusinessField; state: ColumnState };

const tables = mockBusinessTables.tables as BusinessTable[];
const modules = [InfiniteRowModelModule, ColumnApiModule, TextFilterModule, NumberFilterModule];
const statusFields = new Set([
  "operationStatus",
  "promotionStatus",
  "reviewStatus",
  "usageStatus",
]);

const labels = {
  en: {
    title: "Business data tables",
    subtitle: "A focused view of product and content records across the workspace.",
    preview: "Mock data preview",
    connected: "Database connected",
    previewNote: "This table uses local mock JSON.",
    apiNote: "ProductPrice is loaded from PostgreSQL. Other tables still use local mock JSON.",
    productGroup: "Product",
    contentGroup: "Content",
    search: "Search all fields",
    searchPlaceholder: "Search this table…",
    filters: "Filter from the inputs under each column header",
    clearFilters: "Clear filters",
    refresh: "Reload rows",
    columns: "Columns",
    rows: "rows",
    loaded: "Total",
    clickRow: "Select a row to inspect the full record",
    noRows: "No records match this search.",
    noRowsGrid: "No records to show",
    mockBadge: "MOCK JSON",
    apiBadge: "POSTGRESQL API",
    resetColumns: "Reset columns",
    showColumn: "Show column",
    moveUp: "Move up",
    moveDown: "Move down",
    pin: "Pin",
    unpinned: "Not pinned",
    pinLeft: "Pin left",
    pinRight: "Pin right",
    detail: "Record details",
    fullValue: "Full value",
    jsonView: "JSON view",
    fieldsView: "Fields",
    relation: "Product relation",
    openProduct: "Open product record",
    mockRecord: "Synthetic record",
    databaseRecord: "Database record",
    loadError: "Could not load ProductPrice rows. Check the backend connection and retry.",
    retry: "Retry",
    sourceMetadata: "Columns are limited to documented relationship fields until the API supplies metadata.",
    all: "All",
    true: "Yes",
    false: "No",
    close: "Close",
    searchLabel: "Search all fields in this table",
    columnSettings: "Configure visible columns and order",
  },
  zh: {
    title: "业务数据表",
    subtitle: "集中浏览工作区中的产品和内容业务记录。",
    preview: "Mock 数据预览",
    connected: "数据库已连接",
    previewNote: "当前表使用本地 mock JSON。",
    apiNote: "ProductPrice 已从 PostgreSQL 加载，其他表暂时仍使用本地 mock JSON。",
    productGroup: "产品",
    contentGroup: "内容",
    search: "检索全部字段",
    searchPlaceholder: "搜索当前表…",
    filters: "可在各列标题下的输入框中筛选",
    clearFilters: "清除筛选",
    refresh: "重新加载数据",
    columns: "列配置",
    rows: "条记录",
    loaded: "总计",
    clickRow: "选择一行以查看完整记录",
    noRows: "没有符合条件的记录。",
    noRowsGrid: "没有可显示的记录",
    mockBadge: "模拟 JSON",
    apiBadge: "POSTGRESQL API",
    resetColumns: "恢复默认列",
    showColumn: "显示列",
    moveUp: "上移",
    moveDown: "下移",
    pin: "固定",
    unpinned: "不固定",
    pinLeft: "固定到左侧",
    pinRight: "固定到右侧",
    detail: "记录详情",
    fullValue: "完整内容",
    jsonView: "JSON 视图",
    fieldsView: "字段详情",
    relation: "关联产品",
    openProduct: "查看产品主资料",
    mockRecord: "模拟记录",
    databaseRecord: "数据库记录",
    loadError: "ProductPrice 加载失败，请检查后端连接后重试。",
    retry: "重试",
    sourceMetadata: "API 元数据补充前，仅展示已确认的产品关联字段。",
    all: "全部",
    true: "是",
    false: "否",
    close: "关闭",
    searchLabel: "检索当前表中的全部字段",
    columnSettings: "配置显示列和字段顺序",
  },
} satisfies Record<Locale, Record<string, string>>;

const statusLabels: Record<string, { en: string; zh: string }> = {
  active: { en: "Active", zh: "运营中" },
  pending_review: { en: "Pending review", zh: "待审核" },
  paused: { en: "Paused", zh: "已暂停" },
  ready: { en: "Ready", zh: "就绪" },
  not_started: { en: "Not started", zh: "未开始" },
  in_progress: { en: "In progress", zh: "进行中" },
  published: { en: "Published", zh: "已发布" },
  hold: { en: "On hold", zh: "暂缓" },
  approved: { en: "Approved", zh: "已通过" },
  pending: { en: "Pending", zh: "待审核" },
  changes_requested: { en: "Changes requested", zh: "需要修改" },
  draft: { en: "Draft", zh: "草稿" },
  planned: { en: "Planned", zh: "已计划" },
  in_use: { en: "In use", zh: "使用中" },
  archived: { en: "Archived", zh: "已归档" },
};

function fieldLabel(field: BusinessField, locale: Locale) {
  return locale === "zh" ? field.labelZh : field.labelEn;
}

function formatValue(value: unknown, field: BusinessField, locale: Locale, truncate = true) {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "boolean") return value ? labels[locale].true : labels[locale].false;
  if (Array.isArray(value)) return value.map(String).join(" · ");
  if (typeof value === "object") return JSON.stringify(value);

  const text = String(value);
  if (statusFields.has(field.field) && statusLabels[text]) {
    return statusLabels[text][locale];
  }
  if (truncate && field.longText && text.length > 86) return `${text.slice(0, 83)}…`;
  return text;
}

function rowKey(table: BusinessTable, row: BusinessRow) {
  if (row.id !== null && row.id !== undefined) return String(row.id);
  if (table.key === "RealProductResearch") return String(row.id ?? "");
  if (table.key === "ProductPrice") {
    return `${row.researchId}:${row.sourceFileId}:${row.variant}`;
  }
  if (table.key === "ProductOperation") return `${row.researchId}:${row.sourceFileId}`;
  if (table.key === "ProductDocument") return `${row.researchId}:${row.sourceFileId}`;
  return `${row.sourceFileId}:${row.sourceRow}`;
}

function savedColumnState(key: string): StoredColumnState | null {
  try {
    const saved = window.localStorage.getItem(key);
    return saved ? (JSON.parse(saved) as StoredColumnState) : null;
  } catch {
    return null;
  }
}

function persistColumnState(api: GridApi<BusinessRow>, storageKey: string) {
  try {
    window.localStorage.setItem(storageKey, JSON.stringify(api.getColumnState()));
  } catch {
    // A full or disabled localStorage should not interrupt table use.
  }
}

function statusTone(value: unknown) {
  const status = String(value ?? "");
  if (["approved", "active", "ready", "published", "in_use"].includes(status)) {
    return "business-status business-status-positive";
  }
  if (["changes_requested", "paused", "hold", "archived"].includes(status)) {
    return "business-status business-status-muted";
  }
  return "business-status business-status-pending";
}

export function BusinessDataTablesPage() {
  const { i18n } = useTranslation();
  const locale: Locale = i18n.language.toLowerCase().startsWith("zh") ? "zh" : "en";
  const copy = labels[locale];
  const { activeMembership } = useApplicationAuth();
  const { data: session } = useSession();
  const [activeTableKey, setActiveTableKey] = useState("RealProductResearch");
  const [searchValue, setSearchValue] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [matchCount, setMatchCount] = useState<number | null>(tables[0].rows.length);
  const [queryError, setQueryError] = useState(false);
  const [selectedRecord, setSelectedRecord] = useState<BusinessRow | null>(null);
  const [showJson, setShowJson] = useState(false);
  const [columnsOpen, setColumnsOpen] = useState(false);
  const [columnVersion, setColumnVersion] = useState(0);
  const gridRef = useRef<AgGridReact<BusinessRow>>(null);
  const searchInputRef = useRef<HTMLInputElement>(null);
  const columnsAnchorRef = useRef<HTMLDivElement>(null);
  const previousTableKey = useRef(activeTableKey);

  const activeTable = tables.find((table) => table.key === activeTableKey) ?? tables[0];
  const storageKey = [
    "business-data-columns-v1",
    activeMembership?.workspaceId ?? "workspace",
    session?.user?.id ?? "anonymous",
    activeTable.key,
  ].join(":");

  const gridTheme = useMemo<Theme>(
    () =>
      themeQuartz.withParams({
        accentColor: "var(--primary)",
        backgroundColor: "var(--card)",
        borderColor: "var(--border)",
        foregroundColor: "var(--card-foreground)",
        headerBackgroundColor: "var(--muted)",
        headerTextColor: "var(--foreground)",
        fontFamily: "inherit",
        fontSize: "12px",
        spacing: 8,
      }),
    []
  );

  const columnDefs = useMemo<ColDef<BusinessRow>[]>(
    () =>
      activeTable.fields.map((field) => ({
        cellDataType: field.type === "number" ? "number" : "text",
        field: field.field,
        filter: field.filterable
          ? field.type === "number"
            ? "agNumberColumnFilter"
            : "agTextColumnFilter"
          : false,
        filterParams: { debounceMs: 250 },
        headerName: fieldLabel(field, locale),
        initialHide: !field.defaultVisible,
        minWidth: 100,
        resizable: true,
        sortable: field.sortable,
        tooltipValueGetter: ({ value }) => String(value ?? ""),
        valueFormatter: ({ value }) => formatValue(value, field, locale),
        width: field.width,
        cellRenderer: statusFields.has(field.field)
          ? ({ value }: { value: unknown }) => (
              <span className={statusTone(value)}>{formatValue(value, field, locale, false)}</span>
            )
          : undefined,
      })),
    [activeTable, locale]
  );

  const datasource = useMemo<IDatasource>(() => {
    let destroyed = false;
    const pendingTimers = new Set<number>();
    const pendingRequests = new Set<AbortController>();
    let previousCriteria = "";
    let criteriaVersion = 0;

    return {
      getRows: (params: IGetRowsParams<BusinessRow>) => {
        if (activeTable.key === "ProductPrice") {
          const criteria = JSON.stringify({
            search: debouncedSearch,
            filterModel: params.filterModel,
            sortModel: params.sortModel,
          });
          if (criteria !== previousCriteria) {
            previousCriteria = criteria;
            criteriaVersion += 1;
            pendingRequests.forEach((request) => request.abort());
            pendingRequests.clear();
            setMatchCount(null);
          }
          const requestCriteriaVersion = criteriaVersion;
          setQueryError(false);
          const controller = new AbortController();
          pendingRequests.add(controller);
          const path = buildProductPriceRowsPath({
            workspaceId: activeMembership?.workspaceId,
            startRow: params.startRow,
            endRow: params.endRow,
            search: debouncedSearch,
            filterModel: params.filterModel,
            sortModel: params.sortModel,
          });
          void requestBackend<BusinessTableRowsResponse>(
            path,
            { signal: controller.signal },
            { timeoutMs: 30_000 }
          ).then((page) => {
            pendingRequests.delete(controller);
            if (
              destroyed ||
              controller.signal.aborted ||
              requestCriteriaVersion !== criteriaVersion
            ) return;
            setMatchCount(page.total);
            params.successCallback(page.rows, page.total);
          }).catch(() => {
            pendingRequests.delete(controller);
            if (
              destroyed ||
              controller.signal.aborted ||
              requestCriteriaVersion !== criteriaVersion
            ) return;
            setQueryError(true);
            params.failCallback();
          });
          return;
        }

        const timer = window.setTimeout(() => {
          pendingTimers.delete(timer);
          if (destroyed) return;

          try {
            const result = queryMockRows(activeTable.rows, {
              startRow: params.startRow,
              endRow: params.endRow,
              search: debouncedSearch,
              filterModel: params.filterModel,
              sortModel: params.sortModel,
            });
            setMatchCount(result.total);
            params.successCallback(result.rows, result.total);
          } catch {
            params.failCallback();
          }
        }, 180);
        pendingTimers.add(timer);
      },
      destroy: () => {
        destroyed = true;
        pendingTimers.forEach((timer) => window.clearTimeout(timer));
        pendingTimers.clear();
        pendingRequests.forEach((controller) => controller.abort());
        pendingRequests.clear();
      },
    };
  }, [activeMembership?.workspaceId, activeTable, debouncedSearch]);

  const orderedColumnState = useMemo(() => {
    const state = gridRef.current?.api.getColumnState() ?? [];
    const fieldByName = new Map(activeTable.fields.map((field) => [field.field, field]));
    const stateFields = new Set(state.map((column) => column.colId));
    const ordered: OrderedColumn[] = [
      ...state.flatMap((column) => {
        const field = fieldByName.get(column.colId);
        return field ? [{ field, state: column }] : [];
      }),
      ...activeTable.fields
        .filter((field) => !stateFields.has(field.field))
        .map((field): OrderedColumn => ({
          field,
          state: { colId: field.field, hide: !field.defaultVisible, pinned: null },
        })),
    ];
    return ordered;
  // Column state is managed by AG Grid; this version counter tells React when the drawer changed it.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTable, columnVersion]);

  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedSearch(searchValue.trim()), 260);
    return () => window.clearTimeout(timer);
  }, [searchValue]);

  useEffect(() => {
    if (!columnsOpen) return;

    const closeOnOutsidePointer = (event: PointerEvent) => {
      if (event.target instanceof Node && !columnsAnchorRef.current?.contains(event.target)) {
        setColumnsOpen(false);
      }
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setColumnsOpen(false);
    };

    document.addEventListener("pointerdown", closeOnOutsidePointer);
    window.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("pointerdown", closeOnOutsidePointer);
      window.removeEventListener("keydown", closeOnEscape);
    };
  }, [columnsOpen]);

  useEffect(() => {
    if (previousTableKey.current === activeTable.key) return;
    previousTableKey.current = activeTable.key;
    setSelectedRecord(null);
    setShowJson(false);
    setMatchCount(activeTable.key === "ProductPrice" ? null : activeTable.rows.length);
    setQueryError(false);
    setSearchValue("");
    setDebouncedSearch("");

    const api = gridRef.current?.api;
    if (!api) return;
    api.setFilterModel(null);
    api.resetColumnState();
    const state = savedColumnState(storageKey);
    if (state) api.applyColumnState({ state, applyOrder: true });
    setColumnVersion((version) => version + 1);
  }, [activeTable, storageKey]);

  const onGridReady = useCallback((event: GridReadyEvent<BusinessRow>) => {
    const state = savedColumnState(storageKey);
    if (state) event.api.applyColumnState({ state, applyOrder: true });
  }, [storageKey]);

  const updateColumnPrefs = useCallback(() => {
    const api = gridRef.current?.api;
    if (!api) return;
    persistColumnState(api, storageKey);
    setColumnVersion((version) => version + 1);
  }, [storageKey]);

  const openRelatedProduct = useCallback((researchId: unknown) => {
    const id = String(researchId ?? "");
    setActiveTableKey("RealProductResearch");
    setSearchValue(id);
    setDebouncedSearch(id);
    setSelectedRecord(null);
  }, []);

  const resetFilters = useCallback(() => {
    setSearchValue("");
    setDebouncedSearch("");
    gridRef.current?.api.setFilterModel(null);
  }, []);

  const selectTable = useCallback((table: BusinessTable) => {
    setActiveTableKey(table.key);
    setSearchValue("");
    setDebouncedSearch("");
    setSelectedRecord(null);
    setColumnsOpen(false);
    setMatchCount(table.key === "ProductPrice" ? null : table.rows.length);
    setQueryError(false);
  }, []);

  const onGridColumnStateChanged = useCallback(() => {
    const api = gridRef.current?.api;
    if (!api) return;
    persistColumnState(api, storageKey);
    setColumnVersion((version) => version + 1);
  }, [storageKey]);

  const setColumnVisible = useCallback((field: string, visible: boolean) => {
    gridRef.current?.api.setColumnsVisible([field], visible);
    updateColumnPrefs();
  }, [updateColumnPrefs]);

  const moveColumn = useCallback((field: string, direction: -1 | 1) => {
    const api = gridRef.current?.api;
    if (!api) return;
    const state = api.getColumnState();
    const index = state.findIndex((item) => item.colId === field);
    const targetIndex = index + direction;
    if (index < 0 || targetIndex < 0 || targetIndex >= state.length) return;
    [state[index], state[targetIndex]] = [state[targetIndex], state[index]];
    api.applyColumnState({ state, applyOrder: true });
    updateColumnPrefs();
  }, [updateColumnPrefs]);

  const setColumnPinned = useCallback((field: string, value: string) => {
    const pinned = value === "left" || value === "right" ? value : null;
    gridRef.current?.api.applyColumnState({
      state: [{ colId: field, pinned }],
    });
    updateColumnPrefs();
  }, [updateColumnPrefs]);

  const resetColumns = useCallback(() => {
    const api = gridRef.current?.api;
    if (!api) return;
    api.resetColumnState();
    try {
      window.localStorage.removeItem(storageKey);
    } catch {
      // Ignore unavailable localStorage; the grid reset has already succeeded.
    }
    setColumnVersion((version) => version + 1);
  }, [storageKey]);

  const selectedFields = useMemo(
    () => selectedRecord
      ? activeTable.fields.filter((field) => Object.hasOwn(selectedRecord, field.field))
      : [],
    [activeTable, selectedRecord]
  );

  const productGroup = tables.filter((table) => table.category === "product");
  const contentGroup = tables.filter((table) => table.category === "content");

  return (
    <main className="business-data-page min-h-dvh bg-background px-4 py-6 text-foreground md:px-8 md:py-8">
      <div className="mx-auto flex w-full max-w-[1680px] flex-col gap-5">
        <header className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="mb-2 flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
              <DatabaseIcon aria-hidden="true" className="size-3.5" />
              <span>{locale === "zh" ? "Asianode · 数据浏览" : "Asianode · Data explorer"}</span>
            </div>
            <h1 className="m-0 text-2xl font-semibold tracking-tight text-foreground md:text-[28px]">
              {copy.title}
            </h1>
            <p className="mt-1.5 text-sm text-muted-foreground">{copy.subtitle}</p>
          </div>
          <span className="business-mock-badge">
            <span aria-hidden="true" className="size-1.5 rounded-full bg-current" />
            {activeTable.key === "ProductPrice" ? copy.connected : copy.preview}
          </span>
        </header>

        <section aria-label={locale === "zh" ? "业务表选择" : "Business table selector"} className="flex flex-col gap-3">
          <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
            <span>{copy.productGroup}</span>
            <span aria-hidden="true" className="h-px flex-1 bg-border" />
          </div>
          <div className="flex flex-wrap gap-2">
            {productGroup.map((table) => (
              <TableButton
                active={table.key === activeTable.key}
                key={table.key}
                locale={locale}
                onClick={() => selectTable(table)}
                table={table}
              />
            ))}
          </div>
          <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
            <span>{copy.contentGroup}</span>
            <span aria-hidden="true" className="h-px flex-1 bg-border" />
          </div>
          <div className="flex flex-wrap gap-2">
            {contentGroup.map((table) => (
              <TableButton
                active={table.key === activeTable.key}
                key={table.key}
                locale={locale}
                onClick={() => selectTable(table)}
                table={table}
              />
            ))}
          </div>
        </section>

        <div className="flex items-start gap-2 rounded-lg border border-primary/10 bg-primary/[0.035] px-3 py-2.5 text-xs text-muted-foreground">
          <span aria-hidden="true" className="mt-1 size-1.5 shrink-0 rounded-full bg-primary/60" />
          <span>{activeTable.key === "ProductPrice" ? copy.apiNote : copy.previewNote}</span>
          <span className="ml-auto shrink-0 font-mono text-[10px] tracking-wide text-muted-foreground/70">
            {activeTable.key === "ProductPrice" ? copy.apiBadge : copy.mockBadge}
          </span>
        </div>

        <section className="overflow-hidden rounded-xl border border-border bg-card shadow-[var(--shadow-card)]">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-3 py-3 md:px-4">
            <div className="relative min-w-[220px] flex-1 sm:max-w-[420px]">
              <SearchIcon aria-hidden="true" className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
              <input
                aria-label={copy.searchLabel}
                className="h-9 w-full rounded-md border border-input bg-background pl-9 pr-9 text-sm text-foreground outline-none transition-shadow placeholder:text-muted-foreground/70 focus-visible:ring-2 focus-visible:ring-ring/40"
                onChange={(event) => setSearchValue(event.target.value)}
                placeholder={copy.searchPlaceholder}
                ref={searchInputRef}
                type="search"
                value={searchValue}
              />
              {searchValue ? (
                <button
                  aria-label={copy.close}
                  className="absolute right-2 top-1/2 grid size-6 -translate-y-1/2 place-items-center rounded text-muted-foreground hover:bg-muted hover:text-foreground"
                  onClick={() => { setSearchValue(""); searchInputRef.current?.focus(); }}
                  type="button"
                >
                  <XIcon className="size-3.5" />
                </button>
              ) : null}
            </div>

            <div className="flex flex-wrap items-center gap-2">
              <span className="hidden items-center gap-1.5 text-xs text-muted-foreground xl:flex">
                <FilterXIcon aria-hidden="true" className="size-3.5" />
                {copy.filters}
              </span>
              <button
                className="business-toolbar-button"
                onClick={resetFilters}
                type="button"
              >
                <FilterXIcon aria-hidden="true" className="size-3.5" />
                <span>{copy.clearFilters}</span>
              </button>
              <button
                aria-label={copy.refresh}
                className="business-toolbar-button business-icon-button"
                onClick={() => {
                  setMatchCount(activeTable.key === "ProductPrice" ? null : activeTable.rows.length);
                  setQueryError(false);
                  gridRef.current?.api.purgeInfiniteCache();
                }}
                title={copy.refresh}
                type="button"
              >
                <RefreshCwIcon aria-hidden="true" className="size-3.5" />
              </button>

              <div className="relative" ref={columnsAnchorRef}>
                <button
                  aria-expanded={columnsOpen}
                  aria-label={copy.columnSettings}
                  className={`business-toolbar-button ${columnsOpen ? "business-toolbar-button-active" : ""}`}
                  onClick={() => setColumnsOpen((open) => !open)}
                  type="button"
                >
                  <Columns3Icon aria-hidden="true" className="size-3.5" />
                  <span>{copy.columns}</span>
                  <ChevronDownIcon aria-hidden="true" className={`size-3 transition-transform ${columnsOpen ? "rotate-180" : ""}`} />
                </button>
                {columnsOpen ? (
                  <div className="business-columns-panel" role="dialog" aria-label={copy.columnSettings}>
                    <div className="flex items-center justify-between border-b border-border px-3 py-2.5">
                      <div>
                        <p className="text-xs font-semibold text-foreground">{copy.columns}</p>
                        <p className="mt-0.5 text-[11px] text-muted-foreground">{activeTable.fields.length} {locale === "zh" ? "个字段" : "fields"}</p>
                      </div>
                      <button className="business-text-button" onClick={resetColumns} type="button">{copy.resetColumns}</button>
                    </div>
                    <div className="max-h-[360px] overflow-y-auto p-1.5">
                      {orderedColumnState.map(({ field, state }, index) => (
                        <div className="business-column-row" key={field.field}>
                          <label className="flex min-w-0 flex-1 items-center gap-2 text-xs text-foreground">
                            <input
                              checked={!state.hide}
                              className="size-3.5 accent-[var(--primary)]"
                              onChange={(event) => setColumnVisible(field.field, event.target.checked)}
                              type="checkbox"
                            />
                            <span className="truncate">{fieldLabel(field, locale)}</span>
                          </label>
                          <div className="flex items-center gap-0.5">
                            <button
                              aria-label={`${copy.moveUp}: ${fieldLabel(field, locale)}`}
                              className="business-mini-button"
                              disabled={index === 0}
                              onClick={() => moveColumn(field.field, -1)}
                              type="button"
                            ><ArrowUpIcon className="size-3" /></button>
                            <button
                              aria-label={`${copy.moveDown}: ${fieldLabel(field, locale)}`}
                              className="business-mini-button"
                              disabled={index === orderedColumnState.length - 1}
                              onClick={() => moveColumn(field.field, 1)}
                              type="button"
                            ><ArrowDownIcon className="size-3" /></button>
                            <select
                              aria-label={`${copy.pin}: ${fieldLabel(field, locale)}`}
                              className="business-pin-select"
                              onChange={(event) => setColumnPinned(field.field, event.target.value)}
                              value={state.pinned === "left" || state.pinned === "right" ? state.pinned : ""}
                            >
                              <option value="">{copy.unpinned}</option>
                              <option value="left">{copy.pinLeft}</option>
                              <option value="right">{copy.pinRight}</option>
                            </select>
                          </div>
                        </div>
                      ))}
                    </div>
                    <div className="border-t border-border px-3 py-2 text-[10px] text-muted-foreground">
                      {locale === "zh" ? "拖动表头也可以调整列顺序和宽度。" : "Drag a header to reorder columns or resize it."}
                    </div>
                  </div>
                ) : null}
              </div>
            </div>
          </div>

          {activeTable.columnSource === "documented-fields-only" ? (
            <div className="border-b border-border bg-muted/35 px-4 py-2 text-xs text-muted-foreground">
              {copy.sourceMetadata}
            </div>
          ) : null}

          {queryError ? (
            <div className="flex items-center justify-between gap-3 border-b border-destructive/20 bg-destructive/5 px-4 py-2 text-xs text-destructive" role="alert">
              <span>{copy.loadError}</span>
              <button
                className="business-toolbar-button"
                onClick={() => {
                  setQueryError(false);
                  gridRef.current?.api.purgeInfiniteCache();
                }}
                type="button"
              >
                <RefreshCwIcon aria-hidden="true" className="size-3.5" />
                <span>{copy.retry}</span>
              </button>
            </div>
          ) : null}

          <div className="business-data-grid h-[min(68vh,760px)] min-h-[420px] w-full">
            <AgGridProvider modules={modules}>
              <AgGridReact<BusinessRow>
                animateRows={false}
                cacheBlockSize={30}
                cacheOverflowSize={1}
                columnDefs={columnDefs}
                datasource={datasource}
        defaultColDef={{ floatingFilter: true, resizable: true, sortable: true, suppressMovable: false }}
                getRowId={({ data }) => `${activeTable.key}:${rowKey(activeTable, data)}`}
                infiniteInitialRowCount={activeTable.key === "ProductPrice" ? 30 : Math.min(activeTable.rows.length, 30)}
                maxBlocksInCache={8}
                maxConcurrentDatasourceRequests={1}
                onColumnMoved={onGridColumnStateChanged}
                onColumnPinned={onGridColumnStateChanged}
                onColumnResized={(event) => { if (event.finished) onGridColumnStateChanged(); }}
                onColumnVisible={onGridColumnStateChanged}
                onGridReady={onGridReady}
                onRowClicked={({ data }) => {
                  if (data) {
                    setSelectedRecord(data);
                    setShowJson(false);
                  }
                }}
                rowBuffer={8}
                rowHeight={42}
                rowModelType="infinite"
                suppressCellFocus={false}
                suppressMultiSort
                theme={gridTheme}
                localeText={{ noRowsToShow: copy.noRowsGrid }}
              />
            </AgGridProvider>
          </div>

          <footer className="flex flex-wrap items-center justify-between gap-2 border-t border-border px-4 py-2.5 text-[11px] text-muted-foreground">
            <span className="font-medium text-foreground">{locale === "zh" ? activeTable.labelZh : activeTable.labelEn} <span className="font-mono font-normal text-muted-foreground">· {activeTable.key}</span></span>
            <div className="flex items-center gap-3">
              <span>{copy.loaded}: {matchCount ?? "—"} {copy.rows}</span>
              <span aria-hidden="true" className="size-1 rounded-full bg-border" />
              <span>{copy.clickRow}</span>
            </div>
          </footer>
        </section>
      </div>

      <Sheet open={Boolean(selectedRecord)} onOpenChange={(open) => { if (!open) setSelectedRecord(null); }}>
        <SheetContent className="sm:max-w-xl" side="right">
          {selectedRecord ? (
            <>
              <SheetHeader className="border-b border-border pr-14">
                <div className="mb-1 flex items-center gap-2 text-[10px] font-semibold uppercase tracking-[0.16em] text-muted-foreground">
                  <span>{activeTable.labelZh}</span>
                  <span aria-hidden="true">/</span>
                  <span>{activeTable.key}</span>
                </div>
                <SheetTitle>{copy.detail}</SheetTitle>
                <SheetDescription>
                  {activeTable.key === "ProductPrice" ? copy.databaseRecord : copy.mockRecord}
                  {" · "}{rowKey(activeTable, selectedRecord)}
                </SheetDescription>
                <div className="mt-3 flex gap-1 rounded-lg bg-muted p-1">
                  <button className={`business-detail-tab ${!showJson ? "business-detail-tab-active" : ""}`} onClick={() => setShowJson(false)} type="button">{copy.fieldsView}</button>
                  <button className={`business-detail-tab ${showJson ? "business-detail-tab-active" : ""}`} onClick={() => setShowJson(true)} type="button">{copy.jsonView}</button>
                </div>
              </SheetHeader>

              <div className="flex-1 overflow-y-auto px-6 py-4">
                {showJson ? (
                  <pre className="overflow-x-auto rounded-lg border border-border bg-muted/45 p-4 font-mono text-xs leading-6 text-foreground">
                    {JSON.stringify(selectedRecord, null, 2)}
                  </pre>
                ) : (
                  <dl className="space-y-4">
                    {selectedFields.map((field) => {
                      const value = selectedRecord[field.field];
                      const isLongValue = field.longText && typeof value === "string";
                      return (
                        <div className="business-detail-field" key={field.field}>
                          <dt>{fieldLabel(field, locale)} <code>{field.field}</code></dt>
                          <dd className={isLongValue ? "business-long-value" : ""}>
                            {isLongValue
                              ? String(value)
                              : formatValue(value, field, locale, false)}
                          </dd>
                        </div>
                      );
                    })}
                  </dl>
                )}

                {activeTable.key !== "RealProductResearch" && activeTable.key !== "ProductPrice" && selectedRecord.researchId ? (
                  <div className="mt-6 rounded-lg border border-border bg-muted/35 p-3.5">
                    <div className="mb-2 text-[11px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">{copy.relation}</div>
                    <div className="flex items-center justify-between gap-3">
                      <code className="text-xs">{String(selectedRecord.researchId)}</code>
                      <button className="business-toolbar-button" onClick={() => openRelatedProduct(selectedRecord.researchId)} type="button">
                        <span>{copy.openProduct}</span>
                        <ExternalLinkIcon aria-hidden="true" className="size-3.5" />
                      </button>
                    </div>
                  </div>
                ) : null}
              </div>
            </>
          ) : null}
        </SheetContent>
      </Sheet>
    </main>
  );
}

function TableButton({
  active,
  locale,
  onClick,
  table,
}: {
  active: boolean;
  locale: Locale;
  onClick: () => void;
  table: BusinessTable;
}) {
  return (
    <button
      aria-pressed={active}
      className={`business-table-button ${active ? "business-table-button-active" : ""}`}
      onClick={onClick}
      title={locale === "zh" ? table.descriptionZh : table.descriptionEn}
      type="button"
    >
      <span className="min-w-0 text-left">
        <span className="block truncate text-[13px] font-medium">{locale === "zh" ? table.labelZh : table.labelEn}</span>
        <span className="mt-0.5 block truncate font-mono text-[10px] text-muted-foreground">{table.key}</span>
      </span>
      {active ? <CheckIcon aria-hidden="true" className="size-4 shrink-0" /> : null}
      <span className="sr-only">{table.rows.length} {labels[locale].rows}</span>
    </button>
  );
}
