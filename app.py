import streamlit as st
import google.generativeai as genai
import pandas as pd
import json
import os
import gspread
import ast
from google.oauth2.service_account import Credentials
from datetime import datetime, time

# --- 1. CẤU HÌNH MOBILE-FIRST UI ---
st.set_page_config(page_title="MFG App", page_icon="🏭", layout="wide", initial_sidebar_state="collapsed")

# CSS HACK: BIẾN STREAMLIT THÀNH MOBILE APP
st.markdown("""
<style>
    /* 1. Tối ưu khoảng cách lề cho điện thoại */
    .block-container {
        padding-top: 1rem !important;
        padding-bottom: 5rem !important;
        padding-left: 0.5rem !important;
        padding-right: 0.5rem !important;
    }
    
    /* 2. Ẩn Header mặc định của Streamlit và Footer */
    header[data-testid="stHeader"] { visibility: hidden; height: 0%; }
    footer { visibility: hidden; }
    
    /* 3. Style cho Tab Bar (Giống App Native) */
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
        background-color: white;
        position: sticky;
        top: 0;
        z-index: 999;
        padding-top: 10px;
        border-bottom: 1px solid #eee;
    }
    .stTabs [data-baseweb="tab"] {
        flex-grow: 1;
        justify-content: center;
        border-radius: 8px;
        background-color: #f1f3f4;
        border: none;
        font-weight: 600;
        font-size: 0.9rem;
    }
    .stTabs [aria-selected="true"] {
        background-color: #e8f0fe !important;
        color: #1967d2 !important;
        border: 2px solid #1967d2 !important;
    }

    /* 4. Style cho Card Task (Thẻ công việc) */
    .mobile-card {
        background-color: white;
        padding: 16px;
        border-radius: 12px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.05);
        margin-bottom: 12px;
        border: 1px solid #eee;
    }
    
    /* Priority Badges (Dạng viên thuốc) */
    .badge-pill {
        display: inline-block;
        padding: 4px 10px;
        border-radius: 20px;
        font-size: 0.75rem;
        font-weight: bold;
        color: white;
        margin-right: 5px;
    }
    .bg-High { background-color: #ff5252; }
    .bg-Medium { background-color: #ffa726; }
    .bg-Low { background-color: #66bb6a; }
    
    /* Text Styles */
    .card-title { font-size: 1.1rem; font-weight: 700; color: #202124; margin-bottom: 4px; }
    .card-meta { font-size: 0.85rem; color: #5f6368; display: flex; align-items: center; gap: 5px; }
    
</style>
""", unsafe_allow_html=True)

# --- 2. KẾT NỐI GOOGLE SHEET ---
def get_gsheet_client():
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    try:
        if "gcp_service_account" in st.secrets:
            creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scopes)
            client = gspread.authorize(creds)
            return client
        elif os.path.exists("credentials.json"):
            creds = Credentials.from_service_account_file("credentials.json", scopes=scopes)
            client = gspread.authorize(creds)
            return client
        return None
    except: return None

def load_data():
    client = get_gsheet_client()
    if not client: return []
    try:
        sheet = client.open("MFG_Task_Database").sheet1
        records = sheet.get_all_records()
        clean_data = []
        for r in records:
            # Fix lỗi Checklist
            if 'subtasks' in r:
                try:
                    if isinstance(r['subtasks'], str) and r['subtasks'].strip():
                        r['subtasks'] = ast.literal_eval(r['subtasks'])
                    elif not isinstance(r['subtasks'], list):
                        r['subtasks'] = []
                except: r['subtasks'] = []
            else: r['subtasks'] = []
            
            if 'status' not in r: r['status'] = 'Pending'
            if 'priority' not in r: r['priority'] = 'Medium'
            clean_data.append(r)
        return clean_data
    except: return []

