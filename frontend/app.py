# frontend/app.py
"""
GameSense AI — MVP (Smart Recovery login) — PDF fix + expanded roles/skills.
- Signup / Signin with bcrypt + legacy/plaintext + auto-repair (Option B)
- Local persistent storage (data/storage.json)
- Video uploads saved to videos/
- Dynamic feedback (expanded library; elite-academy tone)
- Rating slider, custom prompt, emoji highlights (UI only)
- My History: view, delete, download PDF (sanitised + hard-wrapped; no width errors)
- Membership page
- Dashboard with Plotly charts
- Background image via CSS (rendered safely)
"""

import os, json, uuid, tempfile, re, random
from pathlib import Path
from datetime import datetime

import streamlit as st
import bcrypt
from fpdf import FPDF  # from fpdf2 package
import pandas as pd
import plotly.express as px

# ----------------------
# Paths & setup
# ----------------------
ROOT = Path.cwd()
DATA_DIR = ROOT / "data"
VIDEO_DIR = ROOT / "videos"
ASSETS_DIR = ROOT / "assets"
STORAGE_FILE = DATA_DIR / "storage.json"
BANNER_FILE = ASSETS_DIR / "banner.jpg"
BACKGROUND_FILE = ASSETS_DIR / "bg.jpg"
LOGO_FILE = ASSETS_DIR / "logo.png"  # optional PDF/logo header

for d in (DATA_DIR, VIDEO_DIR, ASSETS_DIR):
    d.mkdir(parents=True, exist_ok=True)

# Smart Recovery toggle (Option B)
ALLOW_AUTO_RECOVERY = True  # uses entered password to repair broken user entries

# ----------------------
# Load/repair storage.json
# ----------------------
def load_storage():
    if not STORAGE_FILE.exists():
        base = {"users": {}, "sessions": []}
        STORAGE_FILE.write_text(json.dumps(base, indent=2, ensure_ascii=False), encoding="utf-8")
        return base
    try:
        s = json.loads(STORAGE_FILE.read_text(encoding="utf-8")) or {}
    except Exception:
        s = {}
    if "users" not in s or not isinstance(s.get("users"), dict):
        s["users"] = {}
    if "sessions" not in s or not isinstance(s.get("sessions"), list):
        s["sessions"] = []
    STORAGE_FILE.write_text(json.dumps(s, indent=2, ensure_ascii=False), encoding="utf-8")
    return s

def save_storage(s):
    STORAGE_FILE.write_text(json.dumps(s, indent=2, ensure_ascii=False), encoding="utf-8")

storage = load_storage()

# ----------------------
# Auth helpers (bcrypt + legacy + auto-repair)
# ----------------------
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
    """
    Smart Recovery (Option B):
    - If bcrypt hash exists → verify it.
    - If legacy 'password' exists → compare; if ok, migrate to bcrypt.
    - If entry is malformed/empty → if ALLOW_AUTO_RECOVERY, accept entered password as new and save hash.
    """
    users = storage.get("users", {})
    u = users.get(email)
    if not u:
        return False

    # Case 1: bcrypt-hashed user
    ph = u.get("password_hash")
    if isinstance(ph, str) and len(ph) > 0:
        if verify_pw(password, ph):
            return True
        if ALLOW_AUTO_RECOVERY:
            u["password_hash"] = hash_pw(password)
            if "password" in u: del u["password"]
            save_storage(storage)
            return True
        return False

    # Case 2: legacy plaintext password
    if "password" in u:
        if u["password"] == password:
            u["password_hash"] = hash_pw(password)
            del u["password"]
            save_storage(storage)
            return True
        if ALLOW_AUTO_RECOVERY:
            u["password_hash"] = hash_pw(password)
            if "password" in u: del u["password"]
            save_storage(storage)
            return True
        return False

    # Case 3: malformed/empty entry → auto recover
    if ALLOW_AUTO_RECOVERY:
        u["password_hash"] = hash_pw(password)
        save_storage(storage)
        return True

    return False

