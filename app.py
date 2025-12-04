# 必要ライブラリ（コマンドプロンプトでインストール）
# python -m pip install streamlit streamlit-authenticator pandas plotly gspread google-auth bcrypt

import json
import time
from datetime import datetime, date

import bcrypt
import gspread
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components
import streamlit_authenticator as stauth
from google.oauth2 import service_account



# =========================
# Google Sheets 接続まわり
# =========================

SHEET_NAMES = [
    "users",
    "students",
    "exam_results",
    "coaching_reports",
    "eiken_records",
]

SHEET_SCHEMAS = {
    "users": ["username", "name", "password_hash", "role"],
    "students": [
        "student_id",
        "name",
        "grade",           # 中学生 / 高校生
        "school_name",
        "target_school",
        "admission_goal",
        "student_login_id",
        "subjects",        # JSON string
        "mock_subjects",   # JSON string（共通テスト系）
        "created_at",
    ],
    "exam_results": [
        "id",
        "student_id",
        "exam_category",   # 定期テスト / 模試
        "exam_name",
        "date",
        "results_json",    # {科目: {score, target}} のJSON
        "created_at",
    ],
    "coaching_reports": [
        "id",
        "student_id",
        "date",
        "student_eval_json",   # {理解度, 目標達成度, モチベーション}
        "teacher_eval_json",   # {授業態度, 宿題完成度, 前回理解度, コメント}
        "study_schedule_json", # {曜日: 時間}
        "study_targets_json",  # ["目標1", "目標2", "目標3"]
        "created_at",
    ],
    "eiken_records": [
        "id",
        "student_id",
        "target_grade",    # 5級, 4級, ...
        "exam_date",       # 本番日（文字列）
        "practice_date",   # 演習日
        "category",        # 2023第1回など
        "scores_json",     # {reading: {correct,total}, ...}
        "created_at",
    ],
}

# ---------- Google Sheets クライアント ----------

@st.cache_resource
def get_gspread_client():
    info = st.secrets["google_service_account"]
    credentials = service_account.Credentials.from_service_account_info(
        info,
        scopes=[
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ],
    )
    return gspread.authorize(credentials)


@st.cache_resource
def get_spreadsheet():
    client = get_gspread_client()
    spreadsheet_id = st.secrets["gsheets"]["spreadsheet_id"]
    try:
        return client.open_by_key(spreadsheet_id)
    except gspread.exceptions.APIError as e:
        # Google Sheets 側のエラーを画面に表示して処理を止める
        st.error("Google Sheets との通信でエラーが発生しました。\n詳細: {}".format(e))
        st.stop()


@st.cache_data(ttl=60)
def load_all_tables():
    """全ワークシートをまとめて DataFrame 化（60秒キャッシュ）"""
    sh = get_spreadsheet()

    tables = {}

    # students
    try:
        ws_students = sh.worksheet("students")
        rec_students = ws_students.get_all_records()
        tables["students"] = pd.DataFrame(rec_students)
    except Exception:
        tables["students"] = pd.DataFrame()

    # exam_results
    try:
        ws_exam = sh.worksheet("exam_results")
        rec_exam = ws_exam.get_all_records()
        tables["exam_results"] = pd.DataFrame(rec_exam)
    except Exception:
        tables["exam_results"] = pd.DataFrame()

    # coaching_reports
    try:
        ws_coach = sh.worksheet("coaching_reports")
        rec_coach = ws_coach.get_all_records()
        tables["coaching_reports"] = pd.DataFrame(rec_coach)
    except Exception:
        tables["coaching_reports"] = pd.DataFrame()

    # eiken_records
    try:
        ws_eiken = sh.worksheet("eiken_records")
        rec_eiken = ws_eiken.get_all_records()
        tables["eiken_records"] = pd.DataFrame(rec_eiken)
    except Exception:
        tables["eiken_records"] = pd.DataFrame()

    # users
    try:
        ws_users = sh.worksheet("users")
        rec_users = ws_users.get_all_records()
        tables["users"] = pd.DataFrame(rec_users)
    except Exception:
        tables["users"] = pd.DataFrame()

    return tables

# ==============================
# Google Sheets 初期化
# ==============================
def init_sheets():
    sh = get_spreadsheet()

    required_sheets = {
        "users": ["username", "name", "password_hash", "role"],
        "students": [
            "student_id",
            "name",
            "grade",
            "school_name",
            "target_school",
            "admission_goal",
            "student_login_id",
            "subjects",
            "mock_subjects",
            "created_at",          # ← 生徒登録時に入れている created_at に対応
        ],
        "exam_results": [
            "id",
            "student_id",
            "exam_category",
            "exam_name",
            "date",
            "results_json",        # ← dict をそのまま JSON で持つ
            "created_at",
            "teacher_username",    # ← 成績を登録した講師ID
            "teacher_name",        # ← 成績を登録した講師名
        ],
        "coaching_reports": [
            "id",
            "student_id",
            "date",
            "student_eval_json",   # 生徒自己評価（JSON）
            "teacher_eval_json",   # 講師評価（JSON）
            "study_schedule_json", # 自習予定（JSON）
            "study_targets_json",  # 自習目標（JSON）
            "created_at",
            "updated_at",
            "teacher_username",    # 日報を登録した講師ID
            "teacher_name",        # 日報を登録した講師名
        ],
        "eiken_records": [
            "id",
            "student_id",
            "target_grade",
            "exam_date",
            "practice_date",
            "category",
            "scores_json",         # 4技能の正解数など（JSON）
            "created_at",
            "teacher_username",    # 英検演習を登録した講師ID
            "teacher_name",        # 英検演習を登録した講師名
        ],
        "masters": [
            "username",
            "name",
            "password_hash",
            "role",
        ],
    }

    existing_titles = [ws.title for ws in sh.worksheets()]

    for sheet_name, headers in required_sheets.items():
        if sheet_name not in existing_titles:
            ws = sh.add_worksheet(title=sheet_name, rows=1000, cols=max(len(headers), 20))
            ws.append_row(headers)



def get_worksheet(name: str):
    sh = get_spreadsheet()
    try:
        ws = sh.worksheet(name)
    except gspread.exceptions.WorksheetNotFound:
        # 無ければ作成してヘッダー行だけ書き込む
        ws = sh.add_worksheet(title=name, rows=1000, cols=50)
        header = SHEET_SCHEMAS.get(name, [])
        if header:
            ws.update("A1", [header])
    return ws


# ---------- DataFrame 読み書き共通関数 ----------

def _ensure_columns(df: pd.DataFrame, sheet_name: str) -> pd.DataFrame:
    cols = SHEET_SCHEMAS[sheet_name]
    for c in cols:
        if c not in df.columns:
            df[c] = ""
    return df[cols]


@st.cache_data(ttl=300)
def load_sheet_df(sheet_name: str) -> pd.DataFrame:
    ws = get_worksheet(sheet_name)
    records = ws.get_all_records()
    if not records:
        df = pd.DataFrame(columns=SHEET_SCHEMAS[sheet_name])
    else:
        df = pd.DataFrame(records)
        df = _ensure_columns(df, sheet_name)
    return df


def write_sheet_df(sheet_name: str, df: pd.DataFrame):
    df = _ensure_columns(df.copy(), sheet_name)
    ws = get_worksheet(sheet_name)
    ws.clear()
    if df.empty:
        ws.update("A1", [list(df.columns)])
    else:
        data = [list(df.columns)] + df.astype(str).values.tolist()
        ws.update("A1", data)
    # キャッシュクリア
    load_sheet_df.clear()


# ================
# 認証・ユーザー管理
# ================

def ensure_master_user():
    """
    users シートに master ユーザーが存在しなければ作成する。
    username: master
    password: Ubase2025
    role: master
    """
    df = load_sheet_df("users")

    MASTER_USERNAME = "master"
    MASTER_NAME = "管理者"
    MASTER_PASSWORD = "Ubase2025"

    # 空 or username 列が無い場合 → master だけ作って初期化
    if "username" not in df.columns or df.empty:
        hashed = stauth.Hasher.hash(MASTER_PASSWORD)
        df = pd.DataFrame(
            [{
                "username": MASTER_USERNAME,
                "name": MASTER_NAME,
                "password_hash": hashed,
                "role": "master",
            }]
        )
        write_sheet_df("users", df)
        return

    # 既に users シートがあって、master がいない場合だけ追加
    if not (df["username"] == MASTER_USERNAME).any():
        hashed = stauth.Hasher.hash(MASTER_PASSWORD)
        new_row = {
            "username": MASTER_USERNAME,
            "name": MASTER_NAME,
            "password_hash": hashed,
            "role": "master",
        }
        df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
        write_sheet_df("users", df)


def build_authenticator():
    """
    users シートから認証情報とロールを読み込み、streamlit-authenticator を構築。
    """
    df = load_sheet_df("users")
    creds = {"usernames": {}}
    roles = {}
    for _, row in df.iterrows():
        username = str(row["username"])
        if not username:
            continue
        creds["usernames"][username] = {
            "name": row.get("name") or username,
            "password": row.get("password_hash") or "",
        }
        roles[username] = row.get("role") or "teacher"

    authenticator = stauth.Authenticate(
        creds,
        "ubase_cookie",
        "ubase_key",
        cookie_expiry_days=7,
    )
    return authenticator, roles


def get_current_user_role(roles_dict, username: str) -> str:
    return roles_dict.get(username, "teacher")


# =================
# 生徒ID生成ロジック
# =================

# ====================
# 生徒ID採番ユーティリティ
# ====================

def generate_new_student_id(students_df: pd.DataFrame | None = None) -> int:
    """
    一度使われた student_id を二度と再利用しないようにするため、
    students / exam_results / coaching_reports / eiken_records
    の全ての student_id を見て最大値+1 を返す。
    """

    all_ids: list[int] = []

    # 1) students（関数からも呼ばれるので引数があれば優先）
    if students_df is None:
        students_df = get_students_df()
    if students_df is not None and not students_df.empty and "student_id" in students_df.columns:
        for v in students_df["student_id"].astype(str):
            v = v.strip()
            if not v:
                continue
            try:
                all_ids.append(int(v))
            except Exception:
                pass

    # 2) exam_results
    exam_df = get_exam_results_df()
    if exam_df is not None and not exam_df.empty and "student_id" in exam_df.columns:
        for v in exam_df["student_id"].astype(str):
            v = v.strip()
            if not v:
                continue
            try:
                all_ids.append(int(v))
            except Exception:
                pass

    # 3) coaching_reports
    coaching_df = get_coaching_df()
    if coaching_df is not None and not coaching_df.empty and "student_id" in coaching_df.columns:
        for v in coaching_df["student_id"].astype(str):
            v = v.strip()
            if not v:
                continue
            try:
                all_ids.append(int(v))
            except Exception:
                pass

    # 4) eiken_records
    eiken_df = get_eiken_df()
    if eiken_df is not None and not eiken_df.empty and "student_id" in eiken_df.columns:
        for v in eiken_df["student_id"].astype(str):
            v = v.strip()
            if not v:
                continue
            try:
                all_ids.append(int(v))
            except Exception:
                pass

    # 何もなければ初期値からスタート（好きな番号でOK）
    if not all_ids:
        return 250001  # 例：最初のID

    return max(all_ids) + 1


# =========================
# 定期テスト / 模試 科目定義
# =========================

JUNIOR_SUBJECTS = ["国語", "数学", "英語", "理科", "社会"]

HIGH_REGULAR_SUBJECTS = [
    "現代文",
    "言語文化",
    "数学ⅠA",
    "数学ⅡB",
    "数学ⅢC",
    "現代社会",
    "公共",
    "倫理",
    "政治・経済",
    "地理",
    "日本史",
    "世界史",
    "物理",
    "物理基礎",
    "化学",
    "化学基礎",
    "生物",
    "生物基礎",
    "地学",
    "地学基礎",
    "コミュ英",
    "論理表現",
]

HIGH_MOCK_SUBJECTS = [
    "現代文",
    "古文",
    "漢文",
    "地理総合、地理探究",
    "歴史総合、日本史探究",
    "歴史総合、世界史探究",
    "公共、倫理",
    "公共、政治・経済",
    "数学ⅠA",
    "数学ⅡBC",
    "物理",
    "化学",
    "生物",
    "地学",
    "物理基礎",
    "化学基礎",
    "生物基礎",
    "地学基礎",
    "英語R",
    "英語L",
    "情報Ⅰ",
]

REGULAR_EXAM_NAMES = [
    "1学期中間",
    "1学期期末",
    "2学期中間",
    "2学期期末",
    "学年末",
]

EIKEN_GRADES = ["5級", "4級", "3級", "準2級", "2級", "準1級", "1級"]
# 英検 各級ごとの問題数・満点（必要なら後で調整してください）
EIKEN_TOTALS = {
    # reading / listening = 問題数
    # writing / speaking = 満点（得点扱い）
    "5級":   {"reading": 25, "listening": 25, "writing": 0,  "speaking": 0},
    "4級":   {"reading": 35, "listening": 30, "writing": 0,  "speaking": 0},
    "3級":   {"reading": 35, "listening": 30, "writing": 16, "speaking": 16},
    "準2級": {"reading": 37, "listening": 29, "writing": 16, "speaking": 16},
    "2級":   {"reading": 37, "listening": 30, "writing": 16, "speaking": 16},
    "準1級": {"reading": 41, "listening": 29, "writing": 16, "speaking": 20},
    "1級":   {"reading": 41, "listening": 27, "writing": 32, "speaking": 20},
}


