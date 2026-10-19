"""
app.py  –  BloodNet: Inter-Hospital Blood Bank Inventory Balancer
Run:   streamlit run app.py
Needs: blood_balancer.py and real_data.py in the same folder.
"""

import csv, io, math, os, random, tempfile
from collections import defaultdict
from datetime import date, datetime, timedelta

import matplotlib.pyplot as plt
import streamlit as st
from html import escape

import blood_balancer as bb
import real_data as rd

# ─────────────────────────────────────────────────────────────────────────────
# PAGE CONFIG
# ─────────────────────────────────────────────────────────────────────────────
def _favicon():
    """Flat red droplet, drawn at runtime so no emoji or image file is needed."""
    try:
        from PIL import Image, ImageDraw
        im = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        d.ellipse((12, 24, 52, 62), fill="#d92d2d")
        d.polygon([(32, 2), (14, 38), (50, 38)], fill="#d92d2d")
        return im
    except Exception:
        return None


st.set_page_config(
    page_title="BloodNet - Blood Bank Balancer",
    page_icon=_favicon(),
    layout="wide",
    initial_sidebar_state="expanded",
)

PAGES = ["Live Proposals", "Simulation", "Backtest", "Audit Log"]

DARK = dict(bg="#0b0f14", surface="#121922", surface2="#18212c", border="#263243",
            text="#e8edf3", muted="#a8b4c6", accent="#ef4444", soft="rgba(239,68,68,.14)",
            good="#34d399", warn="#fbbf24", bad="#f87171", shadow="0 10px 28px rgba(0,0,0,.5)",
            field="#e8edf3", fieldtext="#000000", fieldbtn="#c9d1db", scheme="dark")
LIGHT = dict(bg="#f5f6f8", surface="#ffffff", surface2="#f0f2f5", border="#dde2e9",
             text="#151a22", muted="#5d6a7c", accent="#d92d2d", soft="rgba(217,45,45,.10)",
             good="#0f9d6b", warn="#b7791f", bad="#d92d2d", shadow="0 10px 26px rgba(20,26,34,.14)",
             field="#ffffff", fieldtext="#000000", fieldbtn="#eceff3", scheme="light")


def _native_theme():
    """Start in whatever mode the browser/Streamlit is already using."""
    try:
        return "Light" if st.context.theme.type == "light" else "Dark"
    except Exception:
        return "Dark"


st.session_state.setdefault("theme", _native_theme())
P = LIGHT if st.session_state.theme == "Light" else DARK

plt.rcParams.update({
    "figure.facecolor": P["surface"], "axes.facecolor": P["surface"],
    "savefig.facecolor": P["surface"], "axes.edgecolor": P["border"],
    "axes.labelcolor": P["muted"], "axes.titlecolor": P["text"],
    "text.color": P["text"], "xtick.color": P["muted"], "ytick.color": P["muted"],
    "legend.facecolor": P["surface"], "legend.edgecolor": P["border"],
    "legend.labelcolor": P["text"], "axes.spines.top": False, "axes.spines.right": False,
    "font.size": 10,
})

BTN_CSS = """
.st-key-theme_toggle{display:flex;justify-content:flex-end;margin-top:.5rem}
.st-key-theme_toggle button{position:relative;overflow:hidden;width:50px!important;height:50px!important;min-height:0!important;padding:0!important;border-radius:50%!important;background:var(--surface)!important;border:1px solid var(--border)!important}
.st-key-theme_toggle button p{font-size:0!important}
.st-key-theme_toggle button:hover{transform:scale(1.1)!important;border-color:var(--accent)!important;box-shadow:0 0 0 5px var(--soft)!important}
.st-key-theme_toggle button::before,.st-key-theme_toggle button::after{content:"";position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);transition:transform .55s ease}
"""
SUN_CSS = BTN_CSS + """
.st-key-theme_toggle button::before{width:14px;height:14px;border-radius:50%;background:var(--accent)}
.st-key-theme_toggle button::after{width:32px;height:32px;border-radius:50%;background:repeating-conic-gradient(var(--accent) 0 12deg,transparent 12deg 45deg);-webkit-mask:radial-gradient(circle,transparent 11px,#000 12px,#000 15px,transparent 16px);mask:radial-gradient(circle,transparent 11px,#000 12px,#000 15px,transparent 16px)}
.st-key-theme_toggle button:hover::after{transform:translate(-50%,-50%) rotate(90deg)}
"""
MOON_CSS = BTN_CSS + """
.st-key-theme_toggle button::before{width:24px;height:24px;border-radius:50%;box-shadow:inset -8px -3px 0 0 var(--text)}
.st-key-theme_toggle button::after{width:3px;height:3px;top:30%;left:72%;border-radius:50%;background:var(--text);box-shadow:6px 9px 0 -.5px var(--text)}
.st-key-theme_toggle button:hover::before{transform:translate(-50%,-50%) rotate(-35deg)}
.st-key-theme_toggle button:hover::after{transform:translate(-50%,-50%) scale(1.8)}
"""


