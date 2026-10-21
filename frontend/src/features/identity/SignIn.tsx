import { useState } from "react";
import type { FormEvent } from "react";
import { api } from "../../lib/api";

export function SignIn({ onSignedIn }: { onSignedIn: () => void }) {
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setError(""); setPending(true);
    try {
      await api("/api/auth/login", { method: "POST", body: JSON.stringify({
        username: form.get("username"), password: form.get("password"),
      }) });
      onSignedIn();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unable to sign in");
    } finally { setPending(false); }
  }
  return <main className="signin">
    <div className="brand">VideoMind<span>Unified knowledge</span></div>
    <section className="panel">
      <p className="eyebrow">YOUR LOCAL WORKSPACE</p>
      <h1>Welcome back.</h1>
      <p className="muted">Sign in to your connected knowledge.</p>
      <form onSubmit={submit}>
        <label htmlFor="username">Username</label>
        <input id="username" name="username" autoComplete="username" required maxLength={64}/>
        <label htmlFor="password">Password</label>
        <input id="password" name="password" type="password" autoComplete="current-password" required maxLength={256}/>
        {error && <p className="error" role="alert">{error}</p>}
        <button disabled={pending} type="submit">{pending ? "Signing in…" : "Sign in"}</button>
      </form>
      <p className="note">Use the account created during local setup.</p>
    </section>
  </main>;
}
