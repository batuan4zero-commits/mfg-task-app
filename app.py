import streamlit as st
import google.generativeai as genai
import pandas as pd
import json
import os
import gspread
from google.oauth2.service_account import Credentials # Thư viện Auth mới
from datetime import datetime, time

# --- 1. CẤU HÌNH & CSS ---
st.set_page_config(page_title="MFG Commander v8.0", page_icon="🏭", layout="wide")

st.markdown("""
<style>
    .mobile-card {
        background-color: white;
        padding: 15px;
        border-radius: 10px;
        box-shadow: 0 2px 5px rgba(0,0,0,0.1);
        margin-bottom: 10px;
        border-left: 5px solid #4285f4;
    }
    .status-tag {
        display: inline-block;
        padding: 2px 8px;
        border-radius: 4px;
        font-size: 0.8em;
        font-weight: bold;
        color: white;
    }
</style>
""", unsafe_allow_html=True)

DB_FILE = "tasks_db.json"

# --- 2. KẾT NỐI GOOGLE SHEET (CHUẨN MỚI) ---
def get_api_key():
    if "GEMINI_API_KEY" in st.secrets:
        return st.secrets["GEMINI_API_KEY"]
    return None

def connect_google_sheet():
    # Define Scope chuẩn
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    
    try:
        # Ưu tiên lấy từ Secrets (Cloud)
        if "gcp_service_account" in st.secrets:
            creds = Credentials.from_service_account_info(
                st.secrets["gcp_service_account"],
                scopes=scopes
            )
            client = gspread.authorize(creds)
            sheet = client.open("MFG_Task_Database").sheet1
            return sheet, "Success"
        # Fallback local (file json)
        elif os.path.exists("credentials.json"):
            creds = Credentials.from_service_account_file("credentials.json", scopes=scopes)
            client = gspread.authorize(creds)
            sheet = client.open("MFG_Task_Database").sheet1
            return sheet, "Success"
        else:
            return None, "⚠️ Chưa cấu hình Secrets/Credentials."
    except Exception as e:
        return None, f"Lỗi Auth: {str(e)}"

def sync_to_gsheet(tasks):
    sheet, msg = connect_google_sheet()
    if sheet:
        try:
            if not tasks: return True, "Trống"
            df = pd.DataFrame(tasks)
            # Chuyển Checklist thành text để lưu lên Sheet dễ đọc
            if 'subtasks' in df.columns:
                df['subtasks'] = df['subtasks'].apply(
                    lambda x: "\n".join([f"[{'x' if i.get('done') else ' '}] {i.get('name')}" for i in x]) 
                    if isinstance(x, list) else str(x)
                )
            df = df.astype(str)
            sheet.clear()
            sheet.update([df.columns.values.tolist()] + df.values.tolist())
            return True, "✅ Đã đồng bộ Cloud!"
        except Exception as e:
            return False, str(e)
    return False, msg

