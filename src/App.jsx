import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { useState } from "react";
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
import { SidebarInset, SidebarProvider } from "./components/ui/sidebar";
import { KnowledgeBaseFiles } from "./components/settings/knowledgeBaseFiles";
import { KnowledgeBaseGrants } from "./components/settings/knowledgeBaseGrants";
import { MemberPermissions } from "./components/settings/memberPermissions";
import { FastApiConnectionTest } from "./components/fastapiConnectionTest";
import {
  LocalActivationPage,
  LocalChangePasswordPage,
} from "./components/auth/localAccountPages";
import { Link, usePathname, useRouter } from "./lib/router";

function AuthGuard({ children }) {
  const { status } = useSession();
  const pathname = usePathname();

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
    return (
      <div className="flex min-h-dvh items-center justify-center bg-background text-sm text-muted-foreground">
        Checking authentication status…
      </div>
    );
  }

  if (status === "unauthenticated") {
    return <Navigate replace to="/login" />;
  }

  return children;
}

function ChatLayout() {
  const { data } = useSession();
  const {
    error: accessError,
    hasPermission,
    refreshCurrentUser,
    status: authStatus,
  } = useApplicationAuth();
  const user = data?.user;

  if (authStatus === "loading" || authStatus === "initializing") {
    return (
      <div className="flex min-h-dvh items-center justify-center bg-background px-6 text-center text-sm text-muted-foreground">
        Loading workspace access…
      </div>
    );
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
          <h1 className="font-semibold text-xl">Unable to load workspace access</h1>
          <p className="mt-2 text-muted-foreground text-sm leading-6">
            Your account is signed in, but workspace access could not be loaded.
          </p>
          <button
            className="mt-5 rounded-md border border-border px-3 py-2 text-sm font-medium transition-colors hover:bg-muted"
            onClick={() => void refreshCurrentUser()}
            type="button"
          >
            Try again
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
                  <SettingsPage title="Workspace permissions">
                    <MemberPermissions />
                  </SettingsPage>
                </PermissionRoute>
              }
              path="settings/members"
            />
            <Route
              element={
                <PermissionRoute permission="knowledge.manage">
                  <SettingsPage title="Knowledge base access">
                    <KnowledgeBaseGrants />
                  </SettingsPage>
                </PermissionRoute>
              }
              path="settings/knowledge-bases"
            />
            <Route
              element={
                <PermissionRoute permission="knowledge.manage">
                  <SettingsPage title="Knowledge base files">
                    <KnowledgeBaseFiles />
                  </SettingsPage>
                </PermissionRoute>
              }
              path="settings/knowledge-bases/files"
            />
            <Route
              element={<SettingsPage title="FastAPI connection"><FastApiConnectionTest /></SettingsPage>}
              path="fastapi-test"
            />
            <Route
              element={
                <SettingsPage title="Change password">
                  <LocalChangePasswordPage />
                </SettingsPage>
              }
              path="settings/password"
            />
            <Route element={<Navigate replace to="/" />} path="*" />
          </Routes>
        </SidebarInset>
      </SidebarProvider>
    </DataStreamProvider>
  );
}

function WorkspaceAccessPendingPage() {
  return (
    <div className="flex min-h-dvh items-center justify-center bg-background px-6 text-center">
      <div className="max-w-md">
        <h1 className="font-semibold text-xl">Account created</h1>
        <p className="mt-2 text-muted-foreground text-sm leading-6">
          Your account is signed in, but it has not been added to a workspace yet.
          Ask a workspace administrator to grant access, then refresh this page.
        </p>
      </div>
    </div>
  );
}

function AccountSuspendedPage() {
  const { signOut } = useApplicationAuth();

  return (
    <div className="flex min-h-dvh items-center justify-center bg-background px-6 text-center">
      <div className="max-w-md">
        <h1 className="font-semibold text-xl">Account suspended</h1>
        <p className="mt-2 text-muted-foreground text-sm leading-6">
          This account cannot access the workspace. Contact a workspace administrator if you believe this is a mistake.
        </p>
        <button
          className="mt-5 rounded-md border border-border px-3 py-2 text-sm font-medium transition-colors hover:bg-muted"
          onClick={() => void signOut()}
          type="button"
        >
          Sign out
        </button>
      </div>
    </div>
  );
}

function PasswordHelpPage() {
  return (
    <div className="flex min-h-dvh w-full items-center justify-center bg-background px-6 text-center">
      <div className="max-w-md">
        <h1 className="font-semibold text-xl">需要重置密码？</h1>
        <p className="mt-2 text-muted-foreground text-sm leading-6">
          如果忘记密码，请联系管理员。
        </p>
        <Link
          className="mt-5 inline-flex rounded-md border border-border px-3 py-2 text-sm font-medium transition-colors hover:bg-muted"
          href="/login"
        >
          返回登录
        </Link>
      </div>
    </div>
  );
}

function ForbiddenPage() {
  return (
    <div className="flex min-h-dvh items-center justify-center bg-background px-6 text-center">
      <div className="max-w-md">
        <h1 className="font-semibold text-xl">Permission required</h1>
        <p className="mt-2 text-muted-foreground text-sm leading-6">
          Your account does not have permission to open this workspace area.
        </p>
      </div>
    </div>
  );
}

function PermissionRoute({ children, permission }) {
  const { hasPermission, status } = useApplicationAuth();

  if (status === "loading" || status === "initializing") {
    return (
      <div className="flex min-h-dvh items-center justify-center bg-background text-sm text-muted-foreground">
        Loading workspace access…
      </div>
    );
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

function SettingsPage({ children, title }) {
  return (
    <main className="min-h-dvh overflow-y-auto bg-background px-4 py-8 md:px-8">
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-6">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Manage workspace configuration and access.
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
          ? "Email or password is incorrect."
          : "Unable to sign in right now. Please try again."
      );
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className="flex min-h-dvh w-full bg-sidebar">
      <div className="flex w-full flex-col bg-background p-8 md:p-16 xl:w-[600px] xl:shrink-0 xl:rounded-r-2xl xl:border-r xl:border-border/40">
        <Link
          className="flex w-fit items-center text-[13px] text-muted-foreground hover:text-foreground"
          href="/"
        >
          ← Back
        </Link>
        <div className="mx-auto flex w-full max-w-md flex-1 flex-col justify-center gap-8">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">
              {isLogin ? "Welcome back" : "Invitation required"}
            </h1>
            <p className="mt-2 text-sm text-muted-foreground">
              {isLogin
                ? "Sign in with your organization account."
                : "New accounts are created by an administrator invitation."}
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
                Email
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
                Password
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
                {isSubmitting ? "Signing in…" : "Sign in"}
              </button>
              <p className="text-center text-[13px] text-muted-foreground">
                如果忘记密码，请联系管理员。
              </p>
            </form>
          ) : null}
          {isLogin ? (
            <p className="text-center text-[13px] text-muted-foreground">
              Need access? Contact your workspace administrator.
            </p>
          ) : (
            <button
              className="h-10 rounded-md border border-border px-4 text-sm font-medium transition-colors hover:bg-muted"
              onClick={() => router.replace("/login")}
              type="button"
            >
              Back to sign in
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
            <TooltipProvider>
              <App />
            </TooltipProvider>
          </ThemeProvider>
        </ApplicationAuthProvider>
      </AuthProvider>
    </BackendQueryProvider>
  );
}
