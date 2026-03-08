from pydantic import BaseModel, Field


class TextIngestRequest(BaseModel):
    text: str = Field(min_length=1)
    doc_type: str = Field(default="auto")


class IngestResponse(BaseModel):
    document_id: int
    inferred_type: str
    confidence: float
    message: str


class JobRunResponse(BaseModel):
    status: str
    detail: str
