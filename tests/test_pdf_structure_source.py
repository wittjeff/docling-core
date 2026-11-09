"""Tests for ``PdfStructureSource``, ``NodeItem.source`` and ``TextItem.text_provenance``.

The structure element behind a node is lineage, not position: it lives in the ``source``
union beside ``TrackSource`` and is available on groups, which have no ``prov``. These tests
cover the JSON round trip, the page bookkeeping in ``filter`` and ``concatenate``, the
discriminator and the compatibility of documents written before the fields existed.
"""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from docling_core.types.doc import (
    BoundingBox,
    DocItemLabel,
    DoclingDocument,
    GroupLabel,
    PdfStructureSource,
    ProvenanceItem,
    Size,
    TableData,
    TrackSource,
)
from docling_core.types.doc.items.text import TextItem

_FIXTURE_DIR = Path(__file__).parent / "data" / "doc" / "pdf_structure_source"


def _prov(page_no: int) -> ProvenanceItem:
    return ProvenanceItem(page_no=page_no, bbox=BoundingBox(l=10, t=10, r=90, b=90), charspan=(0, 0))


def _tagged_doc() -> DoclingDocument:
    """A two-page document whose nodes all carry a structure source."""
    doc = DoclingDocument(name="tagged")
    for page_no in (1, 2):
        doc.add_page(page_no=page_no, size=Size(width=100, height=100))

    section = doc.add_group(
        label=GroupLabel.SECTION,
        name="Sect",
        source=PdfStructureSource(order=0, element_type="Sect", element_ref="10 0", element_id="sect-1"),
    )
    heading = doc.add_heading(
        text="Heading",
        parent=section,
        prov=_prov(1),
        source=PdfStructureSource(
            order=1,
            element_type="H1",
            authored_type="Heading1",
            element_ref="11 0",
            page_no=1,
            mcids=[0],
        ),
    )
    heading.text_provenance = "encoded"
    paragraph = doc.add_text(
        label=DocItemLabel.TEXT,
        text="Body text that runs over two pages",
        parent=section,
        prov=_prov(1),
        source=PdfStructureSource(order=2, element_type="P", element_ref="12 0", page_no=1, mcids=[1, 2]),
    )
    paragraph.prov.append(_prov(2))
    paragraph.source.append(
        PdfStructureSource(order=2, element_type="P", element_ref="12 0", page_no=2, mcids=[0]),
    )
    paragraph.text_provenance = "mixed"
    doc.add_picture(
        parent=section,
        prov=_prov(2),
        source=PdfStructureSource(
            order=3,
            element_type="Figure",
            element_ref="13 0",
            namespace="http://iso.org/pdf2/ssn",
            page_no=2,
            mcids=[1],
        ),
    )
    doc.add_table(
        data=TableData(),
        parent=section,
        prov=_prov(2),
        source=PdfStructureSource(order=4, element_type="Table", element_ref="14 0", page_no=2, mcids=[2, 3]),
    )
    return doc


def _struct_sources(doc: DoclingDocument) -> dict[str, list[PdfStructureSource]]:
    """Structure sources of every node in the tree, keyed by `self_ref`."""
    out: dict[str, list[PdfStructureSource]] = {}
    for item, _ in doc.iterate_items(with_groups=True):
        out[item.self_ref] = [src for src in item.source if isinstance(src, PdfStructureSource)]
    return out


class TestRoundTrip:
    def test_source_and_text_provenance_survive_export_and_validate(self):
        doc = _tagged_doc()

        dumped = doc.export_to_dict()
        loaded = DoclingDocument.model_validate(dumped)

        assert loaded == doc
        assert loaded.groups[0].source == doc.groups[0].source
        assert loaded.texts[0].text_provenance == "encoded"
        assert loaded.texts[1].text_provenance == "mixed"
        assert [src.page_no for src in loaded.texts[1].source] == [1, 2]
        assert loaded.pictures[0].source[0].namespace == "http://iso.org/pdf2/ssn"
        assert loaded.tables[0].source[0].mcids == [2, 3]

    def test_json_omits_the_fields_when_unset(self):
        doc = DoclingDocument(name="plain")
        group = doc.add_group(label=GroupLabel.SECTION)
        doc.add_text(label=DocItemLabel.TEXT, text="Hello", parent=group)
        doc.add_picture(parent=group)
        doc.add_table(data=TableData(), parent=group)

        dumped = doc.export_to_dict()

        assert "source" not in dumped["body"]
        assert "source" not in dumped["groups"][0]
        for key in ("texts", "pictures", "tables"):
            (item,) = dumped[key]
            assert "source" not in item
            assert "text_provenance" not in item

    def test_json_shape_of_a_structure_source(self):
        doc = _tagged_doc()

        dumped = doc.export_to_dict()

        assert dumped["groups"][0]["source"] == [
            {
                "kind": "pdf_struct",
                "element_ref": "10 0",
                "order": 0,
                "element_type": "Sect",
                "element_id": "sect-1",
                "mcids": [],
            }
        ]
        assert dumped["texts"][0]["text_provenance"] == "encoded"
        assert dumped["texts"][0]["source"][0]["authored_type"] == "Heading1"

    def test_defaults_make_every_field_but_order_and_element_type_optional(self):
        src = PdfStructureSource(order=5, element_type="LI")

        assert src.kind == "pdf_struct"
        assert src.element_ref is None
        assert src.namespace is None
        assert src.authored_type is None
        assert src.element_id is None
        assert src.page_no is None
        assert src.mcids == []

        with pytest.raises(ValidationError, match="order"):
            PdfStructureSource(element_type="LI")  # type: ignore[call-arg]
        with pytest.raises(ValidationError, match="element_type"):
            PdfStructureSource(order=5)  # type: ignore[call-arg]

    @pytest.mark.parametrize("value", ["encoded", "actual_text", "mixed", "ocr", "generated"])
    def test_text_provenance_accepts_the_five_values(self, value: str):
        item = TextItem(self_ref="#/texts/0", label=DocItemLabel.TEXT, orig="x", text="x", text_provenance=value)
        assert TextItem.model_validate(item.model_dump()).text_provenance == value

    def test_text_provenance_rejects_other_values(self):
        with pytest.raises(ValidationError, match="text_provenance"):
            TextItem(self_ref="#/texts/0", label=DocItemLabel.TEXT, orig="x", text="x", text_provenance="guessed")