CSS = r"""
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
:root{__ROOT__}
html,body,.stApp,[data-testid="stAppViewContainer"],[data-testid="stMain"]{background:var(--bg)!important;color:var(--text);color-scheme:var(--scheme);font-family:'Inter',system-ui,-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif}
.stApp *:not([data-testid="stIconMaterial"]):not(code):not(pre):not(.bn-chip):not(.bn-id){font-family:'Inter',system-ui,-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif!important}
.stApp.stApp.stApp.stApp.stApp :is(h1,h2,h3,h4,h5,h6,h1 *,h2 *,h3 *,h4 *,h5 *,h6 *,.bn-title,.bn-title *){font-family:'Times New Roman',Times,'Liberation Serif',serif!important}
[data-testid="stHeader"]{background:transparent}
[data-testid="stDecoration"]{display:none}
.block-container{max-width:1240px;padding-top:2.2rem;padding-bottom:4rem}
h1,h2,h3,h4,p,li,label,[data-testid="stMarkdownContainer"],[data-testid="stWidgetLabel"] p{color:var(--text)}
h3{font-weight:650;letter-spacing:-.01em}
[data-testid="stWidgetLabel"] p{color:var(--muted);font-size:.85rem;font-weight:500}
[data-testid="stCaptionContainer"],[data-testid="stCaptionContainer"] *{color:var(--muted)!important}
hr{border-color:var(--border)!important}
code{background:var(--surface2)!important;color:var(--accent)!important;border-radius:6px;padding:.1em .4em}
a{color:var(--accent)}
/* inputs */
[data-baseweb="input"],[data-baseweb="base-input"],[data-baseweb="textarea"],[data-baseweb="select"]>div{background:var(--field)!important;border-color:var(--border)!important;color:var(--fieldtext)!important;border-radius:10px!important;transition:border-color .18s ease,box-shadow .18s ease}
[data-baseweb="input"]:hover,[data-baseweb="textarea"]:hover,[data-baseweb="select"]>div:hover,[data-baseweb="input"]:focus-within,[data-baseweb="textarea"]:focus-within{border-color:var(--accent)!important;box-shadow:0 0 0 3px var(--soft)}
[data-baseweb="select"] div,[data-baseweb="input"] div,[data-baseweb="base-input"],[data-testid="stNumberInputContainer"],[data-testid="stNumberInputContainer"] div{background:var(--field)!important}
input,textarea,[data-baseweb="select"] input{color:var(--fieldtext)!important;-webkit-text-fill-color:var(--fieldtext)!important;background:transparent!important;caret-color:var(--accent)}
input::placeholder,textarea::placeholder{color:#000!important;-webkit-text-fill-color:#000!important;opacity:1!important}
[data-baseweb="select"] [class*="placeholder"],[data-baseweb="select"] [aria-live]{color:#000!important}
[data-testid="InputInstructions"],[data-testid="InputInstructions"] *{color:#000!important;background:transparent!important}
[data-baseweb="datepicker"],[data-baseweb="calendar"]{background:var(--surface)!important}
[data-baseweb="calendar"] *{color:var(--text)!important}
[data-baseweb="select"] *{color:var(--fieldtext)!important}
[data-baseweb="select"] svg{fill:var(--fieldtext)!important}
[data-testid="stNumberInputContainer"] button{background:var(--fieldbtn)!important;color:var(--fieldtext)!important;border:0}
[data-testid="stNumberInputContainer"] button:hover{background:var(--soft)!important;box-shadow:none;transform:none}
[data-testid="stNumberInputContainer"] button svg{fill:var(--fieldtext)!important}
[data-baseweb="popover"]>div,[data-baseweb="menu"],ul[role="listbox"]{background:var(--surface)!important;border:1px solid var(--border);border-radius:10px;box-shadow:var(--shadow)}
li[role="option"]{color:var(--text)!important;transition:background .15s ease,padding-left .15s ease}
li[role="option"]:hover,li[aria-selected="true"]{background:var(--soft)!important;padding-left:1.15rem}
[data-testid="stSliderThumbValue"]{color:var(--text)}
[data-testid="stSliderTickBarMin"],[data-testid="stSliderTickBarMax"]{color:var(--muted)}
/* buttons */
[data-testid^="stBaseButton"],.stButton>button,.stDownloadButton>button{border-radius:10px;border:1px solid var(--border);background:var(--surface);color:var(--text);font-weight:600;transition:transform .18s ease,box-shadow .18s ease,border-color .18s ease,background .18s ease,filter .18s ease}
button p,button div,button span{color:inherit!important}
[data-testid="stBaseButton-primary"],[data-testid="stBaseButton-primaryFormSubmit"],button[kind="primary"],button[kind="primaryFormSubmit"]{background:var(--accent)!important;border-color:var(--accent)!important;color:#fff!important}
button:hover:not(:disabled){transform:translateY(-2px);box-shadow:var(--shadow);border-color:var(--accent)}
[data-testid="stBaseButton-primary"]:hover:not(:disabled),button[kind="primary"]:hover:not(:disabled){filter:brightness(1.08)}
button:active:not(:disabled){transform:translateY(0);box-shadow:none}
button:disabled{opacity:.45}
/* containers */
[data-testid="stExpander"]{border:1px solid var(--border)!important;border-radius:12px!important;background:var(--surface);transition:border-color .2s ease,box-shadow .2s ease}
[data-testid="stExpander"]:hover{border-color:var(--accent)!important;box-shadow:var(--shadow)}
[data-testid="stExpander"] details,[data-testid="stExpander"] summary,[data-testid="stExpander"] summary:hover,[data-testid="stExpander"] summary:focus{background:var(--surface)!important;color:var(--text)!important;border-radius:12px}
[data-testid="stExpander"] summary *{color:inherit!important;background:transparent!important}
[data-testid="stExpander"] summary svg{fill:currentColor!important}
[data-testid="stExpanderDetails"]{background:var(--surface)!important}
[data-testid="stExpander"] summary{transition:color .18s ease}
[data-testid="stExpander"] summary:hover,[data-testid="stExpander"] summary:hover *{color:var(--accent)!important}
[data-testid="stForm"]{border:1px solid var(--border);border-radius:12px;background:var(--surface2);padding:16px}
[data-testid="stFileUploaderDropzone"]{background:var(--surface)!important;border:1px dashed var(--border);border-radius:12px;transition:border-color .2s ease,transform .2s ease,box-shadow .2s ease}
[data-testid="stFileUploaderDropzone"]:hover{border-color:var(--accent);transform:translateY(-2px);box-shadow:var(--shadow)}
[data-testid="stFileUploaderDropzoneInstructions"] *,[data-testid="stFileUploaderFile"] *{color:var(--muted)!important}
[data-testid="stAlert"]{background:var(--surface)!important;border:1px solid var(--border);border-left:3px solid var(--accent);border-radius:10px;transition:transform .2s ease,box-shadow .2s ease}
[data-testid="stAlert"]:hover{transform:translateY(-1px);box-shadow:var(--shadow)}
[data-testid="stAlert"] *{color:var(--text)!important}
[data-testid="stSpinner"] *{color:var(--muted)!important}
[data-testid="stMetric"]{background:var(--surface);border:1px solid var(--border);border-radius:14px;padding:14px 16px;transition:transform .2s ease,box-shadow .2s ease,border-color .2s ease}
[data-testid="stMetric"]:hover{transform:translateY(-3px);box-shadow:var(--shadow);border-color:var(--accent)}
[data-testid="stMetricLabel"] *{color:var(--muted)!important}
[data-testid="stMetricValue"]{color:var(--text);font-size:1.5rem!important;font-weight:700}
/* drawer menu (hamburger + sidebar list) */
[data-testid="stSidebar"]{background:var(--surface)!important;border-right:1px solid var(--border)}
[data-testid="stSidebar"] [data-testid="stSidebarContent"]{padding-top:.5rem}
[data-testid="stSidebarCollapsedControl"] button,[data-testid="stExpandSidebarButton"],[data-testid="collapsedControl"] button,[data-testid="stSidebarCollapseButton"] button{width:42px!important;height:42px!important;border-radius:50%!important;border:0!important;background-color:transparent!important;background-image:linear-gradient(var(--text),var(--text)),linear-gradient(var(--text),var(--text)),linear-gradient(var(--text),var(--text))!important;background-repeat:no-repeat!important;background-size:18px 2px!important;background-position:center 32%,center 50%,center 68%!important;box-shadow:none!important;transition:background-color .18s ease,transform .18s ease!important}
[data-testid="stSidebarCollapsedControl"] button>*,[data-testid="stExpandSidebarButton"]>*,[data-testid="collapsedControl"] button>*,[data-testid="stSidebarCollapseButton"] button>*{opacity:0}
[data-testid="stSidebarCollapsedControl"] button:hover,[data-testid="stExpandSidebarButton"]:hover,[data-testid="collapsedControl"] button:hover,[data-testid="stSidebarCollapseButton"] button:hover{background-color:var(--soft)!important;transform:scale(1.08)!important}
.bn-nav-label{color:var(--muted);font-size:.72rem;font-weight:700;letter-spacing:.08em;text-transform:uppercase;margin:.2rem 0 .6rem .4rem}
[data-testid="stSidebar"] [data-testid="stRadio"] [role="radiogroup"]{gap:4px}
[data-testid="stSidebar"] label[data-baseweb="radio"]{width:100%;margin:0;padding:11px 14px;border-radius:10px;border-left:3px solid transparent;cursor:pointer;transition:background .18s ease,padding-left .18s ease,border-color .18s ease}
[data-testid="stSidebar"] label[data-baseweb="radio"]>div:first-child{display:none}
[data-testid="stSidebar"] label[data-baseweb="radio"] p{font-size:.95rem;font-weight:500;color:var(--muted)}
[data-testid="stSidebar"] label[data-baseweb="radio"]:hover{background:var(--soft);padding-left:20px}
[data-testid="stSidebar"] label[data-baseweb="radio"]:hover p{color:var(--text)}
[data-testid="stSidebar"] label[data-baseweb="radio"]:has(input:checked){background:var(--surface2);border-left-color:var(--accent)}
[data-testid="stSidebar"] label[data-baseweb="radio"]:has(input:checked) p{color:var(--text);font-weight:650}
/* custom components */
.stApp h1.bn-title{font-size:clamp(2.8rem,6vw,4.6rem)!important;font-weight:900!important;letter-spacing:-.02em;line-height:1.02!important;margin:0!important;padding:0!important;-webkit-text-stroke:1.5px currentColor;color:var(--text)}
.bn-title span{color:var(--accent)}
.bn-sub{color:var(--muted);font-size:.95rem;margin-top:.35rem}
.bn-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:12px;margin:.4rem 0 .6rem}
.bn-tile,.bn-card{background:var(--surface);border:1px solid var(--border);border-radius:14px;padding:14px 16px;transition:transform .2s ease,box-shadow .2s ease,border-color .2s ease}
.bn-tile:hover,.bn-card:hover{transform:translateY(-3px);box-shadow:var(--shadow);border-color:var(--accent)}
.bn-card{margin:.9rem 0 .4rem;padding:16px 18px}
.bn-tile h4{margin:0 0 .55rem;font-size:.95rem;font-weight:650}
.bn-row{display:flex;justify-content:space-between;align-items:center;padding:3px 0;font-size:.88rem;color:var(--muted)}
.bn-row:hover{color:var(--text)}
.bn-dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:8px;background:var(--muted)}
.bn-dot.good{background:var(--good)}.bn-dot.warn{background:var(--warn)}.bn-dot.bad{background:var(--bad)}
.bn-chip{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-weight:600;color:var(--text);background:var(--surface2);border:1px solid var(--border);border-radius:6px;padding:1px 7px;font-size:.85em}
.bn-legend{display:flex;gap:18px;color:var(--muted);font-size:.8rem;margin-bottom:.4rem}
.bn-card-top{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap}
.bn-id{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;color:var(--muted);font-size:.85rem;margin-left:6px}
.bn-badge{display:inline-block;padding:2px 10px;border-radius:999px;font-size:.7rem;font-weight:700;letter-spacing:.06em;border:1px solid var(--muted);color:var(--muted)}
.bn-badge.good{color:var(--good);border-color:var(--good)}.bn-badge.warn{color:var(--warn);border-color:var(--warn)}.bn-badge.bad{color:var(--bad);border-color:var(--bad)}
.bn-route{font-size:1.05rem;font-weight:600;margin:.7rem 0 .45rem}
.bn-meta{display:flex;flex-wrap:wrap;gap:4px 22px;color:var(--muted);font-size:.85rem}
.bn-meta b{color:var(--text);font-weight:600}.bn-meta b.bad{color:var(--bad)}
.bn-decision{margin-top:.7rem;padding-top:.6rem;border-top:1px solid var(--border);color:var(--muted);font-size:.85rem}
.bn-decision b{color:var(--text)}
.bn-tablewrap{overflow-x:auto;border:1px solid var(--border);border-radius:12px;background:var(--surface);margin:.4rem 0 1rem}
.bn-table{width:100%;border-collapse:collapse;font-size:.88rem}
.bn-table th{text-align:left;padding:10px 14px;background:var(--surface2);color:var(--muted);font-size:.74rem;font-weight:600;letter-spacing:.05em;text-transform:uppercase;white-space:nowrap;border-bottom:1px solid var(--border)}
.bn-table td{padding:10px 14px;border-bottom:1px solid var(--border);white-space:nowrap;color:var(--text)}
.bn-table tbody tr{transition:background .15s ease}
.bn-table tbody tr:hover{background:var(--soft)}
.bn-table tbody tr:last-child td{border-bottom:0}
.bn-table tr.total td{font-weight:700}
__SYMBOL__
@media (prefers-reduced-motion:reduce){*{transition:none!important;animation:none!important}}
"""
st.markdown("<style>" + CSS.replace("__ROOT__", ";".join(f"--{k}:{v}" for k, v in P.items())).replace("__SYMBOL__", SUN_CSS if P is LIGHT else MOON_CSS) + "</style>",
            unsafe_allow_html=True)

