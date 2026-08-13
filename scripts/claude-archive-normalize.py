#!/usr/bin/env python3
"""Normalize a claude.ai data export into a browsable markdown tree.

Usage: python3 scripts/claude-archive-normalize.py <export-dir>

<export-dir> is the dated archive directory containing raw/ (the unzipped export).
Writes md/ (one file per conversation), projects/ (one file per project doc) and
INDEX.md next to raw/. Re-runnable: existing output is replaced.
"""
import json
import os
import re
import sys
import unicodedata

TRANSLIT = str.maketrans({
    "á": "a", "é": "e", "í": "i", "ó": "o", "ö": "o", "ő": "o",
    "ú": "u", "ü": "u", "ű": "u",
})


def slug(text, limit=60):
    text = (text or "").lower().translate(TRANSLIT)
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return (text[:limit].rstrip("-")) or "cim-nelkul"


def message_text(msg):
    """Prefer the flat text field; fall back to text blocks in content."""
    if msg.get("text"):
        return msg["text"]
    parts = []
    for block in msg.get("content") or []:
        if isinstance(block, dict) and block.get("type") == "text" and block.get("text"):
            parts.append(block["text"])
    return "\n\n".join(parts)


RESULT_LIMIT = 2000
THINKING_LIMIT = 1500

# claude.ai renders tool blocks as this placeholder in the flat text field; the real
# payload only exists in content[]. Strip it so the rendered blocks stand alone.
PLACEHOLDER = re.compile(r"```\s*\n?This block is not supported on your current device yet\.\s*\n?```\s*", re.I)


def clip(text, limit):
    text = str(text)
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n\n_[levagva, meg {len(text) - limit:,} karakter a raw JSON-ben]_"


def render_blocks(msg):
    """Render thinking / tool_use / tool_result blocks that the text field drops."""
    out = []
    for block in msg.get("content") or []:
        if not isinstance(block, dict):
            continue
        kind = block.get("type")

        if kind == "thinking":
            body = (block.get("thinking") or block.get("text") or "").strip()
            if body:
                out += ["<details><summary>Gondolatmenet</summary>", "",
                        clip(body, THINKING_LIMIT), "", "</details>", ""]

        elif kind == "tool_use":
            name = block.get("name") or "?"
            inp = block.get("input") or {}
            out += [f"**Eszkoz: {name}**", ""]
            for key, value in inp.items():
                if isinstance(value, str) and "\n" in value:
                    out += [f"_{key}:_", "", "```", clip(value, RESULT_LIMIT * 4), "```", ""]
                else:
                    out.append(f"- _{key}:_ `{clip(value, 400)}`")
            if inp and not any("\n" in str(v) for v in inp.values()):
                out.append("")

        elif kind == "tool_result":
            name = block.get("name") or "?"
            content = block.get("content")
            body = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False, indent=1)
            if body and body != "null":
                out += [f"<details><summary>Eredmeny: {name}</summary>", "", "```",
                        clip(body, RESULT_LIMIT), "```", "", "</details>", ""]
    return out


def yaml_escape(value):
    return '"' + str(value).replace('"', '\\"') + '"'


def write_conversations(raw, outdir):
    conversations = json.load(open(os.path.join(raw, "conversations.json")))
    rows = []
    for conv in conversations:
        created = (conv.get("created_at") or "")[:10] or "0000-00-00"
        short = (conv.get("uuid") or "")[:8]
        name = f"{created}_{slug(conv.get('name'))}_{short}.md"
        messages = conv.get("chat_messages") or []

        lines = [
            "---",
            f"uuid: {conv.get('uuid')}",
            f"cim: {yaml_escape(conv.get('name') or '(cim nelkul)')}",
            f"letrehozva: {conv.get('created_at')}",
            f"modositva: {conv.get('updated_at')}",
            f"uzenetek: {len(messages)}",
            "forras: claude.ai export",
            "---",
            "",
            f"# {conv.get('name') or '(cim nelkul)'}",
            "",
        ]
        if conv.get("summary"):
            lines += [f"> {conv['summary']}", ""]

        for msg in messages:
            who = "Zoli" if msg.get("sender") == "human" else "Claude"
            stamp = (msg.get("created_at") or "")[:19].replace("T", " ")
            lines.append(f"## {who} &middot; {stamp}".replace("&middot;", "|"))
            lines.append("")
            body = PLACEHOLDER.sub("", message_text(msg)).strip()
            rendered = render_blocks(msg)
            if body:
                lines += [body, ""]
            elif not rendered:
                lines += ["_(nincs szoveges tartalom)_", ""]
            lines += rendered

            for att in msg.get("attachments") or []:
                fname = att.get("file_name") or "?"
                content = att.get("extracted_content") or ""
                lines.append(f"<details><summary>Csatolmany: {fname}</summary>")
                lines.append("")
                lines.append(content.strip() or "_(ures)_")
                lines.append("")
                lines.append("</details>")
                lines.append("")

            missing = [f.get("file_name") or "?" for f in msg.get("files") or []]
            if missing:
                lines.append(f"_[hianyzo fajl: {', '.join(missing)}]_")
                lines.append("")

        with open(os.path.join(outdir, name), "w") as fh:
            fh.write("\n".join(lines))
        rows.append((created, conv.get("name") or "(cim nelkul)", len(messages), name))
    return rows


def write_projects(raw, outdir):
    rows = []
    projects_dir = os.path.join(raw, "projects")
    if not os.path.isdir(projects_dir):
        return rows
    for path in sorted(os.listdir(projects_dir)):
        if not path.endswith(".json"):
            continue
        project = json.load(open(os.path.join(projects_dir, path)))
        docs = project.get("docs") or []
        pslug = slug(project.get("name"))
        pdir = os.path.join(outdir, pslug)
        os.makedirs(pdir, exist_ok=True)
        chars = 0
        for index, doc in enumerate(docs, 1):
            content = doc.get("content") or ""
            chars += len(content)
            fname = f"{index:03d}_{slug(doc.get('filename') or doc.get('uuid'), 50)}.md"
            with open(os.path.join(pdir, fname), "w") as fh:
                fh.write(f"# {doc.get('filename') or '(nevtelen)'}\n\n{content}\n")
        rows.append((project.get("name") or "?", len(docs), chars, pslug))
    return rows


def main():
    base = sys.argv[1] if len(sys.argv) > 1 else "."
    raw = os.path.join(base, "raw")
    md = os.path.join(base, "md")
    pj = os.path.join(base, "projektek")
    os.makedirs(md, exist_ok=True)
    os.makedirs(pj, exist_ok=True)

    conv_rows = write_conversations(raw, md)
    proj_rows = write_projects(raw, pj)

    lines = ["# Claude archivum", "",
             f"{len(conv_rows)} beszelgetes, {sum(r[2] for r in conv_rows)} uzenet.", ""]
    if proj_rows:
        lines += ["## Projektek", ""]
        for name, count, chars, pslug in sorted(proj_rows, key=lambda r: -r[2]):
            lines.append(f"- **{name}** ({count} dokumentum, {chars:,} karakter) `projektek/{pslug}/`")
        lines.append("")
    lines += ["## Beszelgetesek", ""]
    for created, name, count, fname in sorted(conv_rows, reverse=True):
        lines.append(f"- `{created}` [{name}](md/{fname}) ({count} uzenet)")
    with open(os.path.join(base, "INDEX.md"), "w") as fh:
        fh.write("\n".join(lines) + "\n")

    print(f"beszelgetes: {len(conv_rows)} | projekt: {len(proj_rows)} | index: {base}/INDEX.md")


if __name__ == "__main__":
    main()
