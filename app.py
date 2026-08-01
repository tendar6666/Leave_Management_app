import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
from datetime import datetime, timedelta
import uuid
import requests

NTFY_ADMIN_TOPIC = st.secrets.get("ntfy", {}).get("admin_topic")
NTFY_COADMIN_TOPIC = st.secrets.get("ntfy", {}).get("coadmin_topic")
NTFY_ACCOUNT_TOPIC = st.secrets.get("ntfy", {}).get("account_topic")

def send_ntfy_notification(topic, title, message):
    try:
        if topic:
            res = requests.post(
                f"https://ntfy.sh/{topic}",
                data=message.encode('utf-8'),
                headers={"Title": title.encode('utf-8')}
            )
            st.toast(f"Notification sent to {topic}! Status: {res.status_code}")
        else:
            st.error("NTFY topic is missing in st.secrets!")
    except Exception as e:
        st.error(f"NTFY Error: {e}")


import io
from fpdf import FPDF

# --- PAGE CONFIGURATION ---
st.set_page_config(page_title="Leave Management System",
                    page_icon="📅", layout="wide")

# --- INITIALIZE SESSION STATE ---
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
if "user_name" not in st.session_state:
    st.session_state.user_name = None
if "user_role" not in st.session_state:
    st.session_state.user_role = None

# --- DATABASE CONNECTION ---
conn = st.connection("gsheets", type=GSheetsConnection)


@st.cache_data(ttl=15)
def load_users_data():
    try:
        df = conn.read(worksheet="Users", usecols=[
                        "Name", "PIN", "Role", "Post", "JoiningDate"])
        df = df.dropna(subset=["Name", "PIN"])
        df["PIN"] = df["PIN"].astype(object)
        return df
    except Exception as e:
        st.error(f"Error connecting to database (Users): {e}")
        return None


@st.cache_data(ttl=15)
def load_staff_master():
    return conn.read(worksheet="Staff_Master", usecols=list(range(30)))


def inject_balance_formulas(df):
    df_copy = df.copy()
    formula_cols = ["Post", "JoiningDate", "Service Year", "Service Year Penalty", "Actual Service Year",
                    "Addition_UL", "Last_UL_Milestone",
                    "Balance_CL", "Balance_SL", "Balance_AL", "Balance_UL",
                    "Penalty_CL(UL Effect)", "Penalty_SL(UL Effect)", "Penalty_AL(UL Effect)"]

    for col in formula_cols:
        if col in df_copy.columns:
            df_copy[col] = df_copy[col].astype(object)

    for i in range(len(df_copy)):
        r = i + 2
        df_copy.at[df_copy.index[i],
                    "Post"] = f'=IFERROR(VLOOKUP(A{r}, Users!A:E, 4, FALSE), "")'
        df_copy.at[df_copy.index[i],
                    "JoiningDate"] = f'=IFERROR(IF(VLOOKUP(A{r}, Users!A:E, 5, FALSE)="", "", TEXT(VLOOKUP(A{r}, Users!A:E, 5, FALSE), "yyyy-mm-dd")), "")'

        df_copy.at[df_copy.index[i],
                    "Service Year"] = f'=IF(C{r}="", 0, TO_PURE_NUMBER((TODAY() - DATEVALUE(C{r}))/365.25))'
        df_copy.at[df_copy.index[i],
                    "Service Year Penalty"] = f"=AD{r} + AC{r} + Y{r} + AA{r}"
        df_copy.at[df_copy.index[i],
                    "Actual Service Year"] = f'=IF(C{r}="", 0, TO_PURE_NUMBER((TODAY() - (DATEVALUE(C{r}) + E{r}))/365.25))'

        df_copy.at[df_copy.index[i],
                    "Addition_UL"] = f"=IFS(AND(AB{r}=5, (W{r}+AA{r})<182.5), 182.5, AND(AB{r}=10, (W{r}+AA{r})<365), 182.5, AND(AB{r}=15, (W{r}+AA{r})<547.5), 182.5, AND(AB{r}>=20, (W{r}+AA{r})<730), 182.5, TRUE, 0)"
        df_copy.at[df_copy.index[i], "Last_UL_Milestone"] = f"=FLOOR(F{r}/5)*5"

        df_copy.at[df_copy.index[i],
                    "Penalty_CL(UL Effect)"] = f"=ROUND(((Y{r}+AC{r})/30)*0.75*2)/2"
        df_copy.at[df_copy.index[i],
                    "Penalty_SL(UL Effect)"] = f"=ROUND(((Y{r}+AC{r})/30)*1.25*2)/2"
        df_copy.at[df_copy.index[i],
                    "Penalty_AL(UL Effect)"] = f"=ROUND(((Y{r}+AC{r})/30)*2.5*2)/2"

        df_copy.at[df_copy.index[i], "Balance_CL"] = f"=G{r}+H{r}-I{r}-J{r}"
        df_copy.at[df_copy.index[i], "Balance_SL"] = f"=L{r}+M{r}-N{r}-O{r}"
        df_copy.at[df_copy.index[i],
                    "Balance_AL"] = f"=MIN(180, Q{r}+R{r}-S{r}-T{r}-U{r})"
        df_copy.at[df_copy.index[i], "Balance_UL"] = f"=W{r}+X{r}-Y{r}"
    return df_copy


@st.cache_data(ttl=15)
def load_leave_requests():
    try:
        df = conn.read(worksheet="LeaveRequests")
        # Prevent TypeError when assigning strings to newly created empty columns that pandas read as float64
        for col in ["SupportedBy", "ApprovedBy", "PunchedBy", "SelectedCoAdmin", "Department", "Status", "CoAdminAcknowledged", "AccountsPunched", "Reason", "StartHalf", "EndHalf", "ApplicationDate"]:
            if col in df.columns:
                df[col] = df[col].astype(object)
        return df
    except Exception as e:
        return pd.DataFrame(columns=['ID', 'Name', 'LeaveType', 'StartDate', 'EndDate', 'TotalDays', 'Department', 'SelectedCoAdmin', 'Status', 'CoAdminAcknowledged', 'SupportedBy', 'AccountsPunched', 'PunchedBy', 'ApprovedBy'])

# --- HELPER FUNCS ---


def is_unacknowledged(val):
    if pd.isna(val) or val == "" or str(val).strip().lower() in ["false", "no", "0", "nan", "pending"]:
        return True
    return False


def sanitize_text(text):
    if pd.isna(text):
        return ""
    # Return string directly as we now have a Unicode font
    return str(text)


def to_tibetan_numeral(text):
    if not isinstance(text, str):
        text = str(text)
    mapping = {
        '0': '༠', '1': '༡', '2': '༢', '3': '༣', '4': '༤',
        '5': '༥', '6': '༦', '7': '༧', '8': '༨', '9': '༩'
    }
    for k, v in mapping.items():
        text = text.replace(k, v)
    return text


def format_tibetan_date(date_str):
    if not date_str or str(date_str) in ["nan", "NaT"]:
        return ""
    date_str = str(date_str)
    if len(date_str) >= 10 and date_str[4] == '-':
        y, m, d = date_str[:4], date_str[5:7], date_str[8:10]
        return f"ཕྱི་ལོ་ {y} ཟླ་ {m} ཚེས་ {d}"
    return date_str


