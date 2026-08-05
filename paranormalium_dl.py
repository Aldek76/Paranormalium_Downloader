#!/usr/bin/env python3
"""Download Radio Paranormalium podcast MP3s. See README_paranormalium_dl.md.

Usage:
  python3 paranormalium_dl.py --out ~/paranormalium_mp3
  python3 paranormalium_dl.py --out ./mp3 --pages 1 2 3
  python3 paranormalium_dl.py --out ./mp3 --resume
  python3 paranormalium_dl.py --out ./mp3 --missing-log unavailable_ids.txt
"""
# ---------------------------------------------------------------------------
# IMPORTS: all from Python's standard library, so there is nothing to pip install.
# ---------------------------------------------------------------------------
import argparse   # argparse: parse command-line flags like --out or --delay
import os         # os: create directories, check files, build file paths
import re         # re: regular expressions - used to pull (id, title) out of HTML
import sys        # sys: write progress/errors to "standard error" (the terminal)
import time       # time: sleep() so we don't hammer the server too fast
import urllib.error, urllib.request  # urllib: fetch web pages and files over HTTP

# ---------------------------------------------------------------------------
# CONSTANTS: values that never change while the program runs.
# ---------------------------------------------------------------------------
BASE = "https://www.paranormalium.pl"   # site root; every URL is built from this
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "   # UA = "User-Agent": a fake
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")        # browser id so the site
                                                               # treats us like a real browser
HEADERS = {"User-Agent": UA, "Accept-Language": "pl-PL,pl;q=0.9"}  # HTTP headers sent with
                                                                     # every request (Polish preferred)
DEFAULT_END = 371          # the archive has 371 pages (update if the site changes)

# ---------------------------------------------------------------------------
# PRE-COMPILED REGEXES (compiling once is faster than re-doing it per call).
# ---------------------------------------------------------------------------
_clean_re = re.compile(r'<[^>]+>')   # matches any HTML tag like <b> or </div> (used to strip tags)
_ws_re = re.compile(r"\s+")          # matches one-or-more whitespace chars (space/tab/newline)
_bad_re = re.compile(r'[\\/:*?"<>|]')   # filesystem-illegal chars (also safe on Linux)

def clean(t):
    """Turn a messy HTML snippet into plain text: remove tags, fix spaces."""
    if not t:                         # if the input is empty/None, return empty string
        return ""
    t = _clean_re.sub(" ", t)         # replace every <tag> with a single space
    t = t.replace("&nbsp;", " ")      # turn the HTML non-breaking space into a normal space
    return _ws_re.sub(" ", t).strip() # collapse repeated spaces and trim ends

def safe_name(t):
    """Make a string safe to use as a filename (strip illegal chars, cap length)."""
    t = clean(t)                      # first clean the text
    t = _bad_re.sub("_", t)           # replace illegal filename chars with underscore
    t = t.strip(". ")                 # don't start/end with a dot or space
    return t[:120]                    # cap length so file paths stay short

# ---------------------------------------------------------------------------
# fetch_text(): download one listing PAGE as text, with retry + backoff.
# ---------------------------------------------------------------------------
def fetch_text(url, retries=5, timeout=30):
    for i in range(1, retries + 1):            # try up to 'retries' times (1..5)
        try:                                   # attempt the network request
            req = urllib.request.Request(url, headers=HEADERS)  # build an HTTP GET with our headers
            with urllib.request.urlopen(req, timeout=timeout) as r:  # open connection (auto-closes)
                return r.read().decode("utf-8", "replace")   # read bytes, decode to text (utf-8)
        except urllib.error.HTTPError as e:   # server answered but with an error code
            if e.code in (429, 503):           # 429=too many requests, 503=unavailable
                wait = 10 * (2 ** (i - 1))     # exponential backoff: 10,20,40,80,160 seconds
                print(f"  rate-limited {e.code} {url}; sleep {wait}s", file=sys.stderr)  # tell user
                time.sleep(wait)               # pause so the server cools down
            else:                              # any other HTTP error (e.g. 404)
                print(f"  HTTP {e.code} {url}", file=sys.stderr)  # report it
                if i == retries:               # if last try, give up
                    return None
        except Exception as e:                 # network failure, timeout, etc.
            print(f"  err {url}: {e}", file=sys.stderr)  # show the error
            if i == retries:                   # last try -> stop
                return None
            time.sleep(2 * i)                  # small wait before retrying
    return None                                # if all retries failed, return None

