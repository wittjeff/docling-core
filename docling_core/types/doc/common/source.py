"""Source models describing what in the original asset produced a node."""

from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator
from typing_extensions import Self


class BaseSource(BaseModel):
    """Base class for source information.

    Represents the source of an extracted component within a digital asset.
    """

    kind: Annotated[str, Field(description="Kind of source. It is used as a discriminator for the source type.")]


class TrackSource(BaseSource):
    """Source metadata for a cue extracted from a media track.

    A `TrackSource` instance identifies a cue in a media track (audio, video, subtitles, screen-recording captions,
    etc.). A *cue* here refers to any discrete segment that was pulled out of the original asset, e.g., a subtitle
    block, an audio clip, or a timed marker in a screen-recording.
    """

    model_config = ConfigDict(regex_engine="python-re")
    kind: Annotated[Literal["track"], Field(description="Identifies this type of source.")] = "track"
    start_time: Annotated[
        float,
        Field(
            examples=[11.0, 6.5, 5370.0],
            description="Start time offset of the track cue in seconds",
        ),
    ]
    end_time: Annotated[
        float,
        Field(
            examples=[12.0, 8.2, 5370.1],
            description="End time offset of the track cue in seconds",
        ),
    ]
    identifier: Annotated[
        str | None, Field(description="An identifier of the cue", examples=["test", "123", "b72d946"])
    ] = None
    voice: Annotated[
        str | None,
        Field(description="The name of the voice in this track (the speaker)", examples=["John", "Mary", "Speaker 1"]),
    ] = None

    @model_validator(mode="after")
    def check_order(self) -> Self:
        """Ensure start time is less than the end time."""
        if self.end_time <= self.start_time:
            raise ValueError("End time must be greater than start time")
        return self


class PdfStructureSource(BaseSource):
    """The structure element of a tagged PDF that produced this node (ISO 32000-2, 14.7.5).

    A node that spans pages gets one entry per page with the same `element_ref`, as `prov` has one
    `ProvenanceItem` per page. A node whose element has no content of its own (a `Sect` group) gets one entry with
    `page_no=None` and no `mcids`. The values come from the parser: the element identity, the depth-first index,
    the `/S` value before role mapping, the `/NS` URI, the `/ID` entry and the per-cell marked-content ids.
    """

    kind: Annotated[Literal["pdf_struct"], Field(description="Identifies this type of source.")] = "pdf_struct"
    element_ref: Annotated[
        str | None,
        Field(
            description="Identity of the structure element object as '<num> <gen>'; None for a direct object.",
            examples=["12 0", "345 0"],
        ),
    ] = None
    order: Annotated[
        int,
        Field(
            description="Depth-first index of the element in the structure tree, the logical content order "
            "(WTPDF 1.0, 8.2.3).",
            examples=[0, 17],
        ),
    ]
    element_type: Annotated[
        str,
        Field(
            description="Standard structure type after role mapping.",
            examples=["H2", "P", "Figure", "LI", "Sect"],
        ),
    ]
    namespace: Annotated[
        str | None,
        Field(
            description="PDF 2.0 namespace URI of the element type (/NS); None means the default PDF 1.7 namespace.",
            examples=["http://iso.org/pdf2/ssn", "http://www.w3.org/1998/Math/MathML"],
        ),
    ] = None
    authored_type: Annotated[
        str | None,
        Field(
            description="The /S value before role mapping, set only when it differs from `element_type`.",
            examples=["Heading2", "Normal"],
        ),
    ] = None
    element_id: Annotated[
        str | None,
        Field(description="The /ID entry of the element, when present.", examples=["node00012345"]),
    ] = None
    page_no: Annotated[
        int | None,
        Field(
            description="1-based page of the content this entry covers; None for a node with no page content.",
            examples=[1, 12],
        ),
    ] = None
    mcids: Annotated[
        list[int],
        Field(
            description="Marked-content ids on `page_no` that the node's content was collected from.",
            examples=[[3, 4, 5]],
        ),
    ] = []


SourceType = Annotated[TrackSource | PdfStructureSource, Field(discriminator="kind")]
"""Union type for all source types.

This type alias represents a discriminated union of all available source types that can be associated with
nodes in a document. The `kind` field is used as a discriminator to determine the specific source type at runtime.

Currently supported source types:
    - `TrackSource`: For elements extracted from media assets (audio, video, subtitles)
    - `PdfStructureSource`: For nodes produced from the structure tree of a tagged PDF

Notes:
    - Additional source types may be added to this union in the future to support other content sources.
    - `source` records what in the original asset produced a node, in any document kind. It is a lineage record,
        not a position record. For documents with an implicit or explicit layout, such as PDF, HTML, docx, pptx, or
        markdown files, `ProvenanceItem` remains the record of where an item sits on a page.
"""
