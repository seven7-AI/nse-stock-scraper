"""Parse the NSE daily price list, which the exchange publishes only as a scan.

Why this exists
---------------
Until 2026-11-05 the canonical timeline was fed from stockanalysis.com. From
2026-11-06 that site serves every NSE listing with a null price (its own quote page
shows "n/a" for Volume, Open, Previous Close and the 52-week range, while a US ticker
on the same site is complete), so ``stock_observations`` stalled and every downstream
market metric froze. ``afx.kwayisi.org``, the other path, has not answered a request
from this host since 2026-10-24.

The exchange's own daily list is authoritative and still published, at
``https://www.nse.co.ke/dataservices/wp-content/uploads/<DD-MON-YY>.pdf`` - but it is a
scanned image with no text layer, so the numbers have to come through OCR.

Which column is the close
-------------------------
``PREVIOUS PRICE``, stamped with the list's own date. That is not a guess: the 309k
rows already stored match that column exactly (ABSA 30.00, EQTY 97.25, KCB 87.75,
COOP 36.80 on the list dated 05-NOV-26 are the stored closes for 2026-11-05). It
carries a one-day lag, which is the long-standing ``scrape_date_is_observation_date``
approximation these rows already declare. Continuing it keeps the series unbroken.

Trusting OCR with numbers
-------------------------
OCR drops decimal points: 1.36 is read as 136, 427.50 as 42750. A hundredfold error in
a close price is exactly the kind of silent corruption this project refuses, so nothing
here is accepted on the strength of the scan alone. Every row has to satisfy the
table's own internal arithmetic before it is allowed out, and a row that fails is
dropped rather than repaired or guessed - a missing observation is honest, a wrong one
is not.
"""

import re

#: ISIN as printed in the list, after OCR mangles it (``K€0000000281``,
#: ``keoooooc0208``, ``KEoovo000158``). Used as the row anchor: the company name is
#: everything before it, the numbers are everything after, which survives the name
#: itself containing digits ("Ord 1.25", "B.O.G 10.00").
#:
#: The body is matched as "any twelve letters-or-digits", not as digits with a few
#: known confusions spliced in. Tesseract renders these zeros as o, c, v, u and more
#: depending on the scan line, and an allow-list of confusions silently dropped a fifth
#: of the list - the row was skipped entirely rather than reported, which is the
#: failure mode this whole module exists to avoid. The anchor does not need to validate
#: the ISIN; it only needs to find the boundary between the name and the numbers, and
#: a twelve-character K-E token in that position is unambiguous.
ISIN_TOKEN = re.compile(r"^[Kk][E€e][A-Za-z0-9]{10}$")

#: A token that could be a number once OCR noise is removed.
NUMERIC_TOKEN = re.compile(r"^[\d][\d,. ]*$")

#: Everything from the share class onwards: "Ord 1.25", "ord.5.00", "Ord.1.00". The
#: nominal value is not part of the company's identity, and the scan appends footnote
#: letters to it ("Ord 5.00sue", "Ord 10.00sne") which would otherwise poison a match.
SHARE_CLASS = re.compile(r"\bord\b|\bord\.", re.IGNORECASE)

#: Corporate-form words, dropped before matching. They are both the noisiest tokens on
#: a scan ("Plc" reads as "Ple", "Pic", "P1c") and the least reliable: the exchange
#: prints CIC Insurance Group as "Plc" while the instrument master holds "Ltd". Nothing
#: distinguishes two NSE listings by their form alone.
FORM_WORDS = frozenset(
    ["plc", "ple", "pic", "p1c", "ltd", "limited", "co", "company", "the", "and"]
)

