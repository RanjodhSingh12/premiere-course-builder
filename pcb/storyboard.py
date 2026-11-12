"""Read a course storyboard (.docx) into scenes.

Works with the common 5-column layout: Scene | Script (voiceover) | Word count | OST | Notes,
where the OST cell holds "<Title>  <title text>  <OST>  <lines...>". No python-docx needed.
"""
import html
import re
import zipfile


def _cell_text(xml):
    paras = re.findall(r"<w:p[ >].*?</w:p>", xml, re.S) or [xml]
    out = []
    for p in paras:
        t = "".join(re.findall(r"<w:t(?: [^>]*)?>([^<]*)</w:t>", p))
        t = html.unescape(t).strip()
        if t:
            out.append(t)
    return out


def read(path):
    """-> {"title": str|None, "scenes": [{"n", "name", "script": [lines], "title", "ost": [lines], "notes": [lines]}]}"""
    xml = zipfile.ZipFile(path).read("word/document.xml").decode("utf8")
    scenes, title = [], None
    for row in re.findall(r"<w:tr[ >].*?</w:tr>", xml, re.S):
        cells = [_cell_text(c) for c in re.findall(r"<w:tc>.*?</w:tc>", row, re.S)]
        if len(cells) < 4:
            continue
        first = cells[0]
        if title is None and len(cells) >= 2 and any("Video" in x or "Lesson" in x for x in cells[1]):
            title = " ".join(cells[1])
        if not first or not re.match(r"^\d+\.?$", first[0].strip()):
            continue
        n = int(first[0].strip().rstrip("."))
        ost = cells[3]
        s_title, lines, mode = None, [], None
        for x in ost:
            if x.strip().lower() == "<title>":
                mode = "title"
                continue
            if x.strip().lower() == "<ost>":
                mode = "ost"
                continue
            if mode == "title" and s_title is None:
                s_title = x.strip()
            elif mode == "ost":
                lines.append(x.strip())
        scenes.append({"n": n, "name": " ".join(first[1:]).strip(), "script": cells[1], "title": s_title,
                       "ost": lines, "notes": cells[4] if len(cells) > 4 else []})
    return {"title": title, "scenes": scenes}