DAYS_JP = ["月", "火", "水", "木", "金", "土", "日"]

# ★ ここに追加する ↓↓↓

# 学年の候補
GRADE_CHOICES = [
    "小1", "小2", "小3", "小4", "小5", "小6",
    "中1", "中2", "中3",
    "高1", "高2", "高3",
    "既卒",
]

# 進級マップ（必要なら中3→高1を中3→高3などに変えてOK）
PROMOTION_MAP = {
    "小1": "小2",
    "小2": "小3",
    "小3": "小4",
    "小4": "小5",
    "小5": "小6",
    "小6": "中1",
    "中1": "中2",
    "中2": "中3",
    "中3": "高1",
    "高1": "高2",
    "高2": "高3",
}

def promote_grade_value(grade: str) -> str:
    """1つの学年を進級させる。マップに無いものはそのまま返す。"""
    return PROMOTION_MAP.get(grade, grade)


# ==========
# CSS / テーマ
# ==========

def inject_base_css():
    css = """
    <style>
    /* Noto Sans JP を優先して使う（無ければシステムフォント） */
    @import url('https://fonts.googleapis.com/css2?family=Noto+Sans+JP:wght@400;500;600;700;900&display=swap');

    :root {
        --ubase-font-main: 'Noto Sans JP', -apple-system, BlinkMacSystemFont,
                           'Segoe UI', 'Yu Gothic UI', 'Meiryo', sans-serif;
        --ubase-accent: #2563eb;
        --ubase-accent-soft: #e0edff;
        --ubase-border-soft: #e5e7eb;
    }

    /* 全体の文字を少し太め & 行間広めに */
    html, body, [data-testid="stAppViewContainer"] {
        font-family: var(--ubase-font-main);
        font-weight: 500;
        letter-spacing: 0.02em;
        line-height: 1.7;
        color: #111827;
        background-color: #f5f7fb;
    }

    /* サイドバー全体 */
    section[data-testid="stSidebar"] {
        background: linear-gradient(180deg, #f5f7ff 0%, #ecf3ff 40%, #ffffff 100%);
        padding-top: 1.5rem;
        border-right: 1px solid #e5e7eb;
    }
    section[data-testid="stSidebar"] * {
        font-family: var(--ubase-font-main);
        letter-spacing: 0.02em;
    }

    /* タイトル・サブタイトル（ロゴ部分） */
    .ubase-title {
        text-align: left;
        color: #111827;
        font-size: 1.8rem;
        font-weight: 900;
        letter-spacing: 0.12em;
        margin: 0 0 0.2rem 0;
    }
    .ubase-subtitle {
        text-align: left;
        color: #6b7280;
        font-size: 0.85rem;
        font-weight: 600;
        letter-spacing: 0.08em;
        margin-bottom: 1.2rem;
    }

    /* 「ログイン中: ～」などサイドバーのテキストを少し太めに */
    section[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p {
        font-size: 0.9rem;
        font-weight: 600;
        margin-bottom: 0.4rem;
    }

    /* ラジオボタンのラベル（メニュー） */
    section[data-testid="stSidebar"] label {
        font-weight: 600;
        font-size: 0.95rem;
    }

    /* メインボタン（ログアウト以外） */
    .stButton>button {
        background: linear-gradient(135deg, var(--ubase-accent), #1d4ed8) !important;
        color: #ffffff !important;
        border-radius: 999px !important;
        border: none !important;
        padding: 0.45rem 1.5rem !important;
        font-weight: 700 !important;
        font-size: 0.95rem !important;
        box-shadow: 0 8px 18px rgba(37, 99, 235, 0.35) !important;
    }
    .stButton>button:hover {
        background: linear-gradient(135deg, #1d4ed8, #1e40af) !important;
        box-shadow: 0 10px 22px rgba(30, 64, 175, 0.45) !important;
    }

    /* 危険操作ボタン（削除など） */
    .danger-button>button {
        background: #f97373 !important;
        color: #ffffff !important;
        font-weight: 700 !important;
        border-radius: 999px !important;
    }
    .danger-button>button:hover {
        background: #ef4444 !important;
    }

    /* レポート枠・カード類 */
    .report-container {
        border: 1px solid var(--ubase-border-soft);
        padding: 1.4rem;
        border-radius: 16px;
        background-color: #ffffff;
        box-shadow: 0 10px 30px rgba(15, 23, 42, 0.06);
    }
    .report-header {
        text-align: center;
        font-weight: 800;
        font-size: 1.2rem;
        letter-spacing: 0.06em;
        margin-bottom: 0.6rem;
        color: #111827;
    }
    .report-section-title {
        font-weight: 700;
        color: #1d4ed8;
        margin-top: 1.0rem;
        margin-bottom: 0.35rem;
        border-left: 4px solid #2563eb;
        padding-left: 0.45rem;
        font-size: 0.98rem;
        letter-spacing: 0.06em;
    }

    /* テーブル・データフレームのヘッダを太字に */
    .stDataFrame thead tr th,
    .stTable thead tr th {
        font-weight: 700;
        font-size: 0.9rem;
    }

    /* 一般テキストもやや太めに */
    .stMarkdown p, .stMarkdown li {
        font-weight: 500;
        font-size: 0.95rem;
    }
    </style>
    """
    st.markdown(css, unsafe_allow_html=True)



def inject_print_mode_css():
    css = """
    <style>
    section[data-testid="stSidebar"] {
        display: none !important;
    }
    header {
        display: none !important;
    }
    </style>
    """
    st.markdown(css, unsafe_allow_html=True)


# ====================
# ページ共通ユーティリティ
# ====================

def get_students_df():
    return load_sheet_df("students")


def get_exam_results_df():
    return load_sheet_df("exam_results")


def get_coaching_df():
    return load_sheet_df("coaching_reports")


def get_eiken_df():
    return load_sheet_df("eiken_records")


# -----------------
# 生徒管理ページ
# -----------------

def page_student_management(current_role: str):
    st.header("生徒管理")

    students_df = get_students_df()

    # ----------------------
    # 新規登録
    # ----------------------
    st.subheader("新規生徒登録")

    col1, col2 = st.columns(2)
    with col1:
        name = st.text_input("生徒名")

        # ★ 学年は GRADE_CHOICES から選択（例: 中1, 高2 など）
        #   初期値は「中1」にしておく（お好みで変更OK）
        default_grade = "中1" if "中1" in GRADE_CHOICES else GRADE_CHOICES[0]
        grade = st.selectbox("学年", GRADE_CHOICES, index=GRADE_CHOICES.index(default_grade))

    with col2:
        school_name = st.text_input("学校名")
        target_school = st.text_input("志望校")

    admission_goal = st.text_area(
        "入塾時の目標",
        height=80,
        key="new_admission_goal",
    )

    student_login_id = st.text_input("生徒ID（生徒用ログインID・任意）")

    # 科目
    st.markdown("#### 科目設定")
    if grade.startswith("中"):  # 中学生
        subjects = JUNIOR_SUBJECTS
        st.write("中学生は以下の5科目が自動設定されます：", "、".join(subjects))
        mock_subjects = []
    elif grade.startswith("高") or grade == "既卒":  # 高校生・既卒
        st.write("定期テスト科目（高校）")
        regular_selected = st.multiselect("定期テスト科目を選択", HIGH_REGULAR_SUBJECTS)
        st.write("模試受験科目（共通テスト系）")
        mock_selected = st.multiselect("模試受験科目を選択", HIGH_MOCK_SUBJECTS)
        subjects = regular_selected
        mock_subjects = mock_selected
    else:
        # 小学生など → とりあえず中学生と同じ5科目をデフォルトにしておく（必要に応じてカスタマイズ）
        subjects = JUNIOR_SUBJECTS
        mock_subjects = []
        st.write("小学生は暫定的に以下の科目を設定しています：", "、".join(subjects))

    if st.button("生徒を登録", key="register_student"):
        if not name:
            st.error("生徒名を入力してください。")
        else:
            # ★ student_id は generate_new_student_id で一意に決定（削除しても再利用しない前提）
            new_id = generate_new_student_id(students_df)
            new_row = {
                "student_id": str(new_id),
                "name": name,
                "grade": grade,
                "school_name": school_name,
                "target_school": target_school,
                "admission_goal": admission_goal,
                "student_login_id": student_login_id,
                "subjects": json.dumps(subjects, ensure_ascii=False),
                "mock_subjects": json.dumps(mock_subjects, ensure_ascii=False),
                "created_at": datetime.now().isoformat(),
            }
            students_df = pd.concat([students_df, pd.DataFrame([new_row])], ignore_index=True)
            write_sheet_df("students", students_df)
            st.success(f"生徒を登録しました。生徒ID: {new_id}")
            time.sleep(1)
            st.rerun()

    st.markdown("---")
    st.markdown("### 生徒一覧")

    # 最新の生徒データを取得（再読み込み）
    students_df = get_students_df()
    if "student_id" in students_df.columns:
        students_df["student_id"] = students_df["student_id"].astype(str)

    if students_df.empty:
        st.info("まだ生徒が登録されていません。")
    else:
        # 表示するカラムの順番を定義
        display_cols = [
            "student_id",
            "name",
            "grade",
            "school_name",
            "target_school",
            "admission_goal",
            "student_login_id",
            "subjects",
            "mock_subjects",
        ]
        display_cols = [c for c in display_cols if c in students_df.columns]

        df_disp = students_df[display_cols].copy()

        # JSON カラムは見やすいように文字列化（そのまま表示）
        for col in ["subjects", "mock_subjects"]:
            if col in df_disp.columns:
                df_disp[col] = df_disp[col].fillna("").astype(str)

        # カラム名を日本語に変更
        rename_map = {
            "student_id": "生徒ID",
            "name": "生徒名",
            "grade": "学年",
            "school_name": "学校名",
            "target_school": "志望校",
            "admission_goal": "入塾時の目標",
            "student_login_id": "生徒ログインID",
            "subjects": "定期テスト科目",
            "mock_subjects": "模試科目",
        }
        df_disp = df_disp.rename(columns=rename_map)

        st.dataframe(df_disp, use_container_width=True)

    # ----------------------
    # 登録済み生徒の一覧（簡易）
    # ----------------------
    st.markdown("---")
    st.subheader("登録済み生徒一覧（簡易表示）")

    students_df = get_students_df()
    if students_df.empty:
        st.info("生徒が登録されていません。")
        return

    display_df = students_df[["student_id", "name", "grade", "school_name", "target_school"]].copy()
    display_df = display_df.rename(
        columns={
            "student_id": "生徒ID",
            "name": "氏名",
            "grade": "学年",
            "school_name": "在籍校",
            "target_school": "志望校",
        }
    )
    st.dataframe(display_df, use_container_width=True)

    # ----------------------
    # 既存生徒の情報編集（同じIDのまま学年・目標など更新）
    # ----------------------
    st.markdown("---")
    st.subheader("生徒情報の編集（同じIDで学年・目標を更新）")

    if "student_id" in students_df.columns:
        students_df["student_id"] = students_df["student_id"].astype(str)

    edit_options = [
        f'{row["student_id"]} : {row["name"]}'
        for _, row in students_df.iterrows()
    ]

    if not edit_options:
        st.info("編集可能な生徒がいません。")
        return

    selected_label = st.selectbox(
        "編集する生徒を選択",
        edit_options,
        key="edit_student_select",
    )
    selected_id = selected_label.split(" : ")[0]
    target_row = students_df[students_df["student_id"] == selected_id].iloc[0]

    col1, col2 = st.columns(2)

    # ---- 左側：基本情報 ----
    with col1:
        edit_name = st.text_input(
            "氏名",
            value=target_row.get("name", ""),
            key="edit_name",
        )

        current_grade = target_row.get("grade", "")
        if current_grade in GRADE_CHOICES:
            grade_index = GRADE_CHOICES.index(current_grade)
        else:
            grade_index = 0

        edit_grade = st.selectbox(
            "学年",
            GRADE_CHOICES,
            index=grade_index,
            key="edit_grade",
        )

        edit_school_name = st.text_input(
            "在籍校",
            value=target_row.get("school_name", ""),
            key="edit_school_name",
        )

    # ---- 右側：目標など ----
    with col2:
        edit_target_school = st.text_input(
            "志望校",
            value=target_row.get("target_school", ""),
            key="edit_target_school",
        )

        edit_student_login_id = st.text_input(
            "生徒ログインID（任意）",
            value=target_row.get("student_login_id", ""),
            key="edit_student_login_id",
        )

    # 入塾時の目標
    edit_admission_goal = st.text_area(
        "入塾時の目標",
        value=target_row.get("admission_goal", ""),
        height=80,
        key="edit_admission_goal",
    )

    # ---------------- 進級ボタン（単一生徒） ----------------
    st.markdown("#### 学年の自動進級（この生徒だけ）")

    next_grade = promote_grade_value(current_grade)
    if next_grade != current_grade:
        st.write(f"現在の学年: **{current_grade}** → 次の学年候補: **{next_grade}**")
        if st.button("この生徒を進級させる（学年だけ自動更新）", key="promote_single_student"):
            # 表示上の選択を更新
            edit_grade = next_grade
            st.info(f"画面上の学年を「{next_grade}」に変更しました。このあと『生徒情報を更新』を押して保存してください。")
    else:
        st.write(f"現在の学年: **{current_grade}**（進級マップ未設定のため、自動進級はありません）")

    # ---------------- 保存処理 ----------------
    if st.button("生徒情報を更新", key="update_student"):
        idx = students_df[students_df["student_id"] == selected_id].index[0]

        # 同じ student_id のまま、各情報を上書き
        students_df.at[idx, "name"] = edit_name
        students_df.at[idx, "grade"] = edit_grade
        students_df.at[idx, "school_name"] = edit_school_name
        students_df.at[idx, "target_school"] = edit_target_school
        students_df.at[idx, "admission_goal"] = edit_admission_goal
        students_df.at[idx, "student_login_id"] = edit_student_login_id

        write_sheet_df("students", students_df)

        st.success("生徒情報を更新しました。（ID はそのまま、学年・目標のみ変更）")
        time.sleep(0.5)
        st.rerun()

    # ----------------------
    # 学年一括更新（master専用）
    # ----------------------
    if current_role == "master":
        st.markdown("---")
        st.subheader("学年一括更新（年度切り替え）")

        st.info(
            "毎年の年度切り替え時に使う機能です。\n\n"
            "- 例: 小6→中1, 中1→中2, 中2→中3, 中3→高1, 高1→高2, 高2→高3\n"
            "- 進級させたい学年だけを選択して「進級を実行」を押してください。"
        )

        target_grades = st.multiselect(
            "進級させる学年を選択",
            GRADE_CHOICES,
            default=["小6", "中1", "中2", "中3", "高1", "高2"],
        )

        if st.button("上記の学年を一括で進級させる", key="btn_bulk_grade_promotion"):
            if not target_grades:
                st.error("進級対象の学年を1つ以上選択してください。")
            else:
                students_df_all = get_students_df().copy()
                if students_df_all.empty or "grade" not in students_df_all.columns:
                    st.error("生徒データが存在しないか、grade列がありません。")
                else:
                    mask = students_df_all["grade"].isin(target_grades)
                    n_targets = int(mask.sum())

                    if n_targets == 0:
                        st.warning("選択された学年の生徒が見つかりませんでした。")
                    else:
                        students_df_all.loc[mask, "grade"] = students_df_all.loc[mask, "grade"].apply(
                            promote_grade_value
                        )

                        write_sheet_df("students", students_df_all)

                        try:
                            load_sheet_df.clear()
                        except Exception:
                            pass

                        st.success(f"{n_targets} 名の生徒の学年を進級させました。")
                        time.sleep(0.5)
                        st.rerun()

    # ----------------------
    # 生徒削除（masterのみ）
    # ----------------------
    if current_role == "master" and not students_df.empty:
        st.markdown("---")
        st.subheader("生徒削除（master専用）")

        with st.expander("生徒の削除（紐づく成績・日報・英検も削除されます）"):
            delete_labels = [
                f'{row["student_id"]} : {row["name"]}' for _, row in students_df.iterrows()
            ]
            to_delete = st.multiselect("削除対象の生徒を選択", delete_labels)
            admin_password = st.text_input("管理者パスワードを入力", type="password")

            if st.button("選択した生徒を削除", key="delete_students"):
                if not to_delete:
                    st.error("削除対象の生徒を選択してください。")
                elif not admin_password:
                    st.error("管理者パスワードを入力してください。")
                else:
                    users_df = load_sheet_df("users")
                    master_row = users_df[users_df["username"] == "master"]
                    if master_row.empty:
                        st.error("master ユーザーが見つかりません。")
                    else:
                        hashed_pw = master_row.iloc[0]["password_hash"].encode()
                        if not bcrypt.checkpw(admin_password.encode(), hashed_pw):
                            st.error("管理者パスワードが正しくありません。")
                        else:
                            delete_ids = [label.split(" : ")[0] for label in to_delete]

                            # students
                            students_df_new = students_df[~students_df["student_id"].isin(delete_ids)]
                            write_sheet_df("students", students_df_new)

                            # exam_results
                            exam_df = get_exam_results_df()
                            if not exam_df.empty:
                                exam_df = exam_df[~exam_df["student_id"].astype(str).isin(delete_ids)]
                                write_sheet_df("exam_results", exam_df)

                            # coaching_reports
                            coach_df = get_coaching_df()
                            if not coach_df.empty:
                                coach_df = coach_df[~coach_df["student_id"].astype(str).isin(delete_ids)]
                                write_sheet_df("coaching_reports", coach_df)

                            # eiken_records
                            eiken_df = get_eiken_df()
                            if not eiken_df.empty:
                                eiken_df = eiken_df[~eiken_df["student_id"].astype(str).isin(delete_ids)]
                                write_sheet_df("eiken_records", eiken_df)

                            st.success("選択した生徒と紐づくデータを削除しました。")
                            time.sleep(1)
                            st.rerun()


