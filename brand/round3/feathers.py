"""Generate emu plumage for the EMUlator: hundreds of tapered, drooping, hair-like strands
(emu feathers are double-shafted and hang loose), in a dark and a light tone, plus neck tufts.
Writes feathers-body.svgfrag / feathers-neck.svgfrag, spliced into emulator-mascot-v2.svg."""
import math, random
random.seed(7)
INK, DARK, MID, LIGHT = "#14100d", "#2e2722", "#4e4338", "#7a6c5c"

def strand(x, y, length, angle, width, curl):
    """A tapered strand from (x, y) hanging along `angle` (degrees, 90 = straight down)."""
    a = math.radians(angle)
    ex, ey = x + math.cos(a) * length, y + math.sin(a) * length
    # control point: bend sideways by `curl`
    nx, ny = -math.sin(a), math.cos(a)
    cx, cy = (x + ex) / 2 + nx * curl, (y + ey) / 2 + ny * curl
    hw = width / 2
    # two edges meeting in a point at the tip
    p = (f"M{x - nx*hw:.1f} {y - ny*hw:.1f} Q{cx - nx*hw*0.6:.1f} {cy - ny*hw*0.6:.1f} {ex:.1f} {ey:.1f} "
         f"Q{cx + nx*hw*0.6:.1f} {cy + ny*hw*0.6:.1f} {x + nx*hw:.1f} {y + ny*hw:.1f} Z")
    return p

def body():
    out = [f'<path d="M30 640 Q34 540 90 490 Q140 446 200 446 Q262 446 300 488 Q352 540 350 640 Z" fill="{DARK}" stroke="{INK}" stroke-width="7"/>']
    rows = []
    # the coat: rows of strands, drawn BOTTOM row first so each higher row hangs over the roots
    # of the one below - like shingles, the way real plumage lies
    for row in range(9):
        y0 = 452 + row * 20
        half = 62 + row * 18                     # wider further down
        cx = 196 + row * 2
        n = 10 + row * 4
        for i in range(n):
            x = cx - half + (2 * half) * (i + random.random() * 0.6) / n
            length = random.uniform(80, 130)
            ang = 90 + (x - cx) / half * 30 + random.uniform(-6, 6)   # droop down and outwards
            w = random.uniform(11, 18)
            curl = (x - cx) / half * 22 + random.uniform(-10, 10)    # the tips curl away from the middle
            col = random.choice([MID, MID, LIGHT, DARK])
            rows.append(f'<path d="{strand(x, y0, length, ang, w, curl)}" fill="{col}" stroke="{INK}" stroke-width="2.2"/>')
    return out + rows[::-1]

def neck():
    out = []
    # sparse droopy tufts down the front of the neck (follows the S-curve roughly)
    pts = [(268, 280), (262, 300), (252, 322), (240, 344), (228, 366), (220, 388), (216, 448), (222, 466)]
    for (x, y) in pts:
        for k in range(3):
            out.append(f'<path d="{strand(x + random.uniform(-6, 4), y + random.uniform(-4, 4), random.uniform(26, 40), random.uniform(70, 110), random.uniform(5, 8), random.uniform(-6, 6))}" '
                       f'fill="{random.choice([MID, LIGHT])}" stroke="{INK}" stroke-width="1.8"/>')
    return out

def crest():
    """The wild crest: plumes fanning up and back from the top/back of the head, longest at the
    back, every one curling a little backwards - a bad-hair-day emu, not a spiky helmet."""
    out = []
    for i in range(70):
        t = i / 69                                   # 0 = front (near the brow), 1 = back of the head
        x = 300 - t * 96 + random.uniform(-6, 6)
        y = 172 - math.sin(t * math.pi) * 14 + random.uniform(-4, 4)
        ang = -70 - t * 85 + random.uniform(-12, 12)    # front plumes stand up, back ones sweep back
        length = 50 + t * 70 + random.uniform(-10, 25)
        curl = -14 - t * 18 + random.uniform(-8, 8)     # tips curl backwards
        col = random.choice([DARK, MID, MID, LIGHT])
        out.append(f'<path d="{strand(x, y, length, ang, random.uniform(6, 11), curl)}" fill="{col}" stroke="{INK}" stroke-width="2"/>')
    random.shuffle(out)                              # a messy mop, not a neat fan
    return out

open("feathers-crest.svgfrag", "w").write("\n".join(crest()))
open("feathers-body.svgfrag", "w").write("\n".join(body()))
open("feathers-neck.svgfrag", "w").write("\n".join(neck()))
print(len(body()), "body strands")
