# frontend/app.py
"""
GameSense AI — Deployable MVP (GitHub JSON + Videos)
- Auth: passlib (PBKDF2) — bcrypt-free & deploy-safe
- Persistent storage in GitHub:
    • JSON: data/storage.json
    • Videos: data/videos/<id>_<name>.<ext>
- Upload, dynamic feedback (expanded by role/skill)
- Rating slider, custom prompt, emoji highlights
- My History: view, delete, PDF (width-safe)
- Membership (Free / Plus / Academy / Pro)
- Dashboard (Plotly)
- Background CSS + membership cards
- Daily backup: data/backups/storage-YYYYMMDD.json
"""

# --- Silence local OpenSSL/urllib3 warning (macOS LibreSSL) ---
import warnings
warnings.filterwarnings("ignore", message="urllib3 v2 only supports OpenSSL", category=UserWarning)

import os, json, uuid, tempfile, re, random, base64, hmac, hashlib
from pathlib import Path
from datetime import datetime, date
from typing import Optional, Tuple, Dict, Any

import streamlit as st
from passlib.hash import pbkdf2_sha256  # bcrypt-free
from fpdf import FPDF
import pandas as pd
import plotly.express as px
import requests
import urllib3
urllib3.disable_warnings()  # extra quiet locally

# -----------------------------------------------------------------------------
# Page config
# -----------------------------------------------------------------------------
st.set_page_config(page_title="GameSense AI", layout="wide")

# -----------------------------------------------------------------------------
# Paths (local best-effort for assets/temp)
# -----------------------------------------------------------------------------
ROOT = Path.cwd()
DATA_DIR = ROOT / "data"         # local fallback
VIDEO_DIR = ROOT / "videos"      # local fallback preview
ASSETS_DIR = ROOT / "assets"
BACKGROUND_FILE = ASSETS_DIR / "bg.jpg"
BANNER_FILE = ASSETS_DIR / "banner.jpg"
for d in (DATA_DIR, VIDEO_DIR, ASSETS_DIR):
    d.mkdir(parents=True, exist_ok=True)

# -----------------------------------------------------------------------------
# GitHub config (secrets or env)
# -----------------------------------------------------------------------------
GH_TOKEN       = st.secrets.get("GITHUB_TOKEN", os.getenv("GITHUB_TOKEN"))
GH_REPO        = st.secrets.get("GH_REPO", os.getenv("GH_REPO"))  # "owner/repo"
GH_REPO_OWNER  = st.secrets.get("GH_REPO_OWNER", os.getenv("GH_REPO_OWNER"))
GH_REPO_NAME   = st.secrets.get("GH_REPO_NAME", os.getenv("GH_REPO_NAME"))
GH_BRANCH      = st.secrets.get("GH_BRANCH", os.getenv("GH_BRANCH", "main"))
GH_JSON_PATH   = st.secrets.get("GH_JSON_PATH", os.getenv("GH_JSON_PATH", "data/storage.json"))
GH_VIDEOS_DIR  = st.secrets.get("GH_VIDEOS_DIR", os.getenv("GH_VIDEOS_DIR", "data/videos"))
GH_BACKUP_DIR  = st.secrets.get("GH_BACKUP_DIR", os.getenv("GH_BACKUP_DIR", "data/backups"))

# Support owner/name split
if not GH_REPO and GH_REPO_OWNER and GH_REPO_NAME:
    GH_REPO = f"{GH_REPO_OWNER}/{GH_REPO_NAME}"

GH_API = "https://api.github.com"

def gh_headers() -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {GH_TOKEN}" if GH_TOKEN else "",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

def gh_get_file(owner_repo: str, path: str, ref: str = "main") -> Tuple[Optional[str], Optional[str]]:
    """Return (text, sha) or (None, None) if missing/error."""
    try:
        url = f"{GH_API}/repos/{owner_repo}/contents/{path}"
        r = requests.get(url, headers=gh_headers(), params={"ref": ref}, timeout=20)
        if r.status_code == 200:
            data = r.json()
            content_b64 = data.get("content", "")
            sha = data.get("sha")
            decoded = base64.b64decode(content_b64).decode("utf-8", errors="ignore")
            return decoded, sha
        elif r.status_code == 404:
            return None, None
        else:
            st.warning(f"GitHub GET error {r.status_code}: {r.text[:160]}")
            return None, None
    except Exception as e:
        st.warning(f"GitHub GET exception: {e}")
        return None, None

