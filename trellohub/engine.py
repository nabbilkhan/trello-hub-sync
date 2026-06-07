"""The reconciliation engine.

A single ``run(cfg)`` performs one full sync pass:

  1. mirror every source card you are a member of onto the hub board,
  2. two-way status/list moves (your hub board wins conflicts), with an optional
     "Dev column home" for cards in active development,
  3. two-way labels (by name, with a baseline so removals propagate),
  4. mirror the description + checklists, and re-upload/link attachments,
  5. keep the "Collab:" title for shared cards,
  6. archive mirrors whose source you no longer own.

It is idempotent and safe to run as often as you like (a poll timer, a webhook,
or by hand). ``DRY_RUN=1`` logs intended actions without changing anything.
"""
from __future__ import annotations

import datetime
import fcntl
import hashlib
import os
import re
import sys
import time

from . import status as S
from .api import Trello, TrelloError
from .state import State

MAX_BODY = 14000  # Trello desc limit is 16384; leave room for header + marker


def make_logger(cfg):
    def log(msg):
        line = f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S %Z')} {msg}".rstrip()
        sys.stderr.write(line + "\n")
        try:
            os.makedirs(os.path.dirname(cfg.log_path), exist_ok=True)
            with open(cfg.log_path, "a") as f:
                f.write(line + "\n")
        except OSError:
            pass
    return log


def render_checklists(card) -> str:
    parts = []
    for cl in card.get("checklists", []) or []:
        items = sorted(cl.get("checkItems", []) or [], key=lambda i: i.get("pos", 0) or 0)
        lines = [f"- [{'x' if it.get('state') == 'complete' else ' '}] {it.get('name')}" for it in items]
        parts.append(f"**{cl.get('name')}**\n" + "\n".join(lines))
    return "\n\n".join(parts)


def compose_body(card) -> str:
    body = card.get("desc", "") or ""
    checks = render_checklists(card)
    content = body
    if checks:
        content = (content + "\n\n" if content else "") + "### Checklists\n" + checks
    if len(content) > MAX_BODY:
        content = content[:MAX_BODY] + "\n\n_(truncated, open the source card for the full content)_"
    return content or "_(no description on the source card)_"


def content_sig(card, collab) -> str:
    return hashlib.sha1((compose_body(card) + "\x00" + collab).encode("utf-8")).hexdigest()


