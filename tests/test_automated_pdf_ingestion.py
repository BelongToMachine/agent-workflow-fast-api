import asyncio
from pathlib import Path

from scripts.run_automated_pdf_ingestion import (
    MAX_PDF_BYTES,
    ProcessingResult,
    discover_pdf_files,
    limit_pdf_files,
    move_to_archive,
    run_batch,
)


def test_discover_pdf_files_only_returns_root_level_pdfs_below_limit(tmp_path: Path) -> None:
    source_dir = tmp_path / "files"
    source_dir.mkdir()
    (source_dir / "small.pdf").write_bytes(b"%PDF-small")
    (source_dir / "UPPER.PDF").write_bytes(b"%PDF-upper")
    (source_dir / "large.pdf").write_bytes(b"x" * MAX_PDF_BYTES)
    (source_dir / "notes.txt").write_bytes(b"not a pdf")
    (source_dir / "nested").mkdir()
    (source_dir / "nested" / "nested.pdf").write_bytes(b"%PDF-nested")
    (source_dir / "archived").mkdir()
    (source_dir / "archived" / "old.pdf").write_bytes(b"%PDF-old")

    discovered = discover_pdf_files(source_dir)

    assert discovered == [source_dir / "small.pdf", source_dir / "UPPER.PDF"]


def test_limit_pdf_files_selects_only_the_requested_prefix() -> None:
    files = [Path("one.pdf"), Path("two.pdf"), Path("three.pdf")]

    assert limit_pdf_files(files, 1) == [Path("one.pdf")]


def test_run_batch_moves_a_file_only_after_processing_completes(tmp_path: Path) -> None:
    source = tmp_path / "document.pdf"
    source.write_bytes(b"%PDF")
    archive_dir = tmp_path / "archived"
    calls: list[Path] = []

    async def process(path: Path) -> ProcessingResult:
        calls.append(path)
        return ProcessingResult(completed=True, detail="ready")

    summary = asyncio.run(
        run_batch(
            [source],
            archive_dir=archive_dir,
            process_file=process,
            execute=True,
        )
    )

    assert calls == [source]
    assert not source.exists()
    assert (archive_dir / "document.pdf").read_bytes() == b"%PDF"
    assert summary.completed == ["document.pdf"]
    assert summary.failed == []


def test_run_batch_keeps_a_failed_file_in_the_source_directory(tmp_path: Path) -> None:
    source = tmp_path / "broken.pdf"
    source.write_bytes(b"%PDF")
    archive_dir = tmp_path / "archived"

    async def process(_path: Path) -> ProcessingResult:
        return ProcessingResult(completed=False, detail="embedding failed")

    summary = asyncio.run(
        run_batch(
            [source],
            archive_dir=archive_dir,
            process_file=process,
            execute=True,
        )
    )

    assert source.exists()
    assert not archive_dir.exists()
    assert summary.completed == []
    assert summary.failed == [("broken.pdf", "embedding failed")]


def test_run_batch_dry_run_does_not_process_or_move_files(tmp_path: Path) -> None:
    source = tmp_path / "document.pdf"
    source.write_bytes(b"%PDF")
    archive_dir = tmp_path / "archived"
    calls: list[Path] = []

    async def process(path: Path) -> ProcessingResult:
        calls.append(path)
        return ProcessingResult(completed=True, detail="ready")

    summary = asyncio.run(
        run_batch(
            [source],
            archive_dir=archive_dir,
            process_file=process,
            execute=False,
        )
    )

    assert calls == []
    assert source.exists()
    assert not archive_dir.exists()
    assert summary.dry_run == ["document.pdf"]


def test_move_to_archive_does_not_overwrite_an_existing_file(tmp_path: Path) -> None:
    source = tmp_path / "document.pdf"
    source.write_bytes(b"new")
    archive_dir = tmp_path / "archived"
    archive_dir.mkdir()
    existing = archive_dir / "document.pdf"
    existing.write_bytes(b"old")

    try:
        move_to_archive(source, archive_dir)
    except FileExistsError:
        pass
    else:
        raise AssertionError("moving over an existing archived file must fail")

    assert source.read_bytes() == b"new"
    assert existing.read_bytes() == b"old"