def gh_put_text(owner_repo: str, path: str, content_text: str, message: str, branch: str, sha: Optional[str]):
    """Create/update a text file in GitHub."""
    try:
        url = f"{GH_API}/repos/{owner_repo}/contents/{path}"
        body = {
            "message": message,
            "content": base64.b64encode(content_text.encode("utf-8")).decode("utf-8"),
            "branch": branch,
        }
        if sha:
            body["sha"] = sha
        r = requests.put(url, headers=gh_headers(), json=body, timeout=25)
        return r.status_code in (200, 201), r.status_code, r.text
    except Exception as e:
        return False, 0, str(e)

def gh_put_binary(owner_repo: str, path: str, raw_bytes: bytes, message: str, branch: str, sha: Optional[str] = None):
    """Create/update a binary file (e.g., .mp4) in GitHub."""
    try:
        url = f"{GH_API}/repos/{owner_repo}/contents/{path}"
        body = {
            "message": message,
            "content": base64.b64encode(raw_bytes).decode("utf-8"),
            "branch": branch,
        }
        if sha:
            body["sha"] = sha
        r = requests.put(url, headers=gh_headers(), json=body, timeout=60)
        return r.status_code in (200, 201), r.status_code, r.text
    except Exception as e:
        return False, 0, str(e)

def gh_raw_url(owner_repo: str, branch: str, path: str) -> str:
    return f"https://raw.githubusercontent.com/{owner_repo}/{branch}/{path}"

# -----------------------------------------------------------------------------
# Storage (GitHub JSON + local fallback) + Daily backup
# -----------------------------------------------------------------------------
LOCAL_STORAGE_FILE = DATA_DIR / "storage.local.json"  # fallback only

def default_storage() -> Dict[str, Any]:
    return {"users": {}, "sessions": [], "__last_backup": ""}

def load_storage():
    # Prefer GitHub
    if GH_TOKEN and GH_REPO and GH_JSON_PATH:
        txt, sha = gh_get_file(GH_REPO, GH_JSON_PATH, GH_BRANCH)
        if txt is None:
            base = default_storage()
            ok, _, _ = gh_put_text(
                GH_REPO, GH_JSON_PATH,
                json.dumps(base, indent=2, ensure_ascii=False),
                "chore: init storage.json", GH_BRANCH, None
            )
            if ok:
                return base, None
            else:
                st.warning("GitHub storage init failed, using local fallback.")
        else:
            try:
                data = json.loads(txt) or default_storage()
            except Exception:
                data = default_storage()
            data.setdefault("users", {})
            data.setdefault("sessions", [])
            data.setdefault("__last_backup", "")
            return data, sha

    # Local fallback (ephemeral in Cloud)
    if not LOCAL_STORAGE_FILE.exists():
        LOCAL_STORAGE_FILE.write_text(json.dumps(default_storage(), indent=2, ensure_ascii=False), encoding="utf-8")
    try:
        data = json.loads(LOCAL_STORAGE_FILE.read_text(encoding="utf-8"))
    except Exception:
        data = default_storage()
    data.setdefault("users", {})
    data.setdefault("sessions", [])
    data.setdefault("__last_backup", "")
    return data, None

def save_storage(storage: dict, current_sha: Optional[str]) -> Optional[str]:
    txt = json.dumps(storage, indent=2, ensure_ascii=False)
    if GH_TOKEN and GH_REPO and GH_JSON_PATH:
        ok, _, _ = gh_put_text(GH_REPO, GH_JSON_PATH, txt, "chore: update storage.json", GH_BRANCH, current_sha)
        if not ok:
            # retry with fresh sha
            fresh_txt, fresh_sha = gh_get_file(GH_REPO, GH_JSON_PATH, GH_BRANCH)
            ok2, _, _ = gh_put_text(GH_REPO, GH_JSON_PATH, txt, "chore: update storage.json (retry)", GH_BRANCH, fresh_sha)
            if not ok2:
                st.error("GitHub save failed — using local fallback for this session.")
                LOCAL_STORAGE_FILE.write_text(txt, encoding="utf-8")
                return current_sha
            return fresh_sha
        _, new_sha = gh_get_file(GH_REPO, GH_JSON_PATH, GH_BRANCH)
        return new_sha
    else:
        LOCAL_STORAGE_FILE.write_text(txt, encoding="utf-8")
        return current_sha

