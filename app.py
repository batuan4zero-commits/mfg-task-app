import streamlit as st
import google.generativeai as genai
import pandas as pd
import json
import os
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime, time

# --- 1. CẤU HÌNH GIAO DIỆN MFG 4.0 (INDUSTRIAL STYLE) ---
st.set_page_config(page_title="MFG Commander v9.0", page_icon="🏭", layout="wide")

# CSS "Industrial Theme": Gọn gàng, Tương phản cao, Chuyên nghiệp
st.markdown("""
<style>
    /* Tổng thể */
    .main { background-color: #f8f9fa; }
    
    /* Header KPI Cards */
    div[data-testid="metric-container"] {
        background-color: white;
        border: 1px solid #ddd;
        padding: 15px;
        border-radius: 8px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
    }
    
    /* Task Card Design */
    .task-card {
        background-color: white;
        padding: 15px;
        border-radius: 8px;
        border-left: 6px solid #ccc;
        box-shadow: 0 2px 5px rgba(0,0,0,0.08);
        margin-bottom: 12px;
        transition: transform 0.2s;
    }
    .task-card:hover { transform: translateY(-2px); }
    
    /* Priority Colors */
    .border-High { border-left-color: #d93025 !important; } /* Red */
    .border-Medium { border-left-color: #f9ab00 !important; } /* Yellow */
    .border-Low { border-left-color: #1e8e3e !important; } /* Green */
    
    /* Badges */
    .badge {
        padding: 4px 8px;
        border-radius: 4px;
        font-size: 0.75rem;
        font-weight: 700;
        text-transform: uppercase;
        margin-right: 5px;
    }
    .badge-date { background-color: #e8f0fe; color: #1967d2; }
    .badge-cat { background-color: #fce8e6; color: #c5221f; }
    
    /* Tab Styling */
    .stTabs [data-baseweb="tab-list"] { gap: 10px; }
    .stTabs [data-baseweb="tab"] {
        height: 50px;
        white-space: pre-wrap;
        background-color: white;
        border-radius: 5px 5px 0 0;
        border: 1px solid #eee;
    }
    .stTabs [aria-selected="true"] {
        background-color: #e3f2fd;
        border-bottom: 3px solid #1967d2;
        font-weight: bold;
    }
</style>
""", unsafe_allow_html=True)

# --- 2. KẾT NỐI GOOGLE SHEET (DATABASE VĨNH VIỄN) ---
# Xóa bỏ hoàn toàn việc dùng file JSON cục bộ
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

# LOAD DATA TRỰC TIẾP TỪ CLOUD (FIX LỖI MẤT DATA)
def load_data_from_cloud():
    client = get_gsheet_client()
    if not client: return []
    try:
        sheet = client.open("MFG_Task_Database").sheet1
        records = sheet.get_all_records()
        
        # Xử lý dữ liệu thô từ Sheet (String) thành Object Python
        clean_data = []
        for r in records:
            # Parse Subtasks (JSON String -> List)
            if 'subtasks' in r and isinstance(r['subtasks'], str):
                try:
                    # Thay thế dấu nháy đơn thành nháy kép nếu cần để parse JSON chuẩn
                    cleaned_json = r['subtasks'].replace("'", '"').replace("False", "false").replace("True", "true")
                    r['subtasks'] = json.loads(cleaned_json)
                except:
                    r['subtasks'] = [] # Fallback nếu lỗi
            
            # Đảm bảo có đủ trường
            if 'status' not in r: r['status'] = 'Pending'
            if 'priority' not in r: r['priority'] = 'Medium'
            
            clean_data.append(r)
        return clean_data
    except Exception as e:
        # Nếu sheet trống hoặc lỗi, trả về list rỗng
        return []

# SAVE DATA TRỰC TIẾP LÊN CLOUD
def save_data_to_cloud(tasks):
    client = get_gsheet_client()
    if not client: return False, "Lỗi Auth"
    try:
        sheet = client.open("MFG_Task_Database").sheet1
        if not tasks:
            sheet.clear()
            return True, "Đã xóa sạch"
            
        df = pd.DataFrame(tasks)
        # Convert List/Dict thành String để lưu vào Sheet
        if 'subtasks' in df.columns:
            df['subtasks'] = df['subtasks'].apply(lambda x: json.dumps(x, ensure_ascii=False) if isinstance(x, list) else str(x))
        
        df = df.astype(str)
        sheet.clear()
        sheet.update([df.columns.values.tolist()] + df.values.tolist())
        return True, "✅ Saved to Cloud"
    except Exception as e:
        return False, str(e)

