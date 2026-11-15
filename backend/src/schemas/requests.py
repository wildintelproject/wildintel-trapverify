from pydantic import BaseModel, Field


class SetupRequest(BaseModel):
    camtrap_dir: str
    image_base_dir: str = ""
    flat_search: bool = False
    output_dir: str = ""
    target_species: list[str]
    study_start: str
    study_end: str
    occasion_days: int = 5
    # Sampling occasion length in hours, for occasions shorter than a day (e.g. 1 for activity
    # patterns). 0 (the default) means use occasion_days. Older sessions only have occasion_days.
    occasion_hours: int = Field(0, ge=0)
    total_iterations: int = 100000
    gap_seconds: int = 60
    min_score: float = 0.5
    # Optional name to tell sessions apart in the recent-sessions list and the species index.
    session_name: str = Field("", max_length=120)
    # Per-species cut-offs that replace min_score (scientificName -> threshold; <= 0 means none).
    min_score_by_species: dict[str, float] = {}
    # Seed of the pseudo-random order of detection events with the same score (e.g. no scores).
    random_seed: int = 42
    include_burst_context: bool = False
    classified_by: str = "expert_review"
    extended_confirmation: bool = False
    # Optional "actual species" field when rejecting; off by default. Never affects presence logic.
    record_rejection_species: bool = False
    # Pauses longer than this (seconds) between two decisions are idle time, not review time.
    review_idle_seconds: int = 120


class ProgressRequest(BaseModel):
    """Unfinished decisions of one round, saved while the reviewer works."""
    iteration: int
    # observationID of the event's representative detection -> confirmed | rejected | uncertain
    decisions: dict[str, str] = {}
    corrections: dict[str, str] = {}
    decision_times: dict[str, int] = {}


class DecisionsRequest(BaseModel):
    species: str
    iteration: int
    confirmed: list[str]
    # Events marked "uncertain": counted as rejections, only recorded for reporting.
    uncertain: list[str] = []
    # observationID -> actual species typed for a rejected event (only used when the
    # session has record_rejection_species on). Never affects presence logic.
    corrections: dict[str, str] = {}
    # observationID -> epoch milliseconds when the reviewer made the decision in the browser.
    decision_times: dict[str, int] = {}


class RejectRequest(BaseModel):
    mediaId: str


class UnrejectRequest(BaseModel):
    media: list[str]


class ReviewDecisionsRequest(BaseModel):
    confirmed_keys: list[str]


class LoadSessionRequest(BaseModel):
    session_dir: str


class ImportSessionRequest(BaseModel):
    zip_path: str


class RelinkRequest(BaseModel):
    camtrap_dir: str
    image_base_dir: str = ""
    flat_search: bool = False


class RenameSessionRequest(BaseModel):
    session_dir: str = ""          # empty: the active session
    name: str = Field("", max_length=120)


class TrapperLoginRequest(BaseModel):
    url: str
    username: str
    password: str


class TrapperGenerateRequest(BaseModel):
    classification_project_pk: int
    output_dir: str
    clear_cache: bool = False
