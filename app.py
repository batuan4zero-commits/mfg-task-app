import streamlit as st
import google.generativeai as genai
import pandas as pd
import json
import os
import gspread
import ast # Thư viện quan trọng để fix lỗi đọc Checklist
from google.oauth2.service_account import Credentials
from datetime import datetime, time

# --- 1. CẤU HÌNH GIAO DIỆN MFG 4.0 ---
st.set_page_config(page_title="MFG Commander v9.1", page_icon="🏭", layout="wide")

st.markdown("""
<style>
    .main { background-color: #f8f9fa; }
    div[data-testid="metric-container"] {
        background-color: white; border: 1px solid #ddd; padding: 15px; border-radius: 8px;
    }
    .task-card {
        background-color: white; padding: 20px; border-radius: 8px;
        border-left: 6px solid #ccc; box-shadow: 0 2px 5px rgba(0,0,0,0.08);
        margin-bottom: 15px;
    }
    .border-High { border-left-color: #d93025 !important; }
    .border-Medium { border-left-color: #f9ab00 !important; }
    .border-Low { border-left-color: #1e8e3e !important; }
    
    .badge {
        padding: 4px 8px; border-radius: 4px; font-size: 0.75rem; font-weight: 700; text-transform: uppercase; margin-right: 5px;
    }
    .badge-date { background-color: #e8f0fe; color: #1967d2; }
    .badge-cat { background-color: #fce8e6; color: #c5221f; }
    
    /* Progress Bar Style */
    .stProgress > div > div > div > div {
        background-color: #1e8e3e;
    }
</style>
""", unsafe_allow_html=True)

# --- 2. KẾT NỐI CLOUD DATABASE ---
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

# LOAD DATA (FIX LỖI CHECKLIST TẠI ĐÂY)
def load_data_from_cloud():
    client = get_gsheet_client()
    if not client: return []
    try:
        sheet = client.open("MFG_Task_Database").sheet1
        records = sheet.get_all_records()
        
        clean_data = []
        for r in records:
            # --- THUẬT TOÁN SỬA LỖI CHECKLIST ---
            # Dữ liệu từ Sheet là String dạng "[{'name': 'A', 'done': False}]"
            # Ta dùng ast.literal_eval để biến nó lại thành List Python an toàn
            if 'subtasks' in r:
                try:
                    if isinstance(r['subtasks'], str) and r['subtasks'].strip():
                        r['subtasks'] = ast.literal_eval(r['subtasks'])
                    elif not isinstance(r['subtasks'], list):
                        r['subtasks'] = []
                except:
                    r['subtasks'] = [] # Nếu lỗi format thì reset về rỗng
            else:
                r['subtasks'] = []
            
            # Đảm bảo các trường khác không bị lỗi
            if 'status' not in r: r['status'] = 'Pending'
            if 'priority' not in r: r['priority'] = 'Medium'
            
            clean_data.append(r)
        return clean_data
    except Exception as e:
        return []

def save_data_to_cloud(tasks):
    client = get_gsheet_client()
    if not client: return False, "Auth Error"
    try:
        sheet = client.open("MFG_Task_Database").sheet1
        if not tasks:
            sheet.clear()
            return True, "Cleared"
            
        df = pd.DataFrame(tasks)
        # Convert List Subtask thành String để lưu được vào Sheet
        if 'subtasks' in df.columns:
            df['subtasks'] = df['subtasks'].apply(lambda x: str(x) if isinstance(x, list) else str(x))
        
        df = df.astype(str)
        sheet.clear()
        sheet.update([df.columns.values.tolist()] + df.values.tolist())
        return True, "Saved"
    except Exception as e:
        return False, str(e)

