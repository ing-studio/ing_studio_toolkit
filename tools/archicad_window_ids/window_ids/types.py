"""Grouping windows into types and numbering the types Պ-01, Պ-02, ...

A type is: the same library part, the same width x height (to the millimetre) and the same values of the config's
type_params (panes, transom, mullions, frame). The sill height is where a window is placed, not what it is, so it is
not part of the type. Windows of one type that open to the other side (hand_param, "L" / "R") share its number with
a prime: Պ-03 and Պ-03' - the hand with more windows gets the plain number.

Numbers already given are kept: a type whose windows already carry Պ-04 stays Պ-04 on the next run. New types get
the lowest free numbers, in the order of the config's "order" - so the numbering does not depend on whether an
earlier run could write every ID (windows on a locked layer keep their old ID and are numbered like the first time)
and has no holes. --renumber numbers every type afresh.
"""
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from .util import mm, warn


@dataclass
class WindowType:
    number: int
    prime: int              # 0 = plain number, 1 = Պ-03' (the other opening side)
    hand: str
    windows: list = field(default_factory=list)
    label: str = ""

    @property
    def sample(self):
        return self.windows[0]

    @property
    def width(self):
        return self.sample.width

    @property
    def height(self):
        return self.sample.height

    @property
    def part(self):
        return self.sample.part

    def sills(self):
        return sorted({mm(w.sill) for w in self.windows})

    def per_floor(self):
        return dict(sorted(Counter(w.floor for w in self.windows).items()))


def base_key(w):
    return (w.part, mm(w.width), mm(w.height), tuple(sorted(w.params.items())))


def _reading_order(w):
    """Lowest story first, then top to bottom and left to right on the plan."""
    return (w.floor, -round(w.y, 1), round(w.x, 1))


def _group_order(order, members):
    first = min(_reading_order(w) for w in members)
    if order == "size":
        s = members[0]
        return (-mm(s.width) * mm(s.height), -mm(s.width), first)
    if order == "count":
        return (-len(members), first)
    return first  # "floor"


def label(cfg, number, primes):
    """Պ-03, Պ-03' (primes=1); a third opening side would be Պ-03''."""
    return f"{cfg['prefix']}{number:0{int(cfg.get('digits', 2))}d}{cfg.get('prime', chr(39)) * int(primes)}"


def assign(windows, cfg, renumber=False):
    """[WindowType] sorted by label; every window is in exactly one."""
    prefix, prime_mark = cfg["prefix"], cfg.get("prime", "'")
    existing = re.compile("^" + re.escape(prefix) + r"0*(\d+)(" + re.escape(prime_mark) + ")?$")

    groups = defaultdict(list)
    for w in windows:
        groups[base_key(w)].append(w)
    order = cfg.get("order", "floor")
    keys = sorted(groups, key=lambda k: _group_order(order, groups[k]))

    def old(w):
        m = existing.match((w.id or "").strip())
        return (int(m.group(1)), bool(m.group(2))) if m else None

    # numbers kept from the IDs the windows already carry: the most common one of each group, the group with more
    # votes wins a number two groups claim
    number = {}
    if not renumber and cfg.get("keep_existing", True):
        claims = []
        for k in keys:
            votes = Counter(o[0] for o in map(old, groups[k]) if o)
            if votes:
                n, c = votes.most_common(1)[0]
                claims.append((c, k, n))
        taken = set()
        for c, k, n in sorted(claims, key=lambda t: -t[0]):
            if n not in taken:
                number[k] = n
                taken.add(n)
            else:
                warn(f"types: {label(cfg, n, 0)} was used for two different types - one of them gets a new number")
    free = (n for n in range(1, len(keys) + len(number) + 2) if n not in set(number.values()))
    for k in keys:
        if k not in number:
            number[k] = next(free)

    types = []
    for k in keys:
        by_hand = defaultdict(list)
        for w in groups[k]:
            by_hand[w.hand].append(w)
        hands = sorted(by_hand, key=lambda h: (-len(by_hand[h]), min(_reading_order(w) for w in by_hand[h])))
        if len(hands) > 1 and not renumber and cfg.get("keep_existing", True):
            # the hand the windows already mark as the plain one keeps being it
            plain_votes = {h: sum(1 for w in by_hand[h] if (o := old(w)) and o[0] == number[k] and not o[1])
                           - sum(1 for w in by_hand[h] if (o := old(w)) and o[0] == number[k] and o[1])
                           for h in hands}
            best = max(hands, key=lambda h: plain_votes[h])
            if plain_votes[best] > 0:
                hands.remove(best)
                hands.insert(0, best)
        if len(hands) > 2:
            warn(f"types: {label(cfg, number[k], 0)} has windows with {len(hands)} different opening sides "
                 f"({', '.join(h or '-' for h in hands)})")
        for i, h in enumerate(hands):
            members = sorted(by_hand[h], key=_reading_order)
            types.append(WindowType(number=number[k], prime=i, hand=h, windows=members,
                                    label=label(cfg, number[k], i)))
    types.sort(key=lambda t: (t.number, t.prime))
    return types
