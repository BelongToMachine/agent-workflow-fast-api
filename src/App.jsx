import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Toaster } from "sonner";
import { AppSidebar } from "./components/chat/appSidebar";
import { ChatPage } from "./components/chat/chatPage";
import { DataStreamProvider } from "./components/chat/dataStreamProvider";
import { Preview } from "./components/chat/preview";
import { BackendQueryProvider } from "./components/backendQueryProvider";
import { AuthProvider, useSession } from "./lib/auth";
import {
  ApplicationAuthProvider,
  useApplicationAuth,
} from "./lib/auth/applicationAuth";
import { LocalAuthRequestError, signInWithLocalSession } from "./lib/auth/localSession";
import { ThemeProvider } from "./components/themeProvider";
import { TooltipProvider } from "./components/ui/tooltip";
import { LoadingState } from "./components/ui/loadingState";
import { SidebarInset, SidebarProvider } from "./components/ui/sidebar";
import { KnowledgeBaseFiles } from "./components/settings/knowledgeBaseFiles";
import { KnowledgeBaseGrants } from "./components/settings/knowledgeBaseGrants";
import { MemberPermissions } from "./components/settings/memberPermissions";
import { AppearanceSettings } from "./components/settings/appearanceSettings";
import { FastApiConnectionTest } from "./components/fastapiConnectionTest";
import { UploadPage } from "./components/upload/uploadPage";
import {
  LocalActivationPage,
  LocalChangePasswordPage,
} from "./components/auth/localAccountPages";
import { Link, usePathname, useRouter } from "./lib/router";
import { applyAccentColor, getStoredAccentColor } from "./lib/accentColor";

function isKnownRoute(pathname) {
  if (
    pathname === "/" ||
    pathname === "/activate" ||
    pathname === "/access-pending" ||
    pathname === "/account-suspended" ||
    pathname === "/fastapi-test" ||
    pathname === "/forbidden" ||
    pathname === "/forgot-password" ||
    pathname === "/login" ||
    pathname === "/register" ||
    pathname === "/upload" ||
    pathname === "/reset-password" ||
    pathname === "/settings/knowledge-bases" ||
    pathname === "/settings/knowledge-bases/files" ||
    pathname === "/settings/members" ||
    pathname === "/settings/password" ||
    pathname === "/settings/appearance"
  ) {
    return true;
  }

  return /^\/chat\/[^/]+$/.test(pathname);
}

function NotFoundPage() {
  const router = useRouter();
  const { t } = useTranslation();

  return (
    <main
      aria-labelledby="not-found-title"
      className="relative isolate flex min-h-dvh items-center overflow-hidden bg-background px-6 py-12 text-foreground"
    >
      <div
        aria-hidden="true"
        className="pointer-events-none absolute -right-48 -top-48 h-[34rem] w-[34rem] rounded-full border border-border/60"
      />
      <div
        aria-hidden="true"
        className="pointer-events-none absolute -bottom-56 -left-48 h-[28rem] w-[28rem] rounded-full border border-border/40"
      />
      <div className="relative mx-auto grid w-full max-w-5xl items-center gap-12 lg:grid-cols-[minmax(0,1fr)_minmax(20rem,0.8fr)] lg:gap-20">
        <section className="max-w-xl">
          <div className="flex items-center gap-3 text-[11px] font-semibold uppercase tracking-[0.22em] text-muted-foreground">
            <span aria-hidden="true" className="h-2 w-2 rounded-full bg-foreground" />
            {t("app.name")}
          </div>
          <p className="mt-12 text-xs font-medium uppercase tracking-[0.2em] text-muted-foreground">
            {t("app.error404")}
          </p>
          <h1
            className="mt-4 max-w-lg text-balance text-4xl font-semibold tracking-[-0.04em] sm:text-5xl"
            id="not-found-title"
          >
            {t("app.notFoundTitle")}
          </h1>
          <p className="mt-5 max-w-md text-sm leading-7 text-muted-foreground sm:text-base">
            {t("app.notFoundDescription")}
          </p>
          <div className="mt-9 flex flex-wrap items-center gap-3">
            <Link
              className="inline-flex h-10 items-center rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground transition-opacity hover:opacity-90"
              href="/"
            >
              {t("common.backToWorkspace")}
            </Link>
            <button
              className="inline-flex h-10 items-center rounded-md border border-border px-4 text-sm font-medium transition-colors hover:bg-muted"
              onClick={() => router.back()}
              type="button"
            >
              {t("common.previousPage")}
            </button>
          </div>
        </section>

        <section
          aria-hidden="true"
          className="relative min-h-[18rem] overflow-hidden rounded-[2rem] border border-border/60 bg-card/50 px-8 py-10 shadow-[var(--shadow-card)] sm:min-h-[22rem]"
        >
          <div className="absolute inset-x-8 top-8 flex items-center justify-between border-b border-border/60 pb-3 text-[10px] font-medium uppercase tracking-[0.18em] text-muted-foreground">
            <span>{t("app.routeStatus")}</span>
            <span>{t("app.missing")}</span>
          </div>
          <div className="absolute inset-x-8 bottom-8 flex items-end justify-between gap-6">
            <span className="text-[clamp(9rem,22vw,15rem)] font-semibold leading-[0.72] tracking-[-0.12em] text-foreground/[0.07]">
              404
            </span>
            <span className="mb-1 max-w-[7rem] text-right font-mono text-[10px] leading-5 text-muted-foreground">
              {t("app.requestedRouteMissing")}
            </span>
          </div>
        </section>
      </div>
    </main>
  );
}

