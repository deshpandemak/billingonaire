#!/usr/bin/env python3
"""
BHC Status Verifier — cross-checks billing-derived case status against the
LIVE status shown on the Bombay High Court case-status portal.

Built on top of the case-search / session logic from
bhc_order_downloader_v7pp_with_url_audit.py (same Portal.search() call),
but instead of downloading order PDFs, this script parses the case-status
page itself for:
  - Party Name (Petitioner vs Respondent)
  - Case Status  (the portal usually shows something like
    "Disposed" / "Pending" / "DISPOSED OF" near the party name block)

It then logs, per case:
  Sr, Case, BillingStatus, PortalStatus, PartyName, Match/Mismatch,
  StillOngoing2026-27 (Yes/No), DateChecked

IMPORTANT — READ BEFORE RUNNING
--------------------------------
1. This must be run on a machine with network access to
   https://bombayhighcourt.gov.in — it will NOT work in a sandboxed
   environment without that access.
2. The exact HTML layout of the "Status" field near the party name has
   NOT been verified against a live page (no portal access was available
   while writing this script). Run with --debug first on a SMALL sample
   (e.g. --only 1,2,3) — it will dump the raw case-detail HTML section to
   ./bhc_status_check/debug_html/ so you can confirm the extraction is
   reading the right element. If the auto-detected status looks wrong,
   send me one of those dumped HTML files and I will lock in the exact
   selector for you.
3. Uses the same polite rate limiting as the original script
   (DELAY_SECONDS = 6) to avoid hammering the portal.

USAGE
-----
    python3 bhc_status_verifier.py --input case_list_for_portal_check.csv --debug --only 1,2,3
    python3 bhc_status_verifier.py --input case_list_for_portal_check.csv --only-ongoing
    python3 bhc_status_verifier.py --input case_list_for_portal_check.csv --all

SPEED
-----
    Add --workers N to run N independent sessions in parallel (each still
    respects --delay between ITS OWN requests). Start moderate:

        python3 bhc_status_verifier.py --input case_list_for_portal_check.csv --only-ongoing --workers 4

    4 workers at the default 6s delay finishes roughly 4x faster than the
    single-session run. Don't jump straight to a high worker count on a
    government portal - if you start seeing SEARCH_ERROR rows pile up or
    NOT_FOUND_ON_PORTAL where you expect real cases, drop back to fewer
    workers or a longer --delay.
"""

import argparse
import csv
import queue
import re
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    sys.exit("Run:  pip install requests beautifulsoup4")

sys.path.insert(0, str(Path(__file__).resolve().parent))
from court_http import mount_court_adapter  # noqa: E402

CASE_STATUS_URL = "https://bombayhighcourt.gov.in/bhc/casestatus/casenumber"
CASE_TYPES_URL = "https://bombayhighcourt.gov.in/bhc/get-case-types-by-side"
SIDE = "1"
TIMEOUT = 45
DELAY_SECONDS = 6
OUT_DIR = Path("bhc_status_check")
DEBUG_DIR = OUT_DIR / "debug_html"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

# Keywords that indicate a disposed / closed matter when found in the status text
DISPOSAL_KEYWORDS = [
    "DISPOSED",
    "WITHDRAWN",
    "DISMISSED",
    "STRUCK",
    "DECIDED",
    "CLOSED",
]
PENDING_KEYWORDS = ["PENDING", "ONGOING", "ADMITTED", "ADMIT"]


def base_type(ct):
    return re.sub(r"\(ST\)$", "", ct, flags=re.IGNORECASE).strip()


def stampreg(ct):
    return "S" if ct.upper().endswith("(ST)") else "R"


