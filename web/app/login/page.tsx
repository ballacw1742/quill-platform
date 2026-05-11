"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Fingerprint, Loader2 } from "lucide-react";
import { QuillLogo } from "@/components/QuillLogo";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useLogin, useSession } from "@/lib/api";
import type { Session } from "@/lib/schemas";
import {
  isPasskeySupported,
  isUserCancelledError,
  loginWithPasskey,
} from "@/lib/auth";
import { RegisterPasskeyDialog } from "@/components/auth/RegisterPasskeyDialog";
import { toast } from "sonner";

/**
 * /login — iOS-redesign.
 *
 * MOBILE_UX_SPEC.md §"Authentication / /login":
 *   1. Big Quill mark, centered.
 *   2. text-title-1 "Sign in".
 *   3. text-body label-secondary "Use your passkey to continue."
 *   4. Email input.
 *   5. Primary "Sign in with passkey" — full-width 50 px accent filled.
 *   6. Ghost "Register a passkey" below.
 *   7. <details> dev-fallback collapsed by default.
 *
 * Forbidden chrome from the prior design: marketing copy, Card border,
 * footer link, top wordmark+tagline. The form *is* the screen.
 */

const schema = z.object({
  email: z.string().email("Enter a valid email"),
  password: z.string().optional(),
});
type FormValues = z.infer<typeof schema>;

const DEV_FALLBACK =
  typeof process !== "undefined" &&
  process.env.NEXT_PUBLIC_DEV_AUTH_FALLBACK === "1";

const LAST_EMAIL_KEY = "quill.last_login_email";

