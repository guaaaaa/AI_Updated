"""Generate assets/themes.css: the site's colour schemes (each a light and a dark mode).

Every colour is defined in OKLCH, a perceptual space, so a scheme's pastels share one lightness and softness and no
hue jumps out ("mix gently"). Category inks, chart series and the rising/fading pair are derived the same way, then
checked: text inks >= 4.5:1 on their glass, chart colours through the palette validator (lightness band, chroma,
adjacent colour-blind separation, contrast) when --validator points at it.

    python3 pipeline/make_themes.py [--validator path/to/validate_palette.js]

The site picks a scheme with <html data-palette="..."> (palette menu in the top bar, saved per browser).
"""
import json
import math
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets" / "themes.css"

# category slots (tag groups use these) at their default hues; a scheme may shift them
SLOTS = {"aqua": 205, "sky": 245, "lavender": 300, "rose": 355, "peach": 55, "mint": 160, "lime": 125}


# ---------------------------------------------------------------- colour maths
def oklch_to_rgb(L, C, h):
    a, b = C * math.cos(math.radians(h)), C * math.sin(math.radians(h))
    l_, m_, s_ = L + 0.3963377774 * a + 0.2158037573 * b, L - 0.1055613458 * a - 0.0638541728 * b, L - 0.0894841775 * a - 1.2914855480 * b
    l, m, s = l_ ** 3, m_ ** 3, s_ ** 3
    lin = (4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s, -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
           -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s)
    return [12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055 for c in lin]


def hexc(L, C, h):
    """OKLCH -> #rrggbb, reducing chroma until the colour fits in sRGB."""
    lo, hi = 0.0, C
    rgb = oklch_to_rgb(L, C, h)
    if not all(-1e-4 <= c <= 1 + 1e-4 for c in rgb):
        for _ in range(30):
            mid = (lo + hi) / 2
            if all(-1e-4 <= c <= 1 + 1e-4 for c in oklch_to_rgb(L, mid, h)):
                lo = mid
            else:
                hi = mid
        rgb = oklch_to_rgb(L, lo, h)
    return "#" + "".join(f"{round(min(1, max(0, c)) * 255):02x}" for c in rgb)


def rgb(hx):
    return [int(hx[i:i + 2], 16) / 255 for i in (1, 3, 5)]


def rgba(hx, a):
    r, g, b = (round(c * 255) for c in rgb(hx))
    return f"rgba({r}, {g}, {b}, {a})"


def mix(a, b, t):
    """t of b over a (sRGB)."""
    return "#" + "".join(f"{round((x * (1 - t) + y * t) * 255):02x}" for x, y in zip(rgb(a), rgb(b)))


def contrast(a, b):
    def lum(hx):
        r, g, b_ = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb(hx)]
        return 0.2126 * r + 0.7152 * g + 0.0722 * b_
    x, y = sorted((lum(a), lum(b)), reverse=True)
    return (x + 0.05) / (y + 0.05)


