"""Group headlines into stories (greedy word-overlap clustering). Shared by the field model and Week in review.

A headline is {"t": title, "p": publisher, "ts": "YYYY-MM-DD..."}; a story is
{"title", "date", "outlets" (distinct publishers), "n" (headlines), "text" (all its headlines)}.
"""
import re

STOP = set("""the a an of for and or in on with to from by at as is are be its it this that after over into says say said
will could would can may might amid about than more most just up out how why what who when report reports new ai
artificial intelligence""".split())


def tokens(title):
    return {w for w in re.findall(r"[a-z0-9$][a-z0-9$.\-']+", title.lower()) if w not in STOP and len(w) > 2}


def cluster(heads, min_shared=3, threshold=0.5, keep=False):
    clusters = []
    index = {}  # token -> cluster ids (keeps this fast for a month of headlines)
    for h in sorted(heads, key=lambda x: x["ts"]):
        tk = tokens(h["t"])
        if len(tk) < 3:
            continue
        cand = {}
        for w in tk:
            for ci in index.get(w, ()):
                cand[ci] = cand.get(ci, 0) + 1
        best, score = None, 0.0
        for ci, inter in sorted(cand.items()):  # lowest cluster id wins ties, whatever the hash order
            if inter < min_shared:
                continue
            j = inter / max(1, min(len(tk), len(clusters[ci]["seed"])))
            if j > score:
                best, score = ci, j
        if best is not None and score >= threshold:
            c = clusters[best]
            c["items"].append(h)
            c["pubs"].add(h["p"])
        else:
            best = len(clusters)
            clusters.append({"seed": tk, "items": [h], "pubs": {h["p"]}})
        for w in tk:
            index.setdefault(w, set()).add(best)
    out = [{"title": c["items"][0]["t"], "date": c["items"][0]["ts"][:10], "outlets": sorted(c["pubs"]),
            "n": len(c["items"]), "text": " | ".join(i["t"] for i in c["items"]), **({"items": c["items"]} if keep else {})}
           for c in clusters]
    out.sort(key=lambda s: (-len(s["outlets"]), s["date"]))
    return out