storage, storage_sha = load_storage()

def persist():
    global storage_sha
    storage_sha = save_storage(storage, storage_sha)

def ensure_daily_backup():
    try:
        if not (GH_TOKEN and GH_REPO):  # only if GH configured
            return
        today_str = date.today().strftime("%Y%m%d")
        if storage.get("__last_backup") == today_str:
            return
        backup_rel = f"{GH_BACKUP_DIR.strip('/')}/storage-{today_str}.json"
        payload = json.dumps(storage, indent=2, ensure_ascii=False)
        existing, sha = gh_get_file(GH_REPO, backup_rel, GH_BRANCH)
        if existing is None:
            gh_put_text(GH_REPO, backup_rel, payload, f"backup: storage {today_str}", GH_BRANCH, None)
        storage["__last_backup"] = today_str
        persist()
    except Exception as e:
        st.warning(f"Daily backup error: {e}")

if GH_TOKEN and GH_REPO:
    ensure_daily_backup()

# -----------------------------------------------------------------------------
# Auth (PBKDF2 via passlib) — bcrypt-free
# -----------------------------------------------------------------------------
def hash_pw(password: str) -> str:
    # PBKDF2 handles arbitrary length; returns salted hash with params
    return pbkdf2_sha256.hash(password)

def verify_pw(password: str, hashed: str) -> bool:
    try:
        return pbkdf2_sha256.verify(password, hashed)
    except Exception:
        return False

def user_exists(email: str) -> bool:
    return email in storage.get("users", {})

def create_user(email: str, password: str, membership: str = "Free"):
    storage["users"][email] = {
        "password_hash": hash_pw(password),
        "membership": membership,
        "created_at": datetime.utcnow().isoformat()
    }

def authenticate(email: str, password: str) -> bool:
    u = storage.get("users", {}).get(email)
    if not u: return False
    ph = u.get("password_hash")
    if isinstance(ph, str) and ph:
        return verify_pw(password, ph)
    # legacy plaintext (if any)
    if "password" in u:
        if u["password"] == password:
            u["password_hash"] = hash_pw(password); u.pop("password", None)
            return True
        else:
            return False
    # malformed user entry: reject
    return False

