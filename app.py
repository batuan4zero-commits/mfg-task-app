import streamlit as st
import google.generativeai as genai
import pandas as pd
import json
import os
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, time

# --- 1. CẤU HÌNH & CSS ---
st.set_page_config(page_title="MFG Commander v6.1", page_icon="🏭", layout="wide")

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
    .status-badge {
        padding: 2px 8px;
        border-radius: 10px;
        font-size: 0.8em;
        font-weight: bold;
    }
</style>
""", unsafe_allow_html=True)

DB_FILE = "tasks_db.json"
CREDENTIALS_FILE = "credentials.json"

# --- 2. XỬ LÝ API KEY TỰ ĐỘNG ---
def get_api_key():
    if "GEMINI_API_KEY" in st.secrets:
        return st.secrets["GEMINI_API_KEY"]
    return None

# --- 3. GOOGLE SHEET ---
def get_service_email():
    if "gcp_service_account" in st.secrets:
        return st.secrets["gcp_service_account"]["client_email"]
    if os.path.exists(CREDENTIALS_FILE):
        try:
            with open(CREDENTIALS_FILE, 'r') as f:
                return json.load(f).get("client_email")
        except: pass
    return "Chưa cấu hình Credentials"

def connect_google_sheet():
    scope = ["[https://spreadsheets.google.com/feeds](https://spreadsheets.google.com/feeds)", "[https://www.googleapis.com/auth/drive](https://www.googleapis.com/auth/drive)"]
    try:
        if "gcp_service_account" in st.secrets:
            creds = ServiceAccountCredentials.from_json_keyfile_dict(dict(st.secrets["gcp_service_account"]), scope)
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
            if 'subtasks' in df.columns:
                df['subtasks'] = df['subtasks'].apply(lambda x: "\n".join(x) if isinstance(x, list) else str(x))
            df = df.astype(str)
            sheet.clear()
            sheet.update([df.columns.values.tolist()] + df.values.tolist())
            return True, "✅ Đã đồng bộ Cloud!"
        except Exception as e:
            return False, str(e)
    return False, msg

# --- 4. DATABASE & AI (FIXED ERROR) ---
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
    
    # Prompt ép buộc định dạng JSON chuẩn
    prompt = f"""
    Role: Trợ lý sản xuất. 
    Input: "{text}". Deadline: "{deadline}".
    
    Yêu cầu: Trả về ĐÚNG 1 JSON Object (Không trả về List).
    JSON Schema: 
    {{ "task_name": "", "description": "Mô tả ngắn gọn", "priority": "High/Medium/Low", "eisenhower": "Q1/Q2/Q3/Q4", "subtasks": ["Bước 1", "Bước 2"] }}
    """
    
    for model_name in ['gemini-2.0-flash-exp', 'gemini-1.5-flash']:
        try:
            model = genai.GenerativeModel(model_name, generation_config={"response_mime_type": "application/json"})
            response = model.generate_content(prompt)
            
            # --- FIX LỖI TYPE ERROR TẠI ĐÂY ---
            result_text = response.text.strip()
            
            # 1. Parse JSON
            data = json.loads(result_text)
            
            # 2. Nếu AI trả về List (vd: [{...}]), lấy phần tử đầu tiên
            if isinstance(data, list):
                if len(data) > 0: data = data[0]
                else: return None
            
            # 3. Đảm bảo nó là Dictionary
            if isinstance(data, dict):
                return data
                
        except Exception as e:
            print(f"Model {model_name} error: {e}")
            continue
            
    return None

# --- 5. GIAO DIỆN CHÍNH ---

with st.sidebar:
    st.header("⚙️ Cài đặt")
    api_key = get_api_key()
    if api_key:
        st.success("✅ Đã nạp API Key từ hệ thống")
    else:
        api_key = st.text_input("Nhập Gemini API Key", type="password")
    
    st.divider()
    # Nút Sync Manual
    if st.button("🔄 Force Sync Cloud"):
        t = load_tasks()
        ok, m = sync_to_gsheet(t)
        if ok: st.toast(m, icon="☁️")
        else: st.error(m)

st.title("🏭 MFG Copilot Mobile")

# FORM NHẬP LIỆU (MOBILE FRIENDLY)
with st.expander("➕ THÊM TASK MỚI", expanded=True):
    new_task = st.text_input("Nội dung công việc")
    c1, c2 = st.columns(2)
    with c1: d_date = st.date_input("Ngày", value=datetime.now())
    with c2: d_time = st.time_input("Giờ", value=time(17, 0))
    
    if st.button("🚀 Thêm Task", type="primary", use_container_width=True):
        if not api_key: 
            st.error("⚠️ Chưa có API Key!")
        elif not new_task: 
            st.warning("⚠️ Hãy nhập nội dung task.")
        else:
            with st.spinner("🤖 AI đang phân tích..."):
                dl = f"{d_date} {d_time.strftime('%H:%M')}"
                res = analyze_task_ai(api_key, new_task, dl)
                
                # Kiểm tra kỹ trước khi lưu để tránh TypeError
                if res and isinstance(res, dict):
                    tasks = load_tasks()
                    new_item = {
                        "id": len(tasks)+1, 
                        "status": "Pending", 
                        "created_at": str(datetime.now().date()), 
                        "deadline": dl, 
                        **res # Dòng này giờ đã an toàn
                    }
                    tasks.append(new_item)
                    save_tasks(tasks)
                    
                    # Auto sync
                    sync_to_gsheet(tasks)
                    
                    st.toast("Đã thêm thành công!", icon="✅")
                    st.rerun()
                else:
                    st.error("❌ AI không trả về kết quả hợp lệ. Vui lòng thử lại với mô tả rõ hơn.")

# DANH SÁCH TASK
st.divider()
view_mode = st.radio("Chế độ xem:", ["📱 Thẻ (Mobile)", "💻 Bảng (Desktop)"], horizontal=True)
tasks = load_tasks()
pending_tasks = [t for t in tasks if t.get('status') != 'Done']

if view_mode == "📱 Thẻ (Mobile)":
    st.caption(f"Task cần làm: {len(pending_tasks)}")
    for t in reversed(pending_tasks):
        b_color = "#ff4b4b" if t.get('priority') == 'High' else "#3373c4"
        
        with st.container():
            st.markdown(f"""
            <div style="background:white; padding:15px; border-radius:10px; border-left: 5px solid {b_color}; box-shadow: 0 1px 3px rgba(0,0,0,0.1); margin-bottom:10px;">
                <div style="font-weight:bold; font-size:1.1em;">{t.get('task_name', 'No Name')}</div>
                <div style="color:#666; font-size:0.85em; margin: 5px 0;">
                    ⏳ {t.get('deadline')} | 🔥 {t.get('priority')}
                </div>
                <div style="margin-top:5px; font-size:0.95em">{t.get('description', '')}</div>
            </div>
            """, unsafe_allow_html=True)
            
            with st.expander("✅ Checklist thực hiện"):
                subs = t.get('subtasks', [])
                if isinstance(subs, list):
                    for s in subs: st.markdown(f"- {s}")
                else: st.write(str(subs))
                
                if st.button("Hoàn thành", key=f"done_{t['id']}", use_container_width=True):
                    for origin in tasks:
                        if origin['id'] == t['id']: origin['status'] = 'Done'
                    save_tasks(tasks)
                    sync_to_gsheet(tasks)
                    st.rerun()
else:
    if tasks:
        df = pd.DataFrame(tasks)
        df['subtasks'] = df['subtasks'].apply(lambda x: "\n".join(x) if isinstance(x, list) else str(x))
        st.dataframe(df, use_container_width=True, height=500, hide_index=True)