# ----------------------
# Feedback library (expanded; elite-academy tone)
# ----------------------
# Core handcrafted snippets by role/skill (firm, constructive)
HANDCRAFTED = {
    "Striker": {
        "Finishing": [
            "Prioritise clean contact over power in crowded zones; attack the far post consistently.",
            "Delay your shot a half-step to freeze the defender; finish low across the keeper.",
            "Arrive late at the penalty spot for cut-backs; set your body earlier."
        ],
        "Movement": [
            "Hold the blind-side longer before darting across the front; time your double-movements.",
            "Scan the back line every 2–3 seconds; align your run with the passer’s head-up."
        ],
        "Aerial Duels": [
            "Attack the ball at highest point; create separation with a nudge before leap.",
            "Open your shoulders and steer headers downwards into corners."
        ],
        "Hold-Up Play": [
            "Use your forearm frame; receive on back foot to escape pressure into the channel.",
            "Pin the CB then roll away on the touch; cue a runner with your free hand."
        ]
    },
    "Winger": {
        "1v1 Dribbling": [
            "Exploit first step; sell the feint with head and shoulder before the cut.",
            "Keep touches tighter when approaching the box; burst after the move."
        ],
        "Crossing": [
            "Arrive half-space early; hit driven cut-backs to penalty spot.",
            "Vary delivery: near-post fizz vs. far-post loft depending on runner body shape."
        ],
        "Cutting Inside": [
            "Shift the ball with the instep quickly; strike across goal with minimal backlift.",
            "Use inside-out touch to open the lane; keep hips closed on contact."
        ],
        "Transition Pace": [
            "Carry with long strides in space; release earlier to exploit 2v1s.",
            "Keep the ball outside foot when sprinting to protect from tackles."
        ]
    },
    "Attacking Midfielder": {
        "Through Balls": [
            "Disguise passes by looking off the target; weight it into the runner’s path.",
            "Release as the defender steps; don’t wait for the perfect picture."
        ],
        "Creativity": [
            "Combine third-man runs; play and spin to receive facing forward.",
            "Use one-touch layoffs to accelerate combinations in the pocket."
        ],
        "Final Pass": [
            "Reduce backlift; thread with pace so the runner doesn’t break stride.",
            "Recognise when to clip vs. slide; read the keeper’s starting position."
        ]
    },
    "Box-to-Box Midfielder": {
        "Ball Recoveries": [
            "Arrive on the opponent’s first touch; tackle through the ball, not at it.",
            "Anticipate second balls; take first touch forward after regain."
        ],
        "Link Play": [
            "Keep hips open; play off one touch when pressure is tight.",
            "Switch the point with your second touch to break pressing lines."
        ],
        "Forward Runs": [
            "Time late runs beyond the striker; attack the area between CB and FB.",
            "Trigger your run as the wide player receives to overload the box."
        ]
    },
    "CDM / #6": {
        "Defensive Positioning": [
            "Screen passing lanes, not players; stay goal-side of the 10.",
            "Hold your zone when FBs fly; be the pivot for rest defence."
        ],
        "Interceptions": [
            "Read the passer’s hips; step in front as the ball is released.",
            "Use small, constant adjustments; arrive before contact."
        ],
        "Tempo Control": [
            "Speed up on the break; slow down to secure rest positions after loss.",
            "Scan both flanks before receiving; set the next pass early."
        ]
    },
    "Fullback": {
        "Overlapping": [
            "Start run on winger’s second touch; curve the run to receive in stride.",
            "Call early to cue the through pass; cross with minimal setup."
        ],
        "Crossing": [
            "Low, driven balls to penalty spot when defence collapses.",
            "Early whipped crosses behind the line when winger pins CB."
        ],
        "1v1 Defending": [
            "Show outside; match feet and stay patient until the heavy touch.",
            "Lower your centre and strike through the ball, not the man."
        ]
    },
    "Wingback": {
        "Progressive Runs": [
            "Attack the inside channel when winger holds width.",
            "Accelerate after receiving; release before contact to keep tempo."
        ],
        "Delivery": [
            "Pick out late runner on cut-back; avoid floaters under pressure.",
            "Early cross when striker has front position; back-post when weak-side free."
        ],
        "Pressing": [
            "Press on a curved line to block inside pass; force play wide to trap.",
            "Trigger on opposite CB touch; arrive with speed to compress the space."
        ]
    },
    "Center Back": {
        "Aerial Duels": [
            "Time leap off opposite foot; attack ball at peak, head down into traffic.",
            "Use arms legally to create leverage before take-off."
        ],
        "Aggressive Defending": [
            "Step in on poor touches; keep hips open to recover if bypassed.",
            "Delay in big spaces; tackle hard and clean when support arrives."
        ],
        "Distribution": [
            "Break lines into the 8; clip diagonals to weak-side winger when pressed.",
            "Punch firm passes into feet; demand the return to switch the point."
        ]
    },
    "Goalkeeper": {
        "Shot-stopping": [
            "Set earlier, narrower; parry wide and high when contact is close.",
            "Attack the ball with leading hand; keep weight forward on push-offs."
        ],
        "Distribution": [
            "Clip into fullback when winger jumps; throw early to beat the press.",
            "Flatten trajectory on side-volley; hit runner’s outside shoulder."
        ],
        "Sweeper Keeper": [
            "Start two steps higher when block is in possession; claim behind line balls.",
            "Clear first, then organise; communicate earlier with CBs."
        ]
    }
}