# -----------------------------------------------------------------------------
# Feedback library (expanded)
# -----------------------------------------------------------------------------
HANDCRAFTED = {
    "Striker": {
        "Finishing": [
            "Prioritise clean contact over power in crowded zones; attack the far post consistently.",
            "Delay the shot half a step to freeze the defender; finish low across the keeper.",
            "Arrive late for cut-backs; set body earlier before contact."
        ],
        "Movement": [
            "Hold blind-side longer then dart across the front; time double-movements.",
            "Scan the line every 2–3 seconds; align runs with passer’s head-up."
        ],
        "Aerial Duels": [
            "Attack at highest point; create separation before leap.",
            "Open shoulders; steer headers down into corners."
        ],
        "Hold-Up Play": [
            "Use your forearm frame; receive on back foot to escape into the channel.",
            "Pin then roll; cue a runner with your free hand."
        ],
    },
    "Winger": {
        "1v1 Dribbling": [
            "Exploit first step; sell the feint with head/shoulder then burst.",
            "Keep touches tighter near the box; accelerate post-move."
        ],
        "Crossing": [
            "Arrive half-space early; drive cut-backs to the penalty spot.",
            "Vary delivery: near-post fizz vs. far-post loft based on runner shape."
        ],
        "Cutting Inside": [
            "Shift with instep; strike across goal with minimal backlift.",
            "Use inside-out touch to open lane; keep hips closed on contact."
        ],
        "Transition Pace": [
            "Carry with long strides; release earlier to exploit 2v1s.",
            "Outside-foot carry at speed to protect from tackles."
        ],
    },
    "Attacking Midfielder": {
        "Through Balls": [
            "Disguise by looking off target; weight into runner’s path.",
            "Release as defender steps; don’t wait for a perfect picture."
        ],
        "Creativity": [
            "Use third-man runs; play-and-spin to receive facing forward.",
            "One-touch layoffs to accelerate pocket combos."
        ],
        "Final Pass": [
            "Reduce backlift; thread with pace so runner stays in stride.",
            "Clip vs. slide based on keeper’s start position."
        ],
    },
    "Box-to-Box Midfielder": {
        "Ball Recoveries": [
            "Arrive on first touch; tackle through the ball, not at it.",
            "Anticipate second balls; first touch forward after regain."
        ],
        "Link Play": [
            "Keep hips open; one-touch when pressure is tight.",
            "Switch point on second touch to break the press."
        ],
        "Forward Runs": [
            "Time late beyond the striker; attack between CB and FB.",
            "Trigger when wide player receives; overload the box."
        ],
    },
    "CDM / #6": {
        "Defensive Positioning": [
            "Screen lanes, not players; stay goal-side of the 10.",
            "Hold your zone when FBs fly; be the pivot for rest defence."
        ],
        "Interceptions": [
            "Read passer’s hips; step in front as ball is released.",
            "Small constant adjustments; arrive before contact."
        ],
        "Tempo Control": [
            "Speed up on the break; slow to secure rest positions.",
            "Scan both flanks pre-receive; set next pass early."
        ],
    },
    "Fullback": {
        "Overlapping": [
            "Start run on winger’s second touch; curve to receive in stride.",
            "Call early to cue through-pass; cross with minimal setup."
        ],
        "Crossing": [
            "Low driven to penalty spot when defence collapses.",
            "Early whip behind the line when winger pins CB."
        ],
        "1v1 Defending": [
            "Show outside; match feet; wait for heavy touch.",
            "Lower centre; strike through the ball cleanly."
        ],
    },
    "Wingback": {
        "Progressive Runs": [
            "Attack inside channel when winger holds width.",
            "Accelerate after receiving; release before contact."
        ],
        "Delivery": [
            "Pick late runner on cut-back; avoid floaters.",
            "Early cross if striker has front position; back-post when weak-side free."
        ],
        "Pressing": [
            "Curve press to block inside pass; force wide to trap.",
            "Trigger on opposite CB touch; arrive with speed."
        ],
    },
    "Center Back": {
        "Aerial Duels": [
            "Leap off opposite foot; head down into traffic.",
            "Use arms legally for leverage pre take-off."
        ],
        "Aggressive Defending": [
            "Step on poor touches; hips open to recover if bypassed.",
            "Delay in big spaces; tackle hard and clean with cover."
        ],
        "Distribution": [
            "Break lines into the 8; clip diagonals when pressed.",
            "Punch firm into feet; demand the return to switch."
        ],
    },
    "Goalkeeper": {
        "Shot-stopping": [
            "Set earlier/narrower; parry high and wide when close-range.",
            "Attack with leading hand; weight forward on push-offs."
        ],
        "Distribution": [
            "Clip to FB when winger jumps; throw early to beat press.",
            "Flatten side-volley trajectory; hit outside shoulder."
        ],
        "Sweeper Keeper": [
            "Two steps higher in possession; claim balls behind the line.",
            "Clear first; organise immediately after."
        ],
    },
}

def build_feedback_library(handcrafted):
    lib = {}
    strengths = [
        "Tempo control was stable ✅","Scanning frequency acceptable ✅",
        "Decision speed improved ✅","Body shape cleaner before receive ✅",
        "Transitions handled with discipline ✅"
    ]
    improvements = [
        "Improve weak-foot under pressure ⚠️","Accelerate release after first touch ⚠️",
        "Maintain compact distances when stepping ⚠️","Trigger earlier off passer cues ⚠️",
        "Protect central lanes in rest defence ⚠️",
    ]
    drills = [
        "Drill: 6-min 5v2 rondo (2-touch)","Drill: 10x far-post finishes",
        "Drill: 8x clipped diagonals (switch)","Drill: 4x3min counter-press waves",
        "Drill: 12x low driven cut-backs",
    ]
    for role, skills in handcrafted.items():
        lib[role] = {}
        for skill, templates in skills.items():
            expanded = []
            for t in templates:
                expanded.append(t)
                expanded.append(f"{random.choice(strengths)}. {t}")
                expanded.append(f"{t} — {random.choice(improvements)}. {random.choice(drills)}")
            lib[role][skill] = expanded
    lib.setdefault("default", {"default": ["Solid session — add specificity next time."]})
    return lib