class Portal:
    def __init__(self):
        self.s = None
        self.csrf = None
        self.hidden = {}
        self.type_options = []
        self.reinit()

    def reinit(self):
        self.s = requests.Session()
        # The court requires legacy TLS renegotiation; without this every
        # request fails in the handshake. See court_http.
        mount_court_adapter(self.s)
        self.s.headers["User-Agent"] = UA
        self.refresh()
        try:
            self.load_types()
        except requests.RequestException:
            pass

    def refresh(self):
        r = self.s.get(CASE_STATUS_URL, timeout=TIMEOUT)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        meta = soup.find("meta", attrs={"name": "csrf-token"})
        self.csrf = meta.get("content", "") if meta else ""
        self.hidden = {
            i.get("name"): i.get("value", "")
            for i in soup.find_all("input", type="hidden")
            if i.get("name")
        }

    def load_types(self):
        r = self.s.get(CASE_TYPES_URL, params={"side": SIDE}, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
        self.type_options = data if isinstance(data, list) else []

    def resolve_type(self, ct):
        want = base_type(ct).upper()
        aliases = {
            "WP": ("WP", "WRIT PETITION"),
            "CP": ("CP", "CONTEMPT PETITION"),
            "IA": ("IA", "INTERIM APPLICATION", "INTERLOCUTORY APPLICATION"),
            "PIL": ("PIL", "PUBLIC INTEREST LITIGATION"),
            "RPW": ("RPW",),
        }
        fallback = None
        for opt in self.type_options:
            label = str(opt.get("type_name") or opt.get("name") or "").upper().strip()
            head = label.split(" - ")[0].strip()
            fw = head.split()[0] if head else ""
            matched = any(
                fw == a or head == a or head.startswith(a + " ")
                for a in aliases.get(want, (want,))
            )
            if not matched:
                continue
            v = str(opt.get("case_type") or opt.get("value") or want)
            if str(opt.get("type_flag", "")) == "1":
                return v
            if fallback is None:
                fallback = v
        return fallback or want

    def _post_search(self, ct, number, year):
        form = dict(self.hidden)
        form.update(
            {
                "side": SIDE,
                "stampreg": stampreg(ct),
                "case_type": self.resolve_type(ct),
                "case_no": number,
                "year": year,
            }
        )
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": CASE_STATUS_URL,
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "X-CSRF-TOKEN": self.csrf or "",
        }
        r = self.s.post(
            CASE_STATUS_URL,
            data=form,
            headers=headers,
            timeout=TIMEOUT,
            allow_redirects=True,
        )
        if r.status_code == 419:
            self.refresh()
            form.update(self.hidden)
            headers["X-CSRF-TOKEN"] = self.csrf or ""
            r = self.s.post(
                CASE_STATUS_URL,
                data=form,
                headers=headers,
                timeout=TIMEOUT,
                allow_redirects=True,
            )
        if r.status_code not in (200, 302):
            raise requests.HTTPError(f"HTTP {r.status_code} on POST")
        try:
            data = r.json()
            if not data.get("status"):
                return None
            html = data.get("page", "") or None
            return html
        except ValueError:
            return r.text

    def search(self, ct, number, year):
        """Search with retry logic - mirrors download_pdf()'s retry pattern in
        the original downloader script, since the BHC portal drops connections
        intermittently under load (RemoteDisconnected / read timeouts).

        Attempt 1: normal request
        Attempt 2: wait 10s, retry
        Attempt 3: wait 20s, reinit session (fresh cookies + CSRF), retry
        """
        last_err = None
        for attempt in range(1, 4):
            try:
                return self._post_search(ct, number, year)
            except (
                requests.exceptions.ConnectionError,
                requests.exceptions.ChunkedEncodingError,
            ) as e:
                last_err = e
                if attempt == 1:
                    print(
                        f"   connection dropped, retrying in 10s (attempt {attempt}/3)..."
                    )
                    time.sleep(10)
                elif attempt == 2:
                    print(
                        f"   connection dropped again, reiniting session and retrying in 20s (attempt {attempt}/3)..."
                    )
                    time.sleep(20)
                    try:
                        self.reinit()
                    except Exception:
                        pass
            except requests.exceptions.Timeout as e:
                last_err = e
                if attempt < 3:
                    print(f"   timeout on attempt {attempt}/3, waiting 15s...")
                    time.sleep(15)
        raise last_err