# -----------------
# 成績入力・分析ページ
# -----------------

def page_grade_tracker():
    st.header("成績入力・分析")

    # ログイン中講師情報（成績登録者として保存）
    teacher_username = st.session_state.get("username", "")
    teacher_name = st.session_state.get("name", "")

    students_df = get_students_df()
    if students_df.empty:
        st.info("生徒が登録されていません。先に「生徒管理」で登録してください。")
        return

    # student_id を文字列にそろえる
    if "student_id" in students_df.columns:
        students_df["student_id"] = students_df["student_id"].astype(str)

    # 生徒選択
    student_label = st.selectbox(
        "生徒を選択",
        [f'{row["student_id"]} : {row["name"]}' for _, row in students_df.iterrows()],
    )
    student_id = student_label.split(" : ")[0]

    # 生徒行を特定
    sid = str(student_id)
    filtered = students_df[students_df["student_id"] == sid]
    if filtered.empty:
        st.warning("選択された生徒データが見つかりません。画面を再読み込みしてから再度お試しください。")
        st.stop()
    student_row = filtered.iloc[0]

    # 区分
    exam_category = st.radio("テスト区分", ["定期テスト", "模試"], horizontal=True)

    if exam_category == "定期テスト":
        exam_name = st.selectbox("定期テスト名", REGULAR_EXAM_NAMES)
        # 科目リストは subjects
        try:
            subjects = json.loads(student_row.get("subjects") or "[]")
        except Exception:
            subjects = []
    else:
        exam_name = st.text_input("模試名（自由入力）")
        # 科目リストは mock_subjects
        try:
            subjects = json.loads(student_row.get("mock_subjects") or "[]")
        except Exception:
            subjects = []

    exam_date = st.date_input("実施日", value=date.today())

    if not subjects:
        st.warning("この生徒に登録されている科目がありません。「生徒管理」で科目設定を行ってください。")
        return

    # ----------------- 成績入力 -----------------
    st.markdown("#### 科目別の目標点・結果点")
    results = {}
    for subj in subjects:
        col1, col2 = st.columns(2)
        with col1:
            target = st.number_input(
                f"{subj} の目標点",
                min_value=0,
                max_value=1000,
                value=80,
                key=f"grade_target_{sid}_{subj}",
            )
        with col2:
            score = st.number_input(
                f"{subj} の結果点",
                min_value=0,
                max_value=1000,
                value=0,
                key=f"grade_score_{sid}_{subj}",
            )
        results[subj] = {"target": target, "score": score}

    if st.button("成績を登録", key="grade_save_exam"):
        if exam_category == "模試" and not exam_name:
            st.error("模試名を入力してください。")
        else:
            exam_df = get_exam_results_df()

            # 空シート対策 & カラムそろえ
            if exam_df.empty:
                exam_df = pd.DataFrame(
                    columns=[
                        "id",
                        "student_id",
                        "exam_category",
                        "exam_name",
                        "date",
                        "results_json",
                        "created_at",
                        "teacher_username",
                        "teacher_name",
                    ]
                )
            else:
                # 足りないカラムがあれば追加
                for col in [
                    "id",
                    "student_id",
                    "exam_category",
                    "exam_name",
                    "date",
                    "results_json",
                    "created_at",
                    "teacher_username",
                    "teacher_name",
                ]:
                    if col not in exam_df.columns:
                        exam_df[col] = ""

            # ID 採番
            if exam_df["id"].astype(str).str.strip().eq("").all():
                new_id = 1
            else:
                ids = []
                for v in exam_df["id"]:
                    try:
                        ids.append(int(v))
                    except Exception:
                        pass
                new_id = (max(ids) + 1) if ids else 1

            new_row = {
                "id": str(new_id),
                "student_id": str(student_id),
                "exam_category": exam_category,
                "exam_name": exam_name,
                "date": exam_date.isoformat(),
                "results_json": json.dumps(results, ensure_ascii=False),
                "created_at": datetime.now().isoformat(),
                "teacher_username": teacher_username,
                "teacher_name": teacher_name,
            }
            exam_df = pd.concat([exam_df, pd.DataFrame([new_row])], ignore_index=True)
            write_sheet_df("exam_results", exam_df)

            # キャッシュクリアして即反映
            try:
                load_sheet_df.clear()
            except Exception:
                pass
            try:
                load_all_tables.clear()
            except Exception:
                pass

            st.success("成績を登録しました。")
            time.sleep(0.5)
            st.rerun()

    st.markdown("---")
    st.subheader("成績推移")

    # ----------------- 成績表示・グラフ -----------------
    exam_df_all = get_exam_results_df()
    if exam_df_all.empty:
        st.info("この生徒の成績データはまだ登録されていません。")
        return

    # student_id を文字列でそろえてフィルタ
    if "student_id" in exam_df_all.columns:
        exam_df_all["student_id"] = exam_df_all["student_id"].astype(str)
    exam_df = exam_df_all[exam_df_all["student_id"] == str(student_id)].copy()

    if exam_df.empty:
        st.info("この生徒の成績データはまだ登録されていません。")
        return

    # 日付でソート
    if "date" in exam_df.columns:
        exam_df["date_dt"] = pd.to_datetime(exam_df["date"], errors="coerce")
        exam_df = exam_df.sort_values(["date_dt", "exam_category", "exam_name"])
    else:
        exam_df["date_dt"] = pd.NaT

    # 合計点の推移 & 科目別推移
    dates = []
    total_scores = []
    total_targets = []
    subject_scores_dict = {}  # subj -> {"x": [], "y": []}

    for _, row in exam_df.iterrows():
        d = row.get("date", "")
        label = f'{d} {row.get("exam_name", "")}'
        dates.append(label)

        try:
            r = json.loads(row.get("results_json") or "{}")
        except Exception:
            r = {}
        t_score = 0
        t_target = 0
        for subj, vals in r.items():
            score = vals.get("score", 0)
            target = vals.get("target", 0)
            t_score += score
            t_target += target

            if subj not in subject_scores_dict:
                subject_scores_dict[subj] = {"x": [], "y": []}
            subject_scores_dict[subj]["x"].append(label)
            subject_scores_dict[subj]["y"].append(score)

        total_scores.append(t_score)
        total_targets.append(t_target)

    st.markdown("##### 合計点の推移（全年度）")
    fig_total = go.Figure()
    fig_total.add_trace(go.Scatter(x=dates, y=total_scores, mode="lines+markers", name="合計点"))
    fig_total.add_trace(
        go.Scatter(
            x=dates,
            y=total_targets,
            mode="lines+markers",
            name="目標合計",
            line=dict(dash="dash"),
        )
    )
    fig_total.update_layout(xaxis_title="テスト", yaxis_title="得点", legend_title="項目")
    st.plotly_chart(fig_total, use_container_width=True)

    st.markdown("##### 科目別の推移")
    fig_subj = go.Figure()
    for subj, data in subject_scores_dict.items():
        fig_subj.add_trace(
            go.Scatter(x=data["x"], y=data["y"], mode="lines+markers", name=subj)
        )
    fig_subj.update_layout(xaxis_title="テスト", yaxis_title="得点", legend_title="科目")
    st.plotly_chart(fig_subj, use_container_width=True)

    # ----------------- 成績編集 -----------------
    st.markdown("---")
    st.subheader("登録済み成績の編集")

    if "id" not in exam_df.columns:
        st.info("編集可能な成績データがありません。")
    else:
        exam_df["id"] = exam_df["id"].astype(str)
        edit_options = [
            f'{row["id"]} : {row.get("date","")} {row.get("exam_category","")} {row.get("exam_name","")}'
            for _, row in exam_df.iterrows()
        ]

        if not edit_options:
            st.info("編集可能な成績データがありません。")
        else:
            selected_edit = st.selectbox(
                "編集するテストを選択",
                [""] + edit_options,
                key=f"grade_edit_exam_select_{student_id}",
            )

            if selected_edit:
                edit_id = selected_edit.split(" : ")[0]
                target_row = exam_df[exam_df["id"] == edit_id].iloc[0]

                st.markdown("#### 成績内容を編集")

                # 区分
                current_cat = target_row.get("exam_category", "定期テスト")
                edit_exam_category = st.radio(
                    "テスト区分（編集）",
                    ["定期テスト", "模試"],
                    index=0 if current_cat == "定期テスト" else 1,
                    horizontal=True,
                    key=f"edit_exam_category_{edit_id}",
                )

                # テスト名
                if edit_exam_category == "定期テスト":
                    current_name = target_row.get("exam_name", "")
                    if current_name in REGULAR_EXAM_NAMES:
                        idx = REGULAR_EXAM_NAMES.index(current_name)
                    else:
                        idx = 0
                    edit_exam_name = st.selectbox(
                        "定期テスト名（編集）",
                        REGULAR_EXAM_NAMES,
                        index=idx,
                        key=f"edit_exam_name_{edit_id}",
                    )
                else:
                    edit_exam_name = st.text_input(
                        "模試名（編集）",
                        value=target_row.get("exam_name", ""),
                        key=f"edit_exam_name_{edit_id}",
                    )

                # 実施日
                try:
                    edit_exam_date_val = datetime.fromisoformat(
                        target_row.get("date", "")
                    ).date()
                except Exception:
                    edit_exam_date_val = date.today()
                edit_exam_date = st.date_input(
                    "実施日（編集）",
                    value=edit_exam_date_val,
                    key=f"edit_exam_date_{edit_id}",
                )

                # 科目別の点数
                try:
                    res = json.loads(target_row.get("results_json") or "{}")
                except Exception:
                    res = {}

                edit_results = {}
                st.markdown("##### 科目別の目標点・結果点（編集）")
                for subj, vals in res.items():
                    col1, col2 = st.columns(2)
                    with col1:
                        t_val = int(vals.get("target", 0) or 0)
                        target_edit = st.number_input(
                            f"{subj} の目標点（編集）",
                            min_value=0,
                            max_value=1000,
                            value=t_val,
                            key=f"edit_grade_target_{edit_id}_{subj}",
                        )
                    with col2:
                        s_val = int(vals.get("score", 0) or 0)
                        score_edit = st.number_input(
                            f"{subj} の結果点（編集）",
                            min_value=0,
                            max_value=1000,
                            value=s_val,
                            key=f"edit_grade_score_{edit_id}_{subj}",
                        )
                    edit_results[subj] = {"target": target_edit, "score": score_edit}

                if st.button("この成績を更新", key=f"btn_update_exam_{edit_id}"):
                    exam_all = get_exam_results_df()
                    if exam_all.empty or "id" not in exam_all.columns:
                        st.error("成績データが見つかりませんでした。")
                    else:
                        exam_all["id"] = exam_all["id"].astype(str)
                        mask = exam_all["id"] == edit_id
                        if not mask.any():
                            st.error("対象の成績データが見つかりませんでした。")
                        else:
                            idx = exam_all[mask].index[0]
                            exam_all.at[idx, "exam_category"] = edit_exam_category
                            exam_all.at[idx, "exam_name"] = edit_exam_name
                            exam_all.at[idx, "date"] = edit_exam_date.isoformat()
                            exam_all.at[idx, "results_json"] = json.dumps(
                                edit_results, ensure_ascii=False
                            )
                            # 更新者を現在ログイン中の講師で上書き
                            exam_all.at[idx, "teacher_username"] = teacher_username
                            exam_all.at[idx, "teacher_name"] = teacher_name

                            write_sheet_df("exam_results", exam_all)
                            try:
                                load_sheet_df.clear()
                            except Exception:
                                pass
                            try:
                                load_all_tables.clear()
                            except Exception:
                                pass

                            st.success("成績データを更新しました。")
                            time.sleep(1)
                            st.rerun()

    # ----------------- 成績一覧表（テストごと横向き） -----------------
    st.markdown("##### 成績一覧（テストごとの得点）")

    # 1テスト (=1行) ずつ表示
    for _, exam_row in exam_df.iterrows():
        exam_label = f'{exam_row.get("date","")} {exam_row.get("exam_category","")} {exam_row.get("exam_name","")}'
        st.markdown(f"**{exam_label}**")

        try:
            res = json.loads(exam_row.get("results_json") or "{}")
        except Exception:
            res = {}

        if not res:
            st.write("（科目データなし）")
            continue

        subjects = []
        scores = []
        for subj, vals in res.items():
            subjects.append(subj)
            scores.append(vals.get("score", 0))

        df_exam = pd.DataFrame([scores], columns=subjects)
        df_exam.index = ["得点"]
        st.table(df_exam)
        st.markdown("")  # 余白

    # ----------------- 成績削除 -----------------
    with st.expander("成績データの削除"):
        unique_exams = exam_df[["id", "date", "exam_name", "exam_category"]].drop_duplicates()

        delete_options = [
            f'{row["id"]} : {row["date"]} {row["exam_category"]} {row["exam_name"]}'
            for _, row in unique_exams.iterrows()
        ]

        selected_delete = st.selectbox(
            "削除するテストを選択",
            [""] + delete_options,
            key=f"grade_delete_exam_select_{student_id}",
        )

        if st.button(
            "選択した成績を削除",
            key=f"grade_delete_exam_button_{student_id}",
        ):
            if not selected_delete:
                st.error("削除対象を選択してください。")
            else:
                del_id = selected_delete.split(" : ")[0]

                exam_df_all2 = get_exam_results_df()
                if exam_df_all2.empty or "id" not in exam_df_all2.columns:
                    st.error("成績データが見つかりませんでした。")
                else:
                    exam_df_all2["id"] = exam_df_all2["id"].astype(str)
                    exam_df_all2 = exam_df_all2[exam_df_all2["id"] != del_id]
                    write_sheet_df("exam_results", exam_df_all2)

                    try:
                        load_sheet_df.clear()
                    except Exception:
                        pass
                    try:
                        load_all_tables.clear()
                    except Exception:
                        pass

                    st.success("成績データを削除しました。")
                    time.sleep(1)
                    st.rerun()




