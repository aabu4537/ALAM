import type { Metadata } from "next";
import { LoginForm } from "./LoginForm";
import styles from "./login.module.css";

export const metadata: Metadata = {
  title: "Sign in — ALAM",
};

export default function LoginPage() {
  return (
    <div className={styles.wrap}>
      <div className={`${styles.card} page-settle`}>
        <p className={styles.eyebrow}>The Commonplace Book</p>
        <h1 className={styles.title}>ALAM</h1>
        <p className={styles.tagline}>A private reading journal. Yours alone.</p>
        <LoginForm />
      </div>
    </div>
  );
}