# --- 3. DATABASE & AI LOGIC ---
def load_tasks():
    if not os.path.exists(DB_FILE): return []
    try:
        with open(DB_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            # Fix lỗi cấu trúc dữ liệu cũ
            for t in data:
                if "subtasks" not in t: t["subtasks"] = []
                # Convert list string cũ sang list object mới
                new_subs = []
                for s in t["subtasks"]:
                    if isinstance(s, str): new_subs.append({"name": s, "done": False})
                    else: new_subs.append(s)
                t["subtasks"] = new_subs
            return data
    except: return []

def save_tasks(tasks):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(tasks, f, ensure_ascii=False, indent=2)

def analyze_task_ai(api_key, text, deadline):
    genai.configure(api_key=api_key)
    # Prompt cực mạnh để ép ra Subtask
    prompt = f"""
    Input Task: "{text}"
    Deadline: "{deadline}"
    
    YÊU CẦU BẮT BUỘC:
    1. Chia nhỏ task này thành 3-5 bước thực hiện cụ thể (subtasks).
    2. Subtasks KHÔNG ĐƯỢC RỖNG. Nếu task quá đơn giản, hãy bịa ra các bước kiểm tra.
    
    Output JSON Schema:
    {{ 
        "task_name": "Tên ngắn gọn", 
        "description": "Mô tả chi tiết mục tiêu", 
        "priority": "High/Medium/Low", 
        "eisenhower": "Q1/Q2/Q3/Q4", 
        "subtasks": ["Bước 1...", "Bước 2...", "Bước 3..."] 
    }}
    """
    
    for model_name in ['gemini-2.5-flash', 'gemini-2.5-flash']:
        try:
            model = genai.GenerativeModel(model_name, generation_config={"response_mime_type": "application/json"})
            response = model.generate_content(prompt)
            data = json.loads(response.text.strip())
            if isinstance(data, list): data = data[0]
            
            # Chuẩn hóa Checklist ngay lập tức
            final_subs = []
            raw_subs = data.get("subtasks", [])
            if isinstance(raw_subs, list):
                for s in raw_subs: final_subs.append({"name": str(s), "done": False})
            data["subtasks"] = final_subs
            
            return data
        except: continue
    return None

# --- 4. GIAO DIỆN CHÍNH (TAB VIEW) ---

with st.sidebar:
    st.header("⚙️ Cài đặt")
    api_key = get_api_key()
    if api_key: st.success("✅ API Key Ready")
    else: api_key = st.text_input("Gemini API Key", type="password")
    
    st.divider()
    if st.button("🔄 Force Sync Google Sheet"):
        t = load_tasks()
        ok, m = sync_to_gsheet(t)
        if ok: st.toast(m, icon="☁️")
        else: st.error(m)

st.title("🏭 MFG Commander v8")

# --- TAB NAVIGATION ---
tab1, tab2, tab3 = st.tabs(["📝 Công việc", "🎯 Ma trận Ưu tiên", "📊 Dashboard"])

tasks = load_tasks()

# === TAB 1: NHẬP LIỆU & LIST ===
with tab1:
    with st.expander("➕ THÊM TASK MỚI", expanded=True):
        new_task = st.text_input("Nội dung công việc")
        c1, c2 = st.columns(2)
        with c1: d_date = st.date_input("Ngày", value=datetime.now())
        with c2: d_time = st.time_input("Giờ", value=time(17, 0))
        
        if st.button("🚀 Thêm Task", type="primary", use_container_width=True):
            if not api_key: st.error("Thiếu API Key")
            elif not new_task: st.warning("Nhập nội dung")
            else:
                with st.spinner("AI đang chia nhỏ công việc..."):
                    dl = f"{d_date} {d_time.strftime('%H:%M')}"
                    res = analyze_task_ai(api_key, new_task, dl)
                    if res:
                        tasks = load_tasks()
                        tasks.append({
                            "id": int(datetime.now().timestamp()), # ID theo thời gian để không trùng
                            "status": "Pending",
                            "created_at": str(datetime.now().date()),
                            "deadline": dl,
                            **res
                        })
                        save_tasks(tasks)
                        sync_to_gsheet(tasks)
                        st.rerun()

    st.subheader("Danh sách cần làm")
    pending_tasks = [t for t in tasks if t['status'] != 'Done']
    
    for t in reversed(pending_tasks):
        color = "#ff4b4b" if t['priority'] == 'High' else "#3373c4"
        with st.container():
            st.markdown(f"""
            <div style="background:white; padding:15px; border-radius:10px; border-left: 5px solid {color}; box-shadow: 0 1px 3px rgba(0,0,0,0.1); margin-bottom:10px;">
                <div style="font-weight:bold; font-size:1.1em;">{t['task_name']}</div>
                <div style="color:#666; font-size:0.85em;">⏳ {t['deadline']} | {t['eisenhower']}</div>
            </div>
            """, unsafe_allow_html=True)
            
            with st.expander("✅ Checklist & Hành động"):
                st.info(t.get('description', ''))
                
                # CHECKLIST INTERACTIVE
                subs = t.get('subtasks', [])
                updated_subs = []
                has_change = False
                done_count = 0
                
                for i, s in enumerate(subs):
                    is_done = st.checkbox(s['name'], value=s['done'], key=f"c_{t['id']}_{i}")
                    if is_done: done_count += 1
                    if is_done != s['done']:
                        s['done'] = is_done
                        has_change = True
                    updated_subs.append(s)
                
                if len(subs) > 0:
                    st.progress(done_count / len(subs))
                
                if has_change:
                    for org in tasks:
                        if org['id'] == t['id']: org['subtasks'] = updated_subs
                    save_tasks(tasks)
                    st.rerun()

                col_act1, col_act2 = st.columns(2)
                with col_act1:
                    if st.button("🎉 Hoàn thành", key=f"fin_{t['id']}", use_container_width=True):
                        for org in tasks:
                            if org['id'] == t['id']: org['status'] = 'Done'
                        save_tasks(tasks)
                        sync_to_gsheet(tasks)
                        st.rerun()
                with col_act2:
                    if st.button("🗑️ Xóa Task", key=f"del_{t['id']}", type="secondary", use_container_width=True):
                        tasks = [x for x in tasks if x['id'] != t['id']]
                        save_tasks(tasks)
                        sync_to_gsheet(tasks)
                        st.rerun()

# === TAB 2: EISENHOWER ===
with tab2:
    st.caption("Ma trận ưu tiên công việc")
    col1, col2 = st.columns(2)
    
    def render_matrix_card(col, title, color, code):
        items = [t for t in pending_tasks if code in t['eisenhower']]
        with col:
            st.markdown(f"<div style='color:{color}; font-weight:bold; border-bottom:2px solid {color}'>{title} ({len(items)})</div>", unsafe_allow_html=True)
            for t in items:
                st.markdown(f"• {t['task_name']}")

    render_matrix_card(col1, "🔥 DO FIRST (Q1)", "#ff4b4b", "Q1")
    render_matrix_card(col2, "📅 SCHEDULE (Q2)", "#ffa421", "Q2")
    render_matrix_card(col1, "🤝 DELEGATE (Q3)", "#3373c4", "Q3")
    render_matrix_card(col2, "🗑️ DELETE (Q4)", "#6c757d", "Q4")

# === TAB 3: DASHBOARD ===
with tab3:
    st.subheader("📊 Tổng hợp Trạng thái")
    if tasks:
        df = pd.DataFrame(tasks)
        
        # Metrics
        total = len(df)
        done = len(df[df['status'] == 'Done'])
        pending = total - done
        
        m1, m2, m3 = st.columns(3)
        m1.metric("Tổng Task", total)
        m2.metric("Đã xong", done)
        m3.metric("Còn lại", pending)
        
        st.divider()
        st.caption("Chi tiết dữ liệu (Dạng bảng)")
        
        # Format lại subtask để hiển thị bảng
        df_view = df.copy()
        df_view['subtasks'] = df_view['subtasks'].apply(
            lambda x: ", ".join([i['name'] for i in x]) if isinstance(x, list) else str(x)
        )
        
        st.dataframe(
            df_view[['task_name', 'status', 'priority', 'deadline', 'subtasks']],
            use_container_width=True,
            hide_index=True
        )
    else:
        st.info("Chưa có dữ liệu")