# -----------------
# 授業日報・コーチング
# -----------------

def page_coaching():
    st.header("授業日報・コーチング")

    # ログイン中講師情報（誰が日報を書いたか保存）
    teacher_username = st.session_state.get("username", "")
    teacher_name = st.session_state.get("name", "")

    students_df = get_students_df()
    if students_df.empty:
        st.info("生徒が登録されていません。")
        return

    # student_id を文字列にそろえる
    if "student_id" in students_df.columns:
        students_df["student_id"] = students_df["student_id"].astype(str)

    # 生徒選択
    student_label = st.selectbox(
        "生徒を選択",
        [f'{row["student_id"]} : {row["name"]}' for _, row in students_df.iterrows()],
    )
    student_id = student_label.split(" : ")[0]
    student_name = student_label.split(" : ")[1]

    # 日付（新規入力用）
    today = date.today()
    report_date = st.date_input("日付", value=today)
    date_str = report_date.isoformat()

    # この生徒の既存日報
    coaching_df = get_coaching_df()
    if not coaching_df.empty and "student_id" in coaching_df.columns:
        coaching_df["student_id"] = coaching_df["student_id"].astype(str)
        coaching_df_student = coaching_df[coaching_df["student_id"] == str(student_id)]
    else:
        coaching_df_student = pd.DataFrame()

    # 前回の目標表示
    st.subheader("前回までの自習計画・目標（最新）")
    if coaching_df_student.empty:
        st.info("まだ日報が登録されていません。")
    else:
        latest_row = coaching_df_student.sort_values("date").iloc[-1]
        try:
            prev_schedule = json.loads(latest_row.get("study_schedule_json") or "{}")
        except Exception:
            prev_schedule = {}
        try:
            prev_targets = json.loads(latest_row.get("study_targets_json") or "[]")
        except Exception:
            prev_targets = []

        st.markdown("**前回の自習予定（曜日と時間）**")
        if prev_schedule:
            for day, hrs in prev_schedule.items():
                st.write(f"- {day} : {hrs} 時間")
        else:
            st.write("登録なし")

        st.markdown("**前回の自習目標**")
        if prev_targets:
            for i, t in enumerate(prev_targets, start=1):
                if t:
                    st.write(f"- 目標{i}: {t}")
        else:
            st.write("登録なし")

    st.markdown("---")
    st.subheader("今回の授業日報入力（新規・同日上書き）")

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("**生徒自己評価 (1〜5)**")
        stu_understanding = st.slider("授業理解度", 1, 5, 3)
        stu_goal = st.slider("目標達成度", 1, 5, 3)
        stu_motivation = st.slider("モチベーション", 1, 5, 3)

    with col2:
        st.markdown("**講師評価 (1〜5)**")
        tch_attitude = st.slider("授業態度", 1, 5, 3)
        tch_homework = st.slider("宿題完成度", 1, 5, 3)
        tch_prev_understand = st.slider("前回理解度", 1, 5, 3)

    teacher_comment = st.text_area("講師コメント（100字目安）", height=80)

    st.markdown("#### 次回までの自習予定（曜日と時間）")
    selected_days = st.multiselect("勉強する曜日を選択", DAYS_JP)
    schedule_dict = {}
    for d in selected_days:
        hrs = st.number_input(
            f"{d}曜日の目標勉強時間（時間）",
            min_value=0.0,
            max_value=24.0,
            value=1.0,
            step=0.5,
            key=f"hrs_{d}",
        )
        schedule_dict[d] = hrs

    st.markdown("#### 次回までの自習目標（内容）")
    target1 = st.text_input("目標1（例：英単語100個）")
    target2 = st.text_input("目標2")
    target3 = st.text_input("目標3")
    targets_list = [target1, target2, target3]

    # ------------- 保存処理（新規 or 同日上書き）-------------
    if st.button("日報を保存", key="save_coaching"):
        student_eval = {
            "理解度": stu_understanding,
            "目標達成度": stu_goal,
            "モチベーション": stu_motivation,
        }
        teacher_eval = {
            "授業態度": tch_attitude,
            "宿題完成度": tch_homework,
            "前回理解度": tch_prev_understand,
            "コメント": teacher_comment,
        }

        coaching_df_all = get_coaching_df()
        # 空シート対策
        if coaching_df_all.empty:
            coaching_df_all = pd.DataFrame(
                columns=[
                    "id",
                    "student_id",
                    "date",
                    "student_eval_json",
                    "teacher_eval_json",
                    "study_schedule_json",
                    "study_targets_json",
                    "created_at",
                    "updated_at",
                    "teacher_username",
                    "teacher_name",
                ]
            )
        else:
            # 足りないカラムを追加
            for col in [
                "id",
                "student_id",
                "date",
                "student_eval_json",
                "teacher_eval_json",
                "study_schedule_json",
                "study_targets_json",
                "created_at",
                "updated_at",
                "teacher_username",
                "teacher_name",
            ]:
                if col not in coaching_df_all.columns:
                    coaching_df_all[col] = ""

        # 型をそろえる
        if "student_id" in coaching_df_all.columns:
            coaching_df_all["student_id"] = coaching_df_all["student_id"].astype(str)

        # 同一生徒・同一日付があるか確認
        mask = (coaching_df_all["student_id"] == str(student_id)) & (
            coaching_df_all["date"] == date_str
        )

        now_str = datetime.now().isoformat()

        if mask.any():
            # UPDATE
            idx = coaching_df_all[mask].index[0]
            coaching_df_all.at[idx, "student_eval_json"] = json.dumps(student_eval, ensure_ascii=False)
            coaching_df_all.at[idx, "teacher_eval_json"] = json.dumps(teacher_eval, ensure_ascii=False)
            coaching_df_all.at[idx, "study_schedule_json"] = json.dumps(schedule_dict, ensure_ascii=False)
            coaching_df_all.at[idx, "study_targets_json"] = json.dumps(targets_list, ensure_ascii=False)
            coaching_df_all.at[idx, "updated_at"] = now_str
            coaching_df_all.at[idx, "teacher_username"] = teacher_username
            coaching_df_all.at[idx, "teacher_name"] = teacher_name
            msg = "同日のデータが存在したため、上書き保存しました。"
            show = st.warning
        else:
            # 新規 ID 採番
            if "id" not in coaching_df_all.columns:
                coaching_df_all["id"] = ""

            if coaching_df_all["id"].astype(str).str.strip().eq("").all():
                new_id = 1
            else:
                ids = []
                for v in coaching_df_all["id"]:
                    try:
                        ids.append(int(v))
                    except Exception:
                        pass
                new_id = (max(ids) + 1) if ids else 1

            new_row = {
                "id": str(new_id),
                "student_id": str(student_id),
                "date": date_str,
                "student_eval_json": json.dumps(student_eval, ensure_ascii=False),
                "teacher_eval_json": json.dumps(teacher_eval, ensure_ascii=False),
                "study_schedule_json": json.dumps(schedule_dict, ensure_ascii=False),
                "study_targets_json": json.dumps(targets_list, ensure_ascii=False),
                "created_at": now_str,
                "updated_at": now_str,
                "teacher_username": teacher_username,
                "teacher_name": teacher_name,
            }
            coaching_df_all = pd.concat([coaching_df_all, pd.DataFrame([new_row])], ignore_index=True)
            msg = "保存しました。"
            show = st.success

        write_sheet_df("coaching_reports", coaching_df_all)

        # キャッシュをクリアして即反映
        try:
            load_sheet_df.clear()
        except Exception:
            pass
        try:
            load_all_tables.clear()
        except Exception:
            pass

        show(msg)
        time.sleep(0.5)
        st.rerun()

    # ------------- 編集機能（既存日報の編集）-------------
    st.markdown("---")
    st.subheader("登録済み日報の編集")

    coaching_df = get_coaching_df()
    if not coaching_df.empty and "student_id" in coaching_df.columns:
        coaching_df["student_id"] = coaching_df["student_id"].astype(str)
        coaching_df_student = coaching_df[coaching_df["student_id"] == str(student_id)].sort_values(
            "date", ascending=False
        )
        if "id" in coaching_df_student.columns:
            coaching_df_student = coaching_df_student.copy()
            coaching_df_student["id"] = coaching_df_student["id"].astype(str)
    else:
        coaching_df_student = pd.DataFrame()

    if coaching_df_student.empty or "id" not in coaching_df_student.columns:
        st.info("編集可能な日報データがありません。")
    else:
        edit_options = [
            f'{row["id"]} : {row["date"]}' for _, row in coaching_df_student.iterrows()
        ]
        selected_edit = st.selectbox(
            "編集する日報を選択",
            [""] + edit_options,
            key=f"edit_coaching_select_{student_id}",
        )

        if selected_edit:
            edit_id = selected_edit.split(" : ")[0]
            target_row = coaching_df_student[coaching_df_student["id"] == edit_id].iloc[0]

            st.markdown("### 日報内容を編集")

            # 日付（編集）
            try:
                edit_date_val = datetime.fromisoformat(target_row.get("date", "")).date()
            except Exception:
                edit_date_val = date.today()
            edit_report_date = st.date_input(
                "日付（編集）",
                value=edit_date_val,
                key=f"edit_report_date_{edit_id}",
            )

            # JSON → 辞書
            try:
                se = json.loads(target_row.get("student_eval_json") or "{}")
            except Exception:
                se = {}
            try:
                te = json.loads(target_row.get("teacher_eval_json") or "{}")
            except Exception:
                te = {}
            try:
                schedule_old = json.loads(target_row.get("study_schedule_json") or "{}")
            except Exception:
                schedule_old = {}
            try:
                targets_old = json.loads(target_row.get("study_targets_json") or "[]")
            except Exception:
                targets_old = []

            # 安全に int 変換
            def _to_int(v, default=3):
                try:
                    return int(v)
                except Exception:
                    return default

            col1, col2 = st.columns(2)
            with col1:
                st.markdown("**生徒自己評価 (1〜5)（編集）**")
                edit_stu_understanding = st.slider(
                    "授業理解度（編集）",
                    1, 5,
                    _to_int(se.get("理解度", 3)),
                    key=f"edit_stu_understanding_{edit_id}",
                )
                edit_stu_goal = st.slider(
                    "目標達成度（編集）",
                    1, 5,
                    _to_int(se.get("目標達成度", 3)),
                    key=f"edit_stu_goal_{edit_id}",
                )
                edit_stu_motivation = st.slider(
                    "モチベーション（編集）",
                    1, 5,
                    _to_int(se.get("モチベーション", 3)),
                    key=f"edit_stu_motivation_{edit_id}",
                )

            with col2:
                st.markdown("**講師評価 (1〜5)（編集）**")
                edit_tch_attitude = st.slider(
                    "授業態度（編集）",
                    1, 5,
                    _to_int(te.get("授業態度", 3)),
                    key=f"edit_tch_attitude_{edit_id}",
                )
                edit_tch_homework = st.slider(
                    "宿題完成度（編集）",
                    1, 5,
                    _to_int(te.get("宿題完成度", 3)),
                    key=f"edit_tch_homework_{edit_id}",
                )
                edit_tch_prev_understand = st.slider(
                    "前回理解度（編集）",
                    1, 5,
                    _to_int(te.get("前回理解度", 3)),
                    key=f"edit_tch_prev_understand_{edit_id}",
                )

            edit_teacher_comment = st.text_area(
                "講師コメント（編集）",
                value=te.get("コメント", ""),
                height=80,
                key=f"edit_teacher_comment_{edit_id}",
            )

            st.markdown("#### 次回までの自習予定（編集）")
            # もともと時間が入っていた曜日を初期選択
            default_days = [d for d in DAYS_JP if d in (schedule_old or {})]
            edit_selected_days = st.multiselect(
                "勉強する曜日を選択（編集）",
                DAYS_JP,
                default=default_days,
                key=f"edit_days_{edit_id}",
            )
            edit_schedule_dict = {}
            for d in edit_selected_days:
                default_hr = 1.0
                if schedule_old and d in schedule_old:
                    try:
                        default_hr = float(schedule_old[d])
                    except Exception:
                        default_hr = 1.0
                hrs = st.number_input(
                    f"{d}曜日の目標勉強時間（時間）（編集）",
                    min_value=0.0,
                    max_value=24.0,
                    value=default_hr,
                    step=0.5,
                    key=f"edit_hrs_{edit_id}_{d}",
                )
                edit_schedule_dict[d] = hrs

            st.markdown("#### 次回までの自習目標（編集）")
            t1_old = targets_old[0] if len(targets_old) > 0 else ""
            t2_old = targets_old[1] if len(targets_old) > 1 else ""
            t3_old = targets_old[2] if len(targets_old) > 2 else ""

            edit_target1 = st.text_input(
                "目標1（編集）",
                value=t1_old,
                key=f"edit_target1_{edit_id}",
            )
            edit_target2 = st.text_input(
                "目標2（編集）",
                value=t2_old,
                key=f"edit_target2_{edit_id}",
            )
            edit_target3 = st.text_input(
                "目標3（編集）",
                value=t3_old,
                key=f"edit_target3_{edit_id}",
            )
            edit_targets_list = [edit_target1, edit_target2, edit_target3]

            if st.button("この日報を更新", key=f"btn_update_coaching_{edit_id}"):
                # 更新用の dict
                new_student_eval = {
                    "理解度": edit_stu_understanding,
                    "目標達成度": edit_stu_goal,
                    "モチベーション": edit_stu_motivation,
                }
                new_teacher_eval = {
                    "授業態度": edit_tch_attitude,
                    "宿題完成度": edit_tch_homework,
                    "前回理解度": edit_tch_prev_understand,
                    "コメント": edit_teacher_comment,
                }

                coaching_all = get_coaching_df()
                if coaching_all.empty or "id" not in coaching_all.columns:
                    st.error("日報データが見つかりませんでした。")
                else:
                    coaching_all["id"] = coaching_all["id"].astype(str)
                    mask_all = coaching_all["id"] == edit_id
                    if not mask_all.any():
                        st.error("対象の日報データが見つかりませんでした。")
                    else:
                        idx_all = coaching_all[mask_all].index[0]
                        coaching_all.at[idx_all, "date"] = edit_report_date.isoformat()
                        coaching_all.at[idx_all, "student_eval_json"] = json.dumps(
                            new_student_eval, ensure_ascii=False
                        )
                        coaching_all.at[idx_all, "teacher_eval_json"] = json.dumps(
                            new_teacher_eval, ensure_ascii=False
                        )
                        coaching_all.at[idx_all, "study_schedule_json"] = json.dumps(
                            edit_schedule_dict, ensure_ascii=False
                        )
                        coaching_all.at[idx_all, "study_targets_json"] = json.dumps(
                            edit_targets_list, ensure_ascii=False
                        )
                        coaching_all.at[idx_all, "updated_at"] = datetime.now().isoformat()
                        coaching_all.at[idx_all, "teacher_username"] = teacher_username
                        coaching_all.at[idx_all, "teacher_name"] = teacher_name

                        write_sheet_df("coaching_reports", coaching_all)
                        try:
                            load_sheet_df.clear()
                        except Exception:
                            pass
                        try:
                            load_all_tables.clear()
                        except Exception:
                            pass

                        st.success("日報データを更新しました。")
                        time.sleep(1)
                        st.rerun()

    # ------------- 過去の日報履歴（閲覧）-------------
    st.markdown("---")
    st.subheader("過去の日報履歴")

    coaching_df = get_coaching_df()
    if not coaching_df.empty and "student_id" in coaching_df.columns:
        coaching_df["student_id"] = coaching_df["student_id"].astype(str)
        coaching_df_student = coaching_df[coaching_df["student_id"] == str(student_id)].sort_values(
            "date", ascending=False
        )
    else:
        coaching_df_student = pd.DataFrame()

    if coaching_df_student.empty:
        st.info("この生徒の日報はまだ登録されていません。")
    else:
        for _, row in coaching_df_student.iterrows():
            d = row["date"]
            st.markdown(f"### {d} の日報")

            # JSON → 辞書
            try:
                se = json.loads(row.get("student_eval_json") or "{}")
            except Exception:
                se = {}
            try:
                te = json.loads(row.get("teacher_eval_json") or "{}")
            except Exception:
                te = {}

            col1, col2 = st.columns(2)

            # 生徒自己評価
            with col1:
                st.markdown("**生徒自己評価 (1〜5)**")
                st.write(f"- 授業理解度　： {se.get('理解度', '-')}")
                st.write(f"- 目標達成度　： {se.get('目標達成度', '-')}")
                st.write(f"- モチベーション： {se.get('モチベーション', '-')}")

            # 講師評価
            with col2:
                st.markdown("**講師評価 (1〜5)**")
                st.write(f"- 授業態度　　： {te.get('授業態度', '-')}")
                st.write(f"- 宿題完成度　： {te.get('宿題完成度', '-')}")
                st.write(f"- 前回理解度　： {te.get('前回理解度', '-')}")

            # コメント
            st.markdown("**講師コメント**")
            st.write(te.get("コメント", "（コメントなし）"))

            # 担当講師（保存されていれば表示）
            t_name = row.get("teacher_name", "")
            if t_name:
                st.caption(f"担当講師：{t_name}")

            st.markdown("---")

    # ------------- 日報削除 -------------
    with st.expander("日報の削除"):
        delete_options = [
            f'{row["id"]} : {row["date"]}' for _, row in coaching_df_student.iterrows()
        ]
        selected_delete = st.selectbox(
            "削除する日報を選択",
            [""] + delete_options,
            key=f"delete_coaching_select_{student_id}",
        )
        if st.button("選択した日報を削除", key=f"delete_coaching_button_{student_id}"):
            if not selected_delete:
                st.error("削除対象を選択してください。")
            else:
                del_id = selected_delete.split(" : ")[0]
                coaching_df_all = get_coaching_df()
                if not coaching_df_all.empty and "id" in coaching_df_all.columns:
                    coaching_df_all["id"] = coaching_df_all["id"].astype(str)
                    coaching_df_all = coaching_df_all[coaching_df_all["id"] != del_id]
                    write_sheet_df("coaching_reports", coaching_df_all)
                    try:
                        load_sheet_df.clear()
                    except Exception:
                        pass
                    try:
                        load_all_tables.clear()
                    except Exception:
                        pass
                    st.success("日報を削除しました。")
                    time.sleep(1)
                    st.rerun()
                else:
                    st.error("日報データが見つかりませんでした。")