# ---------------------------------------------------------------- the schemes
# glows: (hue, L, C, alpha, where, size) ; series: hues for G&E, Trust, Capabilities, Science, Foundation, Training, News
SCHEMES = [
    {"id": "spring", "name": "Spring · Galaxy", "light_name": "Spring meadow", "dark_name": "Galaxy",
     "light": {"base": (0.987, 0.012, 135), "fillC": 0.058, "accent": 160, "news": 350,
               "glows": [(145, 0.93, 0.065, .85, "4% -8%", "900px 700px"), (232, 0.93, 0.045, .85, "100% 0%", "820px 640px"),
                         (305, 0.93, 0.045, .70, "94% 102%", "900px 720px"), (355, 0.94, 0.040, .75, "-4% 100%", "760px 600px"),
                         (105, 0.965, 0.050, .55, "50% 50%", "640px 520px")],
               "up": (140, 0.62, 0.14), "down": (265, 0.5, 0.13)},
     "dark": {"base": (0.17, 0.055, 282), "accent": 315, "news": 350, "stars": 3,
              "glows": [(305, 0.42, 0.16, .55, "96% -6%", "980px 760px"), (262, 0.38, 0.14, .50, "0% 0%", "900px 700px"),
                        (345, 0.46, 0.15, .32, "88% 104%", "880px 680px"), (210, 0.55, 0.10, .20, "-6% 96%", "760px 600px"),
                        (290, 0.30, 0.10, .30, "50% 55%", "700px 520px")],
              "up": (160, 0.66, 0.12), "down": (300, 0.53, 0.14)}},
    {"id": "blossom", "name": "Blossom · Twilight", "news_L": {"light": 0.46}, "light_name": "Cherry blossom", "dark_name": "Twilight",
     "light": {"base": (0.986, 0.012, 10), "fillC": 0.055, "accent": 335, "news": 18,
               "glows": [(355, 0.915, 0.072, .90, "4% -8%", "900px 700px"), (305, 0.925, 0.052, .78, "100% 0%", "820px 640px"),
                         (45, 0.94, 0.045, .72, "94% 102%", "900px 720px"), (165, 0.955, 0.035, .45, "-4% 100%", "760px 600px"),
                         (10, 0.96, 0.030, .55, "50% 50%", "640px 520px")],
               "up": (20, 0.64, 0.14), "down": (270, 0.49, 0.13)},
     "dark": {"base": (0.19, 0.045, 312), "accent": 350, "news": 20, "stars": 1,
              "glows": [(300, 0.42, 0.13, .48, "100% -4%", "900px 700px"), (275, 0.36, 0.11, .42, "0% 0%", "880px 680px"),
                        (350, 0.52, 0.11, .30, "50% 110%", "1200px 600px"), (40, 0.64, 0.09, .14, "-4% 100%", "760px 560px"),
                        (330, 0.40, 0.10, .22, "50% 40%", "800px 600px")],
              "up": (15, 0.66, 0.12), "down": (270, 0.53, 0.12)}},
    {"id": "lavender", "name": "Lavender · Starry night", "light_name": "Lavender haze", "dark_name": "Starry night",
     "light": {"base": (0.985, 0.013, 300), "fillC": 0.055, "accent": 292, "news": 330,
               "glows": [(300, 0.91, 0.072, .90, "4% -8%", "900px 700px"), (272, 0.92, 0.060, .85, "100% 0%", "820px 640px"),
                         (345, 0.94, 0.045, .62, "94% 102%", "900px 720px"), (170, 0.95, 0.040, .50, "-4% 100%", "760px 600px"),
                         (300, 0.96, 0.030, .50, "50% 50%", "640px 520px")],
               "up": (340, 0.64, 0.14), "down": (275, 0.47, 0.14)},
     "dark": {"base": (0.17, 0.060, 266), "accent": 280, "news": 330, "stars": 5,
              "glows": [(275, 0.40, 0.13, .46, "30% -10%", "1100px 700px"), (300, 0.38, 0.13, .36, "100% 40%", "820px 760px"),
                        (200, 0.40, 0.08, .26, "-4% 100%", "800px 620px"), (85, 0.72, 0.08, .10, "86% 6%", "360px 300px")],
              "up": (340, 0.67, 0.13), "down": (275, 0.54, 0.14)}},
    {"id": "seaglass", "name": "Sea glass · Moonlit sea", "light_name": "Sea glass", "dark_name": "Moonlit sea",
     "light": {"base": (0.986, 0.010, 200), "fillC": 0.052, "accent": 205, "news": 30,
               "glows": [(200, 0.91, 0.065, .90, "4% -8%", "900px 700px"), (240, 0.925, 0.052, .82, "100% 0%", "820px 640px"),
                         (25, 0.94, 0.040, .55, "94% 102%", "900px 720px"), (170, 0.92, 0.060, .80, "-4% 100%", "760px 600px"),
                         (190, 0.96, 0.030, .50, "50% 50%", "640px 520px")],
               "up": (235, 0.52, 0.12), "down": (52, 0.65, 0.13)},
     "dark": {"base": (0.17, 0.045, 238), "accent": 200, "news": 30, "stars": 1,
              "glows": [(195, 0.40, 0.09, .46, "-4% 100%", "900px 700px"), (270, 0.56, 0.05, .26, "90% -6%", "620px 520px"),
                        (250, 0.32, 0.09, .46, "0% 0%", "900px 700px"), (170, 0.40, 0.07, .22, "96% 100%", "760px 600px")],
              "up": (232, 0.56, 0.12), "down": (60, 0.65, 0.12)}},
    {"id": "wellness", "name": "Wellness · Aurora", "light_name": "Wellness", "dark_name": "Aurora",
     "light": {"base": (0.985, 0.008, 20), "fillC": 0.050, "accent": 205, "news": 42,
               "glows": [(205, 0.92, 0.045, .80, "4% -8%", "900px 700px"), (275, 0.93, 0.030, .90, "100% 0%", "820px 640px"),
                         (45, 0.92, 0.045, .72, "92% 102%", "900px 720px"), (355, 0.93, 0.035, .72, "-4% 100%", "760px 600px"),
                         (355, 0.97, 0.015, .65, "50% 50%", "640px 520px")],
               "up": (45, 0.64, 0.13), "down": (228, 0.52, 0.11)},
     "dark": {"base": (0.16, 0.040, 245), "accent": 175, "news": 42, "stars": 2,
              "glows": [(155, 0.62, 0.14, .42, "24% 3%", "1300px 250px"), (180, 0.58, 0.12, .36, "62% 11%", "1150px 230px"),
                        (300, 0.50, 0.14, .38, "92% 1%", "900px 360px"), (165, 0.50, 0.10, .22, "42% 22%", "1500px 190px"),
                        (250, 0.30, 0.08, .45, "50% 100%", "1200px 600px")],
              "up": (160, 0.66, 0.12), "down": (300, 0.56, 0.13)}},
]
SERIES = {   # validated as a set on light and dark chart surfaces (lightness band, chroma, adjacent colour-blind separation)
    "light": {"ge": "#c4772f", "trust": "#cc4f7c", "cap": "#1b87b8", "sci": "#76901c", "fm": "#8a6ad2", "train": "#1f9168"},
    "dark": {"ge": "#c4802f", "trust": "#d65d9c", "cap": "#3a98cc", "sci": "#82a02b", "fm": "#9a7ce0", "train": "#2aa17b"}}