# sidebar drawer (opened with the hamburger button) holds the page list
with st.sidebar:
    st.markdown('<div class="bn-nav-label">Menu</div>', unsafe_allow_html=True)
    page = st.radio("Page", PAGES, key="page", label_visibility="collapsed")

def _flip_theme():
    st.session_state.theme = "Light" if st.session_state.theme == "Dark" else "Dark"


h_title, h_theme = st.columns([11, 1])
with h_title:
    st.markdown('<h1 class="bn-title">Blood<span>Net</span></h1>'
                '<div class="bn-sub">Inter-hospital blood bank inventory balancer</div>',
                unsafe_allow_html=True)
with h_theme:
    st.button("Switch theme", key="theme_toggle", on_click=_flip_theme,
              help="Switch to light mode" if P is DARK else "Switch to dark mode")
st.markdown("---")

# ─────────────────────────────────────────────────────────────────────────────
# SESSION STATE
# ─────────────────────────────────────────────────────────────────────────────
_DEFAULTS = dict(
    proposals=[], approvals={}, audit_log=[],
    live_snapshot=[], live_skipped={}, live_at_risk={},
    live_has_status=True, live_risk_days=7, live_ran=False,
    sim_results=None, bt_results=None,
)
for _k, _v in _DEFAULTS.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v

# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────
def doh_class(d):
    return "bad" if d < 2 else ("warn" if d < 4 else "good")

def priority_label(i):
    if i == 1: return "CRITICAL"
    if i <= 3: return "URGENT"
    return "ROUTINE"

STATUS_KIND = {"approved": "good", "declined": "bad", "pending": "warn"}

def _clean(v):
    return escape(" ".join(str(v).split()))

def html_table(rows):
    """Theme-aware table with row hover (replaces st.dataframe)."""
    if not rows:
        return
    cols = list(rows[0].keys())
    head = "".join(f"<th>{_clean(c)}</th>" for c in cols)
    body = "".join(
        f'<tr{" class=" + chr(34) + "total" + chr(34) if str(r[cols[0]]) == "TOTAL" else ""}>'
        + "".join(f"<td>{_clean(r.get(c, ''))}</td>" for c in cols) + "</tr>"
        for r in rows)
    st.markdown(f'<div class="bn-tablewrap"><table class="bn-table"><thead><tr>{head}</tr></thead>'
                f'<tbody>{body}</tbody></table></div>', unsafe_allow_html=True)

def write_uploads(files: dict, tmpdir: str):
    for name, fobj in files.items():
        with open(os.path.join(tmpdir, name), "wb") as fh:
            fh.write(fobj.read())
        fobj.seek(0)


def fig_waste_stockouts(base_hs, shared_hs):
    names = [h.name for h in base_hs]
    x, w = range(len(names)), 0.35
    fig, axes = plt.subplots(1, 2, figsize=(13, 4))
    for ax, getter, title, colours in [
        (axes[0], lambda h: h.wasted,    "Units Wasted (expired)",  ("#e05252","#5299e0")),
        (axes[1], lambda h: h.stockouts, "Stockout Events",         ("#e08852","#52c0a0")),
    ]:
        ax.bar([i - w/2 for i in x], [getter(h) for h in base_hs],
               w, label="Baseline", color=colours[0], alpha=0.85)
        ax.bar([i + w/2 for i in x], [getter(h) for h in shared_hs],
               w, label="With agents", color=colours[1], alpha=0.85)
        ax.set_title(title); ax.set_xticks(list(x))
        ax.set_xticklabels(names, rotation=20, ha="right", fontsize=8)
        ax.legend(); ax.set_ylabel("Units" if "Wasted" in title else "Events")
    plt.tight_layout()
    return fig


def fig_network(hospitals, comp_log=None, latlon=False):
    """Scatter-plot of hospitals; arcs = completed transfers."""
    fig, ax = plt.subplots(figsize=(7, 5))
    ax.set_facecolor(P["surface"]); fig.patch.set_facecolor(P["surface"])
    get = (lambda h: (h.pos[1], h.pos[0])) if latlon else (lambda h: h.pos)
    name2xy = {h.name: get(h) for h in hospitals}
    if comp_log:
        for e in comp_log:
            frm, to = e["from"].split(":",1)[1], e["to"].split(":",1)[1]
            if frm in name2xy and to in name2xy:
                ax.annotate("", xy=name2xy[to], xytext=name2xy[frm],
                            arrowprops=dict(arrowstyle="->", color="#ff6b6b",
                                           lw=1.1, alpha=0.55,
                                           connectionstyle="arc3,rad=0.18"))
    xs = [v[0] for v in name2xy.values()]
    ys = [v[1] for v in name2xy.values()]
    sizes = [max(160, len(h.inventory)*2) for h in hospitals]
    ax.scatter(xs, ys, s=sizes, c="#4fc3f7", alpha=0.9, zorder=5,
               edgecolors="#81d4fa", linewidths=1.5)
    for h in hospitals:
        ax.annotate(h.name.replace(" ","\n"), name2xy[h.name],
                    textcoords="offset points", xytext=(0,10),
                    ha="center", fontsize=7, color=P["text"])
    ax.set_title("Network map  (size = inventory, arcs = transfers)",
                 color=P["text"], fontsize=8)
    ax.tick_params(colors=P["muted"])
    for sp in ax.spines.values(): sp.set_edgecolor(P["border"])
    ax.set_xlabel("Lon" if latlon else "X (km)", color=P["muted"], fontsize=8)
    ax.set_ylabel("Lat" if latlon else "Y (km)", color=P["muted"], fontsize=8)
    plt.tight_layout(); return fig