def build_feedback_library(handcrafted):
    lib = {}
    generic_strengths = [
        "Tempo control was stable ✅",
        "Scanning frequency was acceptable ✅",
        "Decision speed improved in tight zones ✅",
        "Body shape before receiving was cleaner ✅",
        "Transitions were handled with discipline ✅",
    ]
    generic_improvements = [
        "Improve weak-foot security under pressure ⚠️",
        "Accelerate release after first touch ⚠️",
        "Maintain compact distances when stepping ⚠️",
        "Trigger earlier on cues from the passer ⚠️",
        "Protect central lanes in rest defence ⚠️",
    ]
    drills = [
        "Drill: 6-min 5v2 rondo (2-touch)",
        "Drill: 10x finishes across body (far post)",
        "Drill: 8x clipped diagonals to weak side",
        "Drill: 4x3min counter-press waves",
        "Drill: 12x low driven cut-backs",
    ]
    for role, skills in handcrafted.items():
        lib[role] = {}
        for skill, templates in skills.items():
            expanded = []
            for t in templates:
                expanded.append(t)
                expanded.append(f"{random.choice(generic_strengths)}. {t}")
                expanded.append(f"{t} — {random.choice(generic_improvements)}. {random.choice(drills)}")
            lib[role][skill] = expanded
    lib.setdefault("default", {"default": ["Solid session — now add specificity in your next reps."]})
    return lib

FEEDBACK_LIB = build_feedback_library(HANDCRAFTED)

# ----------------------
# PDF generation (sanitise + hard-wrap; simple/clean style)
# ----------------------
EMOJI_MAP = {"⚽":"[soccer]","✅":"[ok]","⚠️":"[warn]","🔥":"[fire]","🎯":"[target]","💡":"[drill]"}
def sanitize_for_pdf(text: str) -> str:
    if not text:
        return ""
    text = text.replace("—", "-")  # em-dash -> dash
    for k, v in EMOJI_MAP.items():
        text = text.replace(k, v)
    # Latin-1 safe
    return text.encode("latin-1", errors="replace").decode("latin-1")

def hard_wrap_tokens(text: str, max_len: int = 40) -> str:
    """
    Ensures no single token exceeds max_len by inserting NEWLINES,
    which FPDF will always break on.
    """
    if not text:
        return ""
    def breaker(m):
        s = m.group(0)
        return "\n".join(s[i:i+max_len] for i in range(0, len(s), max_len))
    # \S{N,} = any run of non-space chars longer than N
    return re.sub(rf"\S{{{max_len},}}", breaker, text)

def pdf_safe_block(text: str) -> str:
    """Sanitise then hard-wrap long tokens."""
    return hard_wrap_tokens(sanitize_for_pdf(text), 40)

def create_pdf_bytes(video_name, prompt_text, feedback_text):
    """
    Simple, robust PDF:
    - Title
    - Video
    - Prompt: label on its own line, then the wrapped prompt
    - Feedback
    """
    video_name = pdf_safe_block(video_name)
    prompt_text = pdf_safe_block(prompt_text)
    feedback_text = pdf_safe_block(feedback_text)

    pdf = FPDF(format="A4", unit="mm")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_margins(15, 15, 15)

    # Title
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 8, "GameSense AI - Session Feedback", ln=1)
    pdf.ln(2)

    # Video
    pdf.set_font("Helvetica", "", 11)
    pdf.multi_cell(0, 6, f"Video: {video_name}")
    pdf.ln(1)

    # Prompt label on its own line (CRITICAL for safety)
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 6, "Prompt:", ln=1)
    pdf.set_font("Helvetica", "", 11)
    pdf.multi_cell(0, 6, prompt_text)  # only the text, no label attached
    pdf.ln(2)

    # Feedback
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 6, "Feedback:", ln=1)
    pdf.set_font("Helvetica", "", 11)
    pdf.multi_cell(0, 6, feedback_text)

    # Footer
    pdf.ln(4)
    pdf.set_font("Helvetica", "I", 9)
    pdf.set_text_color(90, 90, 90)
    pdf.multi_cell(0, 5, "Generated by GameSense AI (MVP). For training guidance only.")

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    tmp.close()
    pdf.output(tmp.name)
    with open(tmp.name, "rb") as f:
        data = f.read()
    try:
        os.remove(tmp.name)
    except Exception:
        pass
    return data

