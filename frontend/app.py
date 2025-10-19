# frontend/app.py
"""
GameSense AI — MVP (Cloud + GitHub-persistent storage)
- Signup / Signin (bcrypt + smart recovery)
- Persistent storage via GitHub (storage.json committed to repo); fallback to /tmp if secrets missing
- Upload video (saved to /tmp/videos), dynamic mock feedback (expanded role/skills)
- Rating slider, custom prompt, emoji highlights
- My History: view, delete, download PDF (crash-proof: sanitised + hard-wrapped)
- Membership page (Free / Plus / Academy [BEST VALUE] / Pro) — visual only
- Dashboard (Plotly)
- Background image via CSS if assets/bg.jpg exists
"""

import os, json, uuid, tempfile, re, random, base64, time
from pathlib import Path
from datetime import datetime

import streamlit as st
import bcrypt
from fpdf import FPDF
import pandas as pd
import plotly.express as px
import requests

# ------------------------------------------------------------------------------------
# Streamlit page setup
# ------------------------------------------------------------------------------------
st.set_page_config(page_title="GameSense AI", layout="wide")

# ------------------------------------------------------------------------------------
# Paths (videos local in /tmp; storage via GitHub sync)
# ------------------------------------------------------------------------------------
TMP_BASE = Path(tempfile.gettempdir()) / "gamesense_ai"
DATA_DIR = TMP_BASE / "data"
VIDEO_DIR = TMP_BASE / "videos"
ASSETS_DIR = TMP_BASE / "assets"     # optional, likely empty on cloud
for d in (DATA_DIR, VIDEO_DIR, ASSETS_DIR):
    d.mkdir(parents=True, exist_ok=True)

LOCAL_STORAGE_FILE = DATA_DIR / "storage.json"
BACKGROUND_FILE = ASSETS_DIR / "bg.jpg"
BANNER_FILE = ASSETS_DIR / "banner.jpg"

# ------------------------------------------------------------------------------------
# GitHub persistent storage configuration
# Provide via Streamlit Secrets (Manage app → Settings → Secrets) or env vars.
# Required: GITHUB_TOKEN, GH_REPO_OWNER, GH_REPO_NAME
# Optional: GH_BRANCH (default "main"), GH_STORAGE_PATH (default "data/storage.json")
# ------------------------------------------------------------------------------------
GH_TOKEN = st.secrets.get("GITHUB_TOKEN", os.getenv("GITHUB_TOKEN"))
GH_OWNER = st.secrets.get("GH_REPO_OWNER", os.getenv("GH_REPO_OWNER"))
GH_REPO = st.secrets.get("GH_REPO_NAME", os.getenv("GH_REPO_NAME") or os.getenv("GH_REPO"))
GH_BRANCH = st.secrets.get("GH_BRANCH", os.getenv("GH_BRANCH", "main"))
GH_STORAGE_PATH = st.secrets.get("GH_STORAGE_PATH", os.getenv("GH_STORAGE_PATH", "data/storage.json"))

def _gh_headers():
    return {"Authorization": f"Bearer {GH_TOKEN}", "Accept": "application/vnd.github+json"}

def gh_enabled() -> bool:
    return bool(GH_TOKEN and GH_OWNER and GH_REPO and GH_BRANCH and GH_STORAGE_PATH)

def gh_get_storage():
    """Fetch storage.json from GitHub. Returns (dict, sha) or (None, None) if not found/fails."""
    try:
        url = f"https://api.github.com/repos/{GH_OWNER}/{GH_REPO}/contents/{GH_STORAGE_PATH}?ref={GH_BRANCH}"
        r = requests.get(url, headers=_gh_headers(), timeout=15)
        if r.status_code == 200:
            data = r.json()
            content_b64 = data.get("content", "")
            decoded = base64.b64decode(content_b64).decode("utf-8")
            sha = data.get("sha")
            return json.loads(decoded), sha
        elif r.status_code == 404:
            # file not found — treat as empty new file
            return {"users": {}, "sessions": []}, None
        else:
            return None, None
    except Exception:
        return None, None

def gh_put_storage(storage_dict, sha=None):
    """Commit updated storage.json to GitHub."""
    try:
        url = f"https://api.github.com/repos/{GH_OWNER}/{GH_REPO}/contents/{GH_STORAGE_PATH}"
        content_str = json.dumps(storage_dict, indent=2, ensure_ascii=False)
        content_b64 = base64.b64encode(content_str.encode("utf-8")).decode("utf-8")
        msg = f"GameSense AI: update storage.json ({datetime.utcnow().isoformat()})"
        payload = {
            "message": msg,
            "content": content_b64,
            "branch": GH_BRANCH,
        }
        if sha:
            payload["sha"] = sha
        r = requests.put(url, headers=_gh_headers(), json=payload, timeout=20)
        if r.status_code in (200, 201):
            return r.json().get("content", {}).get("sha")
        return None
    except Exception:
        return None