def replay_history(hospitals, init_fc, reserve, minutes, usage_data,
                   receipts, start, n_days, sharing, warmup, seed, approval_rate):
    """Replay n_days of history. Returns per-hospital result dict and matchmaker."""
    orig = bb.APPROVAL_RATE
    bb.APPROVAL_RATE = approval_rate
    hs   = [bb.Hospital(h.name, 0.0, 0.0, h.pos) for h in hospitals]
    rng  = random.Random(seed)
    srng = random.Random(seed + 99)
    _, agents, _, comp, mm = rd.build_network(hs, init_fc, reserve, minutes, rng)
    by_name = {a.h.name: a for a in agents}
    uid = 0
    for a in agents:
        for t in bb.TYPES:
            for _ in range(math.ceil(4 * a.forecast[t])):
                uid += 1
                a.h.inventory.append(bb.Unit(uid, t, srng.randint(10, 30)))
    snap = {}
    for di in range(n_days):
        day = start + timedelta(days=di)
        for name, t, qty, exp in receipts.get(day, []):
            for _ in range(qty):
                uid += 1
                by_name[name].h.inventory.append(bb.Unit(uid, t, (exp - start).days))
        if sharing:
            reqs = []
            for a in agents:
                for r in a.detect_shortfalls(di):
                    r["doh"] = a.days_on_hand(r["btype"], di)
                    reqs.append(r)
            reqs.sort(key=lambda r: r["doh"])
            for r in reqs:
                mm.fulfil(r, di)
        for a in agents:
            h = a.h
            for t in bb.TYPES:
                dem = usage_data.get((day, h.name, t), 0)
                a.observe_demand(t, dem)
                stock = sorted(h.stock(t), key=lambda u: u.expiry)
                for _ in range(dem):
                    if stock:
                        h.inventory.remove(stock.pop(0)); h.served += 1
                    else:
                        h.stockouts += 1
        for h in hs:
            dead = [u for u in h.inventory if u.expiry <= di + 1]
            h.wasted += len(dead)
            h.inventory = [u for u in h.inventory if u.expiry > di + 1]
        if di == warmup - 1:
            snap = {h.name: (h.wasted, h.stockouts, h.served) for h in hs}
    bb.APPROVAL_RATE = orig
    results = {h.name: (
        h.wasted    - snap.get(h.name,(0,0,0))[0],
        h.stockouts - snap.get(h.name,(0,0,0))[1],
        h.served    - snap.get(h.name,(0,0,0))[2],
    ) for h in hs}
    return results, mm, hs


# ─────────────────────────────────────────────────────────────────────────────
# TABS
# ─────────────────────────────────────────────────────────────────────────────
# Pages are chosen from the hamburger menu in the sidebar (variable: page).

