"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import styles from "./login.module.css";

export function LoginForm() {
  const router = useRouter();
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPending(true);
    setError(null);

    try {
      const response = await fetch("/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password }),
      });

      if (response.status === 204) {
        router.push("/");
        router.refresh();
        return;
      }
      if (response.status === 401) {
        setError("That password isn't right.");
      } else if (response.status === 503) {
        setError("No owner password is configured on the server yet.");
      } else {
        setError("Something went wrong. Try again.");
      }
    } catch {
      setError("Couldn't reach the server. Try again.");
    } finally {
      setPending(false);
    }
  }

  return (
    <form className={styles.form} onSubmit={handleSubmit}>
      <label className={styles.label} htmlFor="password">
        Password
      </label>
      <input
        id="password"
        name="password"
        type="password"
        autoFocus
        autoComplete="current-password"
        className={styles.input}
        value={password}
        onChange={(event) => setPassword(event.target.value)}
      />
      {error ? <p className={styles.error}>{error}</p> : null}
      <button type="submit" className={styles.submit} disabled={pending || password.length === 0}>
        {pending ? "Unsealing…" : "Enter"}
      </button>
    </form>
  );
}
