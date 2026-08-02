import styles from "./SpoilerSeal.module.css";

/** The product's actual guarantee, made visual: content the API has
 * withheld or not yet resolved renders under a literal wax seal rather
 * than being grayed out. Never wraps content that was fetched and then
 * hidden client-side — only ever states "the resolution isn't here yet,"
 * about data this component was never given in the first place. */
export function SpoilerSeal({ label }: { label: string }) {
  return (
    <span className={styles.seal} title={label}>
      <span className={styles.wax}>✦</span>
      {label}
    </span>
  );
}