# ═════════════════════════════════════════════════════════════════════════════
# TAB 1 – LIVE PROPOSALS
# ═════════════════════════════════════════════════════════════════════════════
if page == "Live Proposals":
    st.subheader("Live Transfer Proposals")
    st.caption(
        "Upload today's inventory snapshot and recent usage history. "
        "The agent network identifies shortfalls and proposes transfers. "
        "**Nothing is executed until a blood bank technologist approves each one.**"
    )

    with st.expander("Upload data files",
                     expanded=not st.session_state.live_ran):
        lc1, lc2 = st.columns(2)
        with lc1:
            f_hosp = st.file_uploader("hospitals.csv (required)",  type="csv", key="ul_h")
            f_inv  = st.file_uploader("inventory.csv (required)",  type="csv", key="ul_i")
        with lc2:
            f_use  = st.file_uploader("usage.csv (required)",      type="csv", key="ul_u")
            f_rt   = st.file_uploader("routes.csv  (optional)", type="csv", key="ul_r")
        st.caption("Need sample files? Run:  `python real_data.py make-sample sample_data`")
        la, lb, lc = st.columns(3)
        with la: as_of    = st.date_input("Snapshot date", value=date.today())
        with lb: window   = st.number_input("Usage history window (days)", 14, 90, 28)
        with lc: risk_d   = st.number_input("Flag units expiring within (days)", 3, 30, 7)
        run_live = st.button("Analyse Network", type="primary",
                             disabled=not (f_hosp and f_inv and f_use))

    if run_live and f_hosp and f_inv and f_use:
        with tempfile.TemporaryDirectory() as tmp:
            uploads = {"hospitals.csv": f_hosp, "inventory.csv": f_inv, "usage.csv": f_use}
            if f_rt: uploads["routes.csv"] = f_rt
            write_uploads(uploads, tmp)
            try:
                hospitals, reserve, minutes, id2h = rd.load_hospitals(tmp)
                meta, skipped, has_status = rd.load_inventory(tmp, as_of, id2h)
                usage_data, _ = rd.load_usage_receipts(tmp, id2h, need_receipts=False)
                w_start = as_of - timedelta(days=int(window))
                forecasts = rd.forecasts_from_usage(usage_data, hospitals, w_start, as_of)
                _, agents, logistics, comp, mm = rd.build_network(
                    hospitals, forecasts, reserve, minutes, rd.AlwaysApprove())
                reqs = []
                for a in agents:
                    for r in a.detect_shortfalls(0):
                        r["doh"] = a.days_on_hand(r["btype"], 0)
                        reqs.append(r)
                reqs.sort(key=lambda r: r["doh"])
                for r in reqs: mm.fulfil(r, 0)

                proposals = []
                for idx, e in enumerate(comp.log, start=1):
                    route    = logistics.handle("ASSESS_ROUTE",{"from":e["from"],"to":e["to"]})
                    exps     = [meta[u][1] for u in e["units"]]
                    uid_strs = [meta[u][0] for u in e["units"]]
                    arr      = min((x - as_of).days for x in exps) - route["hours"]/24
                    proposals.append(dict(
                        id=f"T{idx:04d}", priority=idx,
                        abo_rh=e["btype"], units=len(e["units"]), unit_ids=uid_strs,
                        donor=e["from"].split(":",1)[1],
                        recipient=e["to"].split(":",1)[1],
                        earliest_expiry=min(exps).isoformat(),
                        shelf_days_on_arrival=round(arr,1),
                        distance_km=round(route["km"],1),
                        transit_hours=round(route["hours"],1),
                    ))

                snapshot = []
                for a in agents:
                    row = {"Hospital": a.h.name}
                    for t in bb.TYPES: row[t] = round(a.days_on_hand(t,0),1)
                    snapshot.append(row)

                at_risk = defaultdict(int)
                for h in hospitals:
                    for u in h.inventory:
                        if u.expiry <= int(risk_d):
                            at_risk[(h.name, u.btype)] += 1

                st.session_state.proposals       = proposals
                st.session_state.approvals       = {}
                st.session_state.live_snapshot   = snapshot
                st.session_state.live_skipped    = skipped
                st.session_state.live_at_risk    = dict(at_risk)
                st.session_state.live_has_status = has_status
                st.session_state.live_risk_days  = int(risk_d)
                st.session_state.live_ran        = True
                st.success(f"Analysis complete — {len(proposals)} transfer(s) proposed "
                           f"across {len(hospitals)} hospitals.")
                st.rerun()
            except rd.DataError as e:
                st.error(f"**Data error:** {e}")

    # ── results ──────────────────────────────────────────────────────────────
    if st.session_state.live_ran:
        if not st.session_state.live_has_status:
            st.warning("inventory.csv has no `status` column — quarantined/reserved "
                       "units may be included. Add it for production use.")
        if st.session_state.live_skipped:
            with st.expander(f"{sum(st.session_state.live_skipped.values())} "
                             "units excluded from analysis"):
                for reason, n in sorted(st.session_state.live_skipped.items()):
                    st.caption(f"• {n} unit(s): {reason}")

        # inventory position
        st.subheader("Network Inventory  (days on hand)")
        snap = st.session_state.live_snapshot
        if snap:
            tiles = ""
            for row in snap:
                lines = "".join(
                    f'<div class="bn-row"><span><i class="bn-dot {doh_class(row[t])}"></i>'
                    f'<span class="bn-chip">{t}</span></span><span>{row[t]} d</span></div>'
                    for t in ("O-","O+","A-","A+","B-","B+","AB-","AB+"))
                tiles += f'<div class="bn-tile"><h4>{_clean(row["Hospital"])}</h4>{lines}</div>'
            st.markdown(
                '<div class="bn-legend"><span><i class="bn-dot bad"></i>under 2 days</span>'
                '<span><i class="bn-dot warn"></i>2 to 4 days</span>'
                '<span><i class="bn-dot good"></i>4 days or more</span></div>'
                f'<div class="bn-grid">{tiles}</div>', unsafe_allow_html=True)

        st.markdown("---")

        # proposal counters
        props = st.session_state.proposals
        n_app = sum(1 for a in st.session_state.approvals.values() if a["status"]=="approved")
        n_dec = sum(1 for a in st.session_state.approvals.values() if a["status"]=="declined")
        n_pen = len(props) - n_app - n_dec

        if props:
            st.subheader(f"Transfer Proposals ({len(props)})")
            m1,m2,m3,m4 = st.columns(4)
            m1.metric("Total",    len(props))
            m2.metric("Pending",  n_pen)
            m3.metric("Approved", n_app)
            m4.metric("Declined", n_dec)

            for p in props:
                pid    = p["id"]
                appr   = st.session_state.approvals.get(pid, {})
                status = appr.get("status", "pending")
                urgent = p["shelf_days_on_arrival"] < 4

                ids_preview = ", ".join(p["unit_ids"][:5]) + ("…" if len(p["unit_ids"]) > 5 else "")
                prio_kind   = "bad" if p["priority"] == 1 else ("warn" if p["priority"] <= 3 else "")
                decision = ""
                if status in ("approved", "declined"):
                    note = f" — {_clean(appr['notes'])}" if appr.get("notes") else ""
                    decision = (f'<div class="bn-decision">{status.capitalize()} by '
                                f'<b>{_clean(appr["approver"])}</b> ({_clean(appr["role"])}) '
                                f'at {_clean(appr["ts"])}{note}</div>')
                st.markdown(
                    f'<div class="bn-card"><div class="bn-card-top"><div>'
                    f'<span class="bn-badge {prio_kind}">{priority_label(p["priority"])}</span>'
                    f'<span class="bn-id">{pid}</span></div>'
                    f'<span class="bn-badge {STATUS_KIND[status]}">{status.upper()}</span></div>'
                    f'<div class="bn-route"><span class="bn-chip">{_clean(p["abo_rh"])}</span> '
                    f'x {p["units"]} units &nbsp; {_clean(p["donor"])} → {_clean(p["recipient"])}</div>'
                    f'<div class="bn-meta"><span>Distance <b>{p["distance_km"]} km</b></span>'
                    f'<span>Transit <b>~{p["transit_hours"]} h</b></span>'
                    f'<span>Earliest expiry <b>{p["earliest_expiry"]}</b></span>'
                    f'<span>Shelf life on arrival <b class="{"bad" if urgent else ""}">'
                    f'{p["shelf_days_on_arrival"]} d</b></span>'
                    f'<span>Unit IDs <b>{_clean(ids_preview)}</b></span></div>{decision}</div>',
                    unsafe_allow_html=True)

                if status == "pending":
                    with st.expander("Review and decide"):
                        with st.form(key=f"form_{pid}"):
                            fa, fb = st.columns(2)
                            with fa:
                                approver_name = st.text_input(
                                    "Approver name / staff ID",
                                    placeholder="e.g. J. Smith  BB-1234")
                                approver_role = st.selectbox("Role", [
                                    "Blood Bank Technologist", "Pathologist",
                                    "Medical Director", "Charge Nurse", "Other"])
                            with fb:
                                notes = st.text_area(
                                    "Notes / conditions (optional)", height=80,
                                    placeholder="e.g. cold-chain confirmed, notify "
                                                "recipient BB on dispatch…")
                            btn_a, btn_d = st.columns(2)
                            with btn_a:
                                do_approve = st.form_submit_button(
                                    "Approve", type="primary",
                                    use_container_width=True)
                            with btn_d:
                                do_decline = st.form_submit_button(
                                    "Decline", use_container_width=True)

                            if do_approve or do_decline:
                                if not approver_name.strip():
                                    st.warning("Enter your name or staff ID before submitting.")
                                else:
                                    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
                                    entry = dict(
                                        status="approved" if do_approve else "declined",
                                        approver=approver_name.strip(),
                                        role=approver_role,
                                        notes=notes.strip(),
                                        ts=ts,
                                    )
                                    st.session_state.approvals[pid] = entry
                                    if do_approve:
                                        st.session_state.audit_log.append({**p, **entry})
                                    st.rerun()

            # download approved
            approved_rows = [
                {**p, **st.session_state.approvals[p["id"]]}
                for p in props
                if st.session_state.approvals.get(p["id"],{}).get("status")=="approved"
            ]
            if approved_rows:
                buf = io.StringIO()
                fields = ["id","priority","abo_rh","units","donor","recipient",
                          "distance_km","transit_hours","earliest_expiry",
                          "shelf_days_on_arrival","approver","role","notes","ts"]
                cw = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
                cw.writeheader(); cw.writerows(approved_rows)
                st.download_button(
                    "Download approved transfer orders (CSV)",
                    data=buf.getvalue(),
                    file_name=f"transfer_orders_{date.today()}.csv",
                    mime="text/csv", type="primary",
                )
        else:
            st.success("Network is balanced — no transfers required at this time.")

        # at-risk units that couldn't be moved
        at_risk = st.session_state.live_at_risk
        if at_risk:
            with st.expander(f"{sum(at_risk.values())} units at risk of expiring "
                             f"within {st.session_state.live_risk_days} days "
                             "(no eligible transfer found)"):
                st.caption("Consider contacting suppliers or sending a manual outreach "
                           "to a partner not in the network.")
                for (hosp,t), n in sorted(at_risk.items(), key=lambda kv:-kv[1])[:15]:
                    st.write(f"• **{hosp}** — `{t}`: {n} unit(s)")

    else:
        st.info("Upload your three data files above and click **Analyse Network** to begin.")