function AuthGuard({ children }) {
  const { status } = useSession();
  const pathname = usePathname();
  const { t } = useTranslation();

  const isPublicAuthRoute =
    pathname === "/activate" ||
    pathname === "/forgot-password" ||
    pathname === "/login" ||
    pathname === "/register" ||
    pathname === "/reset-password";

  if (isPublicAuthRoute) {
    return children;
  }

  if (status === "loading") {
    return <LoadingState message={t("app.loadingAuth")} />;
  }

  if (status === "unauthenticated") {
    if (!isKnownRoute(pathname)) {
      return <NotFoundPage />;
    }
    return <Navigate replace to="/login" />;
  }

  return children;
}

function ChatLayout() {
  const { t } = useTranslation();
  const { data } = useSession();
  const {
    error: accessError,
    hasPermission,
    refreshCurrentUser,
    status: authStatus,
  } = useApplicationAuth();
  const user = data?.user;

  if (authStatus === "loading" || authStatus === "initializing") {
    return <LoadingState message={t("app.loadingAccess")} />;
  }

  if (authStatus === "unauthenticated") {
    return <Navigate replace to="/login" />;
  }

  if (authStatus === "suspended") {
    return <Navigate replace to="/account-suspended" />;
  }

  if (authStatus === "pending_workspace") {
    return <Navigate replace to="/access-pending" />;
  }

  if (authStatus === "error" && accessError) {
    return (
      <div className="flex min-h-dvh items-center justify-center bg-background px-6 text-center">
        <div className="max-w-md">
          <h1 className="font-semibold text-xl">{t("app.unableToLoadAccess")}</h1>
          <p className="mt-2 text-muted-foreground text-sm leading-6">
            {t("app.accessLoadDescription")}
          </p>
          <button
            className="mt-5 rounded-md border border-border px-3 py-2 text-sm font-medium transition-colors hover:bg-muted"
            onClick={() => void refreshCurrentUser()}
            type="button"
          >
            {t("app.retry")}
          </button>
        </div>
      </div>
    );
  }

  return (
    <DataStreamProvider>
      <SidebarProvider defaultOpen>
        <AppSidebar
          canManageKnowledgeBases={
            authStatus === "authenticated" && hasPermission("knowledge.manage")
          }
          canViewPermissions={
            authStatus === "authenticated" && hasPermission("members.read")
          }
          user={user}
        />
        <SidebarInset>
          <Toaster
            position="top-center"
            theme="system"
            toastOptions={{
              className:
                "!bg-card !text-foreground !border-border/50 !shadow-[var(--shadow-float)]",
            }}
          />
          <Routes>
            <Route element={<ChatPage />} index />
            <Route element={<ChatPage />} path="chat/:id" />
            <Route
              element={
                <PermissionRoute permission="members.read">
                  <SettingsPage titleKey="settings.workspacePermissions">
                    <MemberPermissions />
                  </SettingsPage>
                </PermissionRoute>
              }
              path="settings/members"
            />
            <Route
              element={
                <PermissionRoute permission="knowledge.manage">
                  <SettingsPage titleKey="settings.knowledgeBaseAccess">
                    <KnowledgeBaseGrants />
                  </SettingsPage>
                </PermissionRoute>
              }
              path="settings/knowledge-bases"
            />
            <Route
              element={
                <PermissionRoute permission="knowledge.manage">
                  <UploadPage />
                </PermissionRoute>
              }
              path="upload"
            />
            <Route
              element={
                <PermissionRoute permission="knowledge.manage">
                  <SettingsPage titleKey="settings.knowledgeBaseFiles">
                    <KnowledgeBaseFiles />
                  </SettingsPage>
                </PermissionRoute>
              }
              path="settings/knowledge-bases/files"
            />
            <Route
              element={
                <SettingsPage
                  descriptionKey="settings.accentColorPageDescription"
                  titleKey="settings.accentColor"
                >
                  <AppearanceSettings />
                </SettingsPage>
              }
              path="settings/appearance"
            />
            <Route
              element={<SettingsPage titleKey="settings.fastApiConnection"><FastApiConnectionTest /></SettingsPage>}
              path="fastapi-test"
            />
            <Route
              element={
                <SettingsPage titleKey="auth.changePassword">
                  <LocalChangePasswordPage />
                </SettingsPage>
              }
              path="settings/password"
            />
            <Route element={<NotFoundPage />} path="*" />
          </Routes>
        </SidebarInset>
      </SidebarProvider>
    </DataStreamProvider>
  );
}