NEWS_L = {"light": 0.50, "dark": 0.55}   # News sits next to Training: a lightness gap keeps the pair apart


def stars(n_layers):
    """Tiny tiled star dots for night skies (n_layers tiles of different sizes so the pattern does not repeat visibly)."""
    pts = [(31, 47), (143, 19), (211, 113), (89, 171), (277, 61), (17, 233), (181, 251), (257, 199), (121, 97), (61, 289)]
    out = []
    for k in range(n_layers):
        tile = 310 + 70 * k
        for i, (x, y) in enumerate(pts[k % 3::2]):
            a = (.75, .55, .9, .45)[(i + k) % 4]
            r = (1.1, .8, 1.4)[(i + k) % 3]
            out.append(f"radial-gradient({r}px {r}px at {(x * (k + 1)) % tile}px {(y * (k + 2)) % tile}px, rgba(255, 255, 255, {a}) 99%, "
                       f"transparent) 0 0 / {tile}px {tile}px")
    return out


def light_tokens(s):
    L = s["light"]
    bL, bC, bh = L["base"]
    base = hexc(bL, bC, bh)
    hues = dict(SLOTS, coral=L["news"])
    t = {}
    for k, h in hues.items():
        t[f"--{k}"] = hexc(0.905 if k != "coral" else 0.86, L["fillC"] + (0.025 if k == "coral" else 0), h)
        t[f"--{k}-ink"] = hexc(0.47, 0.10, h)
    t["--grad"] = f"linear-gradient(135deg, {hexc(.91, L['fillC'], L['glows'][0][0])} 0%, {hexc(.91, L['fillC'], L['glows'][1][0])} 52%, {hexc(.91, L['fillC'], L['glows'][3][0])} 100%)"
    t["--grad-warm"] = f"linear-gradient(135deg, {hexc(.91, .05, L['news'])} 0%, {hexc(.84, .08, L['news'])} 100%)"
    t["--logo"] = f"linear-gradient(135deg, {', '.join(hexc(.88, L['fillC'] + .01, g[0]) + f' {p}%' for g, p in zip(L['glows'][:4], (0, 40, 72, 100)))})"
    t["--base"] = base
    t["--scene"] = ",\n    ".join([f"radial-gradient({size} at {pos}, {rgba(hexc(gl, gc, gh), a)}, transparent 60%)" for gh, gl, gc, a, pos, size in L["glows"]]
                                    + [f"linear-gradient(180deg, {hexc(min(.995, bL + .006), bC * .7, bh)} 0%, {hexc(bL - .008, bC * 1.2, bh)} 100%)"])
    ink = hexc(0.30, 0.025, bh + 160 if bh < 200 else bh)
    shadow = hexc(0.40, 0.05, bh)
    t.update({"--glass": "rgba(255, 255, 255, .52)", "--glass-strong": "rgba(255, 255, 255, .72)", "--glass-soft": "rgba(255, 255, 255, .36)",
              "--glass-border": "rgba(255, 255, 255, .82)", "--glass-line": rgba(shadow, .08), "--chip-border": rgba(shadow, .12),
              "--chip-bg": "rgba(255, 255, 255, .58)", "--hi": "rgba(255, 255, 255, .38)",
              "--shadow": f"0 1px 1px {rgba(shadow, .05)}, 0 12px 32px -10px {rgba(shadow, .17)}",
              "--shadow-lift": f"0 2px 2px {rgba(shadow, .06)}, 0 18px 40px -12px {rgba(shadow, .24)}",
              "--text": hexc(0.29, 0.022, bh), "--muted": hexc(0.47, 0.022, bh), "--faint": hexc(0.53, 0.02, bh),
              "--accent": hexc(0.48, 0.10, L["accent"]),
              "--pill": "55%", "--tint": "30%", "--tint-border": "56%", "--on-fill": "60%", "--on-border": "90%"})
    del ink
    return t