# --- 3. AI ENGINE (GIỮ NGUYÊN LOGIC) ---
def analyze_task_ai(api_key, text, deadline):
    genai.configure(api_key=api_key)
    prompt = f"""
    Input Task: "{text}" | Deadline: "{deadline}"
    YÊU CẦU: Đóng vai Quản lý sản xuất. Phân tích task này.
    Output JSON Schema:
    {{ 
        "task_name": "Tên ngắn gọn (Tiếng Việt)", 
        "description": "Mô tả chi tiết mục tiêu", 
        "priority": "High/Medium/Low", 
        "eisenhower": "Q1 (Gấp & Quan trọng)/Q2 (Quan trọng)/Q3 (Gấp)/Q4 (Xóa)", 
        "subtasks": [
            {{"name": "Bước 1...", "done": false}}, 
            {{"name": "Bước 2...", "done": false}}
        ] 
    }}
    Lưu ý: subtasks phải là List of Objects có field 'name' và 'done'.
    """
    for model_name in ['gemini-2.0-flash-exp', 'gemini-1.5-flash']:
        try:
            model = genai.GenerativeModel(model_name, generation_config={"response_mime_type": "application/json"})
            response = model.generate_content(prompt)
            data = json.loads(response.text.strip())
            if isinstance(data, list): data = data[0]
            
            # Sanitize subtasks
            if 'subtasks' in data:
                clean_subs = []
                for s in data['subtasks']:
                    if isinstance(s, str): clean_subs.append({"name": s, "done": False})
                    elif isinstance(s, dict): clean_subs.append({"name": s.get('name', 'Step'), "done": s.get('done', False)})
                data['subtasks'] = clean_subs
            return data
        except: continue
    return None

# --- 4. GIAO DIỆN CHÍNH ---

# SIDEBAR: Profile Quản lý
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/3048/3048122.png", width=80)
    st.markdown("### MANAGER PROFILE")
    st.markdown("**Role:** Senior Team Leader")
    st.markdown("**Area:** Manufacturing (MFG)")
    
    st.divider()
    
    # API Key Handling
    if "GEMINI_API_KEY" in st.secrets:
        api_key = st.secrets["GEMINI_API_KEY"]
        st.success("🔑 API Key Active")
    else:
        api_key = st.text_input("Enter API Key", type="password")

    st.divider()
    if st.button("🔄 Reload Data from Cloud"):
        st.cache_data.clear()
        st.rerun()

# HEADER: Dashboard KPI (MFG Style)
st.title("🏭 OPERATION CONTROL CENTER")

# Load data ngay khi vào app
tasks = load_data_from_cloud()

# Tính toán KPI
total_tasks = len(tasks)
pending_tasks = [t for t in tasks if t.get('status') != 'Done']
high_priority = len([t for t in pending_tasks if t.get('priority') == 'High'])
completion_rate = int(((total_tasks - len(pending_tasks)) / total_tasks * 100)) if total_tasks > 0 else 0

kpi1, kpi2, kpi3, kpi4 = st.columns(4)
kpi1.metric("PENDING TASKS", len(pending_tasks), "Tasks")
kpi2.metric("HIGH PRIORITY", high_priority, "Urgent", delta_color="inverse")
kpi3.metric("EFFICIENCY", f"{completion_rate}%", "Completion Rate")
kpi4.metric("TOTAL LOGS", total_tasks, "All Time")

st.divider()

# TABS NAVIGATION
tab_ops, tab_strat, tab_data = st.tabs(["⚙️ OPERATIONS (Thực thi)", "🎯 STRATEGY (Eisenhower)", "📊 DATABASE (Dữ liệu)"])