# --- 3. AI ENGINE (ÉP BUỘC TẠO CHECKLIST) ---
def analyze_task_ai(api_key, text, deadline):
    genai.configure(api_key=api_key)
    prompt = f"""
    Input Task: "{text}" | Deadline: "{deadline}"
    ROLE: Production Manager.
    
    YÊU CẦU QUAN TRỌNG:
    1. Bắt buộc phải chia nhỏ task thành 3-6 bước thực hiện (Checklist).
    2. Nếu task chung chung, hãy tự đề xuất quy trình chuẩn (SOP).
    
    Output JSON Schema:
    {{ 
        "task_name": "Tên Task (Tiếng Việt)", 
        "description": "Mô tả mục tiêu", 
        "priority": "High/Medium/Low", 
        "eisenhower": "Q1/Q2/Q3/Q4", 
        "subtasks": [
            {{"name": "Bước 1: Chuẩn bị...", "done": false}}, 
            {{"name": "Bước 2: Thực hiện...", "done": false}},
            {{"name": "Bước 3: Kiểm tra...", "done": false}}
        ] 
    }}
    """
    for model_name in ['gemini-2.0-flash-exp', 'gemini-1.5-flash']:
        try:
            model = genai.GenerativeModel(model_name, generation_config={"response_mime_type": "application/json"})
            response = model.generate_content(prompt)
            data = json.loads(response.text.strip())
            if isinstance(data, list): data = data[0]
            
            # Validate Subtasks
            clean_subs = []
            if 'subtasks' in data and isinstance(data['subtasks'], list):
                for s in data['subtasks']:
                    name = s.get('name') if isinstance(s, dict) else str(s)
                    clean_subs.append({"name": name, "done": False})
            data['subtasks'] = clean_subs
            
            return data
        except: continue
    return None

# --- 4. GIAO DIỆN CHÍNH ---

with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/3048/3048122.png", width=80)
    st.markdown("### MANAGER PROFILE")
    st.markdown("**Role:** Senior Team Leader (MFG)")
    
    if "GEMINI_API_KEY" in st.secrets:
        api_key = st.secrets["GEMINI_API_KEY"]
        st.success("🔑 API Key Active")
    else:
        api_key = st.text_input("API Key", type="password")

    st.divider()
    if st.button("🔄 Force Reload Data"):
        st.cache_data.clear()
        st.rerun()

st.title("🏭 OPERATION CONTROL CENTER")

# Load Data
tasks = load_data_from_cloud()

# KPI Calculation
total = len(tasks)
pending = [t for t in tasks if t.get('status') != 'Done']
done_count = total - len(pending)
rate = int((done_count / total * 100)) if total > 0 else 0

k1, k2, k3, k4 = st.columns(4)
k1.metric("PENDING", len(pending), "Tasks")
k2.metric("URGENT", len([t for t in pending if t.get('priority')=='High']), "High Priority", delta_color="inverse")
k3.metric("COMPLETION", f"{rate}%", "Rate")
k4.metric("TOTAL", total, "Logs")

st.divider()

tab1, tab2, tab3 = st.tabs(["⚙️ THỰC THI (Operations)", "🎯 CHIẾN LƯỢC (Eisenhower)", "📊 DỮ LIỆU (Database)"])