def save_data(tasks):
    client = get_gsheet_client()
    if not client: return False
    try:
        sheet = client.open("MFG_Task_Database").sheet1
        if not tasks:
            sheet.clear()
            return True
        df = pd.DataFrame(tasks)
        if 'subtasks' in df.columns:
            df['subtasks'] = df['subtasks'].apply(lambda x: str(x))
        df = df.astype(str)
        sheet.clear()
        sheet.update([df.columns.values.tolist()] + df.values.tolist())
        return True
    except: return False

# --- 3. AI LOGIC ---
def analyze_ai(api_key, text, deadline):
    genai.configure(api_key=api_key)
    prompt = f"""
    Input: "{text}" | DL: "{deadline}"
    Yêu cầu: Tạo checklist thực hiện (3-5 bước).
    Output JSON: {{ "task_name": "", "description": "", "priority": "High/Medium/Low", "eisenhower": "Q1/Q2/Q3/Q4", "subtasks": [{{"name": "...", "done": false}}] }}
    """
    for m in ['gemini-2.0-flash-exp', 'gemini-1.5-flash']:
        try:
            model = genai.GenerativeModel(m, generation_config={"response_mime_type": "application/json"})
            res = model.generate_content(prompt)
            data = json.loads(res.text.strip())
            if isinstance(data, list): data = data[0]
            # Validate subtasks
            clean = []
            if 'subtasks' in data and isinstance(data['subtasks'], list):
                for s in data['subtasks']:
                    clean.append({"name": s.get('name', str(s)), "done": False})
            data['subtasks'] = clean
            return data
        except: continue
    return None

# --- 4. GIAO DIỆN CHÍNH ---

# API Key & Sync Check
if "GEMINI_API_KEY" in st.secrets:
    api_key = st.secrets["GEMINI_API_KEY"]
else:
    api_key = st.sidebar.text_input("API Key", type="password")

# Load Data
tasks = load_data()
pending = [t for t in tasks if t.get('status') != 'Done']

# TITLE MOBILE
st.markdown("### 🏭 MFG Mobile App")

# --- TAB NAVIGATION (BOTTOM BAR STYLE) ---
# Dùng Tab ở trên cùng để điều hướng nhanh
tab_list, tab_add, tab_stats = st.tabs(["📋 DANH SÁCH", "➕ THÊM MỚI", "📊 BÁO CÁO"])

# === TAB 1: DANH SÁCH CÔNG VIỆC (HOME SCREEN) ===
with tab_list:
    if not pending:
        st.info("🎉 Tuyệt vời! Không còn việc tồn đọng.")
    
    for t in reversed(pending):
        prio = t.get('priority', 'Medium')
        subs = t.get('subtasks', [])
        
        # Calculate Progress
        total_s = len(subs)
        done_s = sum(1 for s in subs if s.get('done'))
        pct = done_s / total_s if total_s > 0 else 0
        
        # --- TASK CARD ---
        with st.container():
            # Card HTML Structure
            st.markdown(f"""
            <div class="mobile-card">
                <div style="display:flex; justify-content:space-between; align-items:start;">
                    <div>
                        <span class="badge-pill bg-{prio}">{prio}</span>
                        <span style="font-size:0.8rem; color:#888;">{t.get('eisenhower','').split(' ')[0]}</span>
                    </div>
                    <small style="color:#666;">#{t.get('id')}</small>
                </div>
                <div class="card-title" style="margin-top:8px;">{t.get('task_name')}</div>
                <div class="card-meta">📅 Hạn: {t.get('deadline')}</div>
            """, unsafe_allow_html=True)
            
            # Progress Bar (Native Streamlit)
            if total_s > 0:
                st.progress(pct)
                st.caption(f"Tiến độ: {int(pct*100)}% ({done_s}/{total_s})")
            
            st.markdown("</div>", unsafe_allow_html=True)
            
            # Action Expander (Ẩn chi tiết để list gọn)
            with st.expander("Giao diện thực hiện", expanded=False):
                st.markdown(f"**Mô tả:** {t.get('description')}")
                st.markdown("---")
                
                # Checklist
                updated_subs = []
                changed = False
                for i, s in enumerate(subs):
                    check = st.checkbox(s.get('name'), value=s.get('done'), key=f"c_{t['id']}_{i}")
                    if check != s.get('done'):
                        s['done'] = check
                        changed = True
                    updated_subs.append(s)
                
                # Buttons Row
                c1, c2 = st.columns(2)
                with c1:
                    if st.button("✅ HOÀN THÀNH", key=f"done_{t['id']}", use_container_width=True):
                        t['status'] = 'Done'
                        save_data(tasks)
                        st.rerun()
                with c2:
                    if st.button("🗑️ XÓA", key=f"del_{t['id']}", type="secondary", use_container_width=True):
                        tasks = [x for x in tasks if x['id'] != t['id']]
                        save_data(tasks)
                        st.rerun()
                
                if changed:
                    t['subtasks'] = updated_subs
                    save_data(tasks)
                    st.rerun()

