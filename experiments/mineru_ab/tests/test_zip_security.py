from io import BytesIO
from zipfile import ZipFile, ZipInfo

import pytest

from experiments.mineru_ab.adapters.mineru_content_adapter import read_mineru_bundle
from experiments.mineru_ab.providers.mineru_provider import MinerUError


def test_zip_path_traversal_is_rejected():
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr("../sample_content_list.json", "[]")
    with pytest.raises(MinerUError, match="Unsafe path"):
        read_mineru_bundle(buffer.getvalue(), max_result_bytes=10000, max_unpacked_bytes=10000)


def test_unpacked_size_limit_is_enforced():
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        info = ZipInfo("sample_content_list.json")
        archive.writestr(info, "[" + " " * 1000 + "]")
    with pytest.raises(MinerUError, match="expands beyond"):
        read_mineru_bundle(buffer.getvalue(), max_result_bytes=10000, max_unpacked_bytes=100)

