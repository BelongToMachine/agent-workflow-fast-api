import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Preview } from "../chat/preview";
import {
  activateLocalInvitation,
  changeLocalPassword,
  LocalAuthRequestError,
} from "../../lib/auth/localSession";
import { useSession } from "../../lib/auth";
import { Link, useLocationSearch, useRouter } from "../../lib/router";

function LocalAccountShell({ children, eyebrow }) {
  const { t } = useTranslation();
  return (
    <div className="flex min-h-dvh w-full bg-sidebar">
      <div className="flex w-full flex-col bg-background p-8 md:p-16 xl:w-[600px] xl:shrink-0 xl:rounded-r-2xl xl:border-r xl:border-border/40">
        <Link
          className="flex w-fit items-center text-[13px] text-muted-foreground hover:text-foreground"
          href="/"
        >
          ← {t("common.back")}
        </Link>
        <div className="mx-auto flex w-full max-w-md flex-1 flex-col justify-center gap-8">
          <div>
            <p className="text-muted-foreground text-xs font-medium uppercase tracking-[0.18em]">
              {eyebrow}
            </p>
            {children}
          </div>
        </div>
      </div>
      <div className="hidden flex-1 overflow-hidden pl-12 pt-8 xl:block">
        <Preview />
      </div>
    </div>
  );
}

function FormMessage({ children, error = false }) {
  if (!children) {
    return null;
  }

  return (
    <div
      aria-live="polite"
      className={
        error
          ? "rounded-lg border border-destructive/30 bg-destructive/10 px-4 py-3 text-destructive text-sm"
          : "rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-4 py-3 text-emerald-700 text-sm dark:text-emerald-300"
      }
      role="status"
    >
      {children}
    </div>
  );
}