# ------------------------------------------------------------------------------------
# Storage helpers (auto GitHub sync; fallback local)
# ------------------------------------------------------------------------------------
def _ensure_local_base(storage_dict=None):
    """Make sure LOCAL_STORAGE_FILE exists and is minimally valid."""
    if storage_dict is None:
        if not LOCAL_STORAGE_FILE.exists():
            storage_dict = {"users": {}, "sessions": []}
            LOCAL_STORAGE_FILE.write_text(json.dumps(storage_dict, indent=2, ensure_ascii=False), encoding="utf-8")
        else:
            try:
                storage_dict = json.loads(LOCAL_STORAGE_FILE.read_text(encoding="utf-8")) or {}
            except Exception:
                storage_dict = {}
        storage_dict.setdefault("users", {})
        storage_dict.setdefault("sessions", [])
    LOCAL_STORAGE_FILE.write_text(json.dumps(storage_dict, indent=2, ensure_ascii=False), encoding="utf-8")
    return storage_dict

def load_storage():
    # Try GitHub first if enabled
    if gh_enabled():
        data, sha = gh_get_storage()
        if isinstance(data, dict):
            data.setdefault("users", {})
            data.setdefault("sessions", [])
            # also mirror locally to /tmp as cache
            _ensure_local_base(data)
            st.session_state["_gh_sha"] = sha
            return data
        # fallback to local if GH failed
    # Local fallback
    return _ensure_local_base()

def save_storage(storage_dict):
    # Always keep local cache current
    _ensure_local_base(storage_dict)
    # Try committing to GitHub if enabled
    if gh_enabled():
        current_sha = st.session_state.get("_gh_sha")
        new_sha = gh_put_storage(storage_dict, sha=current_sha)
        if new_sha:
            st.session_state["_gh_sha"] = new_sha

storage = load_storage()

# ------------------------------------------------------------------------------------
# Auth (bcrypt + smart recovery)
# ------------------------------------------------------------------------------------
ALLOW_AUTO_RECOVERY = True

