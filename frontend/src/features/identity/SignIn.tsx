import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { api } from "../../lib/api";

export function SignIn({ onSignedIn }: { onSignedIn: (next?: "library") => void }) {
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  const [registration, setRegistration] = useState(false);
  const [signup, setSignup] = useState(false);
  useEffect(() => {
    let current = true;
    void api<{ enabled: boolean }>("/api/auth/signup-info").then(value => { if (current) setRegistration(value.enabled); }).catch(() => {});
    return () => { current = false; };
  }, []);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    if (signup && form.get("password") !== form.get("confirmation")) { setError("Passwords do not match."); return; }
    setError(""); setPending(true);
    try {
      await api(signup ? "/api/auth/signup" : "/api/auth/login", { method: "POST", body: JSON.stringify({
        username: form.get("username"), password: form.get("password"),
        ...(signup ? { password_confirmation: form.get("confirmation"), accept_workspace_access: form.get("access") === "on" } : {}),
      }) });
      onSignedIn(signup ? "library" : undefined);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Unable to sign in"); }
    finally { setPending(false); }
  }
  return <main className="signin">
    <div className="brand">VideoMind<span>Find the original in your files</span></div>
    <section className="panel">
      <p className="eyebrow">YOUR LOCAL WORKSPACE</p>
      <h1>{signup ? "Create your account." : "Welcome back."}</h1>
      <p className="muted">{signup ? "Add your files, let VideoMind prepare them, then search in your own words." : "Sign in to your connected knowledge."}</p>
      <form onSubmit={submit} key={signup ? "signup" : "login"}>
        <label htmlFor="username">Username</label>
        <input id="username" name="username" autoComplete="username" required minLength={signup ? 3 : 1} maxLength={64} pattern="[a-zA-Z0-9_.-]+" disabled={pending}/>
        {signup && <p className="helper muted">3–64 letters, numbers, dots, underscores or hyphens. Names are case insensitive.</p>}
        <label htmlFor="password">Password</label>
        <input id="password" name="password" type="password" autoComplete={signup ? "new-password" : "current-password"} required minLength={signup ? 12 : 1} maxLength={256} disabled={pending}/>
        {signup && <><p className="helper muted">Use at least 12 characters.</p><label htmlFor="confirmation">Confirm password</label><input id="confirmation" name="confirmation" type="password" autoComplete="new-password" required minLength={12} maxLength={256} disabled={pending}/>
          <label className="signup-access"><input type="checkbox" name="access" required disabled={pending}/><span>I understand that my collections are hidden from other members, and workspace owners and admins can access them.</span></label></>}
        {error && <p className="error" role="alert">{error}</p>}
        <button disabled={pending} type="submit">{pending ? (signup ? "Creating account…" : "Signing in…") : signup ? "Create account" : "Sign in"}</button>
      </form>
      {(registration || signup) && <p><button className="text-button" disabled={pending} onClick={() => { setSignup(value => !value); setError(""); }}>{signup ? "Already have an account? Sign in" : "New here? Create an account"}</button></p>}
      {!registration && !signup && <p className="helper muted">Account registration is currently closed. Existing accounts can still sign in.</p>}
    </section>
  </main>;
}