# ═════════════════════════════════════════════════════════════════════════════
# TAB 2 – SIMULATION
# ═════════════════════════════════════════════════════════════════════════════
if page == "Simulation":
    st.subheader("Synthetic Network Simulation")
    st.caption("Use the built-in 6-hospital synthetic scenario to explore how "
               "agent coordination performs under different parameters, or to "
               "generate sample CSV files to try the Live and Backtest modes.")

    with st.form("sim_form"):
        sc1, sc2, sc3 = st.columns(3)
        with sc1:
            sim_days      = st.slider("Duration (days)",              30, 365, bb.DAYS)
            sim_threshold = st.slider("Request threshold (days on hand)", 1.0, 5.0,
                                      bb.REQUEST_THRESHOLD_DAYS, 0.5)
        with sc2:
            sim_target    = st.slider("Restock target (days)",        2.0, 7.0, bb.TARGET_DAYS, 0.5)
            sim_reserve   = st.slider("Safety reserve (days)",        1.0, 5.0, bb.RESERVE_DAYS, 0.5)
        with sc3:
            sim_approval  = st.slider("Technologist approval rate",   0.5, 1.0, bb.APPROVAL_RATE, 0.05)
            sim_seed      = st.number_input("Random seed", value=int(bb.SEED), step=1)
        sa, sb = st.columns(2)
        with sa: run_sim  = st.form_submit_button("Run Simulation",
                                                   type="primary", use_container_width=True)
        with sb: gen_samp = st.form_submit_button("Generate Sample CSV Files",
                                                   use_container_width=True)

    if gen_samp:
        with tempfile.TemporaryDirectory() as tmp:
            rd.make_sample(tmp)
            files_out = {}
            for fname in ("hospitals.csv","inventory.csv","usage.csv","receipts.csv"):
                p = os.path.join(tmp, fname)
                if os.path.exists(p):
                    files_out[fname] = open(p,"rb").read()
        for fname, data in files_out.items():
            st.download_button(f"Download {fname}", data=data,
                               file_name=fname, mime="text/csv",
                               key=f"dl_{fname}")
        st.success("Sample files ready — download each one above, then upload them in "
                   "the **Live Proposals** or **Backtest** tab.")

    if run_sim:
        bb.DAYS = sim_days
        bb.REQUEST_THRESHOLD_DAYS = sim_threshold
        bb.TARGET_DAYS   = sim_target
        bb.RESERVE_DAYS  = sim_reserve
        bb.APPROVAL_RATE = sim_approval
        bb.SEED          = int(sim_seed)
        with st.spinner("Running agents…"):
            sched = bb.make_schedule()
            base_h, *_              = bb.run(False, sched)
            shared_h, mm, comp, bus = bb.run(True,  sched)
        st.session_state.sim_results = dict(
            base=base_h, shared=shared_h, mm=mm, comp=comp, days=sim_days)

    res = st.session_state.sim_results
    if res:
        base_h, shared_h, mm = res["base"], res["shared"], res["mm"]
        bw = sum(h.wasted    for h in base_h)
        sw = sum(h.wasted    for h in shared_h)
        bs = sum(h.stockouts for h in base_h)
        ss = sum(h.stockouts for h in shared_h)

        st.markdown("### Results")
        m1,m2,m3,m4,m5 = st.columns(5)
        m1.metric("Waste — baseline",  bw)
        m2.metric("Waste — agents",    sw, delta=f"{sw-bw:+d}", delta_color="inverse")
        m3.metric("Stockouts — baseline", bs)
        m4.metric("Stockouts — agents",   ss, delta=f"{ss-bs:+d}", delta_color="inverse")
        m5.metric("Transfers executed", mm.transfers)

        st.markdown("---")
        chart_col, map_col = st.columns([3,2])
        with chart_col:
            st.pyplot(fig_waste_stockouts(base_h, shared_h))
        with map_col:
            hospitals = [bb.Hospital(n,dem,sup,pos) for n,dem,sup,pos in bb.HOSPITALS]
            for h_orig, h_new in zip(shared_h, hospitals):
                h_new.inventory = h_orig.inventory
            st.pyplot(fig_network(hospitals, res["comp"].log, latlon=False))

        with st.expander("Per-hospital breakdown"):
            html_table([
                {"Hospital": bh.name,
                 "Waste (baseline)": bh.wasted,  "Waste (agents)":    sh.wasted,
                 "Stockouts (baseline)": bh.stockouts, "Stockouts (agents)": sh.stockouts,
                 "Units served (agents)": sh.served}
                for bh, sh in zip(base_h, shared_h)
            ])

        with st.expander("Transfer log (first 25 entries)"):
            html_table([
                {"Day": e["day"], "Type": e["btype"], "Units": len(e["units"]),
                 "From": e["from"].split(":",1)[1],
                 "To":   e["to"].split(":",1)[1],
                 "km":   e["km"]}
                for e in res["comp"].log[:25]
            ])