def dark_tokens(s):
    D, Lt = s["dark"], s["light"]
    bL, bC, bh = D["base"]
    hues = dict(SLOTS, coral=D["news"])
    t = {}
    for k, h in hues.items():
        t[f"--{k}"] = hexc(0.84 if k != "coral" else 0.80, Lt["fillC"] + (0.035 if k == "coral" else 0.02), h)
        t[f"--{k}-ink"] = hexc(0.85, 0.075, h)
    t["--grad"] = f"linear-gradient(135deg, {hexc(.84, .07, D['glows'][0][0])} 0%, {hexc(.84, .07, D['glows'][1][0])} 55%, {hexc(.84, .07, D['glows'][2][0])} 100%)"
    t["--logo"] = f"linear-gradient(135deg, {', '.join(hexc(.82, .08, g[0]) + f' {p}%' for g, p in zip(D['glows'][:4], (0, 40, 72, 100)))})"
    t["--base"] = hexc(bL, bC, bh)
    layers = stars(D.get("stars", 0)) + [f"radial-gradient({size} at {pos}, {rgba(hexc(gl, gc, gh), a)}, transparent 62%)"
                                          for gh, gl, gc, a, pos, size in D["glows"]]
    t["--scene"] = ",\n    ".join(layers + [f"linear-gradient(180deg, {hexc(bL, bC, bh)} 0%, {hexc(bL + .025, bC * 1.1, bh + 8)} 100%)"])
    glass = hexc(0.24, bC * .9, bh)
    tint = hexc(0.88, 0.04, D["accent"])
    t.update({"--glass": rgba(glass, .55), "--glass-strong": rgba(hexc(0.30, bC, bh), .70), "--glass-soft": "rgba(255, 255, 255, .045)",
              "--glass-border": rgba(tint, .11), "--glass-line": "rgba(255, 255, 255, .07)", "--chip-border": rgba(tint, .15),
              "--chip-bg": "rgba(255, 255, 255, .045)", "--hi": rgba(tint, .07),
              "--sheen": "linear-gradient(180deg, rgba(255, 255, 255, .05) 0%, rgba(255, 255, 255, 0) 40%)",
              "--edge": f"linear-gradient(140deg, {rgba(tint, .26)} 0%, rgba(255, 255, 255, .04) 30%, rgba(255, 255, 255, 0) 55%, {rgba(hexc(.85, .06, D['glows'][1][0]), .16)} 100%)",
              "--shadow": f"0 1px 1px {rgba(hexc(.08, .03, bh), .3)}, 0 14px 36px -12px {rgba(hexc(.08, .03, bh), .65)}",
              "--shadow-lift": f"0 2px 2px {rgba(hexc(.08, .03, bh), .32)}, 0 20px 44px -12px {rgba(hexc(.08, .03, bh), .75)}",
              "--text": hexc(0.95, 0.012, bh), "--muted": hexc(0.82, 0.025, bh), "--faint": hexc(0.74, 0.03, bh),
              "--accent": hexc(0.84, 0.08, D["accent"]),
              "--pill": "20%", "--tint": "12%", "--tint-border": "32%", "--on-fill": "26%", "--on-border": "62%"})
    return t


