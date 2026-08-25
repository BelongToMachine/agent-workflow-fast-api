from pydantic import BaseModel, ConfigDict, Field


class SourceCitation(BaseModel):
    """A source location shared by knowledge search result types."""

    model_config = ConfigDict(populate_by_name=True)

    source_id: str | None = Field(default=None, alias="sourceId")
    file_name: str | None = Field(default=None, alias="fileName")
    sheet: str | None = None
    row: int | None = None
    page: int | None = None
    section: str | None = None


def build_source_citation(
    *,
    source_id: object,
    file_name: object,
    source_sheet: object,
    source_row: object,
) -> SourceCitation:
    return SourceCitation(
        sourceId=None if source_id is None else str(source_id),
        fileName=None if file_name is None else str(file_name),
        sheet=None if source_sheet is None else str(source_sheet),
        row=None if source_row is None else int(source_row),
    )