def hash_pw(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

def verify_pw(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
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
    save_storage(storage)

def authenticate(email: str, password: str) -> bool:
    u = storage.get("users", {}).get(email)
    if not u:
        return False
    ph = u.get("password_hash")
    if isinstance(ph, str) and ph:
        if verify_pw(password, ph):
            return True
        if ALLOW_AUTO_RECOVERY:
            u["password_hash"] = hash_pw(password)
            u.pop("password", None)
            save_storage(storage)
            return True
        return False
    if "password" in u:
        if u["password"] == password:
            u["password_hash"] = hash_pw(password)
            u.pop("password", None)
            save_storage(storage)
            return True
        if ALLOW_AUTO_RECOVERY:
            u["password_hash"] = hash_pw(password)
            u.pop("password", None)
            save_storage(storage)
            return True
        return False
    if ALLOW_AUTO_RECOVERY:
        u["password_hash"] = hash_pw(password)
        save_storage(storage)
        return True
    return False

# ------------------------------------------------------------------------------------
# Feedback Library (expanded)
# ------------------------------------------------------------------------------------
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
            "Vary delivery: near-post fizz vs. far-post loft based on runner body shape."
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
        "Tempo control was stable ✅","Scanning frequency acceptable ✅","Decision speed improved ✅",
        "Body shape cleaner before receive ✅","Transitions handled with discipline ✅"
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

# ------------------------------------------------------------------------------------
# PDF helpers (crash-proof)
# ------------------------------------------------------------------------------------
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
    video_name = pdf_safe_block(video_name)
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

# ------------------------------------------------------------------------------------
# CSS (includes membership card styles)
# ------------------------------------------------------------------------------------
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
/* Membership */
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

# Optional banner
if BANNER_FILE.exists():
    try:
        st.image(str(BANNER_FILE), use_column_width=True)
    except Exception:
        pass

# ------------------------------------------------------------------------------------
# Sidebar (Auth + Nav)
# ------------------------------------------------------------------------------------
with st.sidebar:
    st.title("GameSense AI")
    st.write("AI-style football coaching feedback")
    st.markdown("---")

    if "user" not in st.session_state:
        st.session_state["user"] = None

    if st.session_state["user"]:
        st.markdown(f"**Signed in:** {st.session_state['user']}")
        if st.button("Sign out"):
            st.session_state["user"] = None
            st.rerun()
        st.markdown("---")
        page = st.radio("Go to", ["Upload & Feedback","My History","Membership","Dashboard","Account"])
    else:
        mode = st.radio("Account", ["Sign in","Sign up"])
        if mode == "Sign in":
            email_in = st.text_input("Email", key="email_in")
            pass_in = st.text_input("Password", type="password", key="pass_in")
            if st.button("Sign in", key="btn_signin"):
                if authenticate(email_in, pass_in):
                    st.session_state["user"] = email_in
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
                    create_user(email_up, pass_up)
                    st.success("Account created — sign in now.")
            page = "Account"

if not st.session_state.get("user") and page != "Account":
    st.info("Please sign in to continue.")
    st.stop()

USER = st.session_state.get("user")

# ------------------------------------------------------------------------------------
# Membership card renderer
# ------------------------------------------------------------------------------------
def render_plan(title: str, price: str, perks: list[str], key: str, highlight: bool = False):
    card_class = "plan highlight" if highlight else "plan"
    st.markdown(f'<div class="{card_class}">', unsafe_allow_html=True)
    st.markdown(f"<h3>{title}</h3>", unsafe_allow_html=True)
    st.markdown(f'<div class="price">{price}</div>', unsafe_allow_html=True)
    items = "".join([f"<li>✅ {p}</li>" for p in perks])
    st.markdown(f"<ul>{items}</ul>", unsafe_allow_html=True)
    clicked = st.button(f"Choose {title}", key=key)
    st.markdown("</div>", unsafe_allow_html=True)
    return clicked

# ------------------------------------------------------------------------------------
# Pages
# ------------------------------------------------------------------------------------
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
        save_storage(storage)
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
        st.write("- Use rating to influence highlights.")
        st.write("- PDFs are crash-proof (long text safe).")

    if analyze:
        if not uploaded:
            st.warning("Please upload a video first.")
        else:
            uid = uuid.uuid4().hex
            save_name = f"{uid}_{uploaded.name}"
            save_path = VIDEO_DIR / save_name
            with open(save_path, "wb") as f:
                f.write(uploaded.getbuffer())

            prompt_text = f"Video: {uploaded.name} | Role: {role} | Skill: {skill} | Rating: {rating}"
            if custom and custom.strip():
                prompt_text += " | Note: " + custom.strip()

            feedback = random.choice(FEEDBACK_LIB.get(role, {}).get(skill, FEEDBACK_LIB["default"]["default"]))
            if custom and custom.strip():
                feedback += "\n\nPlayer note: " + custom.strip()
            feedback += f"\n\nSession rating: {rating}/10"

            highlights = []
            if re.search(r"\b(good|great|excellent|ok)\b", feedback, flags=re.I): highlights.append("✅ Strengths")
            if re.search(r"\b(improve|work on|warn|avoid)\b", feedback, flags=re.I): highlights.append("⚠️ Improvements")
            if rating >= 8: highlights.append("🔥 Strong session")
            elif rating <= 4: highlights.append("🔧 Needs work")

            session = {
                "id": uid,
                "user": USER,
                "video_original_name": uploaded.name,
                "video_saved_path": str(save_path),
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
            save_storage(storage)

            st.success("Saved to history")
            st.subheader("AI Feedback")
            st.write(feedback)
            pdf_b = create_pdf_bytes(uploaded.name, prompt_text, feedback)
            st.download_button("Download feedback PDF", pdf_b, file_name=f"{uploaded.name}_feedback.pdf", mime="application/pdf")

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
                    st.download_button("Download PDF", pdfb, file_name=f"{s.get('video_original_name')}_feedback.pdf", mime="application/pdf", key=f"dl_{s.get('id')}")
            with cols[1]:
                vpath = s.get("video_saved_path")
                if vpath and Path(vpath).exists():
                    st.video(vpath)
                else:
                    st.write("Video missing.")
                if st.button("Delete", key=f"del_{s.get('id')}"):
                    try:
                        if vpath and Path(vpath).exists():
                            Path(vpath).unlink()
                    except Exception:
                        pass
                    storage["sessions"] = [x for x in storage.get("sessions", []) if x.get("id") != s.get("id")]
                    save_storage(storage)
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
            ], "key": "choose_academy", "highlight": True,  # BEST VALUE
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
                save_storage(storage)
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
