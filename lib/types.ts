// Mirrors the Pydantic response models in alam/api/routers/*.py. Kept as
// plain interfaces, one file, so a backend field rename is one visible diff
// here rather than a silent drift across many components.

export interface BookSummary {
  id: string;
  title: string;
  author: string | null;
  my_rating: number | null;
  exclusive_shelf: string | null;
  structure_verified: boolean;
  has_active_reading_session: boolean;
  chapter_count: number;
}

export interface StructureUnit {
  id: string;
  ordinal: number;
  label: string;
  first_lines: string | null;
}

export interface BookStructure {
  media_item_id: string;
  title: string;
  structure_verified: boolean;
  units: StructureUnit[];
}

export interface VisibleStructureUnit {
  id: string;
  ordinal: number;
  label: string;
}

export interface VisibleStructure {
  media_item_id: string;
  title: string;
  units: VisibleStructureUnit[];
}

export interface ReadingSession {
  id: string;
  media_item_id: string;
  status: string;
  current_structure_unit_id: string;
  current_ordinal: number;
  current_progress: number;
  started_at: string;
  ended_at: string | null;
}

export interface Prediction {
  id: string;
  statement: string;
  status: "pending" | "confirmed" | "refuted" | "unresolvable" | string;
  made_at_ordinal: number;
  resolution_window: number;
  resolved_at: string | null;
  evidence: string[];
}

export interface JourneySummary {
  id: string;
  media_item_id: string;
  narrative: string;
  generated_at_ordinal: number;
  model: string;
  prompt_version_id: string;
}

export interface Claim {
  text: string;
  cites_type: string;
  cites_id: string;
}

export interface Briefing {
  id: string;
  media_item_id: string;
  title: string;
  author: string | null;
  blurb: string | null;
  subjects: string[];
  claims: Claim[];
}

export interface TasteDriftEntry {
  id: string;
  statement: string;
  confidence: number;
  observation_count: number;
  active: boolean;
  observed_from: string;
  superseded_at: string | null;
}

export interface TasteDriftChain {
  history: TasteDriftEntry[];
}

export interface TasteDrift {
  chains: TasteDriftChain[];
}

export interface RecommendedCandidate {
  media_item_id: string;
  title: string;
  claims: Claim[];
}

export interface Recommendations {
  id: string | null;
  generated_at: string | null;
  recommendations: RecommendedCandidate[];
}

export interface FieldChange {
  field: string;
  old: unknown;
  new: unknown;
}

export interface NewBook {
  title: string;
  author: string;
  dedupe_key: string;
}

export interface UpdatedBook {
  id: string;
  title: string;
  changes: FieldChange[];
}

export interface SkippedRow {
  row_index: number;
  reason: string;
}

export interface ImportDiff {
  to_create: NewBook[];
  to_update: UpdatedBook[];
  unchanged_count: number;
  skipped: SkippedRow[];
}

export interface EpubPreviewUnit {
  ordinal: number;
  label: string;
  first_lines: string | null;
}

export interface EpubPreview {
  title: string | null;
  author: string | null;
  units: EpubPreviewUnit[];
}

export interface Capture {
  id: string;
  reading_session_id: string;
  media_item_id: string;
  structure_unit_id: string;
  structure_ordinal: number;
  status: string;
  raw_transcript: string | null;
  corrected_transcript: string | null;
  created_at: string;
}

export interface Memory {
  id: string;
  memory_type: string;
  content: string;
  structure_ordinal: number;
  created_at: string;
}
