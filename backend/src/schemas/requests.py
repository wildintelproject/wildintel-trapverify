from pydantic import BaseModel


class SetupRequest(BaseModel):
    camtrap_dir: str
    image_base_dir: str = ""
    output_dir: str = ""
    target_species: list[str]
    study_start: str
    study_end: str
    occasion_days: int = 5
    total_iterations: int = 100000
    gap_seconds: int = 60
    min_score: float = 0.5
    include_burst_context: bool = False
    classified_by: str = "expert_review"
    extended_confirmation: bool = False


class DecisionsRequest(BaseModel):
    species: str
    iteration: int
    confirmed: list[str]


class RejectRequest(BaseModel):
    mediaId: str


class UnrejectRequest(BaseModel):
    media: list[str]


class ReviewDecisionsRequest(BaseModel):
    confirmed_keys: list[str]


class LoadSessionRequest(BaseModel):
    session_dir: str


class TrapperLoginRequest(BaseModel):
    url: str
    username: str
    password: str


class TrapperGenerateRequest(BaseModel):
    classification_project_pk: int
    output_dir: str
    clear_cache: bool = False