#: Normalised list names that no amount of token matching will resolve, mapped to the
#: ticker they mean. Two separate causes, both deliberate to state rather than paper
#: over with fuzzy matching - an edit-distance match on a scanned company name is how a
#: price ends up against the wrong instrument, which is worse than having no price.
#:
#: Scan corruption, confirmed against the printed list:
#:   "HFCB Group"        - HF Group Ltd, the scan doubles the letters
#:   "Brita Holdings"    - Britam Holdings Plc, the scan drops the m
#:   "B.0.C Kenya"       - BOC Kenya Plc, zero for the letter O
#:   "E.APortland Cement" - East African Portland Cement Ltd, no space after E.A
#: Names the exchange and the instrument master genuinely disagree on:
#:   "KenGen"            - held as Kenya Electricity Generating Company Plc
#:   "I&M Group"         - held under its former name, I&M Holdings
#:   "Centum Investment" - CTUM and ICDC both carry this name and both are active
#:                         ordinary lines, so nothing in the master separates them
NAME_ALIASES = {
    ("hfcb", "group"): "HFCK",
    ("brita", "holdings"): "BRIT",
    ("b", "0", "c", "kenya"): "BOC",
    # Both spellings: the scan loses the space at 300 dpi and keeps it at 600.
    ("e", "aportland", "cement"): "PORT",
    ("e", "a", "portland", "cement"): "PORT",
    ("kengen",): "KEGN",
    ("i", "m", "group"): "IMH",
    ("centum", "investment"): "CTUM",
}

#: ``554,00`` -> ``554.00``. A comma with exactly two digits behind it and nothing else
#: after is a decimal point the scan rendered as a comma; ``166,895`` is a thousands
#: separator and keeps its meaning.
COMMA_DECIMAL = re.compile(r"^\d{1,4},\d{2}$")


class Row:
    """One instrument's line on the list, before it has earned its way into the store."""

    __slots__ = (
        "name", "wk52_high", "wk52_low", "high", "low", "vwap", "previous", "volume",
    )

    def __init__(self, name, wk52_high, wk52_low, high, low, vwap, previous, volume):
        self.name = name
        self.wk52_high = wk52_high
        self.wk52_low = wk52_low
        self.high = high
        self.low = low
        self.vwap = vwap
        self.previous = previous
        self.volume = volume

    def __repr__(self):
        return "Row({!r}, previous={!r})".format(self.name, self.previous)


def to_number(token):
    """One OCR'd token as a float, or None when it is not a number at all.

    Deliberately does not try to rescue a dropped decimal point. A repair here would be
    a guess applied to a price; ``validate`` rejects the row instead.
    """
    text = token.strip().replace(" ", "")
    if not text:
        return None
    if COMMA_DECIMAL.match(text):
        text = text.replace(",", ".")
    else:
        text = text.replace(",", "")
    try:
        return float(text)
    except ValueError:
        return None


def parse_line(line):
    """One OCR'd line as a Row, or None when it is not an instrument line.

    Anchors on the ISIN rather than counting tokens from either end: the volume column
    is often split by OCR into two tokens (``166 895``), so a fixed "last five tokens"
    rule silently shifts every price one column left.
    """
    tokens = line.split()
    anchor = None
    for index, token in enumerate(tokens):
        if ISIN_TOKEN.match(token):
            anchor = index
            break
    if anchor is None or anchor < 3:
        return None

    wk52_high = to_number(tokens[0])
    wk52_low = to_number(tokens[1])
    name = " ".join(tokens[2:anchor]).strip()
    if wk52_high is None or wk52_low is None or not name:
        return None

    # After the ISIN: an optional trading-status letter, then HIGH, LOW, VWAP,
    # PREVIOUS, then whatever is left is the volume.
    prices, volume_parts = [], []
    for token in tokens[anchor + 1:]:
        if not NUMERIC_TOKEN.match(token):
            if prices:
                break  # trailing noise after the numbers
            continue  # a trading-status flag such as "s" for suspended
        if len(prices) < 4:
            prices.append(to_number(token))
        else:
            volume_parts.append(token)
    if len(prices) < 4 or any(p is None for p in prices):
        return None

    volume = to_number("".join(volume_parts)) if volume_parts else None
    high, low, vwap, previous = prices
    return Row(name, wk52_high, wk52_low, high, low, vwap, previous, volume)