def extract_status_and_parties(html):
    """
    Best-effort extraction of Party Name + Case Status from the case-status
    page HTML. Tries several common patterns since the exact layout has not
    been verified against a live page. Returns (status_text, party_text,
    method_used) so you can see which heuristic fired.

    If none of the heuristics find anything, status_text/party_text will be
    empty strings and method_used will be "NOT_FOUND" — check the debug HTML
    dump for that case and adjust the selectors below.
    """
    soup = BeautifulSoup(html, "html.parser")
    full_text = soup.get_text(" ", strip=True)

    status_text = ""
    party_text = ""
    method = "NOT_FOUND"

    # Heuristic 1: a <label> or <th>/<td> whose text is roughly "Status"
    # followed by a sibling containing the value.
    for tag in soup.find_all(["label", "th", "td", "span", "div", "strong"]):
        label = tag.get_text(strip=True)
        if label.upper() in ("STATUS", "CASE STATUS", "CASE STAGE", "STAGE"):
            # look at next sibling element, or parent's next cell
            sib = tag.find_next_sibling()
            if sib and sib.get_text(strip=True):
                status_text = sib.get_text(strip=True)
                method = f"LABEL_SIBLING:{label}"
                break
            parent = tag.parent
            if parent:
                sibs = parent.find_all_next(limit=3)
                for s in sibs:
                    t = s.get_text(strip=True)
                    if t and t.upper() != label.upper():
                        status_text = t
                        method = f"PARENT_NEXT:{label}"
                        break
            if status_text:
                break

    # Heuristic 2: scan the whole page text for a disposal/pending keyword
    if not status_text:
        upper_text = full_text.upper()
        for kw in DISPOSAL_KEYWORDS + PENDING_KEYWORDS:
            if kw in upper_text:
                # grab a short window of context around the keyword
                idx = upper_text.find(kw)
                status_text = full_text[max(0, idx - 20) : idx + 40].strip()
                method = f"KEYWORD_SCAN:{kw}"
                break

    # Party name: look for "Petitioner" / "Respondent" / "Party" labels
    for tag in soup.find_all(["label", "th", "td", "span", "div", "strong"]):
        label = tag.get_text(strip=True)
        if label.upper() in (
            "PETITIONER",
            "PARTY NAME",
            "PARTIES",
            "PETITIONER VS RESPONDENT",
        ):
            sib = tag.find_next_sibling()
            if sib and sib.get_text(strip=True):
                party_text = sib.get_text(strip=True)
                break
            parent = tag.parent
            if parent and parent.get_text(strip=True):
                party_text = parent.get_text(strip=True)
                break

    return status_text, party_text, method


def classify_status(status_text):
    """Map raw extracted status text to DISPOSED / PENDING / UNKNOWN."""
    if not status_text:
        return "UNKNOWN"
    up = status_text.upper()
    if any(kw in up for kw in DISPOSAL_KEYWORDS):
        return "DISPOSED"
    if any(kw in up for kw in PENDING_KEYWORDS):
        return "PENDING"
    return "UNKNOWN"


def load_input(path):
    rows = []
    with open(path, newline="") as f:
        r = csv.DictReader(f)
        for row in r:
            rows.append(row)
    return rows


