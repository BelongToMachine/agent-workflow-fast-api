"use client";

import { ChevronUp, LanguagesIcon } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { User } from "@/lib/auth";
import { useSession } from "@/lib/auth";
import { useApplicationAuth } from "@/lib/auth/applicationAuth";
import { useTheme } from "next-themes";
import { useCallback } from "react";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
} from "@/components/ui/dropdownMenu";
import {
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/ui/sidebar";
import { guestRegex } from "@/lib/constants";
import {
  languageOptions,
  setAppLanguage,
  type AppLanguage,
} from "@/lib/i18n";
import { LoaderIcon } from "./icons";
import { toast } from "./toast";

function emailToHue(email: string): number {
  let hash = 0;
  for (const char of email) {
    hash = char.charCodeAt(0) + ((hash << 5) - hash);
  }
  return Math.abs(hash) % 360;
}

export function SidebarUserNav({ user }: { user: User }) {
  const { data, status } = useSession();
  const { signOut } = useApplicationAuth();
  const { setTheme, resolvedTheme } = useTheme();
  const { t, i18n } = useTranslation();

  const isGuest = guestRegex.test(data?.user?.email ?? "");
  const handleThemeSelect = useCallback(() => {
    setTheme(resolvedTheme === "dark" ? "light" : "dark");
  }, [resolvedTheme, setTheme]);

  const handleAuthClick = useCallback(() => {
    if (status === "loading") {
      toast({
        description: t("sidebar.authStatusLoading"),
        type: "error",
      });

      return;
    }

    void signOut();
  }, [signOut, status, t]);

  const handleLanguageChange = useCallback((value: string) => {
    if (value === "en" || value === "zh") {
      void setAppLanguage(value as AppLanguage);
    }
  }, []);

  const currentLanguage: AppLanguage = i18n.language.startsWith("zh")
    ? "zh"
    : "en";

  return (
    <SidebarMenu>
      <SidebarMenuItem>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            {status === "loading" ? (
              <SidebarMenuButton className="h-10 justify-between rounded-lg bg-transparent text-sidebar-foreground/50 transition-colors duration-150 data-[state=open]:bg-sidebar-accent data-[state=open]:text-sidebar-accent-foreground">
                <div className="flex flex-row items-center gap-2">
                  <div className="size-6 animate-pulse rounded-full bg-sidebar-foreground/10" />
                  <span className="animate-pulse rounded-md bg-sidebar-foreground/10 text-transparent text-[13px]">
                    {t("common.loadingShort")}
                  </span>
                </div>
                <div className="animate-spin text-sidebar-foreground/50">
                  <LoaderIcon />
                </div>
              </SidebarMenuButton>
            ) : (
              <SidebarMenuButton
                className="h-8 px-2 rounded-lg bg-transparent text-sidebar-foreground/70 transition-colors duration-150 hover:text-sidebar-foreground data-[state=open]:bg-sidebar-accent data-[state=open]:text-sidebar-accent-foreground"
                data-testid="user-nav-button"
              >
                <div
                  className="size-5 shrink-0 rounded-full ring-1 ring-sidebar-border/50"
                  style={{
                    background: `linear-gradient(135deg, oklch(0.35 0.08 ${emailToHue(user.email ?? "")}), oklch(0.25 0.05 ${emailToHue(user.email ?? "") + 40}))`,
                  }}
                />
                <span className="truncate text-[13px]" data-testid="user-email">
                  {isGuest ? t("sidebar.guest") : user?.email}
                </span>
                <ChevronUp className="ml-auto size-3.5 text-sidebar-foreground/50" />
              </SidebarMenuButton>
            )}
          </DropdownMenuTrigger>
          <DropdownMenuContent
            className="w-(--radix-popper-anchor-width) rounded-lg border border-border/60 bg-card/95 backdrop-blur-xl shadow-[var(--shadow-float)]"
            data-testid="user-nav-menu"
            side="top"
          >
            <DropdownMenuItem
              className="cursor-pointer text-[13px]"
              data-testid="user-nav-item-theme"
              onSelect={handleThemeSelect}
            >
              {resolvedTheme === "light"
                ? t("theme.toggleDark")
                : t("theme.toggleLight")}
            </DropdownMenuItem>
            <DropdownMenuSub>
              <DropdownMenuSubTrigger>
                <LanguagesIcon />
                <span>{t("language.label")}</span>
              </DropdownMenuSubTrigger>
              <DropdownMenuSubContent>
                <DropdownMenuRadioGroup
                  onValueChange={handleLanguageChange}
                  value={currentLanguage}
                >
                  {languageOptions.map((option) => (
                    <DropdownMenuRadioItem key={option.code} value={option.code}>
                      {option.code === "en"
                        ? t("language.english")
                        : t("language.chinese")}
                    </DropdownMenuRadioItem>
                  ))}
                </DropdownMenuRadioGroup>
              </DropdownMenuSubContent>
            </DropdownMenuSub>
            <DropdownMenuSeparator />
            <DropdownMenuItem asChild data-testid="user-nav-item-auth">
              <button
                className="w-full cursor-pointer text-[13px]"
                onClick={handleAuthClick}
                type="button"
              >
                {isGuest ? t("sidebar.loginToAccount") : t("sidebar.signOut")}
              </button>
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </SidebarMenuItem>
    </SidebarMenu>
  );
}
