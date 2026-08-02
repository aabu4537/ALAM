import { notFound } from "next/navigation";
import { SpoilerSeal } from "../../components/SpoilerSeal";
import { EndSessionButton } from "./EndSessionButton";
import styles from "./hub.module.css";
import { Recorder } from "./Recorder";
import { apiFetch, apiGetJson } from "@/lib/server-api";
import type {
  Briefing,
  JourneySummary,
  Prediction,
  ReadingSession,
  VisibleStructure,
  VisibleStructureUnit,
} from "@/lib/types";

export default async function BookHubPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;

  const sessionResponse = await apiFetch(`/books/${id}/reading-sessions/active`);
  if (sessionResponse.ok) {
    const readingSession = (await sessionResponse.json()) as ReadingSession;
    return <ReadingDashboard mediaItemId={id} readingSession={readingSession} />;
  }

  const briefingResponse = await apiFetch(`/books/${id}/briefing`);
  if (briefingResponse.status === 404) notFound();
  if (!briefingResponse.ok) {
    return (
      <div className="page-settle">
        <p className={styles.error}>Couldn&apos;t load this book right now. Try again shortly.</p>
      </div>
    );
  }
  const briefing = (await briefingResponse.json()) as Briefing;

  const firstChapterResponse = await apiFetch(`/books/${id}/chapters/first`);
  if (!firstChapterResponse.ok) {
    return (
      <div className="page-settle">
        <p className={styles.error}>This book has no chapters yet.</p>
      </div>
    );
  }
  const firstChapter = (await firstChapterResponse.json()) as VisibleStructureUnit;

  return <PreBookView mediaItemId={id} briefing={briefing} firstChapter={firstChapter} />;
}

async function ReadingDashboard({
  mediaItemId,
  readingSession,
}: {
  mediaItemId: string;
  readingSession: ReadingSession;
}) {
  const [chapters, predictions] = await Promise.all([
    apiGetJson<VisibleStructure>(`/books/${mediaItemId}/chapters`),
    apiGetJson<Prediction[]>(`/books/${mediaItemId}/predictions`),
  ]);

  let journeySummary: JourneySummary | null = null;
  let journeySummaryNote: string | null = null;
  try {
    journeySummary = await apiGetJson<JourneySummary>(`/books/${mediaItemId}/journey-summary`);
  } catch {
    journeySummaryNote = "Journey summary isn't available right now.";
  }

  const currentUnit = chapters.units.find(
    (unit) => unit.id === readingSession.current_structure_unit_id,
  );
  const currentLabel = currentUnit?.label ?? `chapter ${readingSession.current_ordinal}`;

  return (
    <div className="page-settle">
      <p className="stamp" style={{ color: "var(--brass)" }}>
        {chapters.title}
      </p>
      <h1 className={styles.heading}>Reading</h1>
      <p className={styles.progress}>
        <span className="ordinal">{Math.round(readingSession.current_progress * 100)}%</span> through
        — currently {currentLabel}
      </p>

      <div className={styles.spread}>
        <div className={styles.mainColumn}>
          <Recorder mediaItemId={mediaItemId} structureUnitId={readingSession.current_structure_unit_id} label={currentLabel} />

          <section className={styles.section}>
            <h2 className={styles.sectionTitle}>Journey so far</h2>
            {journeySummary ? (
              <p className={styles.narrative}>{journeySummary.narrative}</p>
            ) : (
              <p className={styles.recorderNote}>{journeySummaryNote}</p>
            )}
          </section>

          <EndSessionButton mediaItemId={mediaItemId} readingSessionId={readingSession.id} />
        </div>

        <aside className={styles.marginalia}>
          <h2 className={styles.sectionTitle}>Chapters so far</h2>
          <ol className={styles.chapterList}>
            {chapters.units.map((unit) => (
              <li key={unit.id}>
                <span className="ordinal">{unit.ordinal}</span> {unit.label}
              </li>
            ))}
          </ol>

          <h2 className={styles.sectionTitle}>Predictions</h2>
          {predictions.length === 0 ? (
            <p className={styles.recorderNote}>No predictions yet.</p>
          ) : (
            <ul className={styles.predictionList}>
              {predictions.map((prediction) => (
                <li key={prediction.id}>
                  <p>{prediction.statement}</p>
                  {prediction.status === "pending" ? (
                    <SpoilerSeal label="Not yet resolved" />
                  ) : (
                    <span className={styles.predictionStatus}>{prediction.status}</span>
                  )}
                </li>
              ))}
            </ul>
          )}
        </aside>
      </div>
    </div>
  );
}

function PreBookView({
  mediaItemId,
  briefing,
  firstChapter,
}: {
  mediaItemId: string;
  briefing: Briefing;
  firstChapter: VisibleStructureUnit;
}) {
  return (
    <div className="page-settle">
      <p className="stamp" style={{ color: "var(--brass)" }}>
        Not yet started
      </p>
      <h1 className={styles.heading}>{briefing.title}</h1>
      {briefing.author ? <p className={styles.author}>{briefing.author}</p> : null}
      {briefing.blurb ? <p className={styles.blurb}>{briefing.blurb}</p> : null}
      {briefing.subjects.length > 0 ? (
        <ul className={styles.subjects}>
          {briefing.subjects.map((subject) => (
            <li key={subject}>{subject}</li>
          ))}
        </ul>
      ) : null}

      {briefing.claims.length > 0 ? (
        <section className={styles.section}>
          <h2 className={styles.sectionTitle}>Why this might be for you</h2>
          <ul className={styles.claimList}>
            {briefing.claims.map((claim) => (
              <li key={claim.cites_id}>{claim.text}</li>
            ))}
          </ul>
        </section>
      ) : null}

      <Recorder mediaItemId={mediaItemId} structureUnitId={firstChapter.id} label={firstChapter.label} />
    </div>
  );
}
