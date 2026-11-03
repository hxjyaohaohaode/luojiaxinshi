"""Exact query-centered spans; never hide a tail match behind a head clip."""


def excerpt(text,terms,limit):
    if len(text)<=limit or not terms:return text[:limit],0
    lower=text.lower()
    # Rank a bounded set of match-centered windows by distinct query coverage.
    # Prefer the beginning on ties, retaining the surrounding original wording.
    positions={0}
    for term in terms:
        start=0
        for _ in range(8):
            hit=lower.find(term,start)
            if hit<0:break
            positions.add(max(0,min(len(text)-limit,hit-min(400,limit//4))))
            start=hit+max(1,len(term))
    def score(pos):
        view=lower[pos:pos+limit]
        return sum(min(len(term),8) for term in terms if term in view)
    start=max(sorted(positions),key=score)
    return text[start:start+limit],start