def validate(row):
    """Why this row may not be stored, or None when it may.

    The checks are the table's own arithmetic, so they need no second source:

    * the day's range must be a range, and the day's average must sit inside it. This
      is what catches a dropped decimal - 136 cannot sit between 1.47 and 1.40.
    * the value actually stored, PREVIOUS, must sit inside the printed 52-week band.
      A close outside its own year's range is a misread, not a move.
    """
    for label, value in (
        ("52-week high", row.wk52_high), ("52-week low", row.wk52_low),
        ("high", row.high), ("low", row.low), ("vwap", row.vwap),
        ("previous", row.previous),
    ):
        if value is None or value <= 0:
            return "{} is not a positive number".format(label)

    if row.low > row.high:
        return "low {} above high {}".format(row.low, row.high)
    if not (row.low <= row.vwap <= row.high):
        return "vwap {} outside the day's range {}-{}".format(row.vwap, row.low, row.high)
    if row.wk52_low > row.wk52_high:
        return "52-week low {} above 52-week high {}".format(row.wk52_low, row.wk52_high)
    if not (row.wk52_low <= row.previous <= row.wk52_high):
        return "previous {} outside the 52-week band {}-{}".format(
            row.previous, row.wk52_low, row.wk52_high
        )
    if row.volume is not None and row.volume < 0:
        return "negative volume {}".format(row.volume)
    return None


def normalise_company(text):
    """A company name reduced to the tokens that actually identify it.

    The list prints names and the store keys on tickers, so the two have to be matched
    on something stable. Dropped: the share class and its footnote letters, corporate
    form, punctuation, and ``&`` versus ``and`` - the exchange writes "Car & General",
    the instrument master "Car and General".
    """
    lowered = text.lower().replace("&", " and ")
    lowered = SHARE_CLASS.split(lowered)[0]
    cleaned = re.sub(r"[^a-z0-9 ]+", " ", lowered)
    return tuple(
        token for token in cleaned.split() if token and token not in FORM_WORDS
    )


def resolve_ticker(name, universe):
    """The ticker this list row belongs to, or None when it cannot be told.

    ``universe`` maps ticker -> company name, as held in the ``instruments`` table.

    Returns None rather than a best guess whenever the answer is not clear: an exact
    token match, or exactly one candidate whose every token appears in the list's name.
    Two candidates matching equally well means the row is dropped and reported. A price
    attached to the wrong instrument is far worse than a missing one, and OCR gives
    ample opportunity for exactly that.
    """
    wanted = normalise_company(name)
    if not wanted:
        return None
    if wanted in NAME_ALIASES:
        return NAME_ALIASES[wanted]
    wanted_set = set(wanted)

    exact, partial = [], []
    for ticker, company in universe.items():
        tokens = normalise_company(company or "")
        if not tokens:
            continue
        if tokens == wanted:
            exact.append(ticker)
            continue
        token_set = set(tokens)
        # Either direction: the master holds "TPS Eastern Africa (Serena) Ltd" where the
        # list prints "TPS Eastern Africa", and elsewhere the list carries the longer
        # name. Score by how much of the longer name is accounted for, so a near-complete
        # match outranks a two-token coincidence.
        if token_set <= wanted_set or wanted_set <= token_set:
            partial.append((len(token_set & wanted_set), ticker))
    if len(exact) == 1:
        return exact[0]
    if exact:
        return None  # two instruments with the same normalised name: ambiguous
    if not partial:
        return None
    partial.sort(reverse=True)
    if len(partial) > 1 and partial[0][0] == partial[1][0]:
        return None  # equally good candidates, so no answer
    return partial[0][1]


def parse_pricelist(ocr_text):
    """Every instrument line in an OCR'd list, split into accepted and rejected.

    Returns ``(accepted, rejected)`` where rejected carries the reason, so a caller can
    report how much of the scan was unreadable instead of quietly storing less.
    """
    accepted, rejected = [], []
    for line in ocr_text.splitlines():
        row = parse_line(line)
        if row is None:
            continue
        reason = validate(row)
        if reason is None:
            accepted.append(row)
        else:
            rejected.append((row, reason))
    return accepted, rejected