class TestDiscriminator:
    def test_unknown_kind_fails_validation(self):
        doc = _tagged_doc()
        dumped = doc.export_to_dict()
        dumped["texts"][0]["source"][0]["kind"] = "pdf_widget"

        with pytest.raises(ValidationError, match="kind"):
            DoclingDocument.model_validate(dumped)

    def test_track_and_pdf_struct_coexist_on_one_item(self):
        doc = DoclingDocument(name="mixed")
        item = doc.add_text(
            label=DocItemLabel.TEXT,
            text="Caption line",
            source=TrackSource(start_time=1.0, end_time=2.0),
        )
        item.source.append(PdfStructureSource(order=0, element_type="P", page_no=1))

        loaded = DoclingDocument.model_validate(doc.export_to_dict())

        kinds = [src.kind for src in loaded.texts[0].source]
        assert kinds == ["track", "pdf_struct"]
        assert isinstance(loaded.texts[0].source[0], TrackSource)
        assert isinstance(loaded.texts[0].source[1], PdfStructureSource)


class TestDocumentOperations:
    def test_filter_drops_entries_of_excluded_pages_and_keeps_pageless_ones(self):
        doc = _tagged_doc()

        filtered = doc.filter(page_nrs={2})
        sources = _struct_sources(filtered)

        # the Sect group has no page content and stays, its entry untouched
        assert sources["#/groups/0"] == doc.groups[0].source
        # the two-page paragraph keeps only its page-2 entry, and page 2 stays page 2
        # (`prov` entries of excluded pages are not trimmed by `filter` today; that is out of scope here)
        (paragraph,) = [t for t in filtered.texts if t.text.startswith("Body text")]
        assert [(src.page_no, src.mcids) for src in paragraph.source] == [(2, [0])]
        # page-2-only items are unchanged
        assert filtered.pictures[0].source == doc.pictures[0].source
        assert filtered.tables[0].source == doc.tables[0].source

    def test_filter_without_pages_leaves_source_untouched(self):
        doc = _tagged_doc()

        assert _struct_sources(doc.filter()) == _struct_sources(doc)

    def test_concatenate_shifts_page_no_with_provenance(self):
        first = _tagged_doc()
        second = _tagged_doc()

        merged = DoclingDocument.concatenate([first, second])

        assert len(merged.pages) == 4
        # second copy: pages 1,2 become 3,4 on prov and on structure sources alike
        second_paragraph = merged.texts[3]
        assert second_paragraph.text.startswith("Body text")
        assert [prov.page_no for prov in second_paragraph.prov] == [3, 4]
        assert [src.page_no for src in second_paragraph.source] == [3, 4]
        assert [src.element_ref for src in second_paragraph.source] == ["12 0", "12 0"]
        assert merged.pictures[1].source[0].page_no == 4
        assert merged.tables[1].source[0].page_no == 4
        # pageless group entries do not move, and the first copy is untouched
        assert merged.groups[1].source == first.groups[0].source
        assert [src.page_no for src in merged.texts[1].source] == [1, 2]

    def test_concatenate_does_not_mutate_the_inputs(self):
        first = _tagged_doc()
        second = _tagged_doc()
        before = second.export_to_dict()

        DoclingDocument.concatenate([first, second])

        assert second.export_to_dict() == before

    def test_delete_items_leaves_the_sources_of_other_nodes_alone(self):
        doc = _tagged_doc()
        expected = {ref: srcs for ref, srcs in _struct_sources(doc).items() if ref != "#/texts/0"}

        doc.delete_items(node_items=[doc.texts[0]])

        remaining = _struct_sources(doc)
        # refs after the deleted text shift down by one; sources travel with their node
        assert remaining["#/groups/0"] == expected["#/groups/0"]
        assert remaining["#/texts/0"] == expected["#/texts/1"]
        assert remaining["#/pictures/0"] == expected["#/pictures/0"]
        assert remaining["#/tables/0"] == expected["#/tables/0"]
        assert doc.texts[0].text_provenance == "mixed"


class TestCompatibility:
    def test_a_document_written_on_main_validates_and_exports_unchanged_but_for_version(self):
        """A 1.11.0 document has none of the new fields and must load and dump byte-for-byte, except `version`."""
        raw = json.loads((_FIXTURE_DIR / "main_schema_1_11.json").read_text(encoding="utf-8"))
        assert raw["version"] == "1.11.0"

        doc = DoclingDocument.model_validate(raw)
        dumped = doc.export_to_dict()

        assert dumped["version"] == DoclingDocument.model_fields["version"].default
        assert {**dumped, "version": raw["version"]} == raw
        assert all(not item.source for item, _ in doc.iterate_items(with_groups=True))
        assert all(text.text_provenance is None for text in doc.texts)
