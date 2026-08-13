#!/usr/bin/env python3
"""Extract plain text from the binary documents Zoli re-uploaded to Drive.

Usage: store/rag-venv/bin/python scripts/claude-archive-extract-docs.py <export-dir>

Reads <export-dir>/fajlok/ and writes one .txt per document into
<export-dir>/fajlok-szoveg/. PDFs go through pypdf, spreadsheets through
openpyxl, Word documents through the system `textutil`. Images are skipped.
Re-runnable: existing output files are left alone.
"""
import os
import subprocess
import sys

SKIP_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".heic", ".zip"}


def from_pdf(path):
    from pypdf import PdfReader
    reader = PdfReader(path)
    return "\n\n".join((page.extract_text() or "") for page in reader.pages)


def from_xlsx(path):
    import openpyxl
    book = openpyxl.load_workbook(path, data_only=True, read_only=True)
    out = []
    for sheet in book.worksheets:
        out.append(f"## {sheet.title}")
        for row in sheet.iter_rows(values_only=True):
            cells = [str(c) for c in row if c is not None]
            if cells:
                out.append(" | ".join(cells))
    return "\n".join(out)


def from_word(path):
    result = subprocess.run(["textutil", "-convert", "txt", "-stdout", path],
                            capture_output=True, timeout=120)
    return result.stdout.decode("utf-8", "replace")


def main():
    base = sys.argv[1]
    src = os.path.join(base, "fajlok")
    dst = os.path.join(base, "fajlok-szoveg")
    os.makedirs(dst, exist_ok=True)

    ok = skipped = failed = 0
    for name in sorted(os.listdir(src)):
        ext = os.path.splitext(name)[1].lower()
        if ext in SKIP_EXT:
            skipped += 1
            continue
        out_path = os.path.join(dst, name + ".txt")
        if os.path.exists(out_path):
            skipped += 1
            continue
        path = os.path.join(src, name)
        try:
            if ext == ".pdf":
                text = from_pdf(path)
            elif ext in (".xlsx", ".xlsm"):
                text = from_xlsx(path)
            elif ext in (".docx", ".doc", ".rtf"):
                text = from_word(path)
            elif ext in (".md", ".txt", ".log", ".json", ".py"):
                text = open(path, errors="replace").read()
            else:
                skipped += 1
                continue
        except Exception as exc:
            print(f"HIBA {name}: {exc}")
            failed += 1
            continue
        text = (text or "").strip()
        if len(text) < 30:
            print(f"URES {name} ({len(text)} karakter)")
            failed += 1
            continue
        with open(out_path, "w") as fh:
            fh.write(text)
        ok += 1
    print(f"kinyerve: {ok} | kihagyva: {skipped} | sikertelen: {failed}")


if __name__ == "__main__":
    main()