function AccentColorSync() {
  useEffect(() => {
    applyAccentColor(getStoredAccentColor());
  }, []);

  return null;
}

function WorkspaceAccessPendingPage() {
  const { t } = useTranslation();
  return (
    <div className="flex min-h-dvh items-center justify-center bg-background px-6 text-center">
      <div className="max-w-md">
        <h1 className="font-semibold text-xl">{t("app.accountCreated")}</h1>
        <p className="mt-2 text-muted-foreground text-sm leading-6">
          {t("app.accountCreatedDescription")}
        </p>
      </div>
    </div>
  );
}

function AccountSuspendedPage() {
  const { signOut } = useApplicationAuth();
  const { t } = useTranslation();

  return (
    <div className="flex min-h-dvh items-center justify-center bg-background px-6 text-center">
      <div className="max-w-md">
        <h1 className="font-semibold text-xl">{t("app.accountSuspended")}</h1>
        <p className="mt-2 text-muted-foreground text-sm leading-6">
          {t("app.accountSuspendedDescription")}
        </p>
        <button
          className="mt-5 rounded-md border border-border px-3 py-2 text-sm font-medium transition-colors hover:bg-muted"
          onClick={() => void signOut()}
          type="button"
        >
          {t("sidebar.signOut")}
        </button>
      </div>
    </div>
  );
}

function PasswordHelpPage() {
  const { t } = useTranslation();
  return (
    <div className="flex min-h-dvh w-full items-center justify-center bg-background px-6 text-center">
      <div className="max-w-md">
        <h1 className="font-semibold text-xl">{t("auth.noPasswordReset")}</h1>
        <p className="mt-2 text-muted-foreground text-sm leading-6">
          {t("auth.contactAdmin")}
        </p>
        <Link
          className="mt-5 inline-flex rounded-md border border-border px-3 py-2 text-sm font-medium transition-colors hover:bg-muted"
          href="/login"
        >
          {t("auth.backToSignIn")}
        </Link>
      </div>
    </div>
  );
}

function ForbiddenPage() {
  const { t } = useTranslation();
  return (
    <div className="flex min-h-dvh items-center justify-center bg-background px-6 text-center">
      <div className="max-w-md">
        <h1 className="font-semibold text-xl">{t("app.permissionRequired")}</h1>
        <p className="mt-2 text-muted-foreground text-sm leading-6">
          {t("app.permissionRequiredDescription")}
        </p>
      </div>
    </div>
  );
}

function PermissionRoute({ children, permission }) {
  const { hasPermission, status } = useApplicationAuth();
  const { t } = useTranslation();

  if (status === "loading" || status === "initializing") {
    return <LoadingState message={t("app.loadingAccess")} />;
  }

  if (status === "suspended") {
    return <Navigate replace to="/account-suspended" />;
  }

  if (status === "pending_workspace") {
    return <Navigate replace to="/access-pending" />;
  }

  if (!hasPermission(permission)) {
    return <ForbiddenPage />;
  }

  return children;
}

function SettingsPage({
  children,
  descriptionKey = "settings.manageDescription",
  titleKey,
}) {
  const { t } = useTranslation();
  return (
    <main className="min-h-dvh overflow-y-auto bg-background px-4 py-8 md:px-8">
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-6">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">{t(titleKey)}</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            {t(descriptionKey)}
          </p>
        </div>
        {children}
      </div>
    </main>
  );
}

function AuthPage({ mode }) {
  return <LocalSessionAuthPage mode={mode} />;
}

