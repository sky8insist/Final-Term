import json
from io import BytesIO
from zipfile import ZipFile

import pytest

from experiments.mineru_ab.adapters.mineru_content_adapter import adapt_content_list, read_mineru_bundle
from experiments.mineru_ab.providers.mineru_provider import MinerUError


def _bundle(entries, name="sample_content_list.json"):
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr(name, json.dumps(entries))
        archive.writestr("full.md", "# Sample")
    return buffer.getvalue()


def test_content_list_maps_structure_and_pages():
    entries = [
        {"type": "text", "text": "Title", "text_level": 1, "page_idx": 0, "bbox": [1, 2, 3, 4]},
        {"type": "text", "text": "Body", "page_idx": 0},
        {"type": "table", "table_caption": ["Table 1"], "table_body": "<table></table>", "page_idx": 1},
        {"type": "equation", "text": "x^2", "page_idx": 1},
        {"type": "header", "text": "Repeated header", "page_idx": 1},
    ]
    content, markdown, metadata = read_mineru_bundle(
        _bundle(entries), max_result_bytes=1_000_000, max_unpacked_bytes=1_000_000,
    )
    blocks = adapt_content_list(content)
    assert [block.type for block in blocks] == ["heading", "paragraph", "table", "formula"]
    assert [block.page for block in blocks] == [1, 1, 2, 2]
    assert markdown == "# Sample"
    assert metadata["contentListPath"] == "sample_content_list.json"


def test_content_list_v2_is_not_used_as_stable_input():
    with pytest.raises(MinerUError, match="stable content_list"):
        read_mineru_bundle(
            _bundle([], "sample_content_list_v2.json"),
            max_result_bytes=1_000_000, max_unpacked_bytes=1_000_000,
        )

