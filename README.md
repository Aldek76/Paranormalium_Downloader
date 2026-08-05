# paranormalium_dl.py - README

A small downloader that grabs every MP3 from the Radio Paranormalium podcast
archive (https://www.paranormalium.pl/archiwum) into one folder on your disk.

This README explains the code in plain language, with a focus on the regular
expressions (regexes) and the "missing file" safety check, so you can learn
Python by reading it.

---------------------------------------------------------------------------
## HOW TO RUN

    python3 paranormalium_dl.py --out ~/paranormalium_mp3     # full download
    python3 paranormalium_dl.py --out ./mp3 --pages 1 2 3      # test a few pages
    python3 paranormalium_dl.py --out ./mp3 --start-page 1 --end-page 371
    python3 paranormalium_dl.py --out ./mp3 --resume          # continue a stopped run
    python3 paranormalium_dl.py --out ./mp3 --missing-log unavailable_ids.txt  # name the skip log

The script uses ONLY Python's standard library (urllib, re, ...), so there is
nothing to install with pip.

---------------------------------------------------------------------------
## WHAT THE SCRIPT DOES, STEP BY STEP

1. Build the list of pages:  archiwum,1  ...  archiwum,371  (10 recordings each).
2. For each page, download the HTML and extract every (id, title) pair from the
   "pobierz" (download) links.
3. For each id, request  pobierz-audycje.php?id=<id>  and VALIDATE the response.
4. If it is a real MP3, save it as  "<id> - <title>.mp3"  and log the id.
5. If it is NOT a real file (missing for legal reasons, bad id, etc.), skip it
   gracefully - never write a junk file, never crash.
6. A done.txt in the output folder records every id we got, so --resume can
   skip them next time.

---------------------------------------------------------------------------
## THE REGEXES, EXPLAINED

--- clean() : strip HTML tags from a snippet ---
    r"<[^>]+>"        matches any HTML tag, e.g. <b>, </div>, <a href="...">
                      [^>]  = "any character that is NOT >"
                      +      = "one or more of those"
                      so <[^>]+> = "<" then anything-until-">" then ">" = a whole tag
    r"\s+"            matches one-or-more whitespace chars (space, tab, newline)
                      \s = whitespace,  + = one or more
    We replace tags with a space and collapse whitespace, leaving plain text.

--- safe_name() : make text safe as a filename ---
    r'[\\/:*?"<>|]'   matches any of these characters, which are illegal in
                      Windows filenames (and also kept out for safety on Linux)
    We replace them with "_" and trim leading/trailing dots and spaces.

--- list_entries() : find (id, title) on a listing page ---
    r'href="pobierz-audycje\.php\?id=(\d+)"[^>]*title="([^"]*)"'
        href="pobierz-audycje\.php\?id=   = literal link start ( \. and \? are
                                            escaped because . and ? are regex
                                            symbols; we want the literal characters)
        (\d+)                           = CAPTURE one-or-more digits = the id
        "                               = closing quote of href
        [^>]*                           = any characters up to the closing > of <a>
        title="                         = the title attribute
        ([^"]*)                         = CAPTURE any characters that are not a
                                           quote = the title text
        "                               = closing quote
    We then keep only the part inside the last parentheses of the title
    (the real episode name), using:
        r'\(([^()]*)\)\s*$'
            \(        = literal "("   (escaped, because ( is a regex symbol)
            ([^()]*)  = CAPTURE chars that are not ( or )  = the name
            \)        = literal ")"
            \s*$      = optional trailing spaces, then end of string

---------------------------------------------------------------------------
## THE "MISSING FILE" SAFETY CHECK (your requirement)

Some recordings are unavailable (legal takedown, objection by a recorded person,
or a bad id). For those, the site returns an HTTP 302 redirect with an EMPTY
Location header and NO file. The script handles this in fetch_binary():

    * We follow the request and look at the FINAL status. If it is not 200,
      we treat it as unavailable and return None.
    * If urllib raises on the empty redirect (301/302/303/307/308), we catch it
      and return None immediately (no wasted retries).
    * If the body is tiny (<1000 bytes) we reject it.
    * We check the first bytes are a real MP3:
        - ID3 tag  -> first 3 bytes are b"ID3"  (49 44 33 in hex)
        - raw frame -> first 2 bytes are 0xFF followed by 0xFB/F3/F2/FA/F1
          (the MPEG audio frame sync)
    * Only if ALL checks pass do we write the file.

Back in main(), when fetch_binary() returns None we simply `continue` to the
next recording and do NOT add the id to done.txt - so a later --resume run can
still try that id again (in case it becomes available).

Result: unavailable recordings are skipped with a clear log line, the script
never crashes, and no 0-byte / HTML files land in your folder.

---------------------------------------------------------------------------
## REGEX CHEAT SHEET (symbols used in this script)

    .        any single character (except newline)
    *        zero or more of the previous thing
    +        one or more of the previous thing
    ?        zero or one of the previous thing
    \s       whitespace (space, tab, newline)
    \d       a digit (0-9)
    [^x]     any character that is NOT x
    (...)    capture group - "remember" this part so we can use it later
    \( \)    a literal "(" or ")"  (escaped, because they are regex symbols)
    \. \?    a literal "." or "?"  (escaped, because they are regex symbols)
    r"..."   a "raw" string: backslashes are taken literally, so \s \d \. mean
             what you expect without extra escaping

Tip: read a long regex left-to-right like a sentence. Break it into pieces and
decode each piece - that is exactly how the patterns above are built.

---------------------------------------------------------------------------
## NOTES / LIMITATIONS

- Total size is large: ~3705 files x ~50 MB ~= 185 GB. Check free disk space.
- Be polite: keep --delay >= 0.3s. On HTTP 429 the script backs off
  automatically (10/20/40/80/160s) and --resume can finish the rest later.
- The page count is hardcoded as DEFAULT_END = 371. If the site grows, pass a
  bigger --end-page or update the constant.
- Filenames use the id as a prefix ("3765 - Mustafa - ....mp3") so they stay
  unique and sort in archive order even if two titles look similar.

--- THE --missing-log OPTION ---
  Some recordings are unavailable (legal takedown, objection, bad id). When the
  script skips one, it writes that id to a log file inside --out. By default the
  file is named "missing.txt", but you can choose the name:

      python3 paranormalium_dl.py --out ./mp3 --missing-log unavailable_ids.txt

  The file is created (empty) at startup, then one id per line is appended every
  time a download is skipped. This gives you a clean record of what could NOT be
  downloaded, separate from done.txt (which only lists successes). Note: a skipped
  id is intentionally NOT added to done.txt, so a later --resume run will try it
  again - and if it later succeeds, it moves from missing.txt's intent into done.txt.