# === TAB 2: NHẬP LIỆU (ADD SCREEN) ===
with tab_add:
    st.markdown("#### Tạo công việc mới")
    with st.container():
        # Form nhập liệu tối ưu cho mobile
        txt = st.text_area("Nội dung công việc (Bạn muốn làm gì?)", height=100, placeholder="VD: Kiểm tra chuyền SMT lúc 2h chiều...")
        
        c_d1, c_d2 = st.columns(2)
        with c_d1: d_date = st.date_input("Ngày", value=datetime.now())
        with c_d2: d_time = st.time_input("Giờ", value=time(17,0))
        
        st.write("") # Spacer
        if st.button("🚀 PHÂN TÍCH & TẠO TASK", type="primary", use_container_width=True):
            if not api_key: st.error("Lỗi: Chưa có API Key")
            elif not txt: st.warning("Vui lòng nhập nội dung")
            else:
                with st.spinner("AI đang xử lý..."):
                    dl = f"{d_date} {d_time.strftime('%H:%M')}"
                    res = analyze_ai(api_key, txt, dl)
                    if res:
                        tasks.append({
                            "id": int(datetime.now().timestamp()),
                            "status": "Pending",
                            "created_at": str(datetime.now().date()),
                            "deadline": dl,
                            **res
                        })
                        save_data(tasks)
                        st.toast("✅ Đã tạo task thành công!")
                        # Tự động reload sau 1s
                        st.rerun()

# === TAB 3: BÁO CÁO (STATS SCREEN) ===
with tab_stats:
    st.markdown("#### Tổng quan hôm nay")
    
    total = len(tasks)
    done_cnt = total - len(pending)
    rate = int(done_cnt/total*100) if total > 0 else 0
    
    # KPI Cards Horizontal Scroll
    c1, c2 = st.columns(2)
    c1.metric("Còn lại", len(pending))
    c2.metric("Hoàn thành", f"{rate}%")
    
    st.markdown("---")
    st.markdown("##### 🎯 Phân bổ Eisenhower")
    
    # Hiển thị dạng bảng đơn giản
    q_data = {"Q1 (Gấp & Quan trọng)": 0, "Q2 (Kế hoạch)": 0, "Q3 (Ủy quyền)": 0, "Q4 (Xóa)": 0}
    for t in pending:
        eis = t.get('eisenhower', 'Other')
        if "Q1" in eis: q_data["Q1 (Gấp & Quan trọng)"] += 1
        elif "Q2" in eis: q_data["Q2 (Kế hoạch)"] += 1
        elif "Q3" in eis: q_data["Q3 (Ủy quyền)"] += 1
        elif "Q4" in eis: q_data["Q4 (Xóa)"] += 1
        
    st.bar_chart(pd.DataFrame.from_dict(q_data, orient='index', columns=['Số lượng']))
    
    if st.button("🔄 Đồng bộ dữ liệu thủ công", use_container_width=True):
        st.cache_data.clear()
        st.rerun()