export function LocalActivationPage() {
  const router = useRouter();
  const { update } = useSession();
  const { t } = useTranslation();
  const search = useLocationSearch();
  const token = new URLSearchParams(search).get("token") ?? "";
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [errorMessage, setErrorMessage] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function handleSubmit(event) {
    event.preventDefault();
    setErrorMessage("");
    if (!token) {
      setErrorMessage(t("auth.invitationMissingToken"));
      return;
    }
    if (password !== confirmation) {
      setErrorMessage(t("auth.passwordsDoNotMatch"));
      return;
    }
    if (password.length < 12) {
      setErrorMessage(t("auth.passwordMinLength"));
      return;
    }

    setIsSubmitting(true);
    try {
      await activateLocalInvitation(token, password, name);
      await update();
      router.replace("/");
    } catch (error) {
      setErrorMessage(
        error instanceof LocalAuthRequestError && error.status === 400
          ? error.message
          : t("auth.invitationInvalid")
      );
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <LocalAccountShell eyebrow={t("auth.workspaceInvitation")}>
      <h1 className="mt-3 text-2xl font-semibold tracking-tight">{t("auth.setUpAccount")}</h1>
      <p className="mt-2 text-sm text-muted-foreground">
        {t("auth.choosePassword")}
      </p>
      <form className="mt-8 flex flex-col gap-4" onSubmit={handleSubmit}>
        <FormMessage error>{errorMessage}</FormMessage>
        <label className="flex flex-col gap-2 text-sm font-medium">
          {t("auth.name")} <span className="text-muted-foreground font-normal">({t("common.optional")})</span>
          <input
            autoComplete="name"
            className="h-10 rounded-md border border-input bg-background px-3 text-sm outline-none focus:ring-2 focus:ring-ring"
            onChange={(event) => setName(event.target.value)}
            value={name}
          />
        </label>
        <label className="flex flex-col gap-2 text-sm font-medium">
          {t("auth.password")}
          <input
            autoComplete="new-password"
            className="h-10 rounded-md border border-input bg-background px-3 text-sm outline-none focus:ring-2 focus:ring-ring"
            minLength={12}
            onChange={(event) => setPassword(event.target.value)}
            required
            type="password"
            value={password}
          />
        </label>
        <label className="flex flex-col gap-2 text-sm font-medium">
          {t("auth.confirmPassword")}
          <input
            autoComplete="new-password"
            className="h-10 rounded-md border border-input bg-background px-3 text-sm outline-none focus:ring-2 focus:ring-ring"
            minLength={12}
            onChange={(event) => setConfirmation(event.target.value)}
            required
            type="password"
            value={confirmation}
          />
        </label>
        <button
          className="h-10 rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60"
          disabled={isSubmitting || !token}
          type="submit"
        >
          {isSubmitting ? t("auth.activating") : t("auth.activateAccount")}
        </button>
      </form>
      <p className="mt-5 text-center text-[13px] text-muted-foreground">
        {t("auth.alreadyActivated")}{" "}
        <Link className="text-foreground underline-offset-4 hover:underline" href="/login">
          {t("auth.signIn")}
        </Link>
      </p>
    </LocalAccountShell>
  );
}

export function LocalChangePasswordPage() {
  const { update } = useSession();
  const router = useRouter();
  const { t } = useTranslation();
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [errorMessage, setErrorMessage] = useState("");
  const [successMessage, setSuccessMessage] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function handleSubmit(event) {
    event.preventDefault();
    setErrorMessage("");
    setSuccessMessage("");
    if (newPassword !== confirmation) {
      setErrorMessage(t("auth.passwordsDoNotMatch"));
      return;
    }
    if (newPassword.length < 12) {
      setErrorMessage(t("auth.passwordMinLength"));
      return;
    }

    setIsSubmitting(true);
    try {
      await changeLocalPassword(currentPassword, newPassword);
      await update();
      setCurrentPassword("");
      setNewPassword("");
      setConfirmation("");
      setSuccessMessage(t("auth.passwordChanged"));
    } catch (error) {
      setErrorMessage(
        error instanceof LocalAuthRequestError && error.status === 400
          ? error.message
          : t("auth.unableToChangePassword")
      );
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <LocalAccountShell eyebrow={t("auth.accountSecurity")}>
      <h1 className="mt-3 text-2xl font-semibold tracking-tight">{t("auth.changePassword")}</h1>
      <p className="mt-2 text-sm text-muted-foreground">
        {t("auth.newPasswordDescription")}
      </p>
      <form className="mt-8 flex flex-col gap-4" onSubmit={handleSubmit}>
        <FormMessage error>{errorMessage}</FormMessage>
        <FormMessage>{successMessage}</FormMessage>
        <label className="flex flex-col gap-2 text-sm font-medium">
          {t("auth.currentPassword")}
          <input
            autoComplete="current-password"
            className="h-10 rounded-md border border-input bg-background px-3 text-sm outline-none focus:ring-2 focus:ring-ring"
            onChange={(event) => setCurrentPassword(event.target.value)}
            required
            type="password"
            value={currentPassword}
          />
        </label>
        <label className="flex flex-col gap-2 text-sm font-medium">
          {t("auth.newPassword")}
          <input
            autoComplete="new-password"
            className="h-10 rounded-md border border-input bg-background px-3 text-sm outline-none focus:ring-2 focus:ring-ring"
            minLength={12}
            onChange={(event) => setNewPassword(event.target.value)}
            required
            type="password"
            value={newPassword}
          />
        </label>
        <label className="flex flex-col gap-2 text-sm font-medium">
          {t("auth.confirmNewPassword")}
          <input
            autoComplete="new-password"
            className="h-10 rounded-md border border-input bg-background px-3 text-sm outline-none focus:ring-2 focus:ring-ring"
            minLength={12}
            onChange={(event) => setConfirmation(event.target.value)}
            required
            type="password"
            value={confirmation}
          />
        </label>
        <div className="flex gap-3">
          <button
            className="h-10 flex-1 rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60"
            disabled={isSubmitting}
            type="submit"
          >
            {isSubmitting ? t("auth.saving") : t("auth.changePassword")}
          </button>
          <button
            className="h-10 rounded-md border border-border px-4 text-sm font-medium transition-colors hover:bg-muted"
            onClick={() => router.back()}
            type="button"
          >
            {t("common.cancel")}
          </button>
        </div>
      </form>
    </LocalAccountShell>
  );
}
