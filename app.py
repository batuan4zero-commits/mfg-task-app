import streamlit as st
import google.generativeai as genai
import pandas as pd
import json
import os
import gspread
from google.oauth2.service_account import Credentials # Thư viện mới ổn định hơn
from datetime import datetime, time

# --- 1. CẤU HÌNH & CSS ---
st.set_page_config(page_title="MFG Commander v7.0", page_icon="🏭", layout="wide")

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
    .time-badge {
        background-color: #e8f0fe;
        color: #1967d2;
        padding: 2px 8px;
        border-radius: 12px;
        font-size: 0.85em;
        font-weight: bold;
    }
    .expired-badge {
        background-color: #fce8e6;
        color: #c5221f;
        padding: 2px 8px;
        border-radius: 12px;
        font-size: 0.85em;
        font-weight: bold;
    }
</style>
""", unsafe_allow_html=True)

DB_FILE = "tasks_db.json"

# --- 2. XỬ LÝ KẾT NỐI (FIX LỖI GOOGLE SHEET) ---
def get_api_key():
    if "GEMINI_API_KEY" in st.secrets:
        return st.secrets["GEMINI_API_KEY"]
    return None

def connect_google_sheet():
    # Scope chuẩn cho Google Sheet
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    
    try:
        # Cách kết nối mới dùng google-auth (Ổn định trên Cloud)
        if "gcp_service_account" in st.secrets:
            # Tạo credentials từ secrets dictionary
            creds = Credentials.from_service_account_info(
                st.secrets["gcp_service_account"],
                scopes=scopes
            )
            client = gspread.authorize(creds)
            sheet = client.open("MFG_Task_Database").sheet1
            return sheet, "Success"
        else:
            return None, "⚠️ Chưa cấu hình Secrets trên Cloud."
    except Exception as e:
        return None, f"Lỗi kết nối: {str(e)}"

def sync_to_gsheet(tasks):
    sheet, msg = connect_google_sheet()
    if sheet:
        try:
            if not tasks: return True, "Trống"
            df = pd.DataFrame(tasks)
            
            # Xử lý Subtask (List Dict -> String) để hiển thị trên Excel cho gọn
            if 'subtasks' in df.columns:
                df['subtasks'] = df['subtasks'].apply(lambda x: json.dumps(x, ensure_ascii=False) if isinstance(x, list) else str(x))
            
            df = df.astype(str)
            sheet.clear()
            sheet.update([df.columns.values.tolist()] + df.values.tolist())
            return True, "✅ Đã đồng bộ Cloud!"
        except Exception as e:
            return False, str(e)
    return False, msg

# --- 3. DATABASE & LOGIC ---
def load_tasks():
    if not os.path.exists(DB_FILE): return []
    try:
        with open(DB_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            # MIGRATION: Chuyển đổi dữ liệu cũ (List String) sang mới (List Dict)
            for t in data:
                new_subs = []
                if "subtasks" in t and isinstance(t["subtasks"], list):
                    for item in t["subtasks"]:
                        if isinstance(item, str): # Nếu là kiểu cũ
                            new_subs.append({"name": item, "done": False})
                        else: # Nếu đã là kiểu mới
                            new_subs.append(item)
                t["subtasks"] = new_subs
            return data
    except: return []

def save_tasks(tasks):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(tasks, f, ensure_ascii=False, indent=2)

def calculate_time_left(deadline_str):
    try:
        deadline = datetime.strptime(deadline_str, "%Y-%m-%d %H:%M")
        now = datetime.now()
        
        if now > deadline:
            return "expired", f"Đã quá hạn"
        
        diff = deadline - now
        days = diff.days
        hours = diff.seconds // 3600
        minutes = (diff.seconds // 60) % 60
        
        if days > 0:
            return "valid", f"Còn {days} ngày {hours} giờ"
        else:
            return "valid", f"Còn {hours} giờ {minutes} phút"
    except:
        return "error", "Lỗi ngày tháng"

def analyze_task_ai(api_key, text, deadline):
    genai.configure(api_key=api_key)
    prompt = f"""
    Input: "{text}". Deadline: "{deadline}".
    Yêu cầu: Trả về JSON Object (Không List).
    JSON Schema: 
    {{ "task_name": "", "description": "Mô tả ngắn", "priority": "High/Medium/Low", "eisenhower": "Q1/Q2/Q3/Q4", "subtasks": ["Bước 1", "Bước 2", "Bước 3"] }}
    """
    
    # Thử model mới nhất, fallback về 1.5
    for model_name in ['gemini-2.0-flash-exp', 'gemini-1.5-flash']:
        try:
            model = genai.GenerativeModel(model_name, generation_config={"response_mime_type": "application/json"})
            response = model.generate_content(prompt)
            data = json.loads(response.text.strip())
            
            if isinstance(data, list): data = data[0] # Fix lỗi trả về List
            
            # CHUẨN HÓA SUBTASK NGAY TẠI ĐÂY
            # Biến ["Bước 1"] thành [{"name": "Bước 1", "done": False}]
            final_subtasks = []
            if "subtasks" in data and isinstance(data["subtasks"], list):
                for s in data["subtasks"]:
                    final_subtasks.append({"name": str(s), "done": False})
            data["subtasks"] = final_subtasks
            
            return data
        except: continue
    return None

# --- 4. GIAO DIỆN CHÍNH ---

with st.sidebar:
    st.header("⚙️ Cài đặt")
    api_key = get_api_key()
    if api_key: st.success("✅ Đã nạp API Key")
    else: api_key = st.text_input("Gemini API Key", type="password")
    
    st.divider()
    if st.button("🔄 Force Sync Cloud"):
        t = load_tasks()
        ok, m = sync_to_gsheet(t)
        if ok: st.toast(m, icon="☁️")
        else: st.error(m)

st.title("🏭 MFG Copilot Mobile v7")

# FORM ADD TASK
with st.expander("➕ THÊM TASK MỚI", expanded=True):
    new_task = st.text_input("Nội dung công việc")
    c1, c2 = st.columns(2)
    with c1: d_date = st.date_input("Ngày", value=datetime.now())
    with c2: d_time = st.time_input("Giờ", value=time(17, 0))
    
    if st.button("🚀 Thêm Task", type="primary", use_container_width=True):
        if not api_key: st.error("Thiếu Key")
        elif not new_task: st.warning("Nhập nội dung task")
        else:
            with st.spinner("AI đang xử lý..."):
                dl = f"{d_date} {d_time.strftime('%H:%M')}"
                res = analyze_task_ai(api_key, new_task, dl)
                
                if res and isinstance(res, dict):
                    tasks = load_tasks()
                    new_item = {
                        "id": len(tasks)+1, "status": "Pending", 
                        "created_at": str(datetime.now().date()), "deadline": dl, 
                        **res
                    }
                    tasks.append(new_item)
                    save_tasks(tasks)
                    sync_to_gsheet(tasks)
                    st.toast("Thêm thành công!", icon="✅")
                    st.rerun()

# VIEW TASKS
st.divider()
view_mode = st.radio("Chế độ:", ["📱 Mobile", "💻 Desktop"], horizontal=True)
tasks = load_tasks()
pending_tasks = [t for t in tasks if t.get('status') != 'Done']

if view_mode == "📱 Mobile":
    st.caption(f"Đang có {len(pending_tasks)} task cần làm")
    
    for t in reversed(pending_tasks):
        b_color = "#ff4b4b" if t.get('priority') == 'High' else "#3373c4"
        
        # Tính thời gian còn lại
        time_status, time_text = calculate_time_left(t.get('deadline'))
        badge_class = "expired-badge" if time_status == "expired" else "time-badge"
        
        with st.container():
            st.markdown(f"""
            <div style="background:white; padding:15px; border-radius:10px; border-left: 5px solid {b_color}; box-shadow: 0 1px 3px rgba(0,0,0,0.1); margin-bottom:10px;">
                <div style="display:flex; justify-content:space-between; align-items:center;">
                    <div style="font-weight:bold; font-size:1.1em;">{t.get('task_name')}</div>
                    <span class="{badge_class}">{time_text}</span>
                </div>
                <div style="color:#666; font-size:0.85em; margin: 5px 0;">
                    🔥 {t.get('priority')} | 📂 {t.get('eisenhower')}
                </div>
                <div style="margin-top:5px; font-size:0.95em">{t.get('description')}</div>
            </div>
            """, unsafe_allow_html=True)
            
            # CHECKLIST TƯƠNG TÁC
            with st.expander("✅ Checklist & Tiến độ"):
                # Subtask Logic
                subtasks = t.get('subtasks', [])
                updated_subtasks = []
                has_change = False
                
                completed_count = 0
                
                # Render checkbox cho từng subtask
                for i, sub in enumerate(subtasks):
                    # Đảm bảo sub là dict (đã xử lý ở hàm load_tasks)
                    is_done = st.checkbox(
                        sub['name'], 
                        value=sub['done'], 
                        key=f"chk_{t['id']}_{i}"
                    )
                    
                    if is_done: completed_count += 1
                    
                    # Nếu trạng thái thay đổi, đánh dấu để save
                    if is_done != sub['done']:
                        sub['done'] = is_done
                        has_change = True
                    
                    updated_subtasks.append(sub)
                
                # Hiển thị Progress Bar dựa trên checkbox
                if len(subtasks) > 0:
                    prog_percent = int((completed_count / len(subtasks)) * 100)
                    st.progress(prog_percent)
                    st.caption(f"Tiến độ: {prog_percent}%")
                
                # Nút Lưu Checkbox (Nếu có thay đổi)
                if has_change:
                    for origin in tasks:
                        if origin['id'] == t['id']:
                            origin['subtasks'] = updated_subtasks
                    save_tasks(tasks)
                    st.rerun() # Refresh để cập nhật
                
                # Nút Hoàn thành Task lớn
                if st.button("🎉 Hoàn thành Task này", key=f"fin_{t['id']}", use_container_width=True):
                    for origin in tasks:
                        if origin['id'] == t['id']: origin['status'] = 'Done'
                    save_tasks(tasks)
                    sync_to_gsheet(tasks)
                    st.rerun()

else:
    # Desktop View
    if tasks:
        df = pd.DataFrame(tasks)
        # Flatten subtasks for display
        df['subtasks'] = df['subtasks'].apply(lambda x: "\n".join([f"[{'x' if i['done'] else ' '}] {i['name']}" for i in x]) if isinstance(x, list) else str(x))
        st.dataframe(df, use_container_width=True, height=600, hide_index=True)