def viz_tokens(s, mode):
    m = s[mode]
    t = {f"--viz-{k}": v for k, v in SERIES[mode].items()}
    t["--viz-news"] = hexc(s.get("news_L", {}).get(mode, NEWS_L[mode]), 0.14, m["news"])
    t["--viz-news-solo"] = hexc(0.60 if mode == "light" else 0.66, 0.12, m["news"])
    (uh, uL, uC), (dh, dL, dC) = m["up"], m["down"]
    t["--div-warm"], t["--div-cool"] = hexc(uL, uC, uh), hexc(dL, dC, dh)
    bL, bC, bh = m["base"]
    if mode == "light":
        t["--div-mid"] = hexc(0.93, 0.008, bh)
        t["--up-ink"], t["--down-ink"] = hexc(0.47, 0.11, uh), hexc(0.46, 0.10, dh)
        sh = hexc(0.40, 0.05, bh)
        t.update({"--viz-grid": rgba(sh, .10), "--viz-grid-strong": rgba(sh, .22), "--viz-context": rgba(sh, .26),
                  "--viz-surface": hexc(0.975, 0.008, bh)})
    else:
        t["--div-mid"] = hexc(0.30, 0.03, bh)
        t["--up-ink"], t["--down-ink"] = hexc(0.82, 0.09, uh), hexc(0.80, 0.09, dh)
        t.update({"--viz-grid": "rgba(255, 255, 255, .09)", "--viz-grid-strong": "rgba(255, 255, 255, .22)",
                  "--viz-context": "rgba(255, 255, 255, .26)", "--viz-surface": hexc(0.23, bC * .9, bh)})
    return t


def block(sel, tokens, indent="  "):
    body = "\n".join(f"{indent}  {k}: {v};" for k, v in tokens.items())
    return f"{indent}{sel} {{\n{body}\n{indent}}}"


def checks(s, lt, dt, validator):
    """Return a list of problems (empty = all good)."""
    bad = []
    # light text on white glass over the strongest glow; dark text on dark glass over the strongest glow
    lbg = [mix(hexc(g[1], g[2], g[0]), "#ffffff", .55) for g in s["light"]["glows"]] + [lt["--base"]]
    dglass = hexc(0.24, s["dark"]["base"][1] * .9, s["dark"]["base"][2])
    dbg = [mix(dglass, hexc(g[1], g[2], g[0]), min(.3, g[3] * .6)) for g in s["dark"]["glows"]] + [dt["--base"]]
    for mode, tok, bgs in (("light", lt, lbg), ("dark", dt, dbg)):
        for k in ["--text", "--muted", "--faint", "--accent"] + [f"--{x}-ink" for x in list(SLOTS) + ["coral"]] + ["--up-ink", "--down-ink"]:
            worst = min(contrast(tok[k], b) for b in bgs)
            if worst < 4.5:
                bad.append(f"{mode} {k} {tok[k]} contrast {worst:.2f}")
    if validator:
        for mode, tok in (("light", lt), ("dark", dt)):
            series = ",".join(tok[f"--viz-{k}"] for k in list(SERIES[mode]) + ["news"])
            pair = f"{tok['--div-warm']},{tok['--div-cool']}"
            for name, pal in (("series", series), ("rising/fading", pair)):
                r = subprocess.run(["node", validator, pal, "--mode", mode, "--surface", tok["--viz-surface"]], capture_output=True, text=True)
                for line in r.stdout.splitlines():
                    if "[FAIL]" in line or "[WARN]" in line:
                        bad.append(f"{mode} {name}: {line.strip()}")
    return bad


def main():
    validator = sys.argv[sys.argv.index("--validator") + 1] if "--validator" in sys.argv else None
    css = ["/* Generated by pipeline/make_themes.py -- edit the scheme definitions there, not this file. */"]
    report = {}
    for s in SCHEMES:
        lt, dt = light_tokens(s), dark_tokens(s)
        lt.update(viz_tokens(s, "light"))
        dt.update(viz_tokens(s, "dark"))
        sel = f':root[data-palette="{s["id"]}"]'
        css += [f"/* {s['name']}: light = {s['light_name']}, dark = {s['dark_name']} */", block(sel, lt, ""),
                "@media (prefers-color-scheme: dark) {", block(f'{sel}:not([data-theme="light"])', dt), "}",
                block(f'{sel}[data-theme="dark"]', dt, "")]
        report[s["id"]] = checks(s, lt, dt, validator)
    OUT.write_text("\n".join(css) + "\n", encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)} ({len(SCHEMES)} schemes)")
    for k, v in report.items():
        print(f"  {k}: {'all checks pass' if not v else ''}")
        for x in v:
            print(f"    {x}")
    (ROOT / "assets" / "themes.json").write_text(json.dumps([{"id": s["id"], "name": s["name"], "light": s["light_name"], "dark": s["dark_name"],
        "swatch": [hexc(.88, .07, g[0]) for g in s["light"]["glows"][:4]] + [hexc(.45, .12, g[0]) for g in s["dark"]["glows"][:2]]}
        for s in SCHEMES], indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