# === TAB 1: OPERATIONS ===
with tab_ops:
    # 1. Input Section
    with st.container():
        c_in1, c_in2, c_in3 = st.columns([3, 1, 1])
        with c_in1: new_task_txt = st.text_input("New Assignment", placeholder="VD: Bảo trì máy ép số 3...")
        with c_in2: d_date = st.date_input("Due Date", value=datetime.now())
        with c_in3: d_time = st.time_input("Time", value=time(17, 0))
        
        if st.button("ADD ASSIGNMENT", type="primary", use_container_width=True):
            if not api_key: st.error("Missing API Key")
            elif not new_task_txt: st.warning("Input required")
            else:
                with st.spinner("Analyzing Workload..."):
                    deadline_str = f"{d_date} {d_time.strftime('%H:%M')}"
                    res = analyze_task_ai(api_key, new_task_txt, deadline_str)
                    if res:
                        new_item = {
                            "id": int(datetime.now().timestamp()),
                            "status": "Pending",
                            "created_at": str(datetime.now().date()),
                            "deadline": deadline_str,
                            **res
                        }
                        tasks.append(new_item)
                        save_data_to_cloud(tasks) # Save ngay lập tức
                        st.rerun()

    # 2. Task List (Card View)
    st.markdown("### 📋 ACTIVE ASSIGNMENTS")
    if not pending_tasks:
        st.info("All clear! No pending tasks.")
    
    for t in reversed(pending_tasks):
        prio = t.get('priority', 'Medium')
        
        # Render Card
        with st.container():
            st.markdown(f"""
            <div class="task-card border-{prio}">
                <div style="display:flex; justify-content:space-between;">
                    <span style="font-weight:bold; font-size:1.1rem;">{t.get('task_name')}</span>
                    <span style="color:#666; font-size:0.9rem;">#{t.get('id')}</span>
                </div>
                <div style="margin-top:5px; margin-bottom:10px;">
                    <span class="badge badge-cat">{prio}</span>
                    <span class="badge badge-date">📅 {t.get('deadline')}</span>
                    <span class="badge" style="background:#eee;">{t.get('eisenhower', 'N/A')}</span>
                </div>
                <div style="font-size:0.95rem; color:#444;">{t.get('description')}</div>
            </div>
            """, unsafe_allow_html=True)
            
            # Interactive Section
            with st.expander("🔻 Action & Checklist"):
                # Checklist Logic
                subs = t.get('subtasks', [])
                updated_subs = []
                changed = False
                
                for i, s in enumerate(subs):
                    # Checkbox
                    is_done = st.checkbox(s.get('name', 'Task'), value=s.get('done', False), key=f"sub_{t['id']}_{i}")
                    if is_done != s.get('done', False):
                        s['done'] = is_done
                        changed = True
                    updated_subs.append(s)
                
                # Nút bấm hành động
                ac1, ac2 = st.columns([1, 4])
                with ac1:
                    if st.button("✅ DONE", key=f"dn_{t['id']}"):
                        t['status'] = 'Done'
                        save_data_to_cloud(tasks)
                        st.rerun()
                with ac2:
                    if st.button("🗑️ DELETE", key=f"del_{t['id']}"):
                        tasks = [x for x in tasks if x['id'] != t['id']]
                        save_data_to_cloud(tasks)
                        st.rerun()
                
                if changed:
                    t['subtasks'] = updated_subs
                    save_data_to_cloud(tasks)
                    st.rerun()

# === TAB 2: STRATEGY ===
with tab_strat:
    st.markdown("### 🎯 EISENHOWER MATRIX")
    
    col_q1, col_q2 = st.columns(2)
    col_q3, col_q4 = st.columns(2)
    
    def render_q(col, title, code, bg_color):
        with col:
            st.markdown(f"<div style='background:{bg_color}; padding:10px; border-radius:5px; font-weight:bold; text-align:center;'>{title}</div>", unsafe_allow_html=True)
            items = [x for x in pending_tasks if code in x.get('eisenhower', '')]
            if not items: st.caption("Empty")
            for item in items:
                st.markdown(f"**• {item['task_name']}** <br> <span style='font-size:0.8em; color:grey'>{item['deadline']}</span>", unsafe_allow_html=True)
                st.markdown("---")

    render_q(col_q1, "DO FIRST (Q1)", "Q1", "#ffebee") # Red
    render_q(col_q2, "SCHEDULE (Q2)", "Q2", "#e3f2fd") # Blue
    render_q(col_q3, "DELEGATE (Q3)", "Q3", "#fff3e0") # Orange
    render_q(col_q4, "DELETE (Q4)", "Q4", "#f5f5f5")   # Grey

# === TAB 3: DATA ===
with tab_data:
    st.markdown("### 📊 MASTER DATA RECORD")
    if tasks:
        df = pd.DataFrame(tasks)
        # Clean subtasks for view
        df['subtasks'] = df['subtasks'].apply(lambda x: len(x) if isinstance(x, list) else 0)
        df = df.rename(columns={"subtasks": "Subtask Count"})
        
        st.dataframe(
            df[['id', 'created_at', 'task_name', 'status', 'priority', 'deadline', 'eisenhower']], 
            use_container_width=True,
            hide_index=True
        )
    else:
        st.warning("No data found in Cloud Database.")
