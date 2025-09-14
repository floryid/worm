import streamlit as st
import os
import json
import base64
import sqlite3
import shutil
import platform
import getpass
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from win32crypt import CryptUnprotectData
import datetime
import glob
from fpdf import FPDF
import tempfile

st.markdown("""
    <style>
    body, .stApp {
        background: linear-gradient(135deg, #232526 0%, #414345 100%);
        color: #f8f8f2 !important;
    }
    .stTitle, .stMarkdown, .stCaption, .stSuccess, .stWarning, .stError {
        color: #50fa7b !important;
    }
    .stDataFrame {
        background-color: #282a36 !important;
        color: #f8f8f2 !important;
        border-radius: 10px;
    }
    .css-1v0mbdj, .stButton>button {
        background: linear-gradient(90deg, #ff79c6 0%, #8be9fd 100%);
        color: #282a36 !important;
        border-radius: 8px;
        font-weight: bold;
    }
    .stDownloadButton>button {
        background: linear-gradient(90deg, #bd93f9 0%, #ffb86c 100%);
        color: #282a36 !important;
        border-radius: 8px;
        font-weight: bold;
    }
    </style>
""", unsafe_allow_html=True)
st.title(" Credentials Scan (Selamat Menikmati Hasil Yang Luar Biasa)")

def get_os_paths():
    user = getpass.getuser()
    system = platform.system()
    paths = {
        "Chrome": {
            "Windows": f"C:\\Users\\{user}\\AppData\\Local\\Google\\Chrome\\User Data",
        },
        "Edge": {
            "Windows": f"C:\\Users\\{user}\\AppData\\Local\\Microsoft\\Edge\\User Data",
        }
    }
    return paths

def get_master_key(profile_path):
    local_state_path = os.path.join(profile_path, "Local State")
    try:
        with open(local_state_path, "r", encoding="utf-8") as f:
            local_state = json.loads(f.read())
        encrypted_key = base64.b64decode(local_state["os_crypt"]["encrypted_key"])[5:]
        return CryptUnprotectData(encrypted_key, None, None, None, 0)[1]
    except Exception as e:
        st.warning(f"Gagal mengambil master key: {e}")
        return None

def decrypt_password(encrypted_password, key):
    try:
        if encrypted_password.startswith(b"v10"):
            iv = encrypted_password[3:15]
            payload = encrypted_password[15:]
            cipher = AESGCM(key)
            return cipher.decrypt(iv, payload, None).decode()
        else:
            return CryptUnprotectData(encrypted_password, None, None, None, 0)[1].decode()
    except Exception as e:
        return f"Decryption Failed: {e}"

def get_firefox_profiles():
    user = getpass.getuser()
    system = platform.system()
    if system == "Windows":
        base_path = f"C:\\Users\\{user}\\AppData\\Roaming\\Mozilla\\Firefox\\Profiles"
    elif system == "Darwin":
        base_path = f"/Users/{user}/Library/Application Support/Firefox/Profiles"
    else:
        base_path = f"/home/{user}/.mozilla/firefox"
    return glob.glob(os.path.join(base_path, "*"))

def get_firefox_credentials():
    profiles = get_firefox_profiles()
    output = []
    for profile in profiles:
        logins_path = os.path.join(profile, "logins.json")
        if os.path.exists(logins_path):
            try:
                with open(logins_path, "r", encoding="utf-8") as f:
                    logins = json.load(f)
                for login in logins.get("logins", []):
                    output.append({
                        "browser": "Firefox",
                        "url": login.get("hostname", ""),
                        "username": login.get("username", ""),
                        "password": "(encrypted)",  # Untuk dekripsi, butuh NSS/pyfx/firefox_decrypt
                        "created": login.get("timeCreated", ""),
                        "last_used": login.get("timeLastUsed", "")
                    })
            except Exception as e:
                st.error(f"Gagal membaca Firefox profile: {e}")
    return output

def get_browser_credentials():
    paths = get_os_paths()
    output = []
    # Chrome & Edge
    for browser, os_paths in paths.items():
        path = os_paths.get(platform.system())
        if not path or not os.path.exists(path):
            continue
        master_key = get_master_key(path)
        if not master_key:
            continue
        login_db = os.path.join(path, "Default", "Login Data")
        if not os.path.exists(login_db):
            continue
        temp_db = os.path.join(os.environ.get("TEMP", "."), f"{browser}_temp.db")
        try:
            shutil.copy2(login_db, temp_db)
            conn = sqlite3.connect(temp_db)
            cursor = conn.cursor()
            cursor.execute("SELECT origin_url, username_value, password_value, date_created, date_last_used FROM logins")
            for url, username, password, created, last_used in cursor.fetchall():
                if username and password:
                    decrypted = decrypt_password(password, master_key)
                    output.append({
                        "browser": browser,
                        "url": url,
                        "username": username,
                        "password": decrypted,
                        "created": str(datetime.datetime(1601, 1, 1) + datetime.timedelta(microseconds=created)),
                        "last_used": str(datetime.datetime(1601, 1, 1) + datetime.timedelta(microseconds=last_used))
                    })
            conn.close()
        except Exception as e:
            st.error(f"Gagal membaca database {browser}: {e}")
        finally:
            if os.path.exists(temp_db):
                os.remove(temp_db)
    # Firefox
    output += get_firefox_credentials()
    return output

def generate_pdf(creds):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    pdf.cell(200, 10, txt="Browser Credentials Report", ln=True, align="C")
    pdf.ln(10)
    for cred in creds:
        pdf.multi_cell(0, 10, txt=f"Browser: {cred['browser']}\nURL: {cred['url']}\nUsername: {cred['username']}\nPassword: {cred['password']}\nCreated: {cred['created']}\nLast Used: {cred['last_used']}\n{'-'*40}")
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    pdf.output(temp_file.name)
    temp_file.seek(0)
    return temp_file

if st.button("Ambil Data Credential"):
    creds = get_browser_credentials()
    if creds:
        st.success(f"Berhasil mengambil {len(creds)} credential.")
        st.dataframe(creds)
        st.download_button("Download JSON", data=json.dumps(creds, indent=2), file_name="browser_creds.json")
        pdf_file = generate_pdf(creds)
        with open(pdf_file.name, "rb") as f:
            st.download_button("Download PDF", data=f.read(), file_name="browser_creds.pdf", mime="application/pdf")
    else:
        st.warning("Tidak ada credential ditemukan atau browser tidak didukung.")

st.caption("Hanya mendukung Chrome & Edge di Windows. Fitur Firefox/Safari dinonaktifkan untuk keamanan dan kompatibilitas.")