# -----------------
# 英検対策ページ
# -----------------

def page_eiken():
    st.header("英検対策")

    # ログイン中講師情報（誰が記録したかを保存）
    teacher_username = st.session_state.get("username", "")
    teacher_name = st.session_state.get("name", "")

    students_df = get_students_df()
    if students_df.empty:
        st.info("生徒が登録されていません。")
        return

    # student_id を文字列に統一
    if "student_id" in students_df.columns:
        students_df["student_id"] = students_df["student_id"].astype(str)

    student_label = st.selectbox(
        "生徒を選択",
        [f'{row["student_id"]} : {row["name"]}' for _, row in students_df.iterrows()],
    )
    student_id = student_label.split(" : ")[0]
    student_name = student_label.split(" : ")[1]

    # ---------------- A. 目標級・本番受験日の設定 ----------------
    eiken_df = get_eiken_df()
    if not eiken_df.empty and "student_id" in eiken_df.columns:
        eiken_df["student_id"] = eiken_df["student_id"].astype(str)
        eiken_df_student = eiken_df[eiken_df["student_id"] == str(student_id)].sort_values(
            "practice_date"
        )
    else:
        eiken_df_student = pd.DataFrame()

    st.subheader("A. 目標級・本番受験日の設定")

    # 最新の設定を取得
    target_grade = ""
    exam_date_str = ""
    if not eiken_df_student.empty:
        last = eiken_df_student.iloc[-1]
        target_grade = last.get("target_grade", "")
        exam_date_str = last.get("exam_date", "")

    selected_grade = st.selectbox(
        "目標級",
        EIKEN_GRADES,
        index=EIKEN_GRADES.index(target_grade) if target_grade in EIKEN_GRADES else 2,
    )

    exam_date_input = st.date_input(
        "本番受験日",
        value=datetime.fromisoformat(exam_date_str).date() if exam_date_str else date.today(),
    )

    st.markdown("※ この設定は次の演習記録にも引き継がれます（保護者レポートでも使用されます）。")

    # この級の問題数／満点を取得（5級〜1級ごとに EIKEN_TOTALS で定義しておく）
    totals = EIKEN_TOTALS.get(selected_grade, {})
    rd_total = totals.get("reading", 0)
    ls_total = totals.get("listening", 0)
    wr_total = totals.get("writing", 0)    # 級ごとの満点
    sp_total = totals.get("speaking", 0)   # 級ごとの満点

    # ---------------- B. 過去問・演習レコーダー ----------------
    st.markdown("---")
    st.subheader("B. 過去問・演習レコーダー")

    practice_date = st.date_input("演習日", value=date.today())
    category = st.text_input("実施内容（例：2023年度第1回 過去問）")

    st.markdown("#### 技能別の結果入力（正解数／得点のみ入力）")

    col1, col2 = st.columns(2)
    with col1:
        st.write(f"**Reading（全 {rd_total} 問中）**" if rd_total else "**Reading**")
        rd_correct = st.number_input(
            "Reading 正解数",
            min_value=0,
            max_value=rd_total if rd_total > 0 else 100,
            value=0,
            key="eiken_rd_correct",
        )
        rd_rate = (rd_correct / rd_total * 100) if rd_total else 0
        st.caption(f"正答率：{rd_rate:.1f} %")

        st.write(f"**Listening（全 {ls_total} 問中）**" if ls_total else "**Listening**")
        ls_correct = st.number_input(
            "Listening 正解数",
            min_value=0,
            max_value=ls_total if ls_total > 0 else 100,
            value=0,
            key="eiken_ls_correct",
        )
        ls_rate = (ls_correct / ls_total * 100) if ls_total else 0
        st.caption(f"正答率：{ls_rate:.1f} %")

    with col2:
        st.write(f"**Writing（満点 {wr_total} 点）**" if wr_total else "**Writing**")
        wr_correct = st.number_input(
            "Writing 得点",
            min_value=0,
            max_value=wr_total if wr_total > 0 else 100,
            value=0,
            key="eiken_wr_correct",
        )
        wr_rate = (wr_correct / wr_total * 100) if wr_total else 0
        st.caption(f"正答率：{wr_rate:.1f} %")

        st.write(f"**Speaking（満点 {sp_total} 点）**" if sp_total else "**Speaking**")
        sp_correct = st.number_input(
            "Speaking 得点",
            min_value=0,
            max_value=sp_total if sp_total > 0 else 100,
            value=0,
            key="eiken_sp_correct",
        )
        sp_rate = (sp_correct / sp_total * 100) if sp_total else 0
        st.caption(f"正答率：{sp_rate:.1f} %")

    # ---------------- 保存処理（新規） ----------------
    if st.button("演習記録を保存", key="save_eiken"):
        eiken_all = get_eiken_df()

        # 空シート対策 ＋ カラム保証（teacher_xxx も含める）
        base_cols = [
            "id",
            "student_id",
            "target_grade",
            "exam_date",
            "practice_date",
            "category",
            "scores_json",
            "created_at",
            "updated_at",
            "teacher_username",
            "teacher_name",
        ]
        if eiken_all.empty:
            eiken_all = pd.DataFrame(columns=base_cols)
        else:
            for c in base_cols:
                if c not in eiken_all.columns:
                    eiken_all[c] = ""

        # ID カラムを保証
        if "id" not in eiken_all.columns:
            eiken_all["id"] = ""

        # ID 採番
        if eiken_all["id"].astype(str).str.strip().eq("").all():
            new_id = 1
        else:
            ids = []
            for v in eiken_all["id"]:
                try:
                    ids.append(int(v))
                except Exception:
                    pass
            new_id = (max(ids) + 1) if ids else 1

        now_str = datetime.now().isoformat()

        # 保存するスコア（4技能すべて「correct / total」形式）
        scores = {
            "reading":   {"correct": rd_correct, "total": rd_total},
            "listening": {"correct": ls_correct, "total": ls_total},
            "writing":   {"correct": wr_correct, "total": wr_total},
            "speaking":  {"correct": sp_correct, "total": sp_total},
        }

        new_row = {
            "id": str(new_id),
            "student_id": str(student_id),
            "target_grade": selected_grade,
            "exam_date": exam_date_input.isoformat(),
            "practice_date": practice_date.isoformat(),
            "category": category,
            "scores_json": json.dumps(scores, ensure_ascii=False),
            "created_at": now_str,
            "updated_at": now_str,
            "teacher_username": teacher_username,
            "teacher_name": teacher_name,
        }
        eiken_all = pd.concat([eiken_all, pd.DataFrame([new_row])], ignore_index=True)
        write_sheet_df("eiken_records", eiken_all)

        # キャッシュクリアして即反映
        try:
            load_all_tables.clear()
        except Exception:
            pass
        try:
            load_sheet_df.clear()
        except Exception:
            pass

        st.success("英検演習記録を保存しました。")
        time.sleep(0.5)
        st.rerun()

    # ---------------- C. 分析・推移 ----------------
    st.markdown("---")
    st.subheader("C. 分析・推移")

    eiken_df = get_eiken_df()
    if not eiken_df.empty and "student_id" in eiken_df.columns:
        eiken_df["student_id"] = eiken_df["student_id"].astype(str)
        eiken_df_student = eiken_df[eiken_df["student_id"] == str(student_id)].sort_values(
            "practice_date"
        )
        if "id" in eiken_df_student.columns:
            eiken_df_student = eiken_df_student.copy()
            eiken_df_student["id"] = eiken_df_student["id"].astype(str)
    else:
        eiken_df_student = pd.DataFrame()

    if eiken_df_student.empty:
        st.info("この生徒の英検演習記録はまだありません。")
    else:
        rows = []
        x_labels = []
        rd_rates = []
        ls_rates = []
        wr_rates = []
        sp_rates = []

        for _, row in eiken_df_student.iterrows():
            try:
                s = json.loads(row.get("scores_json") or "{}")
            except Exception:
                s = {}

            # 4技能の正解数・正答率
            def get_rate(skill_key):
                info = s.get(skill_key, {}) or {}
                c = info.get("correct", 0)
                t = info.get("total", 0)
                rate = (c / t * 100) if t else 0
                return c, t, rate

            rd_c, rd_t, rd_r = get_rate("reading")
            ls_c, ls_t, ls_r = get_rate("listening")
            wr_c, wr_t, wr_r = get_rate("writing")
            sp_c, sp_t, sp_r = get_rate("speaking")

            # 横軸のラベル：日付のみ（時刻なし）
            p_raw = row.get("practice_date", "")
            label = ""
            try:
                d = datetime.fromisoformat(p_raw)
                label = d.date().isoformat()
            except Exception:
                label = str(p_raw).split("T")[0] if "T" in str(p_raw) else str(p_raw)

            x_labels.append(label)
            rd_rates.append(rd_r)
            ls_rates.append(ls_r)
            wr_rates.append(wr_r)
            sp_rates.append(sp_r)

            rows.append(
                {
                    "ID": row["id"],
                    "演習日": label,
                    "内容": row.get("category", ""),
                    "R正解数": rd_c,
                    "R正答率(%)": round(rd_r, 1),
                    "L正解数": ls_c,
                    "L正答率(%)": round(ls_r, 1),
                    "W得点": wr_c,
                    "W正答率(%)": round(wr_r, 1),
                    "S得点": sp_c,
                    "S正答率(%)": round(sp_r, 1),
                    "担当講師": row.get("teacher_name", ""),
                }
            )

        # 正答率グラフ（横軸は「日付のみ」）
        st.markdown("##### 技能別正答率の推移（4技能）")
        fig = go.Figure()
        fig.add_trace(
            go.Scatter(x=x_labels, y=rd_rates, mode="lines+markers", name="Reading 正答率")
        )
        fig.add_trace(
            go.Scatter(x=x_labels, y=ls_rates, mode="lines+markers", name="Listening 正答率")
        )
        fig.add_trace(
            go.Scatter(x=x_labels, y=wr_rates, mode="lines+markers", name="Writing 正答率")
        )
        fig.add_trace(
            go.Scatter(x=x_labels, y=sp_rates, mode="lines+markers", name="Speaking 正答率")
        )
        fig.update_layout(
            xaxis_title="演習日",
            yaxis_title="正答率(%)",
            xaxis=dict(type="category"),  # 日付をカテゴリとして扱う（時刻なし）
        )
        st.plotly_chart(fig, use_container_width=True)

        st.markdown("##### 演習記録一覧（4技能）")
        st.dataframe(pd.DataFrame(rows), use_container_width=True)

        # ---------------- 編集機能（英検演習記録の編集） ----------------
        st.markdown("---")
        st.subheader("英検演習記録の編集")

        if eiken_df_student.empty or "id" not in eiken_df_student.columns:
            st.info("編集可能な英検演習データがありません。")
        else:
            edit_options = [
                f'{row["id"]} : {row["practice_date"]} {row.get("category", "")}'
                for _, row in eiken_df_student.iterrows()
            ]
            selected_edit = st.selectbox(
                "編集する演習記録を選択",
                [""] + edit_options,
                key=f"edit_eiken_select_{student_id}",
            )

            if selected_edit:
                edit_id = selected_edit.split(" : ")[0]
                target_row = eiken_df_student[eiken_df_student["id"] == edit_id].iloc[0]

                st.markdown("### 演習記録の内容を編集")

                # 既存値の取得
                old_grade = target_row.get("target_grade", "")
                old_exam_date = target_row.get("exam_date", "")
                old_practice_date = target_row.get("practice_date", "")
                old_category = target_row.get("category", "")

                # scores_json → dict
                try:
                    old_scores = json.loads(target_row.get("scores_json") or "{}")
                except Exception:
                    old_scores = {}

                def _get_skill_info(key):
                    info = old_scores.get(key, {}) or {}
                    c = info.get("correct", 0)
                    t = info.get("total", 0)
                    try:
                        c = int(c)
                    except Exception:
                        c = 0
                    try:
                        t = int(t)
                    except Exception:
                        t = 0
                    return c, t

                rd_c_old, rd_t_old = _get_skill_info("reading")
                ls_c_old, ls_t_old = _get_skill_info("listening")
                wr_c_old, wr_t_old = _get_skill_info("writing")
                sp_c_old, sp_t_old = _get_skill_info("speaking")

                # 日付などの編集
                edit_grade = st.selectbox(
                    "目標級（編集）",
                    EIKEN_GRADES,
                    index=EIKEN_GRADES.index(old_grade) if old_grade in EIKEN_GRADES else 2,
                    key=f"edit_eiken_grade_{edit_id}",
                )

                try:
                    exam_date_val = datetime.fromisoformat(old_exam_date).date()
                except Exception:
                    exam_date_val = date.today()
                edit_exam_date = st.date_input(
                    "本番受験日（編集）",
                    value=exam_date_val,
                    key=f"edit_eiken_exam_date_{edit_id}",
                )

                try:
                    practice_date_val = datetime.fromisoformat(old_practice_date).date()
                except Exception:
                    # practice_date が date-only 文字列の場合も想定
                    try:
                        practice_date_val = datetime.strptime(str(old_practice_date), "%Y-%m-%d").date()
                    except Exception:
                        practice_date_val = date.today()
                edit_practice_date = st.date_input(
                    "演習日（編集）",
                    value=practice_date_val,
                    key=f"edit_eiken_practice_date_{edit_id}",
                )

                edit_category = st.text_input(
                    "実施内容（編集）",
                    value=old_category,
                    key=f"edit_eiken_category_{edit_id}",
                )

                st.markdown("#### 技能別の結果編集")

                col1_e, col2_e = st.columns(2)
                with col1_e:
                    st.write(f"**Reading（全 {rd_t_old} 問中）**" if rd_t_old else "**Reading**")
                    edit_rd_correct = st.number_input(
                        "Reading 正解数（編集）",
                        min_value=0,
                        max_value=rd_t_old if rd_t_old > 0 else 100,
                        value=rd_c_old,
                        key=f"edit_eiken_rd_correct_{edit_id}",
                    )
                    rd_rate_edit = (edit_rd_correct / rd_t_old * 100) if rd_t_old else 0
                    st.caption(f"正答率：{rd_rate_edit:.1f} %")

                    st.write(f"**Listening（全 {ls_t_old} 問中）**" if ls_t_old else "**Listening**")
                    edit_ls_correct = st.number_input(
                        "Listening 正解数（編集）",
                        min_value=0,
                        max_value=ls_t_old if ls_t_old > 0 else 100,
                        value=ls_c_old,
                        key=f"edit_eiken_ls_correct_{edit_id}",
                    )
                    ls_rate_edit = (edit_ls_correct / ls_t_old * 100) if ls_t_old else 0
                    st.caption(f"正答率：{ls_rate_edit:.1f} %")

                with col2_e:
                    st.write(f"**Writing（満点 {wr_t_old} 点）**" if wr_t_old else "**Writing**")
                    edit_wr_correct = st.number_input(
                        "Writing 得点（編集）",
                        min_value=0,
                        max_value=wr_t_old if wr_t_old > 0 else 100,
                        value=wr_c_old,
                        key=f"edit_eiken_wr_correct_{edit_id}",
                    )
                    wr_rate_edit = (edit_wr_correct / wr_t_old * 100) if wr_t_old else 0
                    st.caption(f"正答率：{wr_rate_edit:.1f} %")

                    st.write(f"**Speaking（満点 {sp_t_old} 点）**" if sp_t_old else "**Speaking**")
                    edit_sp_correct = st.number_input(
                        "Speaking 得点（編集）",
                        min_value=0,
                        max_value=sp_t_old if sp_t_old > 0 else 100,
                        value=sp_c_old,
                        key=f"edit_eiken_sp_correct_{edit_id}",
                    )
                    sp_rate_edit = (edit_sp_correct / sp_t_old * 100) if sp_t_old else 0
                    st.caption(f"正答率：{sp_rate_edit:.1f} %")

                if st.button("この演習記録を更新", key=f"btn_update_eiken_{edit_id}"):
                    # 新しい scores_json
                    new_scores = {
                        "reading":   {"correct": edit_rd_correct, "total": rd_t_old},
                        "listening": {"correct": edit_ls_correct, "total": ls_t_old},
                        "writing":   {"correct": edit_wr_correct, "total": wr_t_old},
                        "speaking":  {"correct": edit_sp_correct, "total": sp_t_old},
                    }

                    eiken_all_for_update = get_eiken_df()
                    if eiken_all_for_update.empty or "id" not in eiken_all_for_update.columns:
                        st.error("英検データが見つかりませんでした。")
                    else:
                        eiken_all_for_update["id"] = eiken_all_for_update["id"].astype(str)
                        mask_all = eiken_all_for_update["id"] == edit_id
                        if not mask_all.any():
                            st.error("対象の英検演習データが見つかりませんでした。")
                        else:
                            idx_all = eiken_all_for_update[mask_all].index[0]
                            eiken_all_for_update.at[idx_all, "target_grade"] = edit_grade
                            eiken_all_for_update.at[idx_all, "exam_date"] = edit_exam_date.isoformat()
                            eiken_all_for_update.at[idx_all, "practice_date"] = edit_practice_date.isoformat()
                            eiken_all_for_update.at[idx_all, "category"] = edit_category
                            eiken_all_for_update.at[idx_all, "scores_json"] = json.dumps(
                                new_scores, ensure_ascii=False
                            )
                            eiken_all_for_update.at[idx_all, "updated_at"] = datetime.now().isoformat()
                            eiken_all_for_update.at[idx_all, "teacher_username"] = teacher_username
                            eiken_all_for_update.at[idx_all, "teacher_name"] = teacher_name

                            write_sheet_df("eiken_records", eiken_all_for_update)
                            try:
                                load_all_tables.clear()
                            except Exception:
                                pass
                            try:
                                load_sheet_df.clear()
                            except Exception:
                                pass

                            st.success("英検演習記録を更新しました。")
                            time.sleep(1)
                            st.rerun()

        # ---------------- 削除 ----------------
        with st.expander("英検演習記録の削除"):
            delete_options = [
                f'{row["id"]} : {row["practice_date"]} {row.get("category", "")}'
                for _, row in eiken_df_student.iterrows()
            ]
            selected_delete = st.selectbox(
                "削除する演習記録を選択",
                [""] + delete_options,
                key=f"delete_eiken_select_{student_id}",
            )
            if st.button("選択した演習記録を削除", key=f"delete_eiken_button_{student_id}"):
                if not selected_delete:
                    st.error("削除対象を選択してください。")
                else:
                    del_id = selected_delete.split(" : ")[0]
                    eiken_all = get_eiken_df()
                    if not eiken_all.empty and "id" in eiken_all.columns:
                        eiken_all["id"] = eiken_all["id"].astype(str)
                        eiken_all = eiken_all[eiken_all["id"] != del_id]
                        write_sheet_df("eiken_records", eiken_all)
                        try:
                            load_all_tables.clear()
                        except Exception:
                            pass
                        try:
                            load_sheet_df.clear()
                        except Exception:
                            pass
                        st.success("英検演習記録を削除しました。")
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.error("英検データが見つかりませんでした。")