FEEDBACK_LIB = build_feedback_library(HANDCRAFTED)

# -----------------------------------------------------------------------------
# PDF helpers (sanitise + hard wrap)
# -----------------------------------------------------------------------------
EMOJI_MAP = {"⚽":"[soccer]","✅":"[ok]","⚠️":"[warn]","🔥":"[fire]","🎯":"[target]","💡":"[drill]"}
def sanitize_for_pdf(text: str) -> str:
    if not text: return ""
    text = text.replace("—", "-")
    for k, v in EMOJI_MAP.items():
        text = text.replace(k, v)
    return text.encode("latin-1", errors="replace").decode("latin-1")

def hard_wrap_tokens(text: str, max_len: int = 40) -> str:
    if not text: return ""
    def breaker(m):
        s = m.group(0)
        return "\n".join(s[i:i+max_len] for i in range(0, len(s), max_len))
    return re.sub(rf"\S{{{max_len},}}", breaker, text)

def pdf_safe_block(text: str) -> str:
    return hard_wrap_tokens(sanitize_for_pdf(text), 40)

def create_pdf_bytes(video_name, prompt_text, feedback_text):
    video_name  = pdf_safe_block(video_name)
    prompt_text = pdf_safe_block(prompt_text)
    feedback_text = pdf_safe_block(feedback_text)

    pdf = FPDF(format="A4", unit="mm")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_margins(15, 15, 15)

    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 8, "GameSense AI - Session Feedback", ln=1)
    pdf.ln(2)

    pdf.set_font("Helvetica", "", 11)
    pdf.multi_cell(0, 6, f"Video: {video_name}")
    pdf.ln(1)

    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 6, "Prompt:", ln=1)
    pdf.set_font("Helvetica", "", 11)
    pdf.multi_cell(0, 6, prompt_text)
    pdf.ln(2)

    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 6, "Feedback:", ln=1)
    pdf.set_font("Helvetica", "", 11)
    pdf.multi_cell(0, 6, feedback_text)

    pdf.ln(4)
    pdf.set_font("Helvetica", "I", 9)
    pdf.set_text_color(90, 90, 90)
    pdf.multi_cell(0, 5, "Generated by GameSense AI (MVP). For training guidance only.")

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    tmp.close()
    pdf.output(tmp.name)
    with open(tmp.name, "rb") as f:
        data = f.read()
    try: os.remove(tmp.name)
    except Exception: pass
    return data

# -----------------------------------------------------------------------------
# CSS / Background
# -----------------------------------------------------------------------------
bg_css = ""
if BACKGROUND_FILE.exists():
    bg_css = f"body {{ background-image: url('file://{BACKGROUND_FILE}'); background-size: cover; background-position: center; }}"
