import streamlit as st
import google.generativeai as genai
import pandas as pd
import json
import os
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime, time

# --- 1. CẤU HÌNH & CSS ---
st.set_page_config(page_title="MFG Commander v9.0 (Cloud)", page_icon="🏭", layout="wide")

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
        display: inline-block; padding: 2px 8px;
        border-radius: 4px; font-size: 0.8em; font-weight: bold; color: white;
    }
</style>
""", unsafe_allow_html=True)

# --- 2. KẾT NỐI GOOGLE SHEET (BỘ NHỚ VĨNH VIỄN) ---
def get_api_key():
    if "GEMINI_API_KEY" in st.secrets:
        return st.secrets["GEMINI_API_KEY"]
    return None

def connect_google_sheet():
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    try:
        if "gcp_service_account" in st.secrets:
            creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scopes)
            client = gspread.authorize(creds)
            sheet = client.open("MFG_Task_Database").sheet1
            return sheet
        else:
            st.error("⚠️ Chưa cấu hình Secrets trên Cloud!")
            return None
    except Exception as e:
        st.error(f"Lỗi kết nối GSheet: {str(e)}")
        return None

# --- 3. HÀM LOAD & SAVE TRỰC TIẾP TỪ CLOUD ---

def load_data_from_cloud():
    """Đọc dữ liệu từ Google Sheet mỗi khi mở app"""
    sheet = connect_google_sheet()
    if not sheet: return []
    
    try:
        # Lấy toàn bộ dữ liệu dạng List of Dictionaries
        data = sheet.get_all_records()
        
        # Xử lý checklist (Do trên sheet lưu dạng text, cần convert về list)
        for t in data:
            if "subtasks" in t and isinstance(t["subtasks"], str):
                try:
                    # Cố gắng parse JSON string về List
                    # Format trên sheet: "[{'name': 'A', 'done': False}]"
                    raw_sub = t["subtasks"].replace("'", '"').replace("Txrue", "true").replace("False", "false")
                    t["subtasks"] = json.loads(raw_sub)
                except:
                    # Nếu lỗi parse (do format cũ), chuyển thành list rỗng hoặc text đơn giản
                    t["subtasks"] = []
            elif "subtasks" not in t:
                t["subtasks"] = []
                
        return data
    except Exception as e:
        # Nếu sheet trắng trơn, trả về list rỗng
        return []

def save_data_to_cloud(tasks):
    """Lưu đè dữ liệu lên Google Sheet"""
    sheet = connect_google_sheet()
    if not sheet: return False
    
    try:
        if not tasks: 
            sheet.clear()
            return True
            
        df = pd.DataFrame(tasks)
        
        # Convert Subtasks (List) thành String để lưu được vào ô Excel
        if 'subtasks' in df.columns:
            df['subtasks'] = df['subtasks'].apply(lambda x: json.dumps(x, ensure_ascii=False) if isinstance(x, list) else str(x))
            
        df = df.astype(str) # Convert tất cả sang string để tránh lỗi
        
        sheet.clear() # Xóa cũ
        sheet.update([df.columns.values.tolist()] + df.values.tolist()) # Ghi mới
        return True
    except Exception as e:
        st.error(f"Lỗi lưu Cloud: {str(e)}")
        return False

# --- 4. AI LOGIC ---
def analyze_task_ai(api_key, text, deadline):
    genai.configure(api_key=api_key)
    prompt = f"""
    Input: "{text}", Deadline: "{deadline}".
    Yêu cầu: Trả về JSON Object (Không Markdown).
    Schema: {{ "task_name": "", "description": "", "priority": "High/Medium/Low", "eisenhower": "Q1/Q2/Q3/Q4", "subtasks": ["Bước 1", "Bước 2"] }}
    """
    for model_name in ['gemini-2.0-flash-exp', 'gemini-1.5-flash']:
        try:
            model = genai.GenerativeModel(model_name, generation_config={"response_mime_type": "application/json"})
            res = model.generate_content(prompt)
            data = json.loads(res.text.strip())
            if isinstance(data, list): data = data[0]
            
            # Chuẩn hóa checklist
            final_subs = [{"name": str(s), "done": False} for s in data.get("subtasks", [])]
            data["subtasks"] = final_subs
            return data
        except: continue
    return None

# --- 5. GIAO DIỆN CHÍNH ---

# Load dữ liệu ngay khi vào App
if "tasks" not in st.session_state:
    with st.spinner("☁️ Đang tải dữ liệu từ Google Sheet..."):
        st.session_state["tasks"] = load_data_from_cloud()

tasks = st.session_state["tasks"]

with st.sidebar:
    st.header("⚙️ Cấu hình")
    api_key = get_api_key()
    if api_key: st.success("✅ Hệ thống Online")
    else: api_key = st.text_input("API Key", type="password")
    
    if st.button("🔄 Làm mới dữ liệu"):
        st.session_state["tasks"] = load_data_from_cloud()
        st.rerun()

st.title("🏭 MFG Cloud Manager v9.0")

# TAB VIEW
tab1, tab2, tab3 = st.tabs(["📝 Danh sách", "🎯 Ma trận", "📊 Báo cáo"])

# --- TAB 1: DANH SÁCH ---
with tab1:
    with st.expander("➕ THÊM CÔNG VIỆC MỚI", expanded=True):
        col_in1, col_in2 = st.columns([3, 1])
        new_text = col_in1.text_input("Nội dung task")
        d_date = col_in2.date_input("Deadline", value=datetime.now())
        
        if st.button("🚀 Lưu lên Cloud", type="primary", use_container_width=True):
            if not new_text: st.warning("Chưa nhập nội dung!")
            elif not api_key: st.error("Thiếu API Key")
            else:
                with st.spinner("🤖 AI đang phân tích & Đồng bộ Cloud..."):
                    dl = f"{d_date} 17:00"
                    res = analyze_task_ai(api_key, new_text, dl)
                    if res:
                        new_item = {
                            "id": int(datetime.now().timestamp()),
                            "status": "Pending",
                            "created_at": str(datetime.now().date()),
                            "deadline": dl,
                            **res
                        }
                        tasks.append(new_item)
                        # LƯU NGAY LẬP TỨC
                        if save_data_to_cloud(tasks):
                            st.session_state["tasks"] = tasks # Cập nhật RAM
                            st.toast("Đã lưu an toàn!", icon="✅")
                            st.rerun()

    # HIỂN THỊ LIST
    pending_tasks = [t for t in tasks if t.get('status') != 'Done']
    st.caption(f"Đang có {len(pending_tasks)} task chưa xong")
    
    for t in reversed(pending_tasks):
        color = "#ff4b4b" if t.get('priority') == 'High' else "#3373c4"
        with st.container():
            st.markdown(f"""
            <div class="mobile-card" style="border-left: 5px solid {color};">
                <b>{t.get('task_name')}</b><br>
                <span style="color:gray; font-size:0.9em">⏳ {t.get('deadline')} | {t.get('eisenhower')}</span>
            </div>
            """, unsafe_allow_html=True)
            
            with st.expander("🔻 Chi tiết & Checklist"):
                # Checklist Logic
                subs = t.get('subtasks', [])
                has_change = False
                
                # Nút Xóa Task (Nằm trên cùng cho dễ bấm)
                if st.button("🗑️ Xóa Task này", key=f"del_{t['id']}"):
                    tasks = [x for x in tasks if x['id'] != t['id']]
                    if save_data_to_cloud(tasks):
                        st.session_state["tasks"] = tasks
                        st.rerun()
                
                # Render Checklist
                for i, s in enumerate(subs):
                    is_done = st.checkbox(s['name'], value=s.get('done', False), key=f"c_{t['id']}_{i}")
                    if is_done != s.get('done', False):
                        s['done'] = is_done
                        has_change = True
                
                # Nút Hoàn thành
                if st.button("🎉 Đã xong task này", key=f"fin_{t['id']}", use_container_width=True):
                    t['status'] = 'Done'
                    has_change = True

                # Nếu có thay đổi -> Lưu Cloud
                if has_change:
                    if save_data_to_cloud(tasks):
                        st.session_state["tasks"] = tasks
                        st.rerun()

# --- TAB 2: MA TRẬN ---
with tab2:
    col1, col2 = st.columns(2)
    def render_card(col, title, color, code):
        items = [t for t in pending_tasks if code in t.get('eisenhower', '')]
        with col:
            st.markdown(f"<b style='color:{color}'>{title} ({len(items)})</b>", unsafe_allow_html=True)
            for x in items: st.text(f"• {x.get('task_name')}")
            st.divider()

    render_card(col1, "DO FIRST (Gấp/Quan trọng)", "#ff4b4b", "Q1")
    render_card(col2, "SCHEDULE (Quan trọng)", "#ffa421", "Q2")
    render_card(col1, "DELEGATE (Gấp)", "#3373c4", "Q3")
    render_card(col2, "DELETE (Rác)", "#6c757d", "Q4")

# --- TAB 3: BÁO CÁO ---
with tab3:
    if tasks:
        df = pd.DataFrame(tasks)
        st.metric("Tổng Task", len(df))
        st.dataframe(df, use_container_width=True)
    else:
        st.info("Chưa có dữ liệu nào trên Cloud.")