def run(cfg, dry_run=False) -> dict:
    log = make_logger(cfg)
    t = Trello(cfg.api_key, cfg.token)
    marker_re = re.compile(re.escape(cfg.marker) + r":src=([a-zA-Z0-9]{24});b=([a-zA-Z0-9]{24})")
    dev_enabled = bool(cfg.dev_list_id and cfg.dev_label_id)

    def is_downstream(s):
        return s in cfg.downstream_statuses

    # ---- serialize runs (poll + webhook must not overlap) ------------------
    os.makedirs(os.path.dirname(cfg.lock_path), exist_ok=True)
    lock = open(cfg.lock_path, "w")
    deadline = time.time() + 120
    while True:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except BlockingIOError:
            if time.time() > deadline:
                log("lock busy, skipping run")
                return {}
            time.sleep(1)

    state = State(cfg.state_db)
    tag = " [dry-run]" if dry_run else ""
    c = dict(created=0, skipped_done=0, pushed=0, pulled=0, removed=0,
             labels_added=0, labels_removed=0, content=0, attach=0, excluded=0)

    # 1. hub board lists + label registry
    DAILY_LIST, DAILY_LIST_ST = {}, {}
    hub_lists = t.get(f"/boards/{cfg.hub_board}/lists", fields="name")
    for l in hub_lists:
        s = S.hub_status(l["name"]); DAILY_LIST_ST[l["id"]] = s; DAILY_LIST.setdefault(s, l["id"])
    for l in hub_lists:
        if "backlog" in l["name"].lower():
            DAILY_LIST["backlog"] = l["id"]; break
    DAILY_LIST.setdefault("backlog", hub_lists[0]["id"] if hub_lists else None)

    DLBL_NAME, DLBL_COLOR, DLBL_BYNAME, DLBL_BYCOLOR = {}, {}, {}, {}
    for l in t.get(f"/boards/{cfg.hub_board}/labels", fields="name,color", limit=1000):
        DLBL_NAME[l["id"]] = l.get("name") or ""
        DLBL_COLOR[l["id"]] = l.get("color") or ""
        if l.get("name"): DLBL_BYNAME[l["name"].lower()] = l["id"]
        elif l.get("color"): DLBL_BYCOLOR[l["color"]] = l["id"]

    def daily_label_for(name, color):
        if name and name.lower() in DLBL_BYNAME: return DLBL_BYNAME[name.lower()]
        if not name and color and color in DLBL_BYCOLOR: return DLBL_BYCOLOR[color]
        r = t.post("/labels", name=name or "", color=color or "null", idBoard=cfg.hub_board)
        if name: DLBL_BYNAME[name.lower()] = r["id"]
        elif color: DLBL_BYCOLOR[color] = r["id"]
        DLBL_NAME[r["id"]] = name or ""; DLBL_COLOR[r["id"]] = color or ""
        return r["id"]

    # 2. existing mirrors on the hub board
    MIR = {}
    for card in t.get(f"/boards/{cfg.hub_board}/cards", fields="id,name,desc,idList,idLabels", filter="open"):
        m = marker_re.search(card.get("desc") or "")
        if not m:
            continue
        MIR[m.group(1)] = {"id": card["id"], "board": m.group(2),
                           "status": DAILY_LIST_ST.get(card["idList"], "backlog"),
                           "labels": card.get("idLabels", []) or [], "name": card.get("name", "")}

    # 3. owned source cards
    AS, HOST_LIST = {}, {}
    HLBL_NAME, HLBL_COLOR, HLBL_BYNAME, HLBL_BYCOLOR = {}, {}, {}, {}
    MEMBER_NAME, board_ok = {}, set()
    for src in cfg.sources:
        bid = src.board_id
        try:
            blists = t.get(f"/boards/{bid}/lists", fields="name")
        except TrelloError:
            log(f"WARN: list fetch failed for {src.name} ({bid}); skipping board this run"); continue
        by_status = {}
        for l in blists:
            by_status.setdefault(S.source_status(l["name"]), []).append(l)
        for s, ls in by_status.items():
            ex = [l for l in ls if "executive" in l["name"].lower()]
            HOST_LIST[(bid, s)] = (ex[0] if ex else ls[0])["id"]
        L2S = {l["id"]: S.source_status(l["name"]) for l in blists}
        try:
            for l in t.get(f"/boards/{bid}/labels", fields="name,color", limit=1000):
                HLBL_NAME[(bid, l["id"])] = l.get("name") or ""
                HLBL_COLOR[(bid, l["id"])] = l.get("color") or ""
                if l.get("name"): HLBL_BYNAME[(bid, l["name"].lower())] = l["id"]
                elif l.get("color"): HLBL_BYCOLOR[(bid, l["color"])] = l["id"]
        except TrelloError:
            pass
        try:
            for m in t.get(f"/boards/{bid}/members", fields="fullName"):
                MEMBER_NAME[m["id"]] = m.get("fullName") or m["id"]
        except TrelloError:
            pass
        try:
            cards = t.get(f"/boards/{bid}/cards", fields="id,name,idMembers,idList,shortUrl,idLabels,desc",
                          attachments="true", attachment_fields="name,url,bytes,isUpload",
                          checklists="all", checklist_fields="name",
                          checkItems="all", checkItem_fields="name,state,pos", filter="open")
        except TrelloError:
            log(f"WARN: card fetch failed for {src.name} ({bid}); skipping board this run"); continue
        board_ok.add(bid)
        for card in cards:
            if cfg.member_id not in (card.get("idMembers") or []):
                continue
            card["_board"] = bid
            card["_status"] = L2S.get(card["idList"], "backlog")
            AS[card["id"]] = card

    def host_label_for(bid, name, color):
        if name and (bid, name.lower()) in HLBL_BYNAME: return HLBL_BYNAME[(bid, name.lower())]
        if not name and color and (bid, color) in HLBL_BYCOLOR: return HLBL_BYCOLOR[(bid, color)]
        r = t.post("/labels", name=name or "", color=color or "null", idBoard=bid)
        if name: HLBL_BYNAME[(bid, name.lower())] = r["id"]
        elif color: HLBL_BYCOLOR[(bid, color)] = r["id"]
        HLBL_NAME[(bid, r["id"])] = name or ""
        return r["id"]

    def collab_csv(card):
        return ", ".join(sorted(MEMBER_NAME.get(m, m) for m in (card.get("idMembers") or []) if m != cfg.member_id))

    def card_is_dev(srcid):
        if not dev_enabled:
            return False
        card = AS[srcid]; bid = card["_board"]
        if any((HLBL_NAME.get((bid, lid), "") or "").lower() == "dev" for lid in card.get("idLabels", []) or []):
            return True
        mir = MIR.get(srcid)
        return bool(mir and cfg.dev_label_id in mir["labels"])

    def mirror_desc(card, collab):
        bid = card["_board"]
        header = f"🔁 Auto-mirrored from **{cfg.board_name.get(bid, bid)}** · Source: {card['shortUrl']}"
        collab_line = f"\n👥 Also assigned: {collab}" if collab else ""
        return f"{header}{collab_line}\n\n{compose_body(card)}\n\n---\n{cfg.marker}:src={card['id']};b={bid}"

    # 3b. exclude cards carrying the "initiative" (configurable) label
    if cfg.exclude_label_substring:
        needle = cfg.exclude_label_substring.lower()
        for srcid in list(AS):
            bid = AS[srcid]["_board"]
            if any(needle in (HLBL_NAME.get((bid, lid), "") or "").lower()
                   for lid in AS[srcid].get("idLabels", []) or []):
                del AS[srcid]; c["excluded"] += 1

    def move(cid, lst):
        if not dry_run:
            t.put(f"/cards/{cid}", idList=lst)

    # 4. CREATE mirrors
    for srcid, card in AS.items():
        if srcid in MIR:
            continue
        if card["_status"] == "done":
            c["skipped_done"] += 1; continue
        bid = card["_board"]
        mstatus = "dev" if (card_is_dev(srcid) and not is_downstream(card["_status"])) else card["_status"]
        lst = DAILY_LIST.get(mstatus, DAILY_LIST["backlog"])
        collab = collab_csv(card)
        title = f"Collab: {card['name']}" if collab else card["name"]
        if dry_run:
            log(f"DRY would CREATE [{mstatus}]{' [Collab]' if collab else ''} {{{cfg.board_name.get(bid, bid)}}} {title}")
            c["created"] += 1; continue
        nc = t.post("/cards", idList=lst, name=title, desc=mirror_desc(card, collab),
                    idLabels=cfg.origin_label.get(bid, ""), pos="top")
        try:
            t.post(f"/cards/{nc['id']}/attachments", url=card["shortUrl"], name=f"Source: {cfg.board_name.get(bid, bid)}")
        except TrelloError:
            pass
        MIR[srcid] = {"id": nc["id"], "board": bid, "status": mstatus,
                      "labels": [cfg.origin_label.get(bid, "")], "name": title}
        state.set(srcid, src_board=bid, mirror_id=nc["id"], last_status=mstatus,
                  baseline=[], content_hash=content_sig(card, collab))
        c["created"] += 1
        log(f"CREATED mirror {nc['id']} [{mstatus}]{' [Collab]' if collab else ''} {title}")

    for srcid in AS:
        if srcid in MIR and state.get(srcid) is None:
            state.set(srcid, src_board=AS[srcid]["_board"], mirror_id=MIR[srcid]["id"],
                      last_status=MIR[srcid]["status"], baseline=[], content_hash="")

    # 5. STATUS SYNC (3-way; hub board wins) + optional Dev-column home
    for srcid, card in AS.items():
        mir = MIR.get(srcid)
        if not mir:
            continue
        mid = mir["id"]; bid = card["_board"]
        hs, ms, L = card["_status"], mir["status"], state.get(srcid)["last_status"]
        if card_is_dev(srcid) and not is_downstream(ms) and not is_downstream(hs):
            if ms != "dev":
                if dry_run: log(f"DRY would MOVE mirror {mid} -> Dev column")
                else: move(mid, cfg.dev_list_id); log(f"DEV: pinned mirror {mid} to Dev column")
                c["pulled"] += 1
            state.set(srcid, last_status="dev"); continue
        if ms == "dev":
            dest = DAILY_LIST.get(hs, DAILY_LIST["backlog"])
            if dry_run: log(f"DRY would MOVE mirror {mid} out of Dev -> {hs}")
            else: move(mid, dest); log(f"mirror {mid} leaving Dev -> {hs}")
            state.set(srcid, last_status=hs); c["pulled"] += 1; continue
        if ms == "park":
            continue
        if hs == ms:
            state.set(srcid, last_status=ms); continue
        if ms != L and hs == L:
            dest = HOST_LIST.get((bid, ms))
            if not dest: log(f"SKIP push: {cfg.board_name.get(bid, bid)} has no list for '{ms}' (card {srcid})"); continue
            if dry_run: log(f"DRY would MOVE host {srcid} -> {ms} ({cfg.board_name.get(bid, bid)})")
            else: move(srcid, dest); log(f"PUSHED host {srcid} -> {ms} ({cfg.board_name.get(bid, bid)})")
            state.set(srcid, last_status=ms); c["pushed"] += 1
        elif hs != L and ms == L:
            dest = DAILY_LIST.get(hs, DAILY_LIST["backlog"])
            if dry_run: log(f"DRY would MOVE mirror {mid} -> {hs}")
            else: move(mid, dest); log(f"PULLED mirror {mid} -> {hs} (from {cfg.board_name.get(bid, bid)})")
            state.set(srcid, last_status=hs); c["pulled"] += 1
        else:
            dest = HOST_LIST.get((bid, ms))
            if not dest: log(f"SKIP conflict push: {cfg.board_name.get(bid, bid)} has no list for '{ms}' (card {srcid})"); continue
            if dry_run: log(f"DRY would RESOLVE conflict host {srcid} -> {ms} (hub wins)")
            else: move(srcid, dest); log(f"CONFLICT resolved: host {srcid} -> {ms} (hub wins)")
            state.set(srcid, last_status=ms); c["pushed"] += 1

    # 6. REMOVE mirrors no longer owned
    for srcid, mir in list(MIR.items()):
        if srcid in AS:
            continue
        st = state.get(srcid) or {}
        if st.get("src_board") not in board_ok and mir["board"] not in board_ok:
            continue
        if dry_run:
            log(f"DRY would ARCHIVE mirror {mir['id']} (src {srcid} no longer owned)")
        else:
            try:
                t.put(f"/cards/{mir['id']}", closed="true")
                log(f"ARCHIVED mirror {mir['id']} (src {srcid} no longer owned)")
            except TrelloError:
                continue
        c["removed"] += 1

    # 7. LABELS (two-way, by name, baseline in DB; hub wins removals)
    mech = {DLBL_NAME[lid].lower() for lid in
            ([cfg.dev_label_id] if cfg.dev_label_id else []) + list(cfg.origin_label.values())
            if DLBL_NAME.get(lid)}
    for srcid, card in AS.items():
        mir = MIR.get(srcid)
        if not mir:
            continue
        bid = card["_board"]
        M = {}
        for lid in mir["labels"]:
            nm = DLBL_NAME.get(lid, "")
            if nm and nm.lower() not in mech:
                M[nm.lower()] = (lid, DLBL_COLOR.get(lid, ""), nm)
        Sd = {}
        for lid in card.get("idLabels", []) or []:
            nm = HLBL_NAME.get((bid, lid), "")
            if not nm or nm.lower() in mech:
                continue
            if nm.lower() in Sd: Sd[nm.lower()][0].append(lid)
            else: Sd[nm.lower()] = ([lid], HLBL_COLOR.get((bid, lid), ""), nm)
        B = set(state.get(srcid).get("baseline", []))
        newB = set()
        for k in set(M) | set(Sd) | B:
            inM, inS, inB = k in M, k in Sd, k in B
            if inM:
                newB.add(k)
                if inS:
                    continue
                name, color = M[k][2], M[k][1]
                if dry_run: log(f"DRY would ADD label '{name}' -> source {srcid}"); c["labels_added"] += 1; continue
                try:
                    t.post(f"/cards/{srcid}/idLabels", value=host_label_for(bid, name, color))
                    card.setdefault("idLabels", []).append("_")
                    c["labels_added"] += 1; log(f"ADDED label '{name}' -> source {srcid} ({cfg.board_name.get(bid, bid)})")
                except TrelloError:
                    log(f"WARN: could not add label '{name}' to {cfg.board_name.get(bid, bid)}")
            elif inS:
                name, color = Sd[k][2], Sd[k][1]
                if inB:
                    for hid in Sd[k][0]:
                        if dry_run: log(f"DRY would REMOVE label '{name}' from source {srcid}"); c["labels_removed"] += 1; continue
                        try: t.delete(f"/cards/{srcid}/idLabels/{hid}"); c["labels_removed"] += 1; log(f"REMOVED label '{name}' from source {srcid} ({cfg.board_name.get(bid, bid)})")
                        except TrelloError: pass
                else:
                    newB.add(k)
                    if dry_run: log(f"DRY would ADD label '{name}' -> mirror {mir['id']}"); c["labels_added"] += 1; continue
                    try:
                        t.post(f"/cards/{mir['id']}/idLabels", value=daily_label_for(name, color))
                        mir["labels"].append("_")
                        c["labels_added"] += 1; log(f"ADDED label '{name}' -> mirror {mir['id']}")
                    except TrelloError:
                        log(f"WARN: could not add label '{name}' to hub board")
        state.set(srcid, baseline=sorted(newB))

    # 8. CONTENT + COLLAB title + ATTACHMENTS
    for srcid, card in AS.items():
        mir = MIR.get(srcid)
        if not mir:
            continue
        bid = card["_board"]; mid = mir["id"]; collab = collab_csv(card)
        want_title = f"Collab: {card['name']}" if collab else card["name"]
        if mir.get("name") != want_title and not dry_run:
            try: t.put(f"/cards/{mid}", name=want_title); mir["name"] = want_title
            except TrelloError: pass
        sig = content_sig(card, collab)
        if state.get(srcid).get("content_hash") != sig:
            if dry_run: log(f"DRY would REFRESH content on mirror {mid}")
            else:
                try: t.put(f"/cards/{mid}", desc=mirror_desc(card, collab)); state.set(srcid, content_hash=sig)
                except TrelloError: pass
            c["content"] += 1
        atts = card.get("attachments", []) or []
        if atts:
            have = set()
            try:
                for a in t.get(f"/cards/{mid}/attachments", fields="name,bytes,url,isUpload"):
                    have.add(f"U|{a.get('name','')}|{a.get('bytes',0)}" if a.get("isUpload") else f"L|{a.get('url','')}")
            except TrelloError:
                pass
            for a in atts:
                name = a.get("name", "") or ""; url = a.get("url", "") or ""
                size = a.get("bytes", 0) or 0; isup = bool(a.get("isUpload"))
                key = f"U|{name}|{size}" if isup else f"L|{url}"
                if key in have:
                    continue
                if dry_run: log(f"DRY would COPY attachment '{name}' -> mirror {mid}"); c["attach"] += 1; continue
                try:
                    if isup:
                        if cfg.attach_max_bytes and size > cfg.attach_max_bytes:
                            log(f"SKIP attachment '{name}' on {mid} (too large: {size})"); continue
                        if cfg.attach_max_bytes == 0:
                            t.post(f"/cards/{mid}/attachments", url=url, name=name)
                        else:
                            t.upload(f"/cards/{mid}/attachments", name, t.download(url))
                        log(f"COPIED attachment '{name}' -> mirror {mid}")
                    else:
                        t.post(f"/cards/{mid}/attachments", url=url, name=name)
                        log(f"COPIED link attachment '{name}' -> mirror {mid}")
                    have.add(key); c["attach"] += 1
                except TrelloError:
                    log(f"WARN: failed to copy attachment '{name}' -> mirror {mid}")

    if not dry_run:
        state.flush()
    state.close()
    log("done: owned={} mirrors={} created={} pushed={} pulled={} removed={} "
        "labels_added={} labels_removed={} content={} attach={} excluded={} skipped_done={}{}".format(
            len(AS), len(MIR), c["created"], c["pushed"], c["pulled"], c["removed"],
            c["labels_added"], c["labels_removed"], c["content"], c["attach"], c["excluded"],
            c["skipped_done"], tag))
    return c


def backfill(cfg) -> int:
    """Seed the SQLite state from existing card markers (after losing the DB)."""
    log = make_logger(cfg)
    t = Trello(cfg.api_key, cfg.token)
    state = State(cfg.state_db)
    rx = re.compile(re.escape(cfg.marker) + r":src=([a-zA-Z0-9]{24});b=([a-zA-Z0-9]{24})(?:;st=([a-z_]+))?")
    import base64
    n = 0
    for card in t.get(f"/boards/{cfg.hub_board}/cards", fields="id,desc", filter="open"):
        m = rx.search(card.get("desc") or "")
        if not m:
            continue
        src, bid, st = m.group(1), m.group(2), m.group(3) or "backlog"
        baseline = []
        lbl = re.search(r";lbl=([A-Za-z0-9+/=]+)", card.get("desc") or "")
        if lbl:
            try:
                baseline = [x for x in base64.b64decode(lbl.group(1)).decode("utf-8", "replace").split("\x1f") if x]
            except Exception:
                baseline = []
        state.set(src, src_board=bid, mirror_id=card["id"], last_status=st, baseline=baseline, content_hash="")
        n += 1
    state.flush(); state.close()
    log(f"backfill: seeded {n} mirrors into {cfg.state_db}")
    return n
