from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# URL validation note: Pydantic v2 HttpUrl was evaluated for source_url but not
# used. HttpUrl in Pydantic v2 normalizes URLs on serialization (e.g., may add
# trailing slashes, re-encode percent-encoded characters), which breaks exact-
# match dedup lookups against the stored value. ATS URLs tested
# (Workday, Greenhouse, Lever, Ashby) all use standard https://, so validation
# is not the concern — round-trip fidelity is. Plain str with max_length matches
# the pattern already used for company.link in CompanyCreate.


class ExtensionCaptureRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    company_name: str = Field(max_length=255)
    role: str = Field(max_length=255)
    source_url: str = Field(max_length=2048)
    job_description: str = Field(max_length=50000)


class ExtensionCaptureResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    application_id: UUID
    company_id: UUID
    status: str
    message: str