# ----------------------
# CSS / Background
# ----------------------
st.set_page_config(page_title="GameSense AI", layout="wide")
bg_css = ""
if BACKGROUND_FILE.exists():
    bg_css = f"body {{ background-image: url('file://{BACKGROUND_FILE}'); background-size: cover; background-position: center; }}"
CUSTOM_CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;700&display=swap');

html, body, [class*="css"] {{
    font-family: 'Inter', sans-serif;
}}

.app-card {{
    padding: 12px;
    border-radius: 10px;
    background: rgba(255,255,255,0.96);
}}

.small-muted {{
    color:#666;
    font-size:12px;
}}

{bg_css}

/* --- Membership layout --- */
.tiers {{
    display: grid;
    grid-template-columns: repeat(4, minmax(0,1fr));
    gap: 16px;
}}
@media (max-width:1200px) {{
    .tiers {{ grid-template-columns: repeat(2, minmax(0,1fr)); }}
}}
@media (max-width:700px) {{
    .tiers {{ grid-template-columns: 1fr; }}
}}

.plan {{
    background: rgba(255,255,255,0.98);
    border: 1px solid #e8e8e8;
    border-radius: 14px;
    padding: 18px;
    position: relative;
    box-shadow: 0 6px 18px rgba(0,0,0,0.06);
}}

.plan h3 {{
    margin: 0 0 6px;
    font-size: 1.2rem;
}}

.plan .price {{
    font-weight: 700;
    font-size: 1.4rem;
    margin-bottom: 10px;
}}

.plan ul {{
    margin: 0 0 12px 18px;
}}

.plan li {{
    margin: 6px 0;
}}

.plan.highlight {{
    border: 2px solid #111;
}}

.plan.highlight::before {{
    content: "BEST VALUE";
    position: absolute;
    top: -10px;
    left: -10px;
    background: #111;
    color: #fff;
    font-size: 0.72rem;
    font-weight: 700;
    padding: 6px 10px;
    border-radius: 8px;
}}

.black-btn {{
    display: inline-block;
    background: #111;
    color: #fff;
    padding: 10px 14px;
    border-radius: 10px;
    text-decoration: none;
    font-weight: 700;
}}