export default function LoginPage() {
  const router = useRouter();
  const { data: rawSession } = useSession();
  const session = rawSession as Session | null | undefined;
  const passwordLogin = useLogin();
  // Passkey support must be checked client-side only — SSR has no `window`.
  // Default to true so the SSR HTML shows an enabled button (matching what
  // 99%+ of real users will hydrate to) and avoids hydration mismatch flicker.
  const [passkeyAvailable, setPasskeyAvailable] = React.useState(true);
  React.useEffect(() => {
    setPasskeyAvailable(isPasskeySupported());
  }, []);

  const [passkeyPending, setPasskeyPending] = React.useState(false);
  const [registerOpen, setRegisterOpen] = React.useState(false);

  React.useEffect(() => {
    if (session) router.replace("/queue");
  }, [session, router]);

  // Pre-fill last successful email if available.
  const lastEmail =
    typeof window !== "undefined"
      ? window.localStorage.getItem(LAST_EMAIL_KEY) ?? "charles@quill.local"
      : "charles@quill.local";

  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { email: lastEmail, password: "" },
  });

  const rememberEmail = (email: string) => {
    if (typeof window !== "undefined")
      window.localStorage.setItem(LAST_EMAIL_KEY, email);
  };

  const onPasskey = async () => {
    const email = form.getValues("email");
    if (!email) {
      form.setError("email", { message: "Email required for passkey" });
      return;
    }
    setPasskeyPending(true);
    try {
      const result = await loginWithPasskey(email);
      if (typeof window !== "undefined") {
        window.localStorage.setItem("quill.session", JSON.stringify(result));
        // Mirror the JWT to the canonical key used by lib/api.apiFetch.
        if ((result as { access_token?: string }).access_token) {
          window.localStorage.setItem(
            "quill_session_token",
            (result as { access_token: string }).access_token,
          );
        }
      }
      rememberEmail(email);
      toast.success("Signed in with passkey");
      router.replace("/queue");
    } catch (err) {
      if (isUserCancelledError(err)) {
        toast.message("Passkey prompt cancelled");
      } else {
        // eslint-disable-next-line no-console
        console.error("passkey sign-in failed", err);
        toast.error(
          "Sign-in didn't work — your passkey wasn't recognized. Try again.",
        );
      }
    } finally {
      setPasskeyPending(false);
    }
  };

  const onPassword = (values: FormValues) => {
    if (!values.password) {
      form.setError("password", { message: "Required" });
      return;
    }
    passwordLogin.mutate(
      { email: values.email, password: values.password },
      {
        onSuccess: () => {
          rememberEmail(values.email);
          toast.success("Signed in");
          router.replace("/queue");
        },
        onError: (e) => {
          // eslint-disable-next-line no-console
          console.error("password sign-in failed", e);
          toast.error("Couldn't sign in. Check your email and password.");
        },
      },
    );
  };

  return (
    <main className="flex min-h-screen flex-col bg-bg pt-safe pb-safe">
      <div className="mx-auto flex w-full max-w-sm flex-1 flex-col justify-center px-6 py-10">
        {/* Quill mark — large, centered */}
        <div className="mb-12 flex flex-col items-center gap-4">
          <QuillLogo size={72} className="drop-shadow-md" />
          <span className="text-title-2 font-semibold tracking-tight text-label-primary">
            Quill
          </span>
        </div>

        <div className="mb-8 space-y-1">
          <h1 className="text-title-1 text-label-primary">Sign in</h1>
          <p className="text-body text-label-secondary">
            Use your passkey to continue.
          </p>
        </div>

        <form
          onSubmit={form.handleSubmit(onPassword)}
          className="space-y-4"
          autoComplete="on"
        >
          <div className="space-y-1.5">
            <label
              htmlFor="email"
              className="block text-subhead text-label-secondary"
            >
              Email
            </label>
            <Input
              id="email"
              type="email"
              inputMode="email"
              autoComplete="username webauthn"
              placeholder="you@example.com"
              className="h-[50px] rounded-lg border-separator-opaque bg-bg-tertiary text-body"
              {...form.register("email")}
            />
            {form.formState.errors.email && (
              <p className="text-footnote text-danger">
                {form.formState.errors.email.message}
              </p>
            )}
          </div>

          <Button
            type="button"
            onClick={onPasskey}
            disabled={!passkeyAvailable || passkeyPending}
            className="h-[50px] w-full rounded-lg text-headline text-white"
          >
            {passkeyPending ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" />
                Waiting for passkey…
              </>
            ) : (
              <>
                <Fingerprint className="h-4 w-4" />
                Sign in with passkey
              </>
            )}
          </Button>

          <button
            type="button"
            onClick={() => setRegisterOpen(true)}
            className="block w-full py-3 text-center text-callout text-accent active:opacity-60 no-tap-highlight"
          >
            Register a passkey
          </button>

          {!passkeyAvailable && (
            <div className="rounded-md bg-bg-elevated px-3 py-2 text-footnote text-label-secondary">
              Passkeys aren&rsquo;t supported on this browser. Use Safari,
              Chrome, Edge, or Firefox on a modern device.
            </div>
          )}

          {DEV_FALLBACK && (
            <details className="group rounded-lg bg-bg-elevated px-4 py-3">
              <summary className="flex cursor-pointer list-none items-center justify-between text-footnote text-label-secondary">
                <span>Developer sign-in</span>
                <span className="text-label-tertiary group-open:rotate-90 transition-transform">
                  ›
                </span>
              </summary>
              <div className="mt-3 space-y-3">
                <div className="space-y-1.5">
                  <label
                    htmlFor="password"
                    className="block text-subhead text-label-secondary"
                  >
                    Password
                  </label>
                  <Input
                    id="password"
                    type="password"
                    autoComplete="current-password"
                    placeholder="quill-dev-password"
                    className="h-11 rounded-md bg-bg-tertiary text-body"
                    {...form.register("password")}
                  />
                </div>
                <Button
                  type="submit"
                  variant="secondary"
                  className="h-11 w-full rounded-md text-headline"
                  disabled={passwordLogin.isPending}
                >
                  {passwordLogin.isPending ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : null}
                  Sign in (dev)
                </Button>
              </div>
            </details>
          )}
        </form>
      </div>

      <RegisterPasskeyDialog
        open={registerOpen}
        onOpenChange={setRegisterOpen}
      />
    </main>
  );
}