# -----------------
# 保護者報告作成（Communication Sheet）
# -----------------

def page_parent_report():
    import html
    import json
    import pandas as pd
    import plotly.graph_objects as go
    from datetime import date, datetime
    import streamlit.components.v1 as components

    # ---------- 入力エリア（Streamlit側UI。印刷対象ではない） ----------
    st.markdown('<div class="no-print-input">', unsafe_allow_html=True)

    st.header("保護者報告作成")

    students_df = get_students_df()
    if students_df.empty:
        st.info("生徒が登録されていません。")
        st.markdown('</div>', unsafe_allow_html=True)
        return

    # student_id を文字列に統一
    if "student_id" in students_df.columns:
        students_df["student_id"] = students_df["student_id"].astype(str)

    # （任意）既存の印刷モード：サイドバー非表示など
    with st.expander("印刷モード（サイドバーを隠す）"):
        print_mode = st.checkbox("印刷モード（サイドバーとヘッダーを隠す）を有効にする")
        if print_mode:
            inject_print_mode_css()

    # 生徒選択
    student_label = st.selectbox(
        "生徒を選択",
        [f'{row["student_id"]} : {row["name"]}' for _, row in students_df.iterrows()],
    )
    student_id = student_label.split(" : ")[0]
    student_name = student_label.split(" : ")[1]

    # 対象年月
    col1, col2 = st.columns(2)
    with col1:
        year = st.number_input("対象年", min_value=2000, max_value=2100, value=date.today().year)
    with col2:
        month = st.number_input("対象月", min_value=1, max_value=12, value=date.today().month)

    summary_comment = st.text_area("月次総括コメント（保護者向け）", height=120)

    # レポート生成ボタン
    generate_clicked = st.button("レポートを生成", key="generate_report")

    st.markdown('</div>', unsafe_allow_html=True)  # 入力エリア終了

    # ここから先は「レポートを生成」後だけ
    if not generate_clicked:
        return

    # ---------- データ集計 ----------
    sid = str(student_id)

    coaching_df = get_coaching_df()
    exam_df = get_exam_results_df()
    eiken_df = get_eiken_df()

    if not coaching_df.empty and "student_id" in coaching_df.columns:
        coaching_df["student_id"] = coaching_df["student_id"].astype(str)
        coaching_df = coaching_df[coaching_df["student_id"] == sid]

    if not exam_df.empty and "student_id" in exam_df.columns:
        exam_df["student_id"] = exam_df["student_id"].astype(str)

    if not eiken_df.empty and "student_id" in eiken_df.columns:
        eiken_df["student_id"] = eiken_df["student_id"].astype(str)

    # 対象月の開始・終了
    start_date = date(int(year), int(month), 1)
    if month == 12:
        end_date = date(int(year) + 1, 1, 1)
    else:
        end_date = date(int(year), int(month) + 1, 1)

    # --- 日報の集計（この月の分） ---
    records_month = []
    for _, row in coaching_df.iterrows():
        try:
            d = datetime.fromisoformat(row["date"]).date()
        except Exception:
            continue
        if start_date <= d < end_date:
            records_month.append(row)

    num_sessions = len(records_month)
    total_hours = 0.0
    stu_understanding_list = []
    tch_homework_list = []
    dates_list = []
    stu_understanding_series = []
    stu_goal_series = []
    stu_motivation_series = []
    tch_attitude_series = []
    tch_homework_series = []
    tch_prev_understand_series = []

    for row in records_month:
        d_str = row["date"]
        try:
            _ = datetime.fromisoformat(d_str).date()
        except Exception:
            continue

        dates_list.append(d_str)

        try:
            se = json.loads(row.get("student_eval_json") or "{}")
        except Exception:
            se = {}
        try:
            te = json.loads(row.get("teacher_eval_json") or "{}")
        except Exception:
            te = {}
        try:
            schedule = json.loads(row.get("study_schedule_json") or "{}")
        except Exception:
            schedule = {}

        # 生徒自己評価
        u = se.get("理解度")
        g = se.get("目標達成度")
        m = se.get("モチベーション")
        if isinstance(u, (int, float)):
            stu_understanding_list.append(u)
            stu_understanding_series.append((d_str, u))
        else:
            stu_understanding_series.append((d_str, None))
        if isinstance(g, (int, float)):
            stu_goal_series.append((d_str, g))
        else:
            stu_goal_series.append((d_str, None))
        if isinstance(m, (int, float)):
            stu_motivation_series.append((d_str, m))
        else:
            stu_motivation_series.append((d_str, None))

        # 講師評価
        att = te.get("授業態度")
        hw = te.get("宿題完成度")
        prevu = te.get("前回理解度")
        if isinstance(hw, (int, float)):
            tch_homework_list.append(hw)

        tch_attitude_series.append((d_str, att if isinstance(att, (int, float)) else None))
        tch_homework_series.append((d_str, hw if isinstance(hw, (int, float)) else None))
        tch_prev_understand_series.append((d_str, prevu if isinstance(prevu, (int, float)) else None))

        # 自習予定から時間合計
        for _, hrs in schedule.items():
            try:
                total_hours += float(hrs)
            except Exception:
                pass

    avg_understanding = (
        sum(stu_understanding_list) / len(stu_understanding_list)
        if stu_understanding_list else 0
    )
    avg_homework = (
        sum(tch_homework_list) / len(tch_homework_list)
        if tch_homework_list else 0
    )

    # --- 英検情報 ---
    eiken_df_student = eiken_df[eiken_df["student_id"] == sid].sort_values("practice_date")
    has_eiken = not eiken_df_student.empty

    current_target_grade = ""
    current_exam_date = ""
    month_eiken_rows = []

    if has_eiken:
        last = eiken_df_student.iloc[-1]
        current_target_grade = last.get("target_grade", "")
        current_exam_date = last.get("exam_date", "")

        for _, row in eiken_df_student.iterrows():
            try:
                pd_ = datetime.fromisoformat(row["practice_date"]).date()
            except Exception:
                continue
            if not (start_date <= pd_ < end_date):
                continue

            try:
                s = json.loads(row.get("scores_json") or "{}")
            except Exception:
                s = {}

            def get_skill(skill_key: str):
                info = s.get(skill_key, {}) or {}
                c = info.get("correct", 0)
                t = info.get("total", 0)
                rate = (c / t * 100) if t else 0
                return c, t, rate

            rd_c, rd_t, rd_r = get_skill("reading")
            ls_c, ls_t, ls_r = get_skill("listening")
            wr_c, wr_t, wr_r = get_skill("writing")
            sp_c, sp_t, sp_r = get_skill("speaking")

            month_eiken_rows.append(
                {
                    "演習日": row.get("practice_date", ""),
                    "内容": row.get("category", ""),
                    "R正解数": rd_c,
                    "R正答率(%)": round(rd_r, 1),
                    "L正解数": ls_c,
                    "L正答率(%)": round(ls_r, 1),
                    "W得点": wr_c,
                    "W正答率(%)": round(wr_r, 1),
                    "S得点": sp_c,
                    "S正答率(%)": round(sp_r, 1),
                }
            )

    # --- 成績（入塾〜現在：グラフ用） ---
    exam_df_stu_all = exam_df[exam_df["student_id"] == sid].copy()
    if not exam_df_stu_all.empty:
        exam_df_stu_all["date_dt"] = pd.to_datetime(exam_df_stu_all["date"], errors="coerce")
        exam_df_stu_all = exam_df_stu_all.sort_values("date_dt")

    # ---------- Plotly グラフを HTML に変換（カラー指定） ----------
    fig1_html = ""
    if dates_list:
        x1 = [d for d, _ in stu_understanding_series]
        y_u = [v for _, v in stu_understanding_series]
        y_g = [v for _, v in stu_goal_series]
        y_m = [v for _, v in stu_motivation_series]
        fig1 = go.Figure()
        fig1.add_trace(go.Scatter(
            x=x1, y=y_u, mode="lines+markers", name="理解度",
            line=dict(color="#1f77b4"), marker=dict(color="#1f77b4")
        ))
        fig1.add_trace(go.Scatter(
            x=x1, y=y_g, mode="lines+markers", name="目標達成度",
            line=dict(color="#2ca02c"), marker=dict(color="#2ca02c")
        ))
        fig1.add_trace(go.Scatter(
            x=x1, y=y_m, mode="lines+markers", name="モチベーション",
            line=dict(color="#ff7f0e"), marker=dict(color="#ff7f0e")
        ))
        fig1.update_layout(yaxis=dict(range=[0, 5]), legend_title="項目")
        fig1_html = fig1.to_html(include_plotlyjs=False, full_html=False)

    fig2_html = ""
    if dates_list:
        x2 = [d for d, _ in tch_attitude_series]
        y_att = [v for _, v in tch_attitude_series]
        y_hw = [v for _, v in tch_homework_series]
        y_prev = [v for _, v in tch_prev_understand_series]
        fig2 = go.Figure()
        fig2.add_trace(go.Scatter(
            x=x2, y=y_att, mode="lines+markers", name="授業態度",
            line=dict(color="#9467bd"), marker=dict(color="#9467bd")
        ))
        fig2.add_trace(go.Scatter(
            x=x2, y=y_hw, mode="lines+markers", name="宿題完成度",
            line=dict(color="#8c564b"), marker=dict(color="#8c564b")
        ))
        fig2.add_trace(go.Scatter(
            x=x2, y=y_prev, mode="lines+markers", name="前回理解度",
            line=dict(color="#17becf"), marker=dict(color="#17becf")
        ))
        fig2.update_layout(yaxis=dict(range=[0, 5]), legend_title="項目")
        fig2_html = fig2.to_html(include_plotlyjs=False, full_html=False)

    fig_total_html = ""
    if not exam_df_stu_all.empty:
        dates_exam = []
        total_scores = []
        total_targets = []
        for _, row in exam_df_stu_all.iterrows():
            label = f'{row["date"]} {row["exam_name"]}'
            dates_exam.append(label)
            try:
                res = json.loads(row.get("results_json") or "{}")
            except Exception:
                res = {}
            t_score = 0
            t_target = 0
            for _, vals in res.items():
                t_score += vals.get("score", 0)
                t_target += vals.get("target", 0)
            total_scores.append(t_score)
            total_targets.append(t_target)

        fig_total = go.Figure()
        fig_total.add_trace(go.Scatter(
            x=dates_exam, y=total_scores,
            mode="lines+markers", name="合計点",
            line=dict(color="#1f77b4"), marker=dict(color="#1f77b4")
        ))
        fig_total.add_trace(go.Scatter(
            x=dates_exam, y=total_targets,
            mode="lines+markers", name="目標合計",
            line=dict(color="#d62728", dash="dash"), marker=dict(color="#d62728")
        ))
        fig_total.update_layout(xaxis_title="テスト", yaxis_title="得点", legend_title="項目")
        fig_total_html = fig_total.to_html(include_plotlyjs=False, full_html=False)

    # ---------- テストを「テスト毎の表」でHTML化 ----------
    exam_table_html = ""
    year_exam_rows = []
    if not exam_df_stu_all.empty:
        for _, row in exam_df_stu_all.iterrows():
            try:
                d = datetime.fromisoformat(row["date"]).date()
            except Exception:
                continue
            if d.year == int(year):
                year_exam_rows.append(row)

    if year_exam_rows:
        parts = []
        for row in year_exam_rows:
            exam_label = f'{row["date"]} {row["exam_category"]} {row["exam_name"]}'
            parts.append(
                f'<h4 class="subsection-title">{html.escape(exam_label)}</h4>'
            )
            try:
                res = json.loads(row.get("results_json") or "{}")
            except Exception:
                res = {}

            if not res:
                parts.append("<p>（科目データなし）</p>")
                continue

            subjects = []
            targets = []
            scores = []
            for subj, vals in res.items():
                subjects.append(subj)
                targets.append(vals.get("target", 0))
                scores.append(vals.get("score", 0))

            df_exam = pd.DataFrame({
                "科目": subjects,
                "目標": targets,
                "得点": scores,
            })
            parts.append(
                df_exam.to_html(
                    index=False,
                    classes="score-table",
                    border=0,
                    justify="center",
                    escape=False,
                )
            )
        exam_table_html = "\n".join(parts)
    else:
        exam_table_html = "<p>今年度のテスト結果データがありません。</p>"

    # ---------- 英検テーブル ----------
    if month_eiken_rows:
        eiken_table_df = pd.DataFrame(month_eiken_rows)
        eiken_table_html = eiken_table_df.to_html(
            index=False,
            classes="score-table",
            border=0,
            justify="center",
            escape=False,
        )
    else:
        eiken_table_html = "<p>この月の英検演習記録はありません。</p>"

    # コメント
    summary_comment_html = html.escape(summary_comment).replace("\n", "<br>")
    safe_student_name = html.escape(student_name)

    # ---------- レポート本体 HTML（report-root 内） ----------
    sections = []

    # ヘッダー
    sections.append(
        f'<div class="report-header">'
        f'U-BASE 学習報告書 - {safe_student_name} 様 - {year}年{month}月'
        f'</div>'
    )

    # ① サマリー
    sections.append('<div class="report-section-title">① サマリー</div>')
    sections.append(
        f"""
        <div class="summary-grid">
          <div class="summary-item">
            <div class="summary-label">月間通塾回数</div>
            <div class="summary-value">{num_sessions} 回</div>
          </div>
          <div class="summary-item">
            <div class="summary-label">月間総学習時間（予定）</div>
            <div class="summary-value">{total_hours:.1f} 時間</div>
          </div>
          <div class="summary-item">
            <div class="summary-label">平均授業理解度</div>
            <div class="summary-value">{avg_understanding:.2f} / 5</div>
          </div>
          <div class="summary-item">
            <div class="summary-label">平均宿題達成度</div>
            <div class="summary-value">{avg_homework:.2f} / 5</div>
          </div>
        </div>
        """
    )

    # ② 生徒自己評価
    sections.append('<div class="report-section-title">② 授業日報（生徒自己評価の推移）</div>')
    if fig1_html:
        sections.append(fig1_html)
    else:
        sections.append("<p>この月の授業日報はありません。</p>")

    # ③ 講師評価
    sections.append('<div class="report-section-title">③ 授業日報（講師評価の推移）</div>')
    if fig2_html:
        sections.append(fig2_html)
    else:
        sections.append("<p>この月の授業日報はありません。</p>")

    # ④ 成績推移
    sections.append('<div class="report-section-title">④ 成績推移（入塾〜現在）</div>')
    if fig_total_html:
        sections.append(fig_total_html)
    else:
        sections.append("<p>テスト結果データがありません。</p>")

    # 今年度テスト一覧（テスト毎の表）
    sections.append('<h4 class="subsection-title">今年度のテスト結果一覧</h4>')
    sections.append(exam_table_html)

    # ⑤ 英検
    if has_eiken:
        sections.append('<div class="report-section-title">⑤ 英検対策状況</div>')

        if current_target_grade:
            if current_exam_date:
                sections.append(
                    f"<p><strong>現在の目標:</strong> "
                    f"{html.escape(current_target_grade)} 合格 "
                    f"(試験予定日: {html.escape(str(current_exam_date))})</p>"
                )
            else:
                sections.append(
                    f"<p><strong>現在の目標:</strong> "
                    f"{html.escape(current_target_grade)} 合格 (試験予定日: 未設定)</p>"
                )
        else:
            sections.append("<p>英検の目標級はまだ設定されていません。</p>")

        sections.append('<h4 class="subsection-title">今月の英検演習記録（4技能）</h4>')
        sections.append(eiken_table_html)

    # ⑥ コメント
    sections.append('<div class="report-section-title">⑥ 講師からのメッセージ</div>')
    if summary_comment.strip():
        sections.append(f"<p>{summary_comment_html}</p>")
    else:
        sections.append("<p>（コメント未入力）</p>")

    report_body = "\n".join(sections)

    # ---------- iframe 内CSS（カラー＋印刷設定） ----------
    css_block = """
<style>
@page {
  size: A4 portrait;
  margin: 5mm 8mm;
}
body {
  margin: 0;
  padding: 16px;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  background: #f5f5f5;
}
.report-container {
  max-width: 900px;
  margin: 0 auto;
  background: #ffffff;
  padding: 24px 32px;
  box-shadow: 0 2px 8px rgba(0,0,0,0.08);
  box-sizing: border-box;
}
.report-header {
  font-size: 20px;
  font-weight: 600;
  margin-bottom: 16px;
  border-bottom: 2px solid #4a90e2;
  padding-bottom: 8px;
}
.report-section-title {
  font-size: 16px;
  font-weight: 600;
  margin-top: 24px;
  margin-bottom: 8px;
  color: #333333;
}
.subsection-title {
  font-size: 14px;
  font-weight: 600;
  margin-top: 16px;
  margin-bottom: 4px;
}
.summary-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 8px;
}
.summary-item {
  flex: 1 1 200px;
  background: #f5f7ff;
  border-radius: 8px;
  padding: 8px 10px;
}
.summary-label {
  font-size: 12px;
  color: #555555;
}
.summary-value {
  font-size: 16px;
  font-weight: 600;
  color: #222222;
}
.score-table {
  border-collapse: collapse;
  width: 100%;
  font-size: 13px;
  margin-top: 4px;
}
.score-table th,
.score-table td {
  border: 1px solid #cccccc;
  padding: 4px 6px;
}
.score-table th {
  background: #eef3ff;
  font-weight: 600;
}
.toolbar {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
}
.toolbar button {
  padding: 6px 12px;
  font-size: 13px;
  border-radius: 6px;
  border: none;
  cursor: pointer;
  background: #4a90e2;
  color: #ffffff;
}
.toolbar button.secondary {
  background: #777777;
}
.toolbar button:hover {
  opacity: 0.9;
}
.plotly-graph-div, .js-plotly-plot {
  max-width: 100% !important;
}
@media print {
  body {
    background: #ffffff;
    -webkit-print-color-adjust: exact;
    print-color-adjust: exact;
  }
  .toolbar {
    display: none !important;
  }
}
</style>
"""

    # ---------- iframe 全体 HTML（Plotly CDN + ボタン＋レポート） ----------
    full_html = f"""
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8" />
<title>保護者向けレポート</title>
{css_block}
<script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
</head>
<body>
<div class="toolbar">
  <button onclick="openInNewTab()" type="button">別タブでレポートを表示</button>
  <button class="secondary" onclick="window.print()" type="button">
    このレポートをPDFで保存 / 印刷
  </button>
</div>
<div id="report-root" class="report-container">
{report_body}
</div>

<script>
function openInNewTab() {{
  const reportRoot = document.getElementById('report-root');
  if (!reportRoot) {{
    alert('レポートが見つかりません。');
    return;
  }}
  const newWin = window.open('', '_blank');
  if (!newWin) {{
    alert('ポップアップがブロックされています。');
    return;
  }}
  newWin.document.write(`<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8" />
<title>保護者向けレポート</title>
{css_block}
</head>
<body>${{reportRoot.outerHTML}}</body>
</html>`);
  newWin.document.close();
  newWin.focus();
}}
</script>
</body>
</html>
"""

    components.html(full_html, height=1100, scrolling=True)