# ---------------------------------------------------------------------------
# fetch_binary(): download ONE mp3 as raw bytes, but ONLY if it is a real file.
# (A missing recording returns a 302 to an EMPTY location with no file, so we
#  must validate instead of saving a junk/0-byte file or crashing.)
# ---------------------------------------------------------------------------
def fetch_binary(url, retries=5, timeout=120):
    for i in range(1, retries + 1):            # try up to 'retries' times
        try:                                   # attempt the download
            req = urllib.request.Request(url, headers=HEADERS)  # build the GET request
            with urllib.request.urlopen(req, timeout=timeout) as r:  # open connection
                status = getattr(r, "status", 200)   # final status after following redirects
                if status != 200:                   # must be 200 OK, else not a file
                    print(f"  status {status} (not 200) for {url}", file=sys.stderr)
                    return None
                data = r.read()                     # read ALL the bytes of the response
                if len(data) < 1000:                # tiny/empty body = not a real file
                    print(f"  empty/too-small body ({len(data)} B) for {url}", file=sys.stderr)
                    return None
                ctype = r.headers.get("Content-Type", "").lower()  # response content type
                if "html" in ctype and len(data) < 5000:  # a small html page, not audio
                    print(f"  got html (not mp3) for {url}", file=sys.stderr)
                    return None
                head3 = data[:3]                    # first 3 bytes (ID3 tag check)
                head2 = data[:2]                    # first 2 bytes (MPEG frame-sync check)
                # MP3 starts with b"ID3" tag OR with MPEG frame sync 0xFF 0xFB/F3/F2/FA/F1
                is_mp3 = (head3 == b"ID3") or (head2[0] == 0xFF and head2[1] in (0xFB, 0xF3, 0xF2, 0xFA, 0xF1))
                if not is_mp3:                      # if it isn't an mp3, reject it
                    print(f"  not an mp3 (magic={head3!r}) for {url}", file=sys.stderr)
                    return None
                return data                         # safe: real mp3 bytes
        except urllib.error.HTTPError as e:   # server error during download
            if e.code in (301, 302, 303, 307, 308):  # redirect with no target = unavailable
                print(f"  redirect (unavailable) for {url}", file=sys.stderr)
                return None
            if e.code in (429, 503):           # rate-limited: back off and retry
                wait = 10 * (2 ** (i - 1))     # 10,20,40,80,160 seconds
                print(f"  rate-limited {e.code} {url}; sleep {wait}s", file=sys.stderr)
                time.sleep(wait)
            else:                              # other HTTP error
                print(f"  HTTP {e.code} {url}", file=sys.stderr)
                if i == retries:               # last try -> stop
                    return None
        except Exception as e:                 # network/other failure
            print(f"  err {url}: {e}", file=sys.stderr)  # show it
            if i == retries:                   # last try -> stop
                return None
            time.sleep(2 * i)                  # small wait then retry
    return None                                # all retries failed -> None

# ---------------------------------------------------------------------------
# list_entries(): from a listing page, return (id, title) for each recording.
# ---------------------------------------------------------------------------
def list_entries(html):
    # Find anchors like: <a href="pobierz-audycje.php?id=3765" ... title="Pobierz mp3 (NAME)">
    pairs = re.findall(
        r'href="pobierz-audycje\.php\?id=(\d+)"[^>]*title="([^"]*)"', html)
    out, seen = [], set()           # out = result; seen = dedupe set of ids
    for pid, title in pairs:        # for each (id, title) the regex found
        if pid in seen:             # if we already have this id
            continue                # skip the duplicate
        seen.add(pid)               # remember it
        # title is like "Pobierz mp3 (Real Name)" -> keep just the part in parentheses
        m = re.search(r'\(([^()]*)\)\s*$', title)
        name = m.group(1).strip() if m else title   # the real episode name
        out.append((pid, name))     # add the (id, name) tuple
    return out