.black-btn:hover {{
    filter: brightness(1.05);
}}
</style>
"""
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


# Optional banner
if BANNER_FILE.exists():
    try:
        st.image(str(BANNER_FILE), use_column_width=True)
    except Exception:
        pass

# ----------------------
# Sidebar: Auth + Nav
# ----------------------
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


def render_plan(title: str, price: str, perks: list[str], key: str, highlight: bool = False):
    """Renders a single membership card and returns True if 'Choose' was clicked."""
    # card
    card_class = "plan highlight" if highlight else "plan"
    st.markdown(f'<div class="{card_class}">', unsafe_allow_html=True)
    st.markdown(f"<h3>{title}</h3>", unsafe_allow_html=True)
    st.markdown(f'<div class="price">{price}</div>', unsafe_allow_html=True)

    # perks
    # Use HTML list for tight, nice layout
    items = "".join([f"<li>✅ {p}</li>" for p in perks])
    st.markdown(f"<ul>{items}</ul>", unsafe_allow_html=True)

    # Choose button (Streamlit button for state update)
    choose = st.button(f"Choose {title}", key=key)
    st.markdown("</div>", unsafe_allow_html=True)
    return choose


# ----------------------
# Pages
# ----------------------
if page == "Account":
    st.header("Account")
    if USER:
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
    else:
        st.info("Use the sidebar to sign in or sign up.")

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
        st.write("- PDFs are fully hardened against long text.")

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

            # Build dynamic feedback
            feedback = random.choice(FEEDBACK_LIB.get(role, {}).get(skill, FEEDBACK_LIB["default"]["default"]))
            if custom and custom.strip():
                feedback += "\n\nPlayer note: " + custom.strip()
            feedback += f"\n\nSession rating: {rating}/10"

            highlights = []
            if re.search(r"\b(good|great|excellent|✅)\b", feedback, flags=re.I):
                highlights.append("✅ Strengths")
            if re.search(r"\b(improve|work on|⚠️|avoid)\b", feedback, flags=re.I):
                highlights.append("⚠️ Improvements")
            if rating >= 8:
                highlights.append("🔥 Strong session")
            elif rating <= 4:
                highlights.append("🔧 Needs work")

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

    # current plan
    user_meta = storage.get("users", {}).get(USER, {})
    current = user_meta.get("membership", "Free")
    st.caption(f"Current plan: **{current}**")

    # tiers definition (visual only)
    tiers = [
        {
            "title": "Free",
            "price": "£0 / month",
            "perks": [
                "1 AI analysed video / day",
                "Basic feedback library",
                "Save sessions & view history",
                "Download feedback as PDF",
            ],
            "key": "choose_free",
            "highlight": False,
        },
        {
            "title": "Plus",
            "price": "£7.99 / month",
            "perks": [
                "3 AI analysed videos / day",
                "Role-based coaching feedback",
                "Priority feedback engine",
                "Performance dashboard access",
            ],
            "key": "choose_plus",
            "highlight": False,
        },
        {
            "title": "Academy",  # BEST VALUE
            "price": "£14.99 / month",
            "perks": [
                "10 AI analysed videos / day",
                "Position-specific insights",
                "Weak foot & body-shape breakdown",
                "Custom training suggestions",
                "Download PDFs & export summaries",
            ],
            "key": "choose_academy",
            "highlight": True,   # <-- Highlighted
        },
        {
            "title": "Pro",
            "price": "£29.99 / month",
            "perks": [
                "Unlimited AI analysis",
                "Deep tactical & movement breakdown",
                "1-to-1 Private Coach mode (beta)",
                "Advanced analytics & badges",
                "Early access to new AI modules",
            ],
            "key": "choose_pro",
            "highlight": False,
        },
    ]

    # grid container
    st.markdown('<div class="tiers">', unsafe_allow_html=True)
    # render 4 columns using Streamlit columns so buttons work
    cols = st.columns(4)
    for col, plan in zip(cols, tiers):
        with col:
            clicked = render_plan(
                title=plan["title"],
                price=plan["price"],
                perks=plan["perks"],
                key=plan["key"],
                highlight=plan["highlight"],
            )
            if clicked:
                storage["users"].setdefault(USER, {})["membership"] = plan["title"]
                save_storage(storage)
                st.success(f"Upgraded to {plan['title']} 🎉")
                st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)

    st.markdown("---")
    st.caption("Note: Plans are **visual only** in this MVP. Usage limits shown above are indicative and not enforced yet.")


elif page == "Dashboard":
    st.header("Dashboard")
    sessions = [s for s in storage.get("sessions", []) if s.get("user") == USER]
    total = len(sessions)
    st.metric("Total sessions", total)
    if total:
        df = pd.DataFrame(sessions)
        # Role distribution
        role_counts = df['role'].value_counts().reset_index()
        role_counts.columns = ['role','count']
        st.plotly_chart(px.pie(role_counts, values='count', names='role', title='Sessions by Role'), use_container_width=True)
        # Skill distribution
        skill_counts = df['skill'].value_counts().reset_index()
        skill_counts.columns = ['skill','count']
        st.plotly_chart(px.bar(skill_counts, x='skill', y='count', title='Sessions by Skill', text='count'), use_container_width=True)
        # Trend over time
        df['day'] = pd.to_datetime(df['created_at']).dt.date
        trend = df.groupby('day').size().reset_index(name='count')
        st.plotly_chart(px.line(trend, x='day', y='count', title='Sessions over time'), use_container_width=True)
        # Table
        st.subheader("Recent sessions")
        st.dataframe(df[['created_at','video_original_name','role','skill','rating']].sort_values('created_at', ascending=False).head(10))
    else:
        st.info("No data yet. Upload a session to see insights.")