# ═════════════════════════════════════════════════════════════════════════════
# TAB 3 – BACKTEST
# ═════════════════════════════════════════════════════════════════════════════
if page == "Backtest":
    st.subheader("Historical Backtest")
    st.caption("Replay months of actual receipts and usage with and without the "
               "agent network to estimate the benefit before committing to a pilot.")

    with st.expander("Data files", expanded=True):
        bc1, bc2 = st.columns(2)
        with bc1:
            bt_fh = st.file_uploader("hospitals.csv (required)",  type="csv", key="bt_h")
            bt_fu = st.file_uploader("usage.csv (required)",      type="csv", key="bt_u")
        with bc2:
            bt_fr = st.file_uploader("receipts.csv (required)",   type="csv", key="bt_r")
            bt_rt = st.file_uploader("routes.csv  (optional)", type="csv", key="bt_rt")

        bb1, bb2, bb3 = st.columns(3)
        with bb1: bt_warmup   = st.number_input("Warm-up days (excluded)", 7, 60, 14)
        with bb2: bt_approval = st.slider("Simulated approval rate", 0.5, 1.0, 0.9, 0.05)
        with bb3: bt_seed     = st.number_input("Seed", 1, 9999, 7)
        run_bt = st.button("Run Backtest", type="primary",
                           disabled=not (bt_fh and bt_fu and bt_fr))

    if run_bt and bt_fh and bt_fu and bt_fr:
        with tempfile.TemporaryDirectory() as tmp:
            uploads = {"hospitals.csv": bt_fh, "usage.csv": bt_fu, "receipts.csv": bt_fr}
            if bt_rt: uploads["routes.csv"] = bt_rt
            write_uploads(uploads, tmp)
            try:
                hospitals, reserve, minutes, id2h = rd.load_hospitals(tmp)
                usage_data, receipts = rd.load_usage_receipts(tmp, id2h, need_receipts=True)
                if not usage_data:
                    st.error("usage.csv has no RBC rows."); st.stop()
                start = min(k[0] for k in usage_data)
                end   = max(k[0] for k in usage_data)
                n_days = (end - start).days + 1
                if n_days < int(bt_warmup) + 14:
                    st.error(f"Need at least {int(bt_warmup)+14} days of history "
                             f"(found {n_days})."); st.stop()
                init_fc = rd.forecasts_from_usage(
                    usage_data, hospitals, start, end + timedelta(days=1))

                with st.spinner("Replaying baseline (no sharing)…"):
                    base_res, _, base_hs = replay_history(
                        hospitals, init_fc, reserve, minutes, usage_data,
                        receipts, start, n_days, False,
                        int(bt_warmup), int(bt_seed), bt_approval)
                with st.spinner("Replaying with agent network…"):
                    shared_res, mm_bt, shared_hs = replay_history(
                        hospitals, init_fc, reserve, minutes, usage_data,
                        receipts, start, n_days, True,
                        int(bt_warmup), int(bt_seed), bt_approval)

                st.session_state.bt_results = dict(
                    base=base_res, shared=shared_res, mm=mm_bt,
                    hosp_names=[h.name for h in hospitals],
                    period=f"{start} – {end}", warmup=int(bt_warmup),
                    base_hs=base_hs, shared_hs=shared_hs,
                )
                st.success("Backtest complete.")
                st.rerun()
            except rd.DataError as e:
                st.error(f"**Data error:** {e}")

    bt = st.session_state.bt_results
    if bt:
        st.markdown(f"### Results — {bt['period']} "
                    f"(first {bt['warmup']} days excluded as warm-up)")
        rows, tw, sw_t, ts_b, ts_s = [], 0, 0, 0, 0
        for name in bt["hosp_names"]:
            bw,bs,_ = bt["base"].get(name,(0,0,0))
            sw,ss,_ = bt["shared"].get(name,(0,0,0))
            tw+=bw; sw_t+=sw; ts_b+=bs; ts_s+=ss
            rows.append({"Hospital":name,
                         "Wasted — alone":bw,  "Wasted — agents":sw,
                         "Stockouts — alone":bs,"Stockouts — agents":ss})
        rows.append({"Hospital":"TOTAL","Wasted — alone":tw,"Wasted — agents":sw_t,
                     "Stockouts — alone":ts_b,"Stockouts — agents":ts_s})
        html_table(rows)

        m1,m2,m3,m4 = st.columns(4)
        m1.metric("Waste reduction",    f"{(tw-sw_t)/max(tw,1):.0%}",
                  delta=f"–{tw-sw_t} units", delta_color="inverse")
        m2.metric("Shortage reduction", f"{(ts_b-ts_s)/max(ts_b,1):.0%}",
                  delta=f"–{ts_b-ts_s} events", delta_color="inverse")
        m3.metric("Transfers",  bt["mm"].transfers)
        m4.metric("Units moved",bt["mm"].units_moved)

        st.pyplot(fig_waste_stockouts(bt["base_hs"], bt["shared_hs"]))
        st.caption("Both runs use the same recorded data — compare the two columns "
                   "to each other, not to your actual discard/shortage records. "
                   "Emergency supplier orders that masked shortages won't appear in usage.csv.")


# ═════════════════════════════════════════════════════════════════════════════
# TAB 4 – AUDIT LOG
# ═════════════════════════════════════════════════════════════════════════════
if page == "Audit Log":
    st.subheader("Audit Log — Approved Transfers This Session")
    st.caption(
        "This is a session-only record. **Download it and store it in your "
        "facility's document management system** as part of the chain-of-custody "
        "record required by AABB and FDA regulations."
    )
    log = st.session_state.audit_log
    if log:
        m1,m2,m3 = st.columns(3)
        m1.metric("Approved transfers",    len(log))
        m2.metric("Total units committed", sum(e["units"]  for e in log))
        m3.metric("Blood types covered",   len({e["abo_rh"] for e in log}))

        html_table([{
            "Transfer ID":           e["id"],
            "Blood type":            e["abo_rh"],
            "Units":                 e["units"],
            "From":                  e["donor"],
            "To":                    e["recipient"],
            "Distance (km)":         e["distance_km"],
            "Transit time (h)":      e["transit_hours"],
            "Shelf life on arrival": f"{e['shelf_days_on_arrival']}d",
            "Earliest expiry":       e["earliest_expiry"],
            "Approver":              e["approver"],
            "Role":                  e["role"],
            "Notes":                 e.get("notes",""),
            "Approved at":           e["ts"],
        } for e in log])

        buf = io.StringIO()
        fields = ["id","abo_rh","units","donor","recipient","distance_km",
                  "transit_hours","shelf_days_on_arrival","earliest_expiry",
                  "unit_ids","approver","role","notes","ts"]
        cw = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
        cw.writeheader()
        for e in log:
            row = dict(e); row["unit_ids"] = ";".join(row.get("unit_ids",[]))
            cw.writerow(row)
        st.download_button(
            "Download audit log (CSV)",
            data=buf.getvalue(),
            file_name=f"bloodnet_audit_{date.today()}.csv",
            mime="text/csv", type="primary",
        )
    else:
        st.info("No transfers have been approved this session. "
                "Go to **Live Proposals** to upload data and sign off on transfers.")