# === TAB 1: OPERATIONS ===
with tab1:
    # Input Area
    with st.container():
        c1, c2, c3 = st.columns([3, 1, 1])
        with c1: inp = st.text_input("Giao việc mới", placeholder="VD: Bảo trì máy nén khí...")
        with c2: dd = st.date_input("Hạn chót", value=datetime.now())
        with c3: dt = st.time_input("Giờ", value=time(17,0))
        
        if st.button("PHÂN TÍCH & THÊM TASK", type="primary", use_container_width=True):
            if not api_key: st.error("Thiếu API Key")
            elif not inp: st.warning("Chưa nhập nội dung")
            else:
                with st.spinner("AI đang lập quy trình (SOP)..."):
                    dl = f"{dd} {dt.strftime('%H:%M')}"
                    res = analyze_task_ai(api_key, inp, dl)
                    if res:
                        tasks.append({
                            "id": int(datetime.now().timestamp()),
                            "status": "Pending",
                            "created_at": str(datetime.now().date()),
                            "deadline": dl,
                            **res
                        })
                        save_data_to_cloud(tasks)
                        st.rerun()

    st.markdown("### 📋 DANH SÁCH CÔNG VIỆC")
    
    for t in reversed(pending):
        prio = t.get('priority', 'Medium')
        subs = t.get('subtasks', [])
        
        # Tính toán Progress Bar
        total_sub = len(subs)
        done_sub = sum(1 for s in subs if s.get('done'))
        prog_val = done_sub / total_sub if total_sub > 0 else 0
        
        with st.container():
            # Card Header
            st.markdown(f"""
            <div class="task-card border-{prio}">
                <div style="display:flex; justify-content:space-between;">
                    <span style="font-weight:bold; font-size:1.2rem;">{t.get('task_name')}</span>
                    <span style="color:#888;">#{t.get('id')}</span>
                </div>
                <div style="margin: 8px 0;">
                    <span class="badge badge-cat">{prio}</span>
                    <span class="badge badge-date">📅 {t.get('deadline')}</span>
                    <span class="badge" style="background:#eee">{t.get('eisenhower')}</span>
                </div>
                <div style="margin-bottom:10px;">{t.get('description')}</div>
            """, unsafe_allow_html=True)
            
            # --- PROGRESS BAR HIỂN THỊ TRỰC QUAN ---
            if total_sub > 0:
                st.caption(f"Tiến độ Checklist: {done_sub}/{total_sub} hoàn thành")
                st.progress(prog_val)
            
            st.markdown("</div>", unsafe_allow_html=True)

            # Expander Checklist
            with st.expander(f"🔻 Mở Checklist chi tiết ({done_sub}/{total_sub})"):
                updated_subs = []
                has_change = False
                
                # Render từng dòng Checklist
                for i, s in enumerate(subs):
                    label = s.get('name', 'Step')
                    checked = s.get('done', False)
                    
                    # Checkbox tương tác
                    is_checked = st.checkbox(label, value=checked, key=f"c_{t['id']}_{i}")
                    
                    if is_checked != checked:
                        s['done'] = is_checked
                        has_change = True
                    updated_subs.append(s)
                
                # Nút Done/Delete
                col_btn1, col_btn2 = st.columns([1, 4])
                with col_btn1:
                    if st.button("✅ DONE TASK", key=f"fin_{t['id']}"):
                        t['status'] = 'Done'
                        save_data_to_cloud(tasks)
                        st.rerun()
                with col_btn2:
                    if st.button("🗑️ DELETE", key=f"del_{t['id']}"):
                        tasks = [x for x in tasks if x['id'] != t['id']]
                        save_data_to_cloud(tasks)
                        st.rerun()
                
                # Auto Save khi tick checkbox
                if has_change:
                    t['subtasks'] = updated_subs
                    save_data_to_cloud(tasks)
                    st.rerun()

# === TAB 2 & 3 GIỮ NGUYÊN ===
with tab2:
    st.markdown("### 🎯 EISENHOWER MATRIX")
    c_q1, c_q2 = st.columns(2)
    c_q3, c_q4 = st.columns(2)
    def render_q(col, title, k, color):
        with col:
            st.markdown(f"<div style='background:{color}; padding:10px; border-radius:5px; font-weight:bold; text-align:center;'>{title}</div>", unsafe_allow_html=True)
            items = [x for x in pending if k in x.get('eisenhower','')]
            for i in items: st.markdown(f"**{i['task_name']}**<br><span style='font-size:0.8em'>{i['deadline']}</span><hr style='margin:5px 0'>", unsafe_allow_html=True)
            
    render_q(c_q1, "DO FIRST (Q1)", "Q1", "#ffebee")
    render_q(c_q2, "SCHEDULE (Q2)", "Q2", "#e3f2fd")
    render_q(c_q3, "DELEGATE (Q3)", "Q3", "#fff3e0")
    render_q(c_q4, "DELETE (Q4)", "Q4", "#f5f5f5")

with tab3:
    st.markdown("### 📊 MASTER DATABASE")
    if tasks:
        df = pd.DataFrame(tasks)
        st.dataframe(df.astype(str), use_container_width=True)