# -----------------
# 講師アカウント管理（master専用）
# -----------------

def page_teacher_management(current_username: str, current_role: str):
    if current_role != "master":
        st.error("このページは master 権限のみアクセス可能です。")
        return

    st.header("講師アカウント管理")

    # users シート読み込み（空の場合のカラム保証もしておく）
    users_df = load_sheet_df("users")
    if users_df.empty:
        users_df = pd.DataFrame(
            columns=["username", "name", "password_hash", "role"]
        )

    # 一覧表示用に、ハッシュは隠して username / name / role だけ出す
    display_df = users_df[["username", "name", "role"]].copy()
    display_df = display_df.rename(
        columns={
            "username": "ユーザー名",
            "name": "講師名",
            "role": "権限",
        }
    )
    st.subheader("登録済み講師一覧")
    st.dataframe(display_df, use_container_width=True)

    # ---------------- 新規講師登録 ----------------
    st.markdown("---")
    st.subheader("新規講師登録")
    col1, col2, col3 = st.columns(3)
    with col1:
        new_username = st.text_input("ユーザー名")
    with col2:
        new_name = st.text_input("講師名")
    with col3:
        new_password = st.text_input("初期パスワード", type="password")

    if st.button("講師アカウントを作成", key="create_teacher"):
        if not new_username or not new_password:
            st.error("ユーザー名とパスワードを入力してください。")
        elif (users_df["username"] == new_username).any():
            st.error("このユーザー名は既に使用されています。")
        else:
            # ★ 新しい書き方：Hasher.hash(平文パスワード)
            hashed = stauth.Hasher.hash(new_password)

            new_row = {
                "username": new_username,
                "name": new_name or new_username,
                "password_hash": hashed,
                "role": "teacher",
            }
            users_df = pd.concat([users_df, pd.DataFrame([new_row])], ignore_index=True)
            write_sheet_df("users", users_df)
            st.success("講師アカウントを作成しました。")
            time.sleep(1)
            st.rerun()

    # ---------------- パスワードリセット / アカウント削除 ----------------
    st.markdown("---")
    st.subheader("パスワードリセット / アカウント削除")

    if users_df.empty:
        st.info("ユーザーが登録されていません。")
        return

    usernames = users_df["username"].tolist()
    selected_user = st.selectbox("対象ユーザーを選択", usernames)

    target_row = users_df[users_df["username"] == selected_user].iloc[0]
    st.write(f"名前: {target_row.get('name', '')}, 権限: {target_row.get('role', '')}")

    # パスワード変更
    new_pw = st.text_input("新しいパスワード（変更しない場合は空欄）", type="password")
    if st.button("パスワードを変更", key="change_pw"):
        if not new_pw:
            st.error("新しいパスワードを入力してください。")
        else:
            # ★ ここも必ず new_pw をハッシュ、generate() は使わない
            hashed = stauth.Hasher.hash(new_pw)
            idx = users_df[users_df["username"] == selected_user].index[0]
            users_df.at[idx, "password_hash"] = hashed
            write_sheet_df("users", users_df)
            st.success("パスワードを変更しました。")

    # アカウント削除
    st.markdown("---")
    st.markdown("**アカウント削除（masterは削除できません）**")
    if selected_user == "master":
        st.info("master アカウントは削除できません。")
    else:
        if st.button("このアカウントを削除", key="delete_user"):
            users_df = users_df[users_df["username"] != selected_user]
            write_sheet_df("users", users_df)
            st.success("アカウントを削除しました。")
            time.sleep(1)
            st.rerun()



