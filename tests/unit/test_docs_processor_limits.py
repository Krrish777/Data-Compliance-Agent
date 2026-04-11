import stat
import pytest
from pathlib import Path
from unittest.mock import patch
from src.docs_processing.docs_processor import DocumentProcessor, MAX_FILE_MB


def test_rejects_oversized_pdf(tmp_path):
    big = tmp_path / "big.pdf"
    big.write_bytes(b"%PDF-1.4\n")

    # st_mode must look like a regular file so Path.is_file() doesn't blow up,
    # but st_size must exceed the limit so _process_pdf raises ValueError.
    fake_stat = type(
        "S",
        (),
        {
            "st_size": (MAX_FILE_MB + 10) * 1024 * 1024,
            "st_mode": stat.S_IFREG | 0o644,
        },
    )()

    proc = DocumentProcessor()
    with patch.object(Path, "stat", return_value=fake_stat):
        with pytest.raises(ValueError, match="too large"):
            proc.process_pdf(big)
