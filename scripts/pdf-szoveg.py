"""PDF-szoveg CID-fontos fajlbol, FONTONKENTI ToUnicode terkeppel.

Miert kellett a fontonkenti bontas: az elso valtozat OSSZEVONTA a CMap-eket, es
a fontok kodjai utkoztek -- a "KERESKEDESI" szo K-ja egy masik font emojijakent
jott ki. Egy szabalyzatnal ez elfogadhatatlan: nem talalgatunk betut.
Az ut: /Fn -> font-objektum -> /ToUnicode objektum -> annak a CMap-je, es a
tartalom-streamben kovetjuk, melyik font aktiv (Tf operator).
KORLAT: csak tomoritetlen objektum-szerkezetnel mukodik (/ObjStm nelkul).
"""
import re, sys, zlib

nyers = open(sys.argv[1], "rb").read()

objs = {}
for m in re.finditer(rb"(\d+)\s+0\s+obj(.*?)endobj", nyers, re.S):
    objs[int(m.group(1))] = m.group(2)

def stream_of(o):
    m = re.search(rb"stream\r?\n(.*?)endstream", o, re.S)
    if not m: return None
    try: return zlib.decompress(m.group(1))
    except zlib.error: return m.group(1)

def cmap_from(d):
    cm = {}
    if not d: return cm
    for blokk in re.findall(rb"beginbfchar(.*?)endbfchar", d, re.S):
        for src, dst in re.findall(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", blokk):
            cm[int(src,16)] = bytes.fromhex(dst.decode()).decode("utf-16-be","replace")
    for blokk in re.findall(rb"beginbfrange(.*?)endbfrange", d, re.S):
        for lo, hi, dst in re.findall(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", blokk):
            k = int(dst,16)
            for i in range(int(lo,16), int(hi,16)+1):
                cm[i] = chr(k + (i - int(lo,16)))
    return cm

# font-objektum -> sajat cmap
font_cmap = {}
for num, o in objs.items():
    m = re.search(rb"/ToUnicode\s+(\d+)\s+0\s+R", o)
    if m:
        font_cmap[num] = cmap_from(stream_of(objs.get(int(m.group(1)), b"")))

# /Fn nev -> font-objektum
nev_obj = {}
for m in re.finditer(rb"/Font\s*<<(.*?)>>", nyers, re.S):
    for nev, num in re.findall(rb"/(F\d+)\s+(\d+)\s+0\s+R", m.group(1)):
        nev_obj[nev.decode()] = int(num)
print("fontok: %s | cmapek: %d" % (sorted(nev_obj), len(font_cmap)), file=sys.stderr)

sorok, akt, cm = [], [], {}
for num, o in sorted(objs.items()):
    d = stream_of(o)
    if not d or (b"Tj" not in d and b"TJ" not in d): continue
    for m in re.finditer(rb"/(F\d+)[\s\d.]*Tf|<([0-9A-Fa-f]+)>\s*Tj|\bET\b", d):
        if m.group(1):
            cm = font_cmap.get(nev_obj.get(m.group(1).decode(), -1), {})
        elif m.group(2):
            h = m.group(2).decode()
            akt.append("".join(cm.get(int(h[i:i+4],16), "�") for i in range(0,len(h),4)))
        else:
            if akt: sorok.append("".join(akt)); akt = []
    if akt: sorok.append("".join(akt)); akt = []

ki = "\n".join(s for s in sorok if s.strip())
sys.stdout.write(ki + "\n")
print("ismeretlen glifa: %d" % ki.count("�"), file=sys.stderr)