def process_case(portal, row, args, writer, write_lock, print_lock, idx, total):
    sr = row["Sr"]
    ct, no, yr = row["CaseType"], row["CaseNo"], row["CaseYear"]
    label = row.get("CaseLabel", f"{ct}/{no}/{yr}")
    billing_status = row.get("BillingStatus", "")

    with print_lock:
        print(f"[{idx}/{total}] Sr {sr}: {label}  (billing status: {billing_status})")

    try:
        html = portal.search(ct, no, yr)
    except requests.RequestException as e:
        with print_lock:
            print(f"   Sr {sr} SEARCH FAILED: {e}")
        with write_lock:
            writer.writerow(
                [sr, label, billing_status, "SEARCH_ERROR", "", "", "", "", "", ""]
            )
        return

    if not html:
        with print_lock:
            print(
                f"   Sr {sr}: portal returned no result (status=false) — case not found"
            )
        with write_lock:
            writer.writerow(
                [
                    sr,
                    label,
                    billing_status,
                    "NOT_FOUND_ON_PORTAL",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                ]
            )
        return

    if args.debug:
        debug_file = (
            DEBUG_DIR / f"sr{sr}_{ct.replace('(', '').replace(')', '')}_{no}_{yr}.html"
        )
        debug_file.write_text(html, encoding="utf-8", errors="ignore")

    status_raw, party_name, method = extract_status_and_parties(html)
    portal_status = classify_status(status_raw)

    billing_is_disposed = billing_status.upper() == "DISPOSED"
    portal_is_disposed = portal_status == "DISPOSED"

    if portal_status == "UNKNOWN":
        match = "COULD_NOT_VERIFY"
    elif billing_is_disposed == portal_is_disposed:
        match = "MATCH"
    else:
        match = "MISMATCH"

    still_ongoing_2627 = (
        "No"
        if portal_is_disposed
        else ("Yes" if portal_status == "PENDING" else "UNVERIFIED")
    )

    with print_lock:
        print(
            f"   Sr {sr}: '{status_raw[:60]}' -> {portal_status}  ({method})  | match: {match}"
        )

    with write_lock:
        writer.writerow(
            [
                sr,
                label,
                billing_status,
                status_raw,
                portal_status,
                method,
                party_name,
                match,
                still_ongoing_2627,
                datetime.now().strftime("%Y-%m-%d %H:%M"),
            ]
        )


