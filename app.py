import streamlit as st
import google.generativeai as genai
import pandas as pd
import json
import os
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, time

# --- 1. CẤU HÌNH & CSS MOBILE ---
st.set_page_config(page_title="MFG Commander v6.0", page_icon="🏭", layout="wide")

st.markdown("""
<style>
    /* CSS cho Mobile Card */
    .mobile-card {
        background-color: white;
        padding: 15px;
        border-radius: 10px;
        box-shadow: 0 2px 5px rgba(0,0,0,0.1);
        margin-bottom: 10px;
        border-left: 5px solid #4285f4;
    }
    .mobile-header {
        font-weight: bold;
        font-size: 1.1rem;
        color: #333;
    }
    .mobile-meta {
        font-size: 0.9rem;
        color: #666;
        margin-bottom: 5px;
    }
    
    /* Ẩn bảng trên mobile nếu cần */
    @media (max-width: 640px) {
        .desktop-view { display: none; }
        .mobile-view { display: block; }
    }
</style>
""", unsafe_allow_html=True)

DB_FILE = "tasks_db.json"
CREDENTIALS_FILE = "credentials.json"

# --- 2. XỬ LÝ API KEY TỰ ĐỘNG (SECRETS) ---
def get_api_key():
    # Ưu tiên lấy từ Secrets (khi deploy hoặc cấu hình local)
    if "GEMINI_API_KEY" in st.secrets:
        return st.secrets["GEMINI_API_KEY"]
    return None

# --- 3. MODULE GOOGLE SHEET ---
def get_service_email():
    # Lấy email từ secrets nếu deploy, hoặc file json nếu chạy local
    if "gcp_service_account" in st.secrets:
        return st.secrets["gcp_service_account"]["client_email"]
    
    if os.path.exists(CREDENTIALS_FILE):
        try:
            with open(CREDENTIALS_FILE, 'r') as f:
                data = json.load(f)
                return data.get("client_email")
        except: pass
    return "Chưa cấu hình Credentials"

def connect_google_sheet():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    try:
        # Cách 1: Kết nối khi Deploy lên Streamlit Cloud (Dùng Secrets)
        if "gcp_service_account" in st.secrets:
            creds = ServiceAccountCredentials.from_json_keyfile_dict(dict(st.secrets["gcp_service_account"]), scope)
        # Cách 2: Kết nối Local (Dùng file json)
        elif os.path.exists(CREDENTIALS_FILE):
            creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, scope)
        else:
            return None, "⚠️ Thiếu file credentials hoặc secrets."
            
        client = gspread.authorize(creds)
        sheet = client.open("MFG_Task_Database").sheet1
        return sheet, "Success"
    except Exception as e:
        return None, f"Lỗi GSheet: {str(e)}"

def sync_to_gsheet(tasks):
    sheet, msg = connect_google_sheet()
    if sheet:
        try:
            if not tasks: return True, "Trống"
            df = pd.DataFrame(tasks)
            # Format list to string
            if 'subtasks' in df.columns:
                df['subtasks'] = df['subtasks'].apply(lambda x: "\n".join(x) if isinstance(x, list) else str(x))
            df = df.astype(str)
            sheet.clear()
            sheet.update([df.columns.values.tolist()] + df.values.tolist())
            return True, "✅ Đã đồng bộ Cloud!"
        except Exception as e:
            return False, str(e)
    return False, msg