function LocalSessionAuthPage({ mode }) {
  const router = useRouter();
  const { update } = useSession();
  const { t } = useTranslation();
  const isLogin = mode === "login";
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");

  async function handleSubmit(event) {
    event.preventDefault();
    if (!isLogin) {
      return;
    }

    setErrorMessage("");
    setIsSubmitting(true);
    try {
      await signInWithLocalSession(email, password);
      await update();
      router.replace("/");
    } catch (error) {
      setErrorMessage(
        error instanceof LocalAuthRequestError && error.status === 401
          ? t("auth.emailOrPasswordIncorrect")
          : t("auth.unableToSignIn")
      );
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className="flex min-h-dvh w-full bg-sidebar">
      <div className="flex w-full flex-col bg-background p-8 md:p-16 xl:w-[600px] xl:shrink-0 xl:rounded-r-2xl xl:border-r xl:border-border/40">
        <div className="mx-auto w-full max-w-md">
          <div className="flex items-center gap-2.5">
            <span
              aria-hidden="true"
              className="size-2.5 rounded-full bg-primary"
            />
            <p className="text-[11px] font-semibold uppercase tracking-[0.22em] text-muted-foreground">
              {t("auth.productEyebrow")}
            </p>
          </div>
          <h1 className="mt-4 text-3xl font-semibold tracking-[-0.04em] text-foreground md:text-4xl">
            Asianode Copilot
          </h1>
          <p className="mt-4 max-w-sm text-sm leading-6 text-muted-foreground">
            {t("auth.productDescription")}
          </p>
        </div>
        <div className="mx-auto flex w-full max-w-md flex-1 flex-col justify-center gap-8">
          <div>
            <h2 className="text-2xl font-semibold tracking-tight">
              {isLogin ? t("auth.welcomeBack") : t("auth.invitationRequired")}
            </h2>
            <p className="mt-2 text-sm text-muted-foreground">
              {isLogin
                ? t("auth.signInOrganization")
                : t("auth.invitationOnly")}
            </p>
          </div>
          {errorMessage ? (
            <div
              aria-live="polite"
              className="rounded-lg border border-destructive/30 bg-destructive/10 px-4 py-3 text-destructive text-sm"
              role="alert"
            >
              {errorMessage}
            </div>
          ) : null}
          {isLogin ? (
            <form className="flex flex-col gap-4" onSubmit={handleSubmit}>
              <label className="flex flex-col gap-2 text-sm font-medium">
                {t("auth.email")}
                <input
                  autoComplete="email"
                  className="h-10 rounded-md border border-input bg-background px-3 text-sm outline-none focus:ring-2 focus:ring-ring"
                  onChange={(event) => setEmail(event.target.value)}
                  required
                  type="email"
                  value={email}
                />
              </label>
              <label className="flex flex-col gap-2 text-sm font-medium">
                {t("auth.password")}
                <input
                  autoComplete="current-password"
                  className="h-10 rounded-md border border-input bg-background px-3 text-sm outline-none focus:ring-2 focus:ring-ring"
                  minLength={12}
                  onChange={(event) => setPassword(event.target.value)}
                  required
                  type="password"
                  value={password}
                />
              </label>
              <button
                className="h-10 rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60"
                disabled={isSubmitting}
                type="submit"
              >
                {isSubmitting ? t("auth.signingIn") : t("auth.signIn")}
              </button>
              <p className="text-center text-[13px] text-muted-foreground">
                {t("auth.forgotPassword")}
              </p>
            </form>
          ) : null}
          {isLogin ? (
            <p className="text-center text-[13px] text-muted-foreground">
              {t("auth.needAccess")}
            </p>
          ) : (
            <button
              className="h-10 rounded-md border border-border px-4 text-sm font-medium transition-colors hover:bg-muted"
              onClick={() => router.replace("/login")}
              type="button"
            >
              {t("auth.backToSignIn")}
            </button>
          )}
        </div>
      </div>
      <div className="hidden flex-1 overflow-hidden pl-12 pt-8 xl:block">
        <Preview />
      </div>
    </div>
  );
}

function App() {
  return (
    <BrowserRouter>
      <AuthGuard>
        <Routes>
          <Route element={<LocalActivationPage />} path="/activate" />
          <Route element={<PasswordHelpPage />} path="/forgot-password" />
          <Route element={<PasswordHelpPage />} path="/reset-password" />
          <Route element={<WorkspaceAccessPendingPage />} path="/access-pending" />
          <Route element={<AccountSuspendedPage />} path="/account-suspended" />
          <Route element={<ForbiddenPage />} path="/forbidden" />
          <Route element={<ChatLayout />} path="/*" />
          <Route element={<AuthPage mode="login" />} path="/login" />
          <Route element={<AuthPage mode="register" />} path="/register" />
        </Routes>
      </AuthGuard>
    </BrowserRouter>
  );
}

export default function AppRoot() {
  return (
    <BackendQueryProvider>
      <AuthProvider>
        <ApplicationAuthProvider>
          <ThemeProvider attribute="class" defaultTheme="system" enableSystem>
            <AccentColorSync />
            <TooltipProvider>
              <App />
            </TooltipProvider>
          </ThemeProvider>
        </ApplicationAuthProvider>
      </AuthProvider>
    </BackendQueryProvider>
  );
}