def worker_loop(worker_id, case_queue, args, writer, write_lock, print_lock, total):
    """Each worker gets its OWN Portal (own session/cookies/CSRF) so workers
    don't fight over shared session state. Workers stagger their startup
    slightly so they don't all hit the portal in the exact same instant."""
    time.sleep(worker_id * 1.5)
    with print_lock:
        print(f"[worker {worker_id}] initialising session ...")
    try:
        portal = Portal()
    except Exception as e:
        with print_lock:
            print(f"[worker {worker_id}] FAILED TO INIT: {e}")
        return

    while True:
        try:
            idx, row = case_queue.get_nowait()
        except queue.Empty:
            break
        process_case(portal, row, args, writer, write_lock, print_lock, idx, total)
        case_queue.task_done()
        time.sleep(args.delay)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--input",
        required=True,
        help="CSV with columns: Sr,CaseType,CaseNo,CaseYear,CaseLabel,BillingStatus,...",
    )
    ap.add_argument(
        "--only",
        type=str,
        default="",
        help="comma-separated Sr numbers to check, e.g. --only 1,2,3",
    )
    ap.add_argument(
        "--only-ongoing",
        action="store_true",
        help="only check cases where BillingStatus == ONGOING",
    )
    ap.add_argument(
        "--all", action="store_true", help="check every case in the input file"
    )
    ap.add_argument(
        "--debug",
        action="store_true",
        help="dump raw HTML for each checked case to debug_html/",
    )
    ap.add_argument(
        "--delay",
        type=float,
        default=DELAY_SECONDS,
        help="seconds each worker waits between its own requests (default 6)",
    )
    ap.add_argument(
        "--workers",
        type=int,
        default=1,
        help="number of parallel sessions to run (default 1 = sequential, same as before). "
        "Try 3-4 for a meaningful speedup without hammering the portal.",
    )
    args = ap.parse_args()

    OUT_DIR.mkdir(exist_ok=True)
    if args.debug:
        DEBUG_DIR.mkdir(parents=True, exist_ok=True)

    cases = load_input(args.input)

    if args.only:
        wanted = {int(x) for x in args.only.split(",") if x.strip().isdigit()}
        cases = [c for c in cases if int(c["Sr"]) in wanted]
    elif args.all:
        pass  # keep full list
    elif args.only_ongoing:
        cases = [c for c in cases if c.get("BillingStatus", "").upper() == "ONGOING"]
    else:
        print(
            "Specify --only-ongoing, --all, or --only <Sr,Sr,...>. Defaulting to --only-ongoing."
        )
        cases = [c for c in cases if c.get("BillingStatus", "").upper() == "ONGOING"]

    # Skip Sr numbers already successfully logged (so a re-run after a crash
    # or Ctrl-C only processes what's left, instead of starting over).
    existing_log = OUT_DIR / "portal_status_verification_log.csv"
    already_done = set()
    if existing_log.exists() and not args.only:
        with open(existing_log, newline="") as lf:
            for row in csv.DictReader(lf):
                if row.get("PortalStatusRaw") not in ("SEARCH_ERROR",):
                    already_done.add(row["Sr"])
        if already_done:
            before = len(cases)
            cases = [c for c in cases if c["Sr"] not in already_done]
            print(
                f"Skipping {before - len(cases)} case(s) already logged successfully in a previous run."
            )
            print(
                f"({len(already_done)} total previously logged; SEARCH_ERROR rows will be retried)"
            )

    total = len(cases)
    print(
        f"Checking {total} case(s) against the live BHC portal with {args.workers} worker(s)..."
    )

    log_path = OUT_DIR / "portal_status_verification_log.csv"
    new_log = not log_path.exists()
    lf = open(log_path, "a", newline="")
    writer = csv.writer(lf)
    if new_log:
        writer.writerow(
            [
                "Sr",
                "Case",
                "BillingStatus",
                "PortalStatusRaw",
                "PortalStatusClassified",
                "ExtractionMethod",
                "PartyName",
                "Match",
                "StillOngoing2026-27",
                "DateChecked",
            ]
        )
        lf.flush()

    write_lock = threading.Lock()
    print_lock = threading.Lock()

    if args.workers <= 1:
        # Original sequential path (single session, simplest / most conservative)
        print("Initialising session ...")
        portal = Portal()
        print(f"  csrf token : {'ok' if portal.csrf else 'MISSING'}")
        portal.load_types()
        print(f"  case types : {len(portal.type_options)} loaded")
        for i, row in enumerate(cases, 1):
            process_case(portal, row, args, writer, write_lock, print_lock, i, total)
            lf.flush()
            if i < total:
                time.sleep(args.delay)
    else:
        case_queue = queue.Queue()
        for i, row in enumerate(cases, 1):
            case_queue.put((i, row))

        threads = []
        for wid in range(args.workers):
            t = threading.Thread(
                target=worker_loop,
                args=(wid, case_queue, args, writer, write_lock, print_lock, total),
            )
            t.start()
            threads.append(t)

        # periodically flush while workers run
        while any(t.is_alive() for t in threads):
            lf.flush()
            time.sleep(2)
        for t in threads:
            t.join()

    lf.flush()
    lf.close()

    print(f"\nDone. Log: {log_path}")
    if args.debug:
        print(f"Debug HTML dumped to: {DEBUG_DIR}/")
        print(
            "If PortalStatusClassified shows UNKNOWN often, open a couple of these HTML files,"
        )
        print(
            "find the actual status element, and send it to me so I can hardcode the right selector."
        )
    print("\nColumns:")
    print(
        "  Match = MATCH / MISMATCH / COULD_NOT_VERIFY  (billing-derived vs portal-derived status)"
    )
    print(
        "  StillOngoing2026-27 = No (portal confirms disposed) / Yes (portal confirms pending) / UNVERIFIED"
    )


if __name__ == "__main__":
    main()