# ---------------------------------------------------------------------------
# load_done(): read the ids we already downloaded (for --resume).
# ---------------------------------------------------------------------------
def load_done(path):
    done = set()                     # collect already-downloaded ids
    if os.path.exists(path):          # if the done.txt file exists
        with open(path, encoding="utf-8") as f:
            for line in f:           # each line is one id
                line = line.strip()  # remove whitespace/newline
                if line:             # if not blank
                    done.add(line)   # remember it
    return done

# ---------------------------------------------------------------------------
# main(): the driver - loops over pages, downloads each recording's mp3.
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()                                  # build the CLI parser
    ap.add_argument("--out", default="paranormalium_mp3", help="output directory")  # where to save
    ap.add_argument("--start-page", type=int, default=1)             # first page (default 1)
    ap.add_argument("--end-page", type=int, default=DEFAULT_END)    # last page (default 371)
    ap.add_argument("--pages", nargs="*", type=int, help="explicit page list (overrides start/end)")  # pick pages
    ap.add_argument("--delay", type=float, default=0.4)              # seconds between requests
    ap.add_argument("--resume", action="store_true")                # flag: continue a previous run
    ap.add_argument("--missing-log", default="missing.txt",         # name of the log for skipped ids
                    help="filename (inside --out) for ids that were unavailable/skipped")
    args = ap.parse_args()                                          # parse the actual command line

    os.makedirs(args.out, exist_ok=True)              # create the output dir if it's missing
    done_file = os.path.join(args.out, "done.txt")   # sidecar file listing downloaded ids
    missing_file = os.path.join(args.out, args.missing_log)  # log of unavailable/skipped ids
    open(missing_file, "a", encoding="utf-8").close()        # ensure the log file always exists
    done = load_done(done_file) if args.resume else set()   # load finished ids only if resuming

    pages = args.pages if args.pages else list(range(args.start_page, args.end_page + 1))  # page list
    total = 0                                   # count of files written in THIS run
    for pageno in pages:                        # for each archive page
        url = f"{BASE}/archiwum,{pageno}"       # page URL uses a COMMA: /archiwum,N
        html = fetch_text(url)                  # download the listing page
        if html is None:                        # if it failed after retries
            print(f"skip page {pageno} (fetch failed)", file=sys.stderr)  # report
            continue                             # move to next page
        entries = list_entries(html)            # extract (id, title) from the page
        print(f"[page {pageno}] {len(entries)} recordings", file=sys.stderr)  # progress
        for pid, name in entries:               # for each recording on this page
            if pid in done:                     # if we already downloaded it
                continue                        # skip it
            mp3_url = f"{BASE}/pobierz-audycje.php?id={pid}"   # the download endpoint
            data = fetch_binary(mp3_url)        # download + VALIDATE the mp3
            if data is None:                    # if unavailable/invalid
                with open(missing_file, "a", encoding="utf-8") as mf:  # record the skipped id
                    mf.write(pid + "\n")       # keep a list of what could not be downloaded
                continue                        # skip it (do NOT mark done, so resume can retry)
            fname = f"{pid} - {safe_name(name)}.mp3"   # build a safe filename with id prefix
            fpath = os.path.join(args.out, fname)      # full path in the output dir
            with open(fpath, "wb") as f:              # open the file for writing BINARY
                f.write(data)                         # write the mp3 bytes
            with open(done_file, "a", encoding="utf-8") as f:  # append to the done log
                f.write(pid + "\n")                   # record this id as downloaded
            done.add(pid)                             # remember in memory too
            total += 1                                # count it
            time.sleep(args.delay)                   # polite pause before next request
    print(f"DONE. {total} new files -> {args.out}", file=sys.stderr)  # final report

if __name__ == "__main__":    # only run main() when executed directly (not when imported)
    main()