CUSTOM_CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;700&display=swap');
html, body, [class*="css"] {{ font-family: 'Inter', sans-serif; }}
.app-card {{ padding: 12px; border-radius: 10px; background: rgba(255,255,255,0.96); }}
.small-muted {{ color:#666; font-size:12px; }}
{bg_css}

/* Membership cards */
.tiers {{
  display:grid; grid-template-columns: repeat(4, minmax(0,1fr)); gap:16px;
}}
@media (max-width:1200px) {{
  .tiers {{ grid-template-columns: repeat(2, minmax(0,1fr)); }}
}}
@media (max-width:700px) {{
  .tiers {{ grid-template-columns: 1fr; }}
}}
.plan {{
  background: rgba(255,255,255,0.98); border: 1px solid #e8e8e8; border-radius: 14px;
  padding: 18px; position: relative; box-shadow: 0 6px 18px rgba(0,0,0,0.06);
}}
.plan h3 {{ margin: 0 0 6px; font-size: 1.2rem; }}
.plan .price {{ font-weight: 700; font-size: 1.4rem; margin-bottom: 10px; }}
.plan ul {{ margin: 0 0 12px 18px; }}
.plan li {{ margin: 6px 0; }}
.plan.highlight {{ border: 2px solid #111; }}
.plan.highlight::before {{
  content: "BEST VALUE"; position: absolute; top: -10px; left: -10px;
  background: #111; color: #fff; font-size: 0.72rem; font-weight: 700; padding: 6px 10px; border-radius: 8px;
}}
.black-btn {{
  display:inline-block; background:#111; color:#fff; padding:10px 14px;
  border-radius:10px; text-decoration:none; font-weight:700;
}}
.black-btn:hover {{ filter: brightness(1.05); }}
</style>
"""
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# Header
# -----------------------------------------------------------------------------
st.markdown("## GameSense AI")
st.caption("⚽ Intelligent football training assistant — upload a clip, get structured feedback, track progress.")

if BANNER_FILE.exists():
    try: st.image(str(BANNER_FILE), use_column_width=True)
    except Exception: pass

# -----------------------------------------------------------------------------
# Sidebar: Auth + Nav
# -----------------------------------------------------------------------------
with st.sidebar:
    st.title("Menu")
    if "user" not in st.session_state:
        st.session_state["user"] = None

    if st.session_state["user"]:
        st.markdown(f"**Signed in:** {st.session_state['user']}")
        if st.button("Sign out"):
            st.session_state["user"] = None
            st.rerun()
        st.markdown("---")
        page = st.radio("Navigate to", ["Upload & Feedback","My History","Membership","Dashboard","Account"], index=0)
    else:
        mode = st.radio("Account", ["Sign in","Sign up"], index=0)
        if mode == "Sign in":
            email_in = st.text_input("Email", key="email_in")
            pass_in = st.text_input("Password", type="password", key="pass_in")
            if st.button("Sign in", key="btn_signin"):
                if authenticate(email_in, pass_in):
                    st.session_state["user"] = email_in
                    persist()
                    st.success("Signed in")
                    st.rerun()
                else:
                    st.error("Invalid credentials or user does not exist.")
            page = "Account"
        else:
            email_up = st.text_input("Email (create)", key="email_up")
            pass_up = st.text_input("Password (create)", type="password", key="pass_up")
            if st.button("Create account", key="btn_create"):
                if not email_up or not pass_up:
                    st.error("Provide email and password.")
                elif user_exists(email_up):
                    st.error("User already exists.")
                else:
                    try:
                        create_user(email_up, pass_up)
                        persist()
                        st.success("Account created — sign in now.")
                    except Exception as e:
                        st.error(f"Error creating account: {e}")
            page = "Account"

if not st.session_state.get("user") and page != "Account":
    st.info("Please sign in to continue."); st.stop()

USER = st.session_state.get("user")

# -----------------------------------------------------------------------------
# Membership plan card renderer
# -----------------------------------------------------------------------------
def render_plan(title: str, price: str, perks: list, key: str, highlight: bool = False):
    card_class = "plan highlight" if highlight else "plan"
    st.markdown(f'<div class="{card_class}">', unsafe_allow_html=True)
    st.markdown(f"<h3>{title}</h3>", unsafe_allow_html=True)
    st.markdown(f'<div class="price">{price}</div>', unsafe_allow_html=True)
    items = "".join([f"<li>✅ {p}</li>" for p in perks])
    st.markdown(f"<ul>{items}</ul>", unsafe_allow_html=True)
    clicked = st.button(f"Choose {title}", key=key)
    st.markdown("</div>", unsafe_allow_html=True)
    return clicked

# -----------------------------------------------------------------------------
# Video upload → GitHub helper
# -----------------------------------------------------------------------------
def save_video_to_github(file_bytes: bytes, gh_videos_dir: str, gh_repo: str, gh_branch: str, fname: str):
    """
    Saves video bytes into GH_VIDEOS_DIR/fname via GitHub Contents API.
    Returns (ok, raw_url or error_message).
    """
    rel_path = f"{gh_videos_dir.rstrip('/')}/{fname}"
    ok, code, resp = gh_put_binary(
        gh_repo, rel_path, file_bytes,
        message=f"feat: add video {fname}",
        branch=gh_branch, sha=None
    )
    if ok:
        return True, gh_raw_url(gh_repo, gh_branch, rel_path)
    else:
        return False, f"GitHub video upload failed ({code}): {resp[:160]}"

# -----------------------------------------------------------------------------
# Pages
# -----------------------------------------------------------------------------
if page == "Account":
    st.header("Account")
    meta = storage["users"].get(USER, {})
    st.success(f"Signed in as {USER}")
    st.write(f"- Created: {meta.get('created_at','-')}")
    st.write(f"- Membership: {meta.get('membership','Free')}")
    st.markdown("---")
    if st.button("Delete my account"):
        storage["users"].pop(USER, None)
        storage["sessions"] = [s for s in storage.get("sessions", []) if s.get("user") != USER]
        persist()
        st.session_state["user"] = None
        st.success("Account deleted.")
        st.rerun()

elif page == "Upload & Feedback":
    st.header("Upload training clip & get feedback")
    c1, c2 = st.columns([3,1])
    with c1:
        uploaded = st.file_uploader("Upload video (.mp4/.mov)", type=["mp4","mov"])
        role = st.selectbox("Player role", list(FEEDBACK_LIB.keys()))
        skill = st.selectbox("Skill focus", list(FEEDBACK_LIB.get(role, {}).keys()))
        rating = st.slider("Rate this session (1-10)", 1, 10, 7)
        custom = st.text_area("Custom prompt (optional)", placeholder="e.g. improve first touch under pressure")
        analyze = st.button("Analyze & Save")
    with c2:
        st.markdown("### Tips")
        st.write("- Keep clips short (30–60s).")
        st.write("- Rating influences highlights.")
        st.write("- PDFs are hardened against long text.")

    if analyze:
        if not uploaded:
            st.warning("Please upload a video first.")
        else:
            uid = uuid.uuid4().hex
            original_name = uploaded.name
            ext = Path(original_name).suffix.lower() or ".mp4"
            gh_fname = f"{uid}_{Path(original_name).stem}{ext}"

            raw = uploaded.read()

            # local best-effort (optional)
            local_path_str = ""
            try:
                local_path = VIDEO_DIR / gh_fname
                with open(local_path, "wb") as f:
                    f.write(raw)
                local_path_str = str(local_path)
            except Exception:
                pass

            ok, video_url_or_err = save_video_to_github(raw, GH_VIDEOS_DIR, GH_REPO, GH_BRANCH, gh_fname)
            if not ok:
                st.error(video_url_or_err)
                video_raw_url = ""
            else:
                video_raw_url = video_url_or_err

            prompt_text = f"Video: {original_name} | Role: {role} | Skill: {skill} | Rating: {rating}"
            if custom and custom.strip():
                prompt_text += " | Note: " + custom.strip()

            feedback = random.choice(FEEDBACK_LIB.get(role, {}).get(skill, FEEDBACK_LIB["default"]["default"]))
            if custom and custom.strip():
                feedback += "\n\nPlayer note: " + custom.strip()
            feedback += f"\n\nSession rating: {rating}/10"

            highlights = []
            if re.search(r"\b(good|great|excellent|ok|✅)\b", feedback, flags=re.I): highlights.append("✅ Strengths")
            if re.search(r"\b(improve|work on|warn|avoid|⚠️)\b", feedback, flags=re.I): highlights.append("⚠️ Improvements")
            if rating >= 8: highlights.append("🔥 Strong session")
            elif rating <= 4: highlights.append("🔧 Needs work")

            session = {
                "id": uid,
                "user": USER,
                "video_original_name": original_name,
                "video_saved_path": local_path_str,      # optional local
                "video_github_raw_url": video_raw_url,   # authoritative for playback
                "role": role,
                "skill": skill,
                "rating": rating,
                "custom_prompt": custom,
                "prompt_text": prompt_text,
                "feedback": feedback,
                "highlights": highlights,
                "created_at": datetime.utcnow().isoformat()
            }
            storage.setdefault("sessions", []).append(session)
            persist()

            st.success("Saved to history")
            st.subheader("AI Feedback")
            st.write(feedback)

            pdf_b = create_pdf_bytes(original_name, prompt_text, feedback)
            st.download_button("Download feedback PDF", pdf_b, file_name=f"{Path(original_name).stem}_feedback.pdf", mime="application/pdf")

elif page == "My History":
    st.header("My History")
    sessions = [s for s in storage.get("sessions", []) if s.get("user") == USER]
    if not sessions:
        st.info("No sessions yet. Upload a clip to create entries.")
    else:
        for s in sorted(sessions, key=lambda x: x.get("created_at",""), reverse=True):
            st.markdown("---")
            st.subheader(f"{s.get('video_original_name')} • {s.get('role')} / {s.get('skill')}")
            st.caption(s.get("created_at"))
            cols = st.columns([2,1])
            with cols[0]:
                with st.expander("AI Feedback"):
                    st.write(s.get("feedback"))
                st.write(f"Rating: {s.get('rating')}/10")
                st.write(f"Highlights: {', '.join(s.get('highlights') or []) or 'None'}")
                if st.button("Generate PDF", key=f"pdfbtn_{s.get('id')}"):
                    pdfb = create_pdf_bytes(s.get("video_original_name"), s.get("prompt_text"), s.get("feedback"))
                    st.download_button(
                        "Download PDF", pdfb,
                        file_name=f"{Path(s.get('video_original_name','video')).stem}_feedback.pdf",
                        mime="application/pdf",
                        key=f"dl_{s.get('id')}"
                    )

            with cols[1]:
                url = s.get("video_github_raw_url")
                if url:
                    st.video(url)
                else:
                    vpath = s.get("video_saved_path")
                    if vpath and Path(vpath).exists():
                        st.video(vpath)
                    else:
                        st.write("Video not available.")

                if st.button("Delete", key=f"del_{s.get('id')}"):
                    storage["sessions"] = [x for x in storage.get("sessions", []) if x.get("id") != s.get("id")]
                    persist()
                    st.success("Deleted")
                    st.rerun()

elif page == "Membership":
    st.header("Membership")
    user_meta = storage.get("users", {}).get(USER, {})
    st.write(f"Current plan: **{user_meta.get('membership','Free')}**")

    tiers = [
        {
            "title": "Free", "price": "£0 / month",
            "perks": [
                "1 AI analysed video / day",
                "Basic feedback library",
                "Save sessions & view history",
                "Download feedback as PDF",
            ], "key": "choose_free", "highlight": False,
        },
        {
            "title": "Plus", "price": "£7.99 / month",
            "perks": [
                "3 AI analysed videos / day",
                "Role-based coaching feedback",
                "Priority feedback engine",
                "Performance dashboard access",
            ], "key": "choose_plus", "highlight": False,
        },
        {
            "title": "Academy", "price": "£14.99 / month",
            "perks": [
                "10 AI analysed videos / day",
                "Position-specific insights",
                "Weak foot & body-shape breakdown",
                "Custom training suggestions",
                "Download PDFs & export summaries",
            ], "key": "choose_academy", "highlight": True,
        },
        {
            "title": "Pro", "price": "£29.99 / month",
            "perks": [
                "Unlimited AI analysis",
                "Deep tactical & movement breakdown",
                "1-to-1 Private Coach mode (beta)",
                "Advanced analytics & badges",
                "Early access to new AI modules",
            ], "key": "choose_pro", "highlight": False,
        },
    ]

    st.markdown('<div class="tiers">', unsafe_allow_html=True)
    cols = st.columns(4)
    for col, plan in zip(cols, tiers):
        with col:
            if render_plan(plan["title"], plan["price"], plan["perks"], plan["key"], plan["highlight"]):
                storage["users"].setdefault(USER, {})["membership"] = plan["title"]
                persist()
                st.success(f"Upgraded to {plan['title']} 🎉")
                st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)
    st.markdown("---")
    st.caption("Note: Plans are visual only in this MVP. Limits shown are indicative and not enforced yet.")

elif page == "Dashboard":
    st.header("Dashboard")
    sessions = [s for s in storage.get("sessions", []) if s.get("user") == USER]
    total = len(sessions)
    st.metric("Total sessions", total)
    if total:
        df = pd.DataFrame(sessions)
        role_counts = df['role'].value_counts().reset_index()
        role_counts.columns = ['role','count']
        st.plotly_chart(px.pie(role_counts, values='count', names='role', title='Sessions by Role'), use_container_width=True)

        skill_counts = df['skill'].value_counts().reset_index()
        skill_counts.columns = ['skill','count']
        st.plotly_chart(px.bar(skill_counts, x='skill', y='count', title='Sessions by Skill', text='count'), use_container_width=True)

        df['day'] = pd.to_datetime(df['created_at']).dt.date
        trend = df.groupby('day').size().reset_index(name='count')
        st.plotly_chart(px.line(trend, x='day', y='count', title='Sessions over time'), use_container_width=True)

        st.subheader("Recent sessions")
        st.dataframe(df[['created_at','video_original_name','role','skill','rating']].sort_values('created_at', ascending=False).head(10))
    else:
        st.info("No data yet. Upload a session to see insights.")