# --- 4. DATA & AI ---
def load_tasks():
    if not os.path.exists(DB_FILE): return []
    try:
        with open(DB_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except: return []

def save_tasks(tasks):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(tasks, f, ensure_ascii=False, indent=2)

def analyze_task_ai(api_key, text, deadline):
    genai.configure(api_key=api_key)
    # Thử model mới nhất, fallback về 1.5
    for model_name in ['gemini-2.0-flash-exp', 'gemini-1.5-flash']:
        try:
            model = genai.GenerativeModel(model_name, generation_config={"response_mime_type": "application/json"})
            prompt = f"""
            Role: Trợ lý sản xuất. Input: "{text}". Deadline: "{deadline}".
            Output JSON: {{ "task_name": "", "description": "Ngắn gọn súc tích", "priority": "High/Medium/Low", "eisenhower": "Q1/Q2/Q3/Q4", "subtasks": ["Bước 1", "Bước 2"] }}
            """
            response = model.generate_content(prompt)
            return json.loads(response.text)
        except: continue
    return None

# --- 5. GIAO DIỆN CHÍNH ---

# SIDEBAR
with st.sidebar:
    st.header("⚙️ Cài đặt")
    
    # Logic API Key thông minh
    secret_key = get_api_key()
    if secret_key:
        st.success("✅ Đã nạp API Key từ hệ thống")
        api_key = secret_key
    else:
        api_key = st.text_input("Nhập Gemini API Key", type="password")
        st.caption("Mẹo: Setup 'secrets.toml' để không phải nhập lại.")

    st.divider()
    
    # Hiển thị Email Robot
    robot_mail = get_service_email()
    st.info(f"📧 Bot Email:\n{robot_mail}")
    
    if st.button("🔄 Sync Google Sheet"):
        t = load_tasks()
        ok, m = sync_to_gsheet(t)
        if ok: st.toast(m, icon="☁️")
        else: st.error(m)

# MAIN UI
st.title("🏭 MFG Copilot Mobile")

# INPUT FORM (Rút gọn cho mobile)
with st.expander("➕ THÊM TASK MỚI", expanded=True):
    new_task = st.text_input("Nội dung công việc")
    c1, c2 = st.columns(2)
    with c1: d_date = st.date_input("Ngày", value=datetime.now())
    with c2: d_time = st.time_input("Giờ", value=time(17, 0))
    
    if st.button("🚀 Thêm Task", type="primary", use_container_width=True):
        if not api_key: st.error("Thiếu API Key")
        elif not new_task: st.warning("Nhập nội dung task")
        else:
            with st.spinner("AI processing..."):
                dl = f"{d_date} {d_time.strftime('%H:%M')}"
                res = analyze_task_ai(api_key, new_task, dl)
                if res:
                    tasks = load_tasks()
                    tasks.append({"id": len(tasks)+1, "status": "Pending", "created_at": str(datetime.now().date()), "deadline": dl, **res})
                    save_tasks(tasks)
                    sync_to_gsheet(tasks) # Auto sync
                    st.rerun()

# VIEW MODE SWITCHER
st.divider()
view_mode = st.radio("Chế độ xem:", ["📱 Mobile Card", "💻 Desktop Table"], horizontal=True)

tasks = load_tasks()
pending_tasks = [t for t in tasks if t.get('status') != 'Done']

if view_mode == "📱 Mobile Card":
    # GIAO DIỆN MOBILE TỐI ƯU
    st.caption(f"Đang hiển thị {len(pending_tasks)} task chưa hoàn thành")
    
    for t in reversed(pending_tasks): # Hiện task mới nhất lên đầu
        # Quyết định màu sắc dựa trên Priority
        border_color = "#ff4b4b" if t['priority'] == 'High' else "#3373c4"
        
        with st.container():
            st.markdown(f"""
            <div style="background:white; padding:15px; border-radius:10px; border-left: 5px solid {border_color}; box-shadow: 0 1px 3px rgba(0,0,0,0.1); margin-bottom:10px;">
                <div style="font-weight:bold; font-size:1.1em;">{t['task_name']}</div>
                <div style="color:#666; font-size:0.85em; margin: 5px 0;">⏳ {t['deadline']} | 🔥 {t['priority']} | 📂 {t['eisenhower']}</div>
                <div style="margin-top:5px;">{t['description']}</div>
            </div>
            """, unsafe_allow_html=True)
            
            # Subtask & Action Expand
            with st.expander("Chi tiết & Checklist"):
                # Checklist
                subtasks = t.get('subtasks', [])
                if isinstance(subtasks, list):
                    for s in subtasks: st.markdown(f"- {s}")
                else: st.write(str(subtasks))
                
                if st.button("✅ Hoàn thành", key=f"m_done_{t['id']}", use_container_width=True):
                    for origin_t in tasks:
                        if origin_t['id'] == t['id']: origin_t['status'] = 'Done'
                    save_tasks(tasks)
                    sync_to_gsheet(tasks)
                    st.rerun()

else:
    # GIAO DIỆN DESKTOP (Full Table)
    if tasks:
        df = pd.DataFrame(tasks)
        df['subtasks'] = df['subtasks'].apply(lambda x: "\n".join(x) if isinstance(x, list) else str(x))
        st.dataframe(
            df, 
            use_container_width=True, 
            height=600,
            column_config={
                "description": st.column_config.TextColumn("Mô tả", width="large"),
                "subtasks": st.column_config.TextColumn("Checklist", width="large")
            }
        )