# ==========
# メイン関数
# ==========

def main():
    # ページ設定（最初の Streamlit 呼び出し）
    st.set_page_config(page_title="U-BASE", layout="wide")

    # 共通CSS
    inject_base_css()

    # ★ Google Sheets 初期化 & master ユーザー作成は
    #   セッションごとに「最初の1回だけ」実行する
    if "ubase_initialized" not in st.session_state:
        init_sheets()        # シート有無チェック & 作成
        ensure_master_user() # master ユーザーが無ければ作成
        st.session_state["ubase_initialized"] = True

    # 認証オブジェクト作成
    authenticator, roles_dict = build_authenticator()

    # ===== ログイン画面 =====
    # ロゴ表示
    st.markdown('<div class="ubase-title">U-BASE</div>', unsafe_allow_html=True)
    st.markdown('<div class="ubase-subtitle">Education Management System</div>', unsafe_allow_html=True)

    # ★ login の戻り値は使わず、session_state から取得する
    authenticator.login(
        "main",  # location
        fields={
            "Form name": "ログイン",
            "Username": "ユーザー名",
            "Password": "パスワード",
            "Login": "ログイン",
        },
    )

    auth_status = st.session_state.get("authentication_status", None)
    username = st.session_state.get("username", "")
    name = st.session_state.get("name", "")

    if auth_status is False:
        st.error("ユーザー名またはパスワードが正しくありません。")
        return
    if auth_status is None:
        st.info("ユーザー名とパスワードを入力してください。")
        return

    # ===== ここから先はログイン成功後 =====
    current_role = get_current_user_role(roles_dict, username)

    # サイドバー
    st.sidebar.title("U-BASE メニュー")
    st.sidebar.markdown(f"**ログイン中:** {name}（{current_role}）")
    authenticator.logout("ログアウト", "sidebar")

    menu_options = [
        "生徒管理",
        "成績入力・分析",
        "授業日報・コーチング",
        "英検対策",
        "保護者報告作成",
    ]
    if current_role == "master":
        menu_options.append("講師アカウント管理")

    page = st.sidebar.radio("ページを選択", menu_options)

    # ページ振り分け
    if page == "生徒管理":
        page_student_management(current_role)
    elif page == "成績入力・分析":
        page_grade_tracker()
    elif page == "授業日報・コーチング":
        page_coaching()
    elif page == "英検対策":
        page_eiken()
    elif page == "保護者報告作成":
        page_parent_report()
    elif page == "講師アカウント管理":
        page_teacher_management(username, current_role)


if __name__ == "__main__":
    main()