def generate_leave_pdf(row):
    try:
        pdf = FPDF()
        pdf.set_text_shaping(True)
        # Load the custom Tibetan font
        pdf.add_font("Monlam", style="", fname="Monlam_Uni_OuChan2.ttf")
        pdf.add_page()

        # Header (Size 16)
        pdf.set_font("Monlam", "", 16)
        pdf.cell(0, 10, "སྤྱི་ཁྱབ་རྩིས་ཞིབ་ལས་ཁང་།",
                new_x="LMARGIN", new_y="NEXT", align="C")
        pdf.cell(0, 10, "(དགོངས་ཞུ་འགེངས་ཤོག)",
                new_x="LMARGIN", new_y="NEXT", align="C")

        pdf.ln(10)

        # Body (Size 12)
        pdf.set_font("Monlam", "", 12)

        staff_df = load_staff_master()
        joining_date = ""
        post = ""
        if staff_df is not None and not staff_df.empty:
            user_data = staff_df[staff_df["Name"] == row.get("Name", "")]
            if not user_data.empty:
                joining_date = str(user_data.iloc[0].get("JoiningDate", ""))
                post = str(user_data.iloc[0].get(
                    "Post", "") if "Post" in user_data.columns else "")
                if post == "nan":
                    post = ""
                if joining_date == "nan" or joining_date == "NaT":
                    joining_date = ""

        pdf.cell(95, 10, f"༡། མཚན། {row.get('Name', '')}")
        pdf.cell(
            95, 10, f"༢། ལས་བྱེད་དུ་བསྐོ་གཞག་ཞུས་ཚེས། {to_tibetan_numeral(format_tibetan_date(joining_date))}", new_x="LMARGIN", new_y="NEXT")

        pdf.cell(95, 10, f"༣། གནས་རིམ།/གོ་གནས། {to_tibetan_numeral(post)}")
        pdf.cell(
            95, 10, f"༤། ལས་ཁུངས་དང་སྡེ་ཚན། {row.get('Department', '')}", new_x="LMARGIN", new_y="NEXT")

        pdf.ln(2)
        start = str(row.get('StartDate', ''))
        end = str(row.get('EndDate', ''))

        def get_tibetan_half(half_val):
            if not half_val or pd.isna(half_val):
                return ""
            if "Morning" in str(half_val):
                return " (ཞོགས་པ།)"
            if "Evening" in str(half_val):
                return " (ཉིན་རྒྱབ།)"
            if "Full Day" in str(half_val):
                return " (ཉིན་ཆ་ཚང་།)"
            return ""

        start_tib = get_tibetan_half(row.get('StartHalf', ''))
        end_tib = get_tibetan_half(row.get('EndHalf', ''))

        if len(start) >= 10 and len(end) >= 10:
            date_str = f"༥། ཕྱི་ལོ་ {start[:4]} ཟླ་ {start[5:7]} ཚེས་ {start[8:10]}{start_tib} ནས་ ཕྱི་ལོ་ {end[:4]} ཟླ་ {end[5:7]} ཚེས་ {end[8:10]}{end_tib} བར།"
        else:
            date_str = f"༥། ཕྱི་ལོ་ {start}{start_tib} ནས་ {end}{end_tib} བར།"
        pdf.cell(0, 10, to_tibetan_numeral(date_str),
                new_x="LMARGIN", new_y="NEXT")

        pdf.cell(
            0, 10, f"གུང་གསེང་ཉིན་གྲངས་ཇི་ཞུས། {to_tibetan_numeral(row.get('TotalDays', ''))}", new_x="LMARGIN", new_y="NEXT")

        l_type = str(row.get('LeaveType', '')).upper()

        pdf.set_font("Monlam", "", 10)
        pdf.write(6, "(གུང་གསེང་གི་ངོ་བོ། ")

        pdf.set_font("Monlam", "U" if "AL" in l_type else "", 10)
        pdf.write(6, "ཐོབ་སེང་། ")

        pdf.set_font("Monlam", "U" if "CL" in l_type else "", 10)
        pdf.write(6, "ངེས་མེད། ")

        pdf.set_font("Monlam", "U" if "SL" in l_type else "", 10)
        pdf.write(6, "ནད་དགོངས། ")

        pdf.set_font("Monlam", "U" if "ML" in l_type else "", 10)
        pdf.write(6, "ཕྲུ་གུ་བཙས་སྐབས། ")

        pdf.set_font("Monlam", "U" if "PL" in l_type else "", 10)
        pdf.write(6, "བཟའ་ཟླར་ཕྲུ་གུ་བཙས་སྐབས་རོགས་སྐྱོར། ")

        pdf.set_font("Monlam", "U" if "UL" in l_type else "", 10)
        pdf.write(6, "དམིགས་བསལ་ཕོགས་མེད་གུང་གསེང་། ")

        reason = row.get('Reason', '')
        if "OTHER" in l_type and reason:
            other_text = f"གཞན་ ({reason}) "
        else:
            other_text = "གཞན་ (.......................) "

        pdf.set_font("Monlam", "U" if "OTHER" in l_type else "", 10)
        pdf.write(6, other_text)

        pdf.set_font("Monlam", "", 10)
        pdf.write(6, "བཅས་གང་ཡིན་ལ་འགྲིག་རྟགས་རྒྱག་དགོས།)")
        pdf.ln(8)

        pdf.set_font("Monlam", "", 12)
        pdf.cell(0, 10, "༦། གུང་གསེང་ལྷག་བསྡད་གནས་སྟངས་གཤམ་གསལ།",
                new_x="LMARGIN", new_y="NEXT")

        bal = calculate_balances(row.get('Name', ''))

        pdf.cell(95, 10, f"ཀ། ངེས་མེད། {to_tibetan_numeral(bal['CL'])}")
        pdf.cell(
            95, 10, f"ཁ། ཐོབ་སེང་། {to_tibetan_numeral(bal['AL'])}", new_x="LMARGIN", new_y="NEXT")

        pdf.cell(95, 10, f"ག། ནད་དགོངས། {to_tibetan_numeral(bal['SL'])}")
        pdf.cell(
            95, 10, f"ང། དམིགས་བསལ་ཕོགས་མེད། {to_tibetan_numeral(bal['UL'])}", new_x="LMARGIN", new_y="NEXT")

        pdf.cell(
            0, 10, f"ཅ། གཞན། {to_tibetan_numeral(row.get('Reason', ''))}", new_x="LMARGIN", new_y="NEXT")

        app_date = str(row.get('ApplicationDate', ''))
        if app_date and app_date != "nan":
            pdf.cell(
                0, 10, f"༧། སྙན་ཞུ་ཕུལ་བའི་ཚེས། {to_tibetan_numeral(format_tibetan_date(app_date))}", new_x="LMARGIN", new_y="NEXT")

        pdf.ln(10)

        y = pdf.get_y()
        pdf.line(20, y, 95, y)
        pdf.line(115, y, 190, y)

        pdf.set_xy(20, y - 8)
        pdf.cell(75, 10, f"{row.get('Name', '')}", align="C")
        pdf.set_xy(20, y + 2)
        pdf.multi_cell(
            75, 6, "དགོངས་སྙན་འབུལ་མཁན་དོ་བདག་ལས་བྱེད་ཀྱི་ས་རྟགས།", align="C")

        pdf.set_xy(115, y - 8)
        punched_by = str(row.get('PunchedBy', '')).strip()
        if punched_by and punched_by != "nan":
            pdf.cell(75, 10, punched_by, align="C")
        pdf.set_xy(115, y + 2)
        pdf.multi_cell(75, 6, "རྩིས་པས་ཞིབ་འཇུག་ཟིན་པའི་དག་མཆན།", align="C")

        pdf.ln(20)
        y = pdf.get_y()
        pdf.line(20, y, 95, y)
        pdf.line(115, y, 190, y)

        pdf.set_xy(20, y - 8)
        supported_by = str(row.get('SupportedBy', '')).strip()
        if supported_by and supported_by != "nan":
            pdf.cell(75, 10, supported_by, align="C")
        pdf.set_xy(20, y + 2)
        pdf.multi_cell(
            75, 6, "བཀའ་འཁྲོལ་བརྒྱབ་གཉེར།\n(འབྲེལ་ཡོད་ཟུང་དྲུང་།)", align="C")

        pdf.set_xy(115, y - 8)
        approved_by = str(row.get('ApprovedBy', '')).strip()
        if approved_by and approved_by != "nan":
            pdf.cell(75, 10, approved_by, align="C")
        pdf.set_xy(115, y + 2)
        pdf.multi_cell(
            75, 6, "བཀའ་འཁྲོལ་ཆོག་མཆན།\nའགན་འཛིན།/དྲུང་ཆེ།", align="C")

        return bytes(pdf.output())
    except Exception as e:
        import streamlit as st
        st.error(f"Failed to generate PDF: {e}")
        return b""


def preview_pdf(pdf_bytes):
    from streamlit_pdf_viewer import pdf_viewer
    pdf_viewer(input=pdf_bytes, width=700)


@st.dialog("📄 PDF Preview", width="large")
def open_pdf_dialog(pdf_bytes, filename="Leave.pdf"):
    preview_pdf(pdf_bytes)
    st.download_button("⬇️ Download PDF", data=pdf_bytes,
                        file_name=filename, mime="application/pdf")

# --- MATH ENGINE ---


def calculate_balances(user_name):
    staff_df = load_staff_master()
    if staff_df is None or staff_df.empty:
        return {"CL": 0.0, "SL": 0.0, "AL": 0.0, "UL": 0.0}

    user_record = staff_df[staff_df["Name"] == user_name]
    if user_record.empty:
        return {"CL": 0.0, "SL": 0.0, "AL": 0.0, "UL": 0.0}

    user_data = user_record.iloc[0]

    def safe_float(val):
        if pd.isnull(val):
            return 0.0
        val_str = str(val).strip()
        if val_str == "":
            return 0.0
        try:
            return float(val)
        except:
            return 0.0

    return {
        "CL": safe_float(user_data.get("Balance_CL", 0)),
        "SL": safe_float(user_data.get("Balance_SL", 0)),
        "AL": safe_float(user_data.get("Balance_AL", 0)),
        "UL": safe_float(user_data.get("Balance_UL", 0)),
        "JoiningDate": user_data.get("JoiningDate"),
        "Service_Year_Penalty": safe_float(user_data.get("Service Year Penalty", 0)),
        "Actual_Service_Year": safe_float(user_data.get("Actual Service Year", 0))
    }

# --- AUTHENTICATION & LOGIN UI ---


def login_screen():
    st.title("Login")
    st.markdown("Please login to access the Leave Management System.")

    users_df = load_users_data()

    if users_df is not None and not users_df.empty:
        names = users_df["Name"].tolist()

        with st.form("login_form"):
            selected_name = st.selectbox("Select your Name", options=names)
            entered_pin = st.text_input(
                "Enter 4-digit PIN", type="password", max_chars=4)
            submit_button = st.form_submit_button("Login")

            if submit_button:
                user_record = users_df[users_df["Name"]
                                        == selected_name].iloc[0]
                stored_pin = str(user_record["PIN"]).split('.')[0].zfill(4)

                if str(entered_pin) == stored_pin:
                    st.session_state.logged_in = True
                    st.session_state.user_name = selected_name
                    st.session_state.user_role = user_record["Role"]
                    st.success("Login successful!")
                    st.rerun()
                else:
                    st.error("Incorrect PIN. Please try again.")
    else:
        st.warning(
            "No users found in the database or database connection failed.")


