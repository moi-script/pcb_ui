"""Extract wiring coordinates (tracks + vias) from a KiCad PCB file.

kiutils does not support the KiCad 10 (version 2026xxxx) file format, so this
parses the s-expression directly. All coordinates are in millimetres.
"""


def parse_sexpr(text):
    """Parse KiCad s-expression text into nested Python lists/strings."""
    tokens = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c in "()":
            tokens.append(c)
            i += 1
        elif c == '"':                       # quoted string (may contain spaces)
            j = i + 1
            buf = []
            while j < n:
                if text[j] == "\\":          # escape
                    buf.append(text[j + 1])
                    j += 2
                elif text[j] == '"':
                    break
                else:
                    buf.append(text[j])
                    j += 1
            tokens.append('"' + "".join(buf))   # mark as string literal
            i = j + 1
        elif c.isspace():
            i += 1
        else:                                # bare atom
            j = i
            while j < n and text[j] not in '()" \t\r\n':
                j += 1
            tokens.append(text[i:j])
            i = j

    def build(pos):
        node = []
        while pos < len(tokens):
            tok = tokens[pos]
            if tok == "(":
                child, pos = build(pos + 1)
                node.append(child)
            elif tok == ")":
                return node, pos + 1
            else:
                node.append(tok)
                pos += 1
        return node, pos

    # Skip leading whitespace token handling; top level starts with '('
    tree, _ = build(1)   # tokens[0] is the opening '(' of (kicad_pcb ...)
    return tree


def tag(node):
    return node[0] if node and isinstance(node[0], str) else None


def find(node, name):
    """First direct child list with the given tag."""
    for child in node:
        if isinstance(child, list) and tag(child) == name:
            return child
    return None


def unquote(atom):
    return atom[1:] if isinstance(atom, str) and atom.startswith('"') else atom


def num(atom):
    return float(atom)


def extract_wiring(text):
    """Parse KiCad PCB s-expression text into a list of track/via dicts (mm).

    This is the importable entry point used by the web server; it takes the
    file *contents* so it works on any uploaded board, not just labExam.
    """
    board = parse_sexpr(text)
    wiring = []

    for node in board:
        if not isinstance(node, list):
            continue

        # 1. Track segments
        if tag(node) == "segment":
            start = find(node, "start")
            end = find(node, "end")
            width = find(node, "width")
            layer = find(node, "layer")
            net = find(node, "net")
            wiring.append({
                "type": "track",
                "net": unquote(net[1]) if net and len(net) > 1 else "N/A",
                "start": (num(start[1]), num(start[2])),   # mm
                "end": (num(end[1]), num(end[2])),         # mm
                "width_mm": num(width[1]),
                "layer": unquote(layer[1]),
            })

        # 2. Vias (none in labExam, but handled for completeness)
        elif tag(node) == "via":
            at = find(node, "at")
            size = find(node, "size")
            drill = find(node, "drill")
            net = find(node, "net")
            wiring.append({
                "type": "via",
                "net": unquote(net[1]) if net and len(net) > 1 else "N/A",
                "position": (num(at[1]), num(at[2])),      # mm
                "drill_mm": num(drill[1]) if drill else None,
                "size_mm": num(size[1]) if size else None,
            })

    return wiring


def read_file(path="newProject.kicad_pcb"):
    """Read a .kicad_pcb from disk and return its wiring data."""
    with open(path, "r", encoding="utf-8") as f:
        return extract_wiring(f.read())


# Backward-compatible module-level data, used by pcb_gcode.py and the CLI.
# Guarded so importing this module never fails if labExam isn't present.
try:
    wiring_data = read_file()
except FileNotFoundError:
    wiring_data = []


if __name__ == "__main__":
    print(f"Extracted {len(wiring_data)} wiring elements.")
    for row in wiring_data:
        print(row)