# --- DASHBOARDS ---
def employee_dashboard(hide_title=False):
    if not hide_title:
        st.title("Employee Dashboard")

    balances = calculate_balances(st.session_state.user_name)
    st.subheader("Your Leave Balances")

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Casual Leave (CL)", balances["CL"])
    col2.metric("Sick Leave (SL)", balances["SL"])
    col3.metric("Annual Leave (AL)", balances["AL"])
    col4.metric("Unpaid Leave (UL)", balances["UL"])

    st.divider()

    # Live Actual Service Year Calculation
    st.subheader("Your Leave Profile")
    try:
        actual_service_year = balances.get("Actual_Service_Year", 0.0)

        if actual_service_year < 0:
            st.info("Service hasn't started yet based on penalties.")
        else:
            total_service_days = actual_service_year * 365.25
            years = int(total_service_days // 365.25)
            remaining_days = total_service_days - (years * 365.25)
            months = int(remaining_days // 30.41666667)
            days = int(remaining_days - (months * 30.41666667))

            st.metric("Actual Service Tenure",
                        f"{years} Years, {months} Months, {days} Days")

            penalty_days = balances.get("Service_Year_Penalty", 0)
            joining_date = balances.get("JoiningDate", "N/A")
            st.caption(
                f"Joining Date: {joining_date} | Service Penalties Applied: {penalty_days} days")
    except Exception as e:
        st.write("Service Year: N/A")

    st.divider()

    co_admins = []
    users_df = load_users_data()
    if users_df is not None and not users_df.empty:
        co_admins = users_df[users_df["Role"] == "Co-Admin"]["Name"].tolist()

    st.subheader("Submit a Request")

    action = st.radio("Select Action:", [
                        "Request Leave", "Leave Reversal / Return Early"], horizontal=True)
    is_reversal = (action == "Leave Reversal / Return Early")

    if is_reversal:
        st.info("💡 **Return Early:** Use this to restore days to your leave balance if you returned to work earlier than originally approved. The days you enter below will be added back to your balance.")

    leave_options = {
        "CL": "CL (Casual Leave)",
        "SL": "SL (Sick Leave)",
        "AL": "AL (Annual Leave)",
        "UL": "UL (Unpaid Leave)",
        "ML": "ML (Maternity Leave)",
        "PL": "PL (Paternity Leave)",
        "Other": "Other"
    }
    leave_type_selection = st.selectbox(
        "Leave Type", list(leave_options.values()))
    leave_type = [k for k, v in leave_options.items() if v ==
                leave_type_selection][0]

    reason = ""
    effects_service_year = "No"
    if leave_type == "Other":
        reason = st.text_input("Specify Leave Reason/Type")
        if st.checkbox("Does this leave affect your service year? (Delays tenure)"):
            effects_service_year = "Yes"
            st.warning("⚠️ Warning: By checking this box (e.g. for Education Leave), your total Service Year and milestones will be delayed by the exact number of days you take.")

    department = st.text_input("Department (ལས་ཁུངས་དང་སྡེ་ཚན།)")
    selected_coadmin = st.selectbox(
        "Select Co-Admin for Support", ["None"] + co_admins)

    application_date = st.date_input("Application Date", datetime.today())

    col_start, col_end = st.columns(2)
    start_date = col_start.date_input("Start Date")
    start_half = col_start.radio("Start Time", [
                                "Full Day ཉིན་ཆ་ཚང་།", "Morning ཞོགས་པ།", "Evening ཉིན་རྒྱབ།"], index=0, horizontal=True)
    end_date = col_end.date_input("End Date")
    end_half = col_end.radio("End Time", [
                            "Full Day ཉིན་ཆ་ཚང་།", "Morning ཞོགས་པ།", "Evening ཉིན་རྒྱབ།"], index=0, horizontal=True)

    base_days = (end_date - start_date).days + 1
    if base_days < 1:
        base_days = 1
    max_allowed = float(base_days)
    min_allowed = max(0.5, float(base_days - 1.0))

    total_days = st.number_input("Total Days (to request or restore)",
                                min_value=min_allowed, max_value=max_allowed, value=max_allowed, step=0.5)
    final_days = -total_days if is_reversal else total_days

    st.write("---")
    col_sub, col_prev = st.columns(2)

    preview_row = {
        "Name": st.session_state.user_name,
        "LeaveType": f"Return-{leave_type}" if is_reversal else leave_type,
        "Reason": reason,
        "EffectsServiceYear": effects_service_year,
        "ApplicationDate": application_date.strftime("%Y-%m-%d"),
        "StartDate": start_date.strftime("%Y-%m-%d"),
        "StartHalf": start_half,
        "EndDate": end_date.strftime("%Y-%m-%d"),
        "EndHalf": end_half,
        "TotalDays": final_days,
        "Department": department,
        "SelectedCoAdmin": selected_coadmin,
        "SupportedBy": "",
        "ApprovedBy": "",
        "PunchedBy": ""
    }

    preview_pdf_bytes = generate_leave_pdf(preview_row)
    if col_prev.button("👁️ Preview PDF Form"):
        open_pdf_dialog(preview_pdf_bytes, "Preview.pdf")

    if col_sub.button("Submit Reversal" if is_reversal else "Submit Request", type="primary"):
        if total_days <= 0:
            st.error("Total days must be greater than 0.")
        elif start_date > end_date:
            st.error("End Date must be after or equal to Start Date.")
        elif start_date != end_date and total_days < 1:
            st.error(
                "Total days must be at least 1 when your leave spans multiple days.")
        else:
            try:
                df_requests = load_leave_requests()
                new_request = pd.DataFrame([{
                    "ID": str(uuid.uuid4())[:8].upper(),
                    "Name": st.session_state.user_name,
                    "LeaveType": f"Return-{leave_type}" if is_reversal else leave_type,
                    "Reason": reason,
                    "EffectsServiceYear": effects_service_year,
                    "ApplicationDate": application_date.strftime("%Y-%m-%d"),
                    "StartDate": start_date.strftime("%Y-%m-%d"),
                    "StartHalf": start_half,
                    "EndDate": end_date.strftime("%Y-%m-%d"),
                    "EndHalf": end_half,
                    "TotalDays": final_days,
                    "Department": department,
                    "SelectedCoAdmin": selected_coadmin,
                    "Status": "Pending",
                    "CoAdminAcknowledged": "No",
                    "SupportedBy": "",
                    "AccountsPunched": "No",
                    "PunchedBy": "",
                    "ApprovedBy": ""
                }])
                updated_df = pd.concat(
                    [df_requests, new_request], ignore_index=True)
                conn.update(worksheet="LeaveRequests", data=updated_df)
                st.cache_data.clear()
                st.success("Request submitted successfully!")
                send_ntfy_notification(
                    NTFY_ADMIN_TOPIC, 
                    "New Leave Request 🚨", 
                    f"{st.session_state.user_name} requested {total_days} day(s) of {leave_type}. Pending approval!"
                )
                if selected_coadmin and selected_coadmin != "None":
                    send_ntfy_notification(
                        NTFY_COADMIN_TOPIC,
                        "Leave Support Requested 🤝",
                        f"{st.session_state.user_name} requested {total_days} day(s) of {leave_type} and selected {selected_coadmin} as Co-Admin."
                    )
                send_ntfy_notification(
                    NTFY_ACCOUNT_TOPIC,
                    "New Leave Request ℹ️",
                    f"{st.session_state.user_name} requested {total_days} day(s) of {leave_type}. (FYI - Pending Approval)"
                )
                st.rerun()
            except Exception as e:
                st.error(f"Failed to submit request: {e}")

    st.divider()

    st.subheader("Your Past Requests")
    df_requests = load_leave_requests()
    if not df_requests.empty and "Name" in df_requests.columns:
        user_requests = df_requests[df_requests["Name"]
                                    == st.session_state.user_name]
        if not user_requests.empty:
            pending = user_requests[user_requests["Status"] == "Pending"]
            others = user_requests[user_requests["Status"] != "Pending"]

            if not pending.empty:
                st.markdown("**⏳ Pending Requests (Can be deleted)**")
                for idx, row in pending.iterrows():
                    col1, col2, col3 = st.columns([4, 1, 1])
                    col1.write(
                        f"**{row['LeaveType']}** for {row['TotalDays']} days ({row['StartDate']} to {row['EndDate']})")
                    
                    pdf_bytes = generate_leave_pdf(row)
                    if col2.button("📄 Preview", key=f"prev_emp_pend_{row['ID']}"):
                        open_pdf_dialog(pdf_bytes, f"{row['Name']}_Leave.pdf")
                        
                    if col3.button("🗑️ Delete", key=f"del_{row['ID']}"):
                        df_requests = df_requests.drop(idx)
                        conn.update(worksheet="LeaveRequests",
                                    data=df_requests)
                        st.cache_data.clear()
                        send_ntfy_notification(
                            NTFY_ADMIN_TOPIC,
                            "Leave Supported 🤝",
                            f"Co-Admin {st.session_state.user_name} supported {row['TotalDays']} day(s) of leave for {row['Name']}."
                        )
                        send_ntfy_notification(
                            NTFY_ACCOUNT_TOPIC,
                            "Leave Supported ℹ️",
                            f"Co-Admin {st.session_state.user_name} supported {row['TotalDays']} day(s) of leave for {row['Name']}. (FYI - Awaiting Admin Approval)"
                        )
                        st.rerun()

            if not others.empty:
                st.markdown("**✅ Processed Requests**")
                for idx, row in others.iterrows():
                    col1, col2 = st.columns([5, 1])
                    col1.write(
                        f"**{row['LeaveType']}** for {row['TotalDays']} days ({row['StartDate']} to {row['EndDate']}) - Status: {row['Status']}")
                    if row['Status'] == "Approved":
                        pdf_bytes = generate_leave_pdf(row)
                        if col2.button("📄 Preview PDF", key=f"prev_emp_{row['ID']}"):
                            open_pdf_dialog(
                                pdf_bytes, f"{row['Name']}_{row['StartDate']}_Leave.pdf")
        else:
            st.info("You have no past leave requests.")
    else:
        st.info("No leave requests found in the database.")


def leave_accounting_engine():
    st.divider()
    st.header("⚙️ Leave Accounting Engine")

    tab1, tab2, tab3, tab4, tab5 = st.tabs(
        ["FY Rollover", "AL Encashment", "Add User", "Leave Statement", "Factory Reset"])

    staff_df = load_staff_master()

    with tab1:
        def s_float(val):
            if pd.isnull(val):
                return 0.0
            val_str = str(val).strip()
            if val_str == "":
                return 0.0
            try:
                return float(val)
            except:
                return 0.0

        st.subheader("Process Financial Year Rollover")
        st.warning("⚠️ **Warning: FY Rollover will carry forward AL/UL balances, set Opening CL/SL to 0, add standard allowances (AL 30, SL 15, CL 9), and factor in UL delays/penalties.**")

        archive_name = st.text_input(
            "Name of ending Financial Year (e.g. FY2025-2026) for Archive", "FY2025-2026")

        if st.button("Calculate & Apply FY Rollover", type="primary"):
            if staff_df is not None and not staff_df.empty:
                try:
                    for idx, row in staff_df.iterrows():
                        curr_al = s_float(row.get("Balance_AL", 0))
                        curr_ul = s_float(row.get("Balance_UL", 0))

                        staff_df.at[idx, "Opening_AL"] = min(180.0, curr_al)
                        staff_df.at[idx, "Opening_UL"] = curr_ul
                        staff_df.at[idx, "Opening_CL"] = 0.0
                        staff_df.at[idx, "Opening_SL"] = 0.0

                        staff_df.at[idx, "Addition_AL"] = 30.0
                        staff_df.at[idx, "Addition_SL"] = 15.0
                        staff_df.at[idx, "Addition_CL"] = 9.0

                        staff_df.at[idx, "Used_AL"] = 0.0
                        staff_df.at[idx, "Used_SL"] = 0.0
                        staff_df.at[idx, "Used_CL"] = 0.0
                        staff_df.at[idx, "Used_UL"] = 0.0

                        used_ul_this_year = s_float(row.get("Used_UL", 0))

                        cum_ul = s_float(
                            row.get("Cumulative_UL", 0)) if "Cumulative_UL" in staff_df.columns else 0
                        staff_df.at[idx, "Cumulative_UL"] = cum_ul + \
                            used_ul_this_year
                        curr_eff = s_float(row.get("Current Year Leave affecting Service Year", 0)
                                            ) if "Current Year Leave affecting Service Year" in staff_df.columns else 0
                        cum_eff = s_float(row.get("Cummulative leave effecting Service year.(Education Leave & Etc).", 0)
                                        ) if "Cummulative leave effecting Service year.(Education Leave & Etc)." in staff_df.columns else 0
                        staff_df.at[idx,
                                    "Cummulative leave effecting Service year.(Education Leave & Etc)."] = cum_eff + curr_eff

                        if "Current Year Leave affecting Service Year" in staff_df.columns:
                            staff_df.at[idx,
                                        "Current Year Leave affecting Service Year"] = 0.0

                        # Recalculate exactly to prevent double counting
                        effect_days = s_float(
                            staff_df.at[idx, "Cummulative leave effecting Service year.(Education Leave & Etc)."])
                        effect_days_curr = 0.0  # Just rolled over
                        ul_used = 0.0  # It was just rolled over to Cumulative_UL, so used is 0
                        ul_cum = s_float(staff_df.at[idx, "Cumulative_UL"])

                        service_penalty = effect_days + effect_days_curr + ul_used + ul_cum
                        staff_df.at[idx,
                                    "Service Year Penalty"] = service_penalty

                        ul_addition = 0.0

                        if "Actual Service Year" not in staff_df.columns:
                            staff_df["Actual Service Year"] = 0.0
                        if "Service Year" not in staff_df.columns:
                            staff_df["Service Year"] = 0.0
                        staff_df["Actual Service Year"] = staff_df["Actual Service Year"].astype(
                            float)
                        staff_df["Service Year"] = staff_df["Service Year"].astype(
                            float)

                        try:
                            if pd.isnull(row.get("JoiningDate")) or str(row.get("JoiningDate")).strip() == "":
                                continue

                            joining_date = pd.to_datetime(row["JoiningDate"])
                            calendar_service_years = (
                                datetime.now() - joining_date).days / 365.25
                            staff_df.loc[idx, "Service Year"] = round(
                                calendar_service_years, 2)

                            if service_penalty == 0:
                                tenure_years = calendar_service_years
                            else:
                                true_service_start = joining_date + \
                                    timedelta(days=service_penalty)
                                tenure_years = (
                                    datetime.now() - true_service_start).days / 365.25
                            staff_df.loc[idx, "Actual Service Year"] = round(
                                tenure_years, 2)

                            last_ms = s_float(row.get(
                                "Last_UL_Milestone", 0)) if "Last_UL_Milestone" in staff_df.columns else 0

                            if tenure_years >= 20 and last_ms < 20:
                                ul_addition = 182.5
                                staff_df.at[idx, "Last_UL_Milestone"] = 20
                            elif tenure_years >= 15 and last_ms < 15:
                                ul_addition = 182.5
                                staff_df.at[idx, "Last_UL_Milestone"] = 15
                            elif tenure_years >= 10 and last_ms < 10:
                                ul_addition = 182.5
                                staff_df.at[idx, "Last_UL_Milestone"] = 10
                            elif tenure_years >= 5 and last_ms < 5:
                                ul_addition = 182.5
                                staff_df.at[idx, "Last_UL_Milestone"] = 5
                        except:
                            pass

                        staff_df.at[idx, "Addition_UL"] = ul_addition

                    fixed_cols = ["Name", "Post", "JoiningDate", "Service Year",
                                "Service Year Penalty", "Actual Service Year"]
                    cl_cols = ["Opening_CL", "Addition_CL",
                                "Penalty_CL(UL Effect)", "Used_CL", "Balance_CL"]
                    sl_cols = ["Opening_SL", "Addition_SL",
                                "Penalty_SL(UL Effect)", "Used_SL", "Balance_SL"]
                    al_cols = ["Opening_AL", "Addition_AL",
                                "Penalty_AL(UL Effect)", "Used_AL", "Encashed_AL", "Balance_AL"]
                    ul_cols = ["Opening_UL", "Addition_UL", "Used_UL", "Balance_UL", "Cumulative_UL", "Last_UL_Milestone",
                                "Current Year Leave affecting Service Year", "Cummulative leave effecting Service year.(Education Leave & Etc)."]

                    all_ordered_cols = [c for c in fixed_cols + cl_cols +
                                        sl_cols + al_cols + ul_cols if c in staff_df.columns]
                    other_cols = [
                        c for c in staff_df.columns if c not in all_ordered_cols]
                    staff_df = staff_df[all_ordered_cols + other_cols]

                    conn.update(worksheet="Staff_Master",
                                data=inject_balance_formulas(staff_df))

                    # --- ARCHIVING LOGIC ---
                    try:
                        df_req = load_leave_requests()
                        if df_req is not None and not df_req.empty:
                            archive_sheet = f"LeaveRequests_Archive_{archive_name.replace('/', '_')}"

                            # Create worksheet if it doesn't exist
                            try:
                                spread = conn.client._open_spreadsheet(
                                    spreadsheet=None, folder_id=None)
                                try:
                                    spread.worksheet(archive_sheet)
                                except Exception:
                                    spread.add_worksheet(
                                        title=archive_sheet, rows="1000", cols="20")
                            except Exception as e:
                                st.warning(
                                    f"Could not check/create worksheet structure, attempting direct update. Error: {e}")

                            conn.update(worksheet=archive_sheet, data=df_req)

                            # Wipe main requests sheet
                            empty_req = pd.DataFrame(columns=df_req.columns)
                            conn.update(worksheet="LeaveRequests",
                                        data=empty_req)
                    except Exception as archive_e:
                        st.error(f"Archiving failed: {archive_e}")

                    st.cache_data.clear()
                    st.success(
                        f"FY Rollover Successful! All data archived to {archive_sheet}.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error during rollover: {e}")

    with tab2:
        st.subheader("AL Encashment")
        if staff_df is not None and not staff_df.empty:
            encash_user = st.selectbox(
                "Select Employee", staff_df["Name"].tolist(), key="encash_user")
            encash_days = st.number_input(
                "Days to Encash", min_value=0.5, step=0.5)
            if st.button("Process Encashment"):
                idx = staff_df[staff_df["Name"] == encash_user].index[0]
                curr_al = float(staff_df.at[idx, "Balance_AL"]) if pd.notnull(
                    staff_df.at[idx, "Balance_AL"]) else 0

                if encash_days > curr_al:
                    st.error(
                        "Cannot encash more days than the current AL balance.")
                else:
                    curr_encashed = float(staff_df.at[idx, "Encashed_AL"]) if "Encashed_AL" in staff_df.columns and pd.notnull(
                        staff_df.at[idx, "Encashed_AL"]) else 0
                    staff_df.at[idx,
                                "Encashed_AL"] = curr_encashed + encash_days

                    conn.update(worksheet="Staff_Master",
                                data=inject_balance_formulas(staff_df))
                    st.cache_data.clear()
                    st.success(
                        f"Successfully encashed {encash_days} AL days for {encash_user}.")
                    st.rerun()

    with tab3:
        st.subheader("Add New User")
        with st.form("add_user_form"):
            new_name = st.text_input(
                "Full Name (Type in Tibetan Font to show it in Leave Form that is in Tibetan)")
            new_post = st.text_input(
                "Post (Type in Tibetan Font to show it in Leave Form that is in Tibetan)")
            new_join = st.date_input("Joining Date")
            new_pin = st.text_input(
                "4-Digit PIN", type="password", max_chars=4)
            new_role = st.selectbox(
                "Role", ["Employee", "Admin", "Co-Admin", "Accounts"])

            if st.form_submit_button("Add User"):
                st.cache_data.clear()  # Force fresh read so manual Google Sheet edits aren't overwritten
                if len(new_pin) != 4 or not new_pin.isdigit():
                    st.error("PIN must be 4 digits.")
                else:
                    users_df = load_users_data()
                    if new_name in users_df["Name"].values:
                        st.error("User already exists!")
                    else:
                        # Prorate calculation
                        fy_end = datetime(
                            new_join.year if new_join.month < 4 else new_join.year + 1, 3, 31).date()
                        days_worked = max(0, (fy_end - new_join).days + 1)
                        prop = days_worked / 365.25

                        import math
                        pro_al = math.ceil((30 * prop) * 2) / 2.0
                        pro_sl = math.ceil((15 * prop) * 2) / 2.0
                        pro_cl = math.ceil((9 * prop) * 2) / 2.0

                        new_staff_row = pd.DataFrame([{
                            "Name": new_name, "Post": new_post, "JoiningDate": new_join.strftime("%Y-%m-%d"),
                            "Opening_CL": 0, "Addition_CL": pro_cl, "Used_CL": 0, "Balance_CL": pro_cl,
                            "Opening_SL": 0, "Addition_SL": pro_sl, "Used_SL": 0, "Balance_SL": pro_sl,
                            "Opening_AL": 0, "Addition_AL": pro_al, "Used_AL": 0, "Balance_AL": pro_al,
                            "Opening_UL": 0, "Addition_UL": 0, "Used_UL": 0, "Balance_UL": 0,
                            "Encashed_AL": 0, "Cumulative_UL": 0, "Last_UL_Milestone": 0, "Current Year Leave affecting Service Year": 0, "Cummulative leave effecting Service year.(Education Leave & Etc).": 0
                        }])

                        new_user_row = pd.DataFrame(
                            [{"Name": new_name, "PIN": new_pin, "Role": new_role, "Post": new_post, "JoiningDate": new_join.strftime("%Y-%m-%d")}])

                        conn.update(worksheet="Staff_Master", data=inject_balance_formulas(
                            pd.concat([staff_df, new_staff_row], ignore_index=True)))
                        conn.update(worksheet="Users", data=pd.concat(
                            [users_df, new_user_row], ignore_index=True))
                        st.cache_data.clear()
                        st.success(
                            f"User {new_name} added successfully with prorated balances!")

    with tab4:
        st.subheader("Leave Statement Export")
        if staff_df is not None and not staff_df.empty:
            col1, col2 = st.columns(2)

            with col1:
                st.markdown("**Single Employee Statement**")
                export_user = st.selectbox(
                    "Select Employee", staff_df["Name"].tolist(), key="exp_user")

                user_record = staff_df[staff_df["Name"] == export_user].iloc[0]
                data = {
                    "Leave Type": ["Casual Leave (CL)", "Sick Leave (SL)", "Annual Leave (AL)", "Unpaid Leave (UL)"],
                    "Opening Balance": [user_record.get("Opening_CL", 0), user_record.get("Opening_SL", 0), user_record.get("Opening_AL", 0), user_record.get("Opening_UL", 0)],
                    "Addition": [user_record.get("Addition_CL", 0), user_record.get("Addition_SL", 0), user_record.get("Addition_AL", 0), user_record.get("Addition_UL", 0)],
                    "Used": [user_record.get("Used_CL", 0), user_record.get("Used_SL", 0), user_record.get("Used_AL", 0), user_record.get("Used_UL", 0)],
                    "Closing Balance": [user_record.get("Balance_CL", 0), user_record.get("Balance_SL", 0), user_record.get("Balance_AL", 0), user_record.get("Balance_UL", 0)]
                }
                stmt_df = pd.DataFrame(data)
                import io
                buffer_single = io.BytesIO()
                with pd.ExcelWriter(buffer_single, engine='openpyxl') as writer:
                    stmt_df.to_excel(writer, index=False,
                                    sheet_name='Leave Statement')

                st.download_button(
                    label=f"⬇️ Download {export_user} Statement",
                    data=buffer_single.getvalue(),
                    file_name=f"{export_user}_Leave_Statement.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key="dl_single"
                )

            with col2:
                st.markdown("**All Employees Statement**")
                st.write(
                    "Generates a single master Excel table containing all employees and their complete leave balances.")
                buffer_all = io.BytesIO()
                with pd.ExcelWriter(buffer_all, engine='openpyxl') as writer:
                    fixed_cols = ["Name", "Post", "JoiningDate", "Service Year",
                                "Service Year Penalty", "Actual Service Year"]
                    cl_cols = ["Opening_CL", "Addition_CL",
                                "Penalty_CL(UL Effect)", "Used_CL", "Balance_CL"]
                    sl_cols = ["Opening_SL", "Addition_SL",
                                "Penalty_SL(UL Effect)", "Used_SL", "Balance_SL"]
                    al_cols = ["Opening_AL", "Addition_AL",
                                "Penalty_AL(UL Effect)", "Used_AL", "Encashed_AL", "Balance_AL"]
                    ul_cols = ["Opening_UL", "Addition_UL", "Used_UL", "Balance_UL", "Cumulative_UL", "Last_UL_Milestone",
                                "Current Year Leave affecting Service Year", "Cummulative leave effecting Service year.(Education Leave & Etc)."]

                    export_cols = [c for c in fixed_cols + cl_cols +
                                    sl_cols + al_cols + ul_cols if c in staff_df.columns]
                    export_df = staff_df[export_cols]
                    export_df.to_excel(writer, index=False,
                                        sheet_name="Master Leave Statement")

                st.download_button(
                    label="⬇️ Download All Employees Statement",
                    data=buffer_all.getvalue(),
                    file_name="All_Employees_Master_Statement.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key="dl_all",
                    type="primary"
                )

    with tab5:
        st.subheader("Factory Reset (Wipe Dummy Data)")
        st.error("⚠️ **DANGER:** This will completely wipe all leave balances, usage, and history for all employees. Everything will be reset to 0.")
        if staff_df is not None and not staff_df.empty:
            if st.button("🚨 WIPE ALL LEAVE DATA TO 0", type="primary"):
                try:
                    for idx, row in staff_df.iterrows():
                        cols_to_zero = ["Opening_CL", "Addition_CL", "Used_CL", "Balance_CL",
                                        "Opening_SL", "Addition_SL", "Used_SL", "Balance_SL",
                                        "Opening_AL", "Addition_AL", "Used_AL", "Balance_AL", "Encashed_AL",
                                        "Opening_UL", "Addition_UL", "Used_UL", "Balance_UL",
                                        "Cumulative_UL", "Last_UL_Milestone", "Current Year Leave affecting Service Year", "Cummulative leave effecting Service year.(Education Leave & Etc).",
                                        "Penalty_AL(UL Effect)", "Penalty_SL(UL Effect)", "Penalty_CL(UL Effect)",
                                        "Service Year Penalty"]
                        for col in cols_to_zero:
                            staff_df.at[idx, col] = 0.0
                    conn.update(worksheet="Staff_Master",
                                data=inject_balance_formulas(staff_df))
                    st.cache_data.clear()
                    st.success(
                        "Successfully wiped all data! Everything is exactly 0.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Failed to factory reset: {e}")


def render_calculate_service_year_button():
    if st.button("🔄 Calculate Actual Service Year", type="primary"):
        staff_df = load_staff_master()
        if staff_df is not None and not staff_df.empty:
            try:
                if "Actual Service Year" not in staff_df.columns:
                    staff_df["Actual Service Year"] = 0.0
                if "Service Year" not in staff_df.columns:
                    staff_df["Service Year"] = 0.0
                if "Service Year Penalty" not in staff_df.columns:
                    staff_df["Service Year Penalty"] = 0.0

                # Force float dtypes so pandas doesn't silently truncate to int
                staff_df["Actual Service Year"] = staff_df["Actual Service Year"].astype(
                    float)
                staff_df["Service Year"] = staff_df["Service Year"].astype(
                    float)
                staff_df["Service Year Penalty"] = staff_df["Service Year Penalty"].astype(
                    float)

                for idx, row in staff_df.iterrows():
                    try:
                        if pd.isnull(row.get("JoiningDate")) or str(row.get("JoiningDate")).strip() == "":
                            continue

                        joining_date = pd.to_datetime(row["JoiningDate"])
                        calendar_service_years = (
                            datetime.now() - joining_date).days / 365.25
                        staff_df.loc[idx, "Service Year"] = round(
                            calendar_service_years, 2)

                        def s_float(val):
                            if pd.isnull(val):
                                return 0.0
                            val_str = str(val).strip()
                            if val_str == "":
                                return 0.0
                            try:
                                return float(val)
                            except:
                                return 0.0

                        effect_days_curr = s_float(
                            row.get("Current Year Leave affecting Service Year", 0))
                        effect_days_cum = s_float(
                            row.get("Cummulative leave effecting Service year.(Education Leave & Etc).", 0))
                        ul_used = s_float(row.get("Used_UL", 0))
                        ul_cum = s_float(row.get("Cumulative_UL", 0))

                        service_penalty = effect_days_cum + effect_days_curr + ul_used + ul_cum
                        staff_df.loc[idx,
                                    "Service Year Penalty"] = service_penalty

                        if service_penalty == 0:
                            tenure_years = calendar_service_years
                        else:
                            true_service_start = joining_date + \
                                timedelta(days=service_penalty)
                            tenure_years = (datetime.now() -
                                            true_service_start).days / 365.25
                        staff_df.loc[idx, "Actual Service Year"] = round(
                            tenure_years, 2)

                        last_ms = s_float(row.get(
                            "Last_UL_Milestone", 0)) if "Last_UL_Milestone" in staff_df.columns else 0
                        ul_addition = 0
                        if tenure_years >= 20 and last_ms < 20:
                            ul_addition = 182.5
                            staff_df.loc[idx, "Last_UL_Milestone"] = 20
                        elif tenure_years >= 15 and last_ms < 15:
                            ul_addition = 182.5
                            staff_df.loc[idx, "Last_UL_Milestone"] = 15
                        elif tenure_years >= 10 and last_ms < 10:
                            ul_addition = 182.5
                            staff_df.loc[idx, "Last_UL_Milestone"] = 10
                        elif tenure_years >= 5 and last_ms < 5:
                            ul_addition = 182.5
                            staff_df.loc[idx, "Last_UL_Milestone"] = 5

                        if ul_addition > 0:
                            curr_add = s_float(
                                row.get("Addition_UL", 0)) if "Addition_UL" in staff_df.columns else 0
                            staff_df.loc[idx,
                                        "Addition_UL"] = curr_add + ul_addition

                    except Exception as e:
                        pass

                fixed_cols = ["Name", "Post", "JoiningDate", "Service Year",
                                "Service Year Penalty", "Actual Service Year"]
                cl_cols = ["Opening_CL", "Addition_CL",
                            "Penalty_CL(UL Effect)", "Used_CL", "Balance_CL"]
                sl_cols = ["Opening_SL", "Addition_SL",
                            "Penalty_SL(UL Effect)", "Used_SL", "Balance_SL"]
                al_cols = ["Opening_AL", "Addition_AL",
                            "Penalty_AL(UL Effect)", "Used_AL", "Encashed_AL", "Balance_AL"]
                ul_cols = ["Opening_UL", "Addition_UL", "Used_UL", "Balance_UL", "Cumulative_UL", "Last_UL_Milestone",
                            "Current Year Leave affecting Service Year", "Cummulative leave effecting Service year.(Education Leave & Etc)."]

                for col in fixed_cols + cl_cols + sl_cols + al_cols + ul_cols:
                    if col not in staff_df.columns:
                        if col in fixed_cols and col not in ["Service Year", "Service Year Penalty", "Actual Service Year"]:
                            staff_df[col] = ""
                        else:
                            staff_df[col] = 0.0

                all_ordered_cols = fixed_cols + cl_cols + sl_cols + al_cols + ul_cols
                other_cols = [
                    c for c in staff_df.columns if c not in all_ordered_cols]
                staff_df = staff_df[all_ordered_cols + other_cols]

                print("DEBUG STAFF_DF:", staff_df[[
                        "Actual Service Year"]].head())

                conn.update(worksheet="Staff_Master",
                            data=inject_balance_formulas(staff_df))
                st.cache_data.clear()
                st.success("Successfully calculated Actual Service Years!")
            except Exception as e:
                st.error(f"Error syncing service years: {e}")


def render_financial_year_settings():
    import streamlit as st
    st.subheader("📅 Financial Year Settings")
    try:
        fy_df = conn.read(worksheet="FinancialYear")
        if fy_df is not None and not fy_df.empty:
            current_start = str(fy_df.iloc[0].get("Start Date", ""))
            current_end = str(fy_df.iloc[0].get("End Date", ""))

            with st.form("fy_form"):
                new_start = st.text_input(
                    "Start Date (e.g. 2025-04-01)", value=current_start)
                new_end = st.text_input(
                    "End Date (e.g. 2026-03-31)", value=current_end)
                if st.form_submit_button("Update Financial Year"):
                    fy_df.at[0, "Start Date"] = new_start
                    fy_df.at[0, "End Date"] = new_end
                    fy_df.at[0, "Today's Date"] = "=TODAY()"
                    conn.update(worksheet="FinancialYear", data=fy_df)
                    st.cache_data.clear()
                    st.success("Financial Year Updated!")
                    st.rerun()
    except Exception as e:
        st.error(f"Could not load FinancialYear sheet: {e}")


def render_master_balance_table():
    st.subheader("Master Balance Table")
    staff_df = load_staff_master()
    if staff_df is not None and not staff_df.empty:
        balances_list = []
        for name in staff_df["Name"]:
            bal = calculate_balances(name)
            balances_list.append({
                "Name": name,
                "CL": bal["CL"],
                "SL": bal["SL"],
                "AL": bal["AL"],
                "UL": bal["UL"]
            })
        st.dataframe(pd.DataFrame(balances_list),
                    width="stretch", hide_index=True)
    else:
        st.info("No staff data found in Staff_Master.")


def render_user_management(is_admin):
    st.subheader("User Management")
    users_df = load_users_data()
    if users_df is not None and not users_df.empty:
        user_names = users_df["Name"].tolist()
        selected_user = st.selectbox("Select User to Manage", user_names)

        if selected_user:
            user_idx = users_df[users_df["Name"] == selected_user].index[0]
            current_role = users_df.at[user_idx, "Role"]
            current_pin = users_df.at[user_idx, "PIN"]

            current_pin_str = str(current_pin)
            if current_pin_str.endswith(".0"):
                current_pin_str = current_pin_str[:-2]

            st.write(f"**Current Role:** {current_role}")
            new_pin = st.text_input(
                "New PIN / Passcode", value=current_pin_str, type="password", max_chars=4)

            if is_admin:
                available_roles = ["Employee",
                                    "Co-Admin", "Accounts", "Admin"]
            else:
                available_roles = ["Employee", "Accounts"]

            if current_role not in available_roles and not is_admin:
                st.warning(
                    "You do not have permission to change this user's role.")
                new_role = current_role
            else:
                default_idx = available_roles.index(
                    current_role) if current_role in available_roles else 0
                new_role = st.selectbox(
                    "New Role", available_roles, index=default_idx)

            if st.button("Update User Details", type="primary"):
                users_df.at[user_idx, "PIN"] = new_pin
                users_df.at[user_idx, "Role"] = new_role
                conn.update(worksheet="Users", data=users_df)
                st.success(
                    f"Successfully updated details for {selected_user}!")
                st.cache_data.clear()
                st.rerun()


def admin_dashboard():
    render_financial_year_settings()
    st.title("Admin Dashboard")
    
    tab1, tab2, tab3 = st.tabs(["Admin Tasks", "My Leave Profile", "User Management"])
    
    with tab2:
        employee_dashboard(hide_title=True)
        
    with tab3:
        render_user_management(is_admin=True)
        
    with tab1:
        render_master_balance_table()
        st.divider()
        staff_df = load_staff_master()
        st.subheader("Pending Approvals")
        df_requests = load_leave_requests()
        if not df_requests.empty and "Status" in df_requests.columns:
            pending_requests = df_requests[df_requests["Status"] == "Pending"]
            if pending_requests.empty:
                st.info("No pending requests to approve. Good job!")
            else:
                st.error(f"🔔 You have {len(pending_requests)} leave request(s) waiting for approval!")
                for idx, row in pending_requests.iterrows():
                    with st.expander(f"{row['Name']} - {row['LeaveType']} ({row['TotalDays']} days)"):
                        st.write(f"**Dates:** {row['StartDate']} to {row['EndDate']}")
                        st.write(f"**Department:** {row.get('Department', '')}")
                        if "Other" in str(row['LeaveType']) or row.get("EffectsServiceYear") == "Yes":
                            st.warning(f"🚨 **ATTENTION:** This is an '{row['LeaveType']}' leave. The employee has checked 'EffectsServiceYear = {row.get('EffectsServiceYear')}'. Please double-check if this type of leave (e.g. Education Leave) should delay their service year before approving!")
                        co_status = "✅ Supported" if str(row.get('CoAdminAcknowledged', '')).strip().lower() == "supported" else "⏳ Pending"
                        st.caption(f"**Co-Admin Status:** {co_status}")
                        pdf_bytes = generate_leave_pdf(row)
                        if st.button("📄 Preview PDF", key=f"preview_pending_admin_{row['ID']}"):
                            open_pdf_dialog(pdf_bytes, f"{row['Name']}_{row['StartDate']}_Leave_Preview.pdf")
                        col1, col2 = st.columns(2)
                        if col1.button("Approve", key=f"approve_{row['ID']}"):
                            df_requests.at[idx, "Status"] = "Approved"
                            df_requests.at[idx, "ApprovedBy"] = st.session_state.user_name
                            conn.update(worksheet="LeaveRequests", data=df_requests)
                            if staff_df is not None:
                                employee_idx = staff_df[staff_df["Name"] == row["Name"]].index
                                if not employee_idx.empty:
                                    e_idx = employee_idx[0]
                                    leave_type = row["LeaveType"]
                                    actual_leave_type = leave_type.replace("Return-", "")
                                    if actual_leave_type in ["CL", "SL", "AL", "UL"]:
                                        col_name = f"Used_{actual_leave_type}"
                                        if col_name in staff_df.columns:
                                            current_used = float(staff_df.at[e_idx, col_name]) if pd.notnull(staff_df.at[e_idx, col_name]) else 0
                                            staff_df.at[e_idx, col_name] = current_used + float(row["TotalDays"])
                                            balance_col = f"Balance_{actual_leave_type}"
                                            if balance_col in staff_df.columns:
                                                current_bal = float(staff_df.at[e_idx, balance_col]) if pd.notnull(staff_df.at[e_idx, balance_col]) else 0
                                                staff_df.at[e_idx, balance_col] = current_bal - float(row["TotalDays"])
                                    if row.get("EffectsServiceYear") == "Yes":
                                        cum_col = "Current Year Leave affecting Service Year"
                                        if cum_col in staff_df.columns:
                                            current_cum = float(staff_df.at[e_idx, cum_col]) if pd.notnull(staff_df.at[e_idx, cum_col]) else 0
                                            staff_df.at[e_idx, cum_col] = current_cum + float(row["TotalDays"])
                                    penalty_col = "Service Year Penalty"
                                    if penalty_col in staff_df.columns:
                                        def sf(val):
                                            try: return float(val)
                                            except: return 0.0
                                        curr_eff = sf(staff_df.at[e_idx, "Current Year Leave affecting Service Year"]) if "Current Year Leave affecting Service Year" in staff_df.columns else 0.0
                                        eff = sf(staff_df.at[e_idx, "Cummulative leave effecting Service year.(Education Leave & Etc)."]) if "Cummulative leave effecting Service year.(Education Leave & Etc)." in staff_df.columns else 0.0
                                        u_ul = sf(staff_df.at[e_idx, "Used_UL"]) if "Used_UL" in staff_df.columns else 0.0
                                        c_ul = sf(staff_df.at[e_idx, "Cumulative_UL"]) if "Cumulative_UL" in staff_df.columns else 0.0
                                        staff_df.at[e_idx, penalty_col] = eff + curr_eff + u_ul + c_ul
                                    conn.update(worksheet="Staff_Master", data=inject_balance_formulas(staff_df))
                            st.cache_data.clear()
                            st.success(f"Approved {row['Name']}'s request!")
                            send_ntfy_notification(
                                NTFY_ACCOUNT_TOPIC,
                                "Leave Approved - Action Required 📝",
                                f"Admin approved {row['TotalDays']} day(s) of {row['LeaveType']} for {row['Name']}. Please punch it in the register!"
                            )
                            send_ntfy_notification(
                                NTFY_COADMIN_TOPIC,
                                "Leave Approved ✅",
                                f"Admin approved {row['TotalDays']} day(s) of leave for {row['Name']}."
                            )
                            st.rerun()
                        if col2.button("Reject", key=f"reject_{row['ID']}"):
                            df_requests.at[idx, "Status"] = "Rejected"
                            conn.update(worksheet="LeaveRequests", data=df_requests)
                            st.cache_data.clear()
                            st.warning(f"Rejected {row['Name']}'s request.")
                            st.rerun()
        st.divider()
        st.subheader("Approved Leaves (PDF Archive)")
        approved_requests = df_requests[df_requests["Status"] == "Approved"]
        if not approved_requests.empty:
            for idx, row in approved_requests.iterrows():
                col1, col2 = st.columns([5, 1])
                col1.write(f"**{row['Name']}** - {row['LeaveType']} ({row['StartDate']} to {row['EndDate']})")
                pdf_bytes = generate_leave_pdf(row)
                if col2.button("📄 Preview PDF", key=f"prev_admin_{row['ID']}"):
                    open_pdf_dialog(pdf_bytes, f"{row['Name']}_{row['StartDate']}_Leave.pdf")
        else:
            st.info("No approved leaves found.")
    st.divider()
    st.subheader("Financial Year Management")
    leave_accounting_engine()


def coadmin_dashboard():
    st.title("Co-Admin Dashboard")

    st.subheader("Your Leave Profile")
    employee_dashboard(hide_title=True)

    st.divider()
    st.header("Co-Admin Support Portal")

    df_requests = load_leave_requests()

    st.subheader("Office Availability Overview")
    if not df_requests.empty:
        overview = df_requests[df_requests["Status"].isin(
            ["Pending", "Approved"])]
        if not overview.empty:
            for idx, row in overview.iterrows():
                col1, col2 = st.columns([5, 1])
                col1.write(
                    f"**{row['Name']}** - {row['LeaveType']} ({row['StartDate']} to {row['EndDate']}) - {row['Status']}")
                if row['Status'] == "Approved":
                    pdf_bytes = generate_leave_pdf(row)
                    if col2.button("📄 Preview PDF", key=f"prev_co_{row['ID']}"):
                        open_pdf_dialog(
                            pdf_bytes, f"{row['Name']}_{row['StartDate']}_Leave.pdf")
        else:
            st.info("No data available.")
    else:
        st.info("No data available.")

    st.divider()

    st.subheader("Requests to Support")
    if not df_requests.empty and "SelectedCoAdmin" in df_requests.columns:
        to_review = df_requests[
            (df_requests["SelectedCoAdmin"] == st.session_state.user_name) &
            (df_requests["CoAdminAcknowledged"].apply(is_unacknowledged))
        ]

        if to_review.empty:
            st.info("No requests currently assigned to you for support.")
        else:
            st.error(
                f"🔔 You have {len(to_review)} leave request(s) waiting for your support!")
            for idx, row in to_review.iterrows():
                with st.expander(f"{row['Name']} requested {row['TotalDays']} days of {row['LeaveType']}"):
                    st.write(
                        f"**Dates:** {row['StartDate']} to {row['EndDate']}")
                    st.write(f"**Department:** {row.get('Department', '')}")
                    if "Other" in str(row['LeaveType']) or row.get("EffectsServiceYear") == "Yes":
                        st.warning(
                            f"🚨 **ATTENTION:** This is an '{row['LeaveType']}' leave. The employee has checked 'EffectsServiceYear = {row.get('EffectsServiceYear')}'. Please double-check if this type of leave (e.g. Education Leave) should delay their service year before approving!")
                    if st.button("Support Request", type="primary", key=f"ack_{row['ID']}"):
                        df_requests.at[idx,
                                        "CoAdminAcknowledged"] = "Supported"
                        df_requests.at[idx,
                                        "SupportedBy"] = st.session_state.user_name
                        conn.update(worksheet="LeaveRequests",
                                    data=df_requests)
                        st.cache_data.clear()
                        send_ntfy_notification(
                            NTFY_ADMIN_TOPIC,
                            "Leave Supported 🤝",
                            f"Co-Admin {st.session_state.user_name} supported {row['TotalDays']} day(s) of leave for {row['Name']}."
                        )
                        send_ntfy_notification(
                            NTFY_ACCOUNT_TOPIC,
                            "Leave Supported ℹ️",
                            f"Co-Admin {st.session_state.user_name} supported {row['TotalDays']} day(s) of leave for {row['Name']}. (FYI - Awaiting Admin Approval)"
                        )
                        st.rerun()
    else:
        st.info("No leave requests found.")


def accounts_dashboard():
    render_financial_year_settings()
    st.title("Accounts Dashboard")
    
    tab1, tab2, tab3 = st.tabs(["Accounts Tasks", "My Leave Profile", "User Management"])
    
    with tab2:
        employee_dashboard(hide_title=True)
        
    with tab3:
        render_user_management(is_admin=False)
        
    with tab1:
        render_master_balance_table()
        st.divider()
        
        df_requests = load_leave_requests()
        
        st.subheader("All Leaves Overview")
        if not df_requests.empty:
            for idx, row in df_requests.iterrows():
                col1, col2 = st.columns([5, 1])
                col1.write(f"**{row['Name']}** - {row['LeaveType']} ({row['StartDate']} to {row['EndDate']}) - Status: {row['Status']}")
                if row['Status'] == "Approved":
                    pdf_bytes = generate_leave_pdf(row)
                    col2.download_button("📄 PDF", data=pdf_bytes, file_name=f"{row['Name']}_{row['StartDate']}_Leave.pdf", mime="application/pdf", key=f"dl_acc_{row['ID']}")
        else:
            st.info("No data available.")
            
        st.divider()
        
        st.subheader("Action Required: Manual Attendance Register")
        if not df_requests.empty:
            action_required = df_requests[
                (df_requests["Status"] == "Approved") & 
                (df_requests["AccountsPunched"].apply(is_unacknowledged))
            ]
            
            if action_required.empty:
                st.info("No approved requests require manual punching right now.")
            else:
                st.error(f"🔔 You have {len(action_required)} approved leave request(s) waiting to be punched in the register!")
                for idx, row in action_required.iterrows():
                    with st.expander(f"{row['Name']} took {row['TotalDays']} days of {row['LeaveType']}"):
                        st.write(f"**Dates:** {row['StartDate']} to {row['EndDate']}")
                        st.write(f"**Department:** {row.get('Department', '')}")
                        if "Other" in str(row['LeaveType']) or row.get("EffectsServiceYear") == "Yes":
                            st.warning(f"🚨 **ATTENTION:** This is an '{row['LeaveType']}' leave. The employee has checked 'EffectsServiceYear = {row.get('EffectsServiceYear')}'. This will permanently delay their Service Year!")
                        
                        co_status = "✅ Supported" if str(row.get('CoAdminAcknowledged', '')).strip().lower() == "supported" else "⏳ Pending"
                        admin_status = "✅ Approved" if str(row.get('Status', '')).strip().lower() == "approved" else f"ℹ️ {row.get('Status', 'Unknown')}"
                        
                        st.caption(f"**Admin:** {admin_status} &nbsp;|&nbsp; **Co-Admin:** {co_status}")
                        
                        pdf_bytes = generate_leave_pdf(row)
                        col_btn1, col_btn2 = st.columns(2)
                        
                        if col_btn1.button("📄 Preview PDF", key=f"prev_act_{row['ID']}"):
                            open_pdf_dialog(pdf_bytes, f"{row['Name']}_{row['StartDate']}_Leave.pdf")
                            
                        if col_btn2.button("Mark Punched in Register", type="primary", key=f"punch_{row['ID']}"):
                            df_requests.at[idx, "AccountsPunched"] = "Punched"
                            df_requests.at[idx, "PunchedBy"] = st.session_state.user_name
                            conn.update(worksheet="LeaveRequests", data=df_requests)
                            st.cache_data.clear()
                            send_ntfy_notification(
                                NTFY_ADMIN_TOPIC,
                                "Leave Punched in Register 📚",
                                f"Accountant {st.session_state.user_name} punched in {row['TotalDays']} day(s) of leave for {row['Name']}."
                            )
                            send_ntfy_notification(
                                NTFY_COADMIN_TOPIC,
                                "Leave Punched in Register 📚",
                                f"Accountant {st.session_state.user_name} punched in {row['TotalDays']} day(s) of leave for {row['Name']}."
                            )
                            st.rerun()
                            
        leave_accounting_engine()



def render_smart_notifications(role, user_name):
    df_requests = load_leave_requests()
    if df_requests is None or df_requests.empty:
        return
        
    if role == "Admin":
        if "Status" in df_requests.columns:
            pending = df_requests[df_requests["Status"] == "Pending"]
            if not pending.empty:
                st.warning(f"🚨 You have {len(pending)} pending leave request(s) waiting for your approval! Please check the **Admin Tasks** tab.")
                
    elif role == "Co-Admin":
        if "SelectedCoAdmin" in df_requests.columns and "CoAdminAcknowledged" in df_requests.columns:
            def is_coadmin_pending(x):
                return str(x).strip() == "" or str(x).lower() == "nan"
            pending = df_requests[(df_requests["SelectedCoAdmin"] == user_name) & (df_requests["Status"] == "Pending") & (df_requests["CoAdminAcknowledged"].apply(is_coadmin_pending))]
            if not pending.empty:
                st.warning(f"🚨 You have {len(pending)} pending leave request(s) waiting for your support! Please check the list below.")
                
    elif role == "Accountant":
        if "Status" in df_requests.columns and "AccountsPunched" in df_requests.columns:
            pending = df_requests[(df_requests["Status"] == "Approved") & (df_requests["AccountsPunched"].apply(is_unacknowledged))]
            if not pending.empty:
                st.warning(f"🚨 You have {len(pending)} approved leave(s) waiting to be punched in the register! Please check the **Accounts Tasks** tab.")


def main_dashboard():

    # AUTO-SYNC USERS -> STAFF MASTER
    users_df = load_users_data()
    staff_df = load_staff_master()
    if users_df is not None and staff_df is not None:
        missing_users = []
        staff_names = staff_df["Name"].dropna().tolist(
        ) if "Name" in staff_df.columns else []
        for _, user_row in users_df.iterrows():
            name = user_row.get("Name")
            if pd.notnull(name) and str(name).strip() != "" and name not in staff_names:
                new_row = {
                    "Name": name, "Post": user_row.get("Post", ""), "JoiningDate": user_row.get("JoiningDate", ""),
                    "Opening_CL": 0, "Addition_CL": 0, "Used_CL": 0, "Balance_CL": 0, "Penalty_CL(UL Effect)": 0,
                    "Opening_SL": 0, "Addition_SL": 0, "Used_SL": 0, "Balance_SL": 0, "Penalty_SL(UL Effect)": 0,
                    "Opening_AL": 0, "Addition_AL": 0, "Used_AL": 0, "Balance_AL": 0, "Penalty_AL(UL Effect)": 0, "Encashed_AL": 0,
                    "Opening_UL": 0, "Addition_UL": 0, "Used_UL": 0, "Balance_UL": 0,
                    "Cumulative_UL": 0, "Last_UL_Milestone": 0, "Current Year Leave affecting Service Year": 0, "Cummulative leave effecting Service year.(Education Leave & Etc).": 0,
                    "Service Year Penalty": 0
                }
                missing_users.append(new_row)
        if missing_users:
            new_df = pd.DataFrame(missing_users)
            staff_df = pd.concat([staff_df, new_df], ignore_index=True)
            conn.update(worksheet="Staff_Master",
                        data=inject_balance_formulas(staff_df))
            st.cache_data.clear()
            st.rerun()

    st.sidebar.title(f"Welcome, {st.session_state.user_name}")
    st.sidebar.write(f"**Role:** {st.session_state.user_role}")

    with st.sidebar.expander("🔑 Change PIN"):
        new_pin = st.text_input(
            "New 4-digit PIN", type="password", max_chars=4)
        confirm_pin = st.text_input(
            "Confirm New PIN", type="password", max_chars=4)
        if st.button("Update PIN"):
            clean_new_pin = new_pin.strip()
            clean_confirm_pin = confirm_pin.strip()
            if len(clean_new_pin) != 4 or not clean_new_pin.isdigit():
                st.error("PIN must be exactly 4 numeric digits.")
            elif clean_new_pin != clean_confirm_pin:
                st.error("PINs do not match!")
            else:
                users_df = load_users_data()
                if users_df is not None:
                    user_idx = users_df[users_df["Name"] ==
                                        st.session_state.user_name].index
                    if not user_idx.empty:
                        users_df.at[user_idx[0], "PIN"] = clean_new_pin
                        conn.update(worksheet="Users", data=users_df)
                        st.cache_data.clear()
                        st.success("PIN updated successfully!")

    st.sidebar.divider()

    if st.sidebar.button("Logout"):
        st.session_state.logged_in = False
        st.session_state.user_name = None
        st.session_state.user_role = None
        st.cache_data.clear()
        st.rerun()

    role = st.session_state.user_role

    render_smart_notifications(role, st.session_state.user_name)

    if role == "Employee":
        employee_dashboard()
    elif role == "Admin":
        admin_dashboard()
    elif role == "Co-Admin":
        coadmin_dashboard()
    elif role == "Accounts":
        accounts_dashboard()
    else:
        st.title("Dashboard")
        st.error("Welcome! Role not recognized.")


# --- MAIN APP FLOW ---
if not st.session_state.logged_in:
    login_screen()
else:
    main_dashboard()
