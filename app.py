import os
import json
import mimetypes
import urllib.request
import urllib.error
import re
import streamlit as st
from google import genai
from google.genai import types

# 불필요한 경고문 차단
import warnings
warnings.filterwarnings("ignore")
os.environ["GRPC_VERBOSITY"] = "ERROR"
os.environ["GLOG_minloglevel"] = "2"

# =======================================================
# 1. 인증 정보 셋팅
# =======================================================
GEMINI_API_KEY = "AQ.Ab8RN6JbokxhhJ_QKUFF0bWn37bX7ypsF5BEguAQkPEgdzELeQ"
COM_CODE = "684364"
USER_ID = "BEBEANRF"
API_CERT_KEY = "5cac3fd68b28643018946222cb23389874"
ECOUNT_HOST = "https://oapiad.ecount.com"

@st.cache_resource
def get_genai_client():
    return genai.Client(api_key=GEMINI_API_KEY)

client = get_genai_client()

# =======================================================
# 통신 및 핵심 로직
# =======================================================
def post_request(url, payload):
    clean_url = url.replace("[", "").replace("]", "").strip()
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(clean_url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as response:
        return json.loads(response.read().decode("utf-8"))

# 👈 [핵심 변경] 여러 장의 사진을 동시에 분석하도록 수정
def extract_biz_info(uploaded_files):
    contents = []
    
    # 첨부된 모든 사진을 하나씩 읽어서 AI에게 전달할 준비
    for f in uploaded_files:
        file_bytes = f.read()
        mime_type = "image/jpeg" if f.name.endswith(('jpg', 'jpeg')) else f.type
        contents.append(types.Part.from_bytes(data=file_bytes, mime_type=mime_type))
    
    prompt = """
    당신은 대한민국 사업자등록증 및 대화 캡처본 전문 판독 AI입니다.
    제공된 1개 또는 여러 개의 이미지(사업자등록증, 카톡 캡처 등)를 분석하여 정보를 정확히 추출하세요.
    반드시 JSON 형식으로만 응답하며, 마크다운 코드블록 없이 순수 JSON 문자열만 출력하세요.
    이미지에서 발견되지 않은 정보는 빈 문자열("")로 남겨두세요.
    {
        "상호명": "상호 (법인명/단체명)",
        "사업자등록번호": "하이픈 포함 사업자번호",
        "대표자명": "성명",
        "업태": "업태",
        "종목": "종목",
        "주소": "사업장 주소",
        "이메일": "이메일 주소 (예: abc@def.com)",
        "연락처": "휴대폰 번호 또는 전화번호 (하이픈 포함)"
    }
    """
    contents.append(prompt)

    try:
        res = client.models.generate_content(
            model="gemini-3.6-flash", contents=contents,
            config=types.GenerateContentConfig(response_mime_type="application/json")
        )
    except Exception:
        res = client.models.generate_content(
            model="gemini-3.6-flash", contents=contents,
            config=types.GenerateContentConfig(response_mime_type="application/json")
        )
    return json.loads(res.text)

def find_matching_group(user_inputs, default_prices):
    if not os.path.exists('price_groups.json'): return None
    with open('price_groups.json', 'r', encoding='utf-8') as f: groups = json.load(f)
    
    target_prices = default_prices.copy()
    target_prices.update(user_inputs)
    
    for g in groups:
        prices = g.get("prices", {})
        match = True
        for key, target_price in target_prices.items():
            group_price = prices.get(key, default_prices[key])
            if group_price != target_price:
                match = False
                break
        if match: return g["code"]
    return None

def get_ecount_session():
    login_url = f"{ECOUNT_HOST}/OAPI/V2/OAPILogin"
    login_payload = {
        "COM_CODE": COM_CODE, "USER_ID": USER_ID,
        "API_CERT_KEY": API_CERT_KEY, "LAN_TYPE": "ko-KR", "ZONE": "AD"
    }
    try:
        res = post_request(login_url, login_payload)
        if str(res.get("Status")) == "200":
            data = res.get("Data", {})
            session_id = None
            if isinstance(data, dict):
                if "SESSION_ID" in data:
                    session_id = data["SESSION_ID"]
                elif "Datas" in data:
                    datas = data["Datas"]
                    if isinstance(datas, str):
                        session_id = datas
                    elif isinstance(datas, dict) and "SESSION_ID" in datas:
                        session_id = datas["SESSION_ID"]
            
            if session_id:
                return session_id, "✅ 로그인 성공"
            return None, f"❌ 세션키를 찾을 수 없습니다. (응답: {res})"
        return None, f"❌ 로그인 실패: {res}"
    except Exception as e:
        return None, f"❌ 로그인 에러(통신 문제): {str(e)}"

def save_customer_to_ecount(session_id, biz_info, group_code, email, phone, search_keyword):
    url = f"{ECOUNT_HOST}/OAPI/V2/AccountBasic/SaveBasicCust?SESSION_ID={session_id}"
    clean_biz_no = biz_info.get("사업자등록번호", "").replace("-", "")
    
    payload = {
        "CustList": [{
            "BulkDatas": {
                "CUST": clean_biz_no,
                "BUSINESS_NO": clean_biz_no,
                "CUST_NAME": biz_info.get("상호명", ""),
                "BOSS_NAME": biz_info.get("대표자명", ""),
                "UPTAE": biz_info.get("업태", ""),
                "JONGMOK": biz_info.get("종목", ""),
                "ADDR": biz_info.get("주소", ""), 
                "EMAIL": email,
                "HP_NO": phone,
                "PRICE_GROUP": group_code,
                "KWRD": search_keyword
            }
        }]
    }
    try:
        res = post_request(url, payload)
        return True, f"✅ 이카운트 API 요청 완료 (할당된 T그룹: {group_code})\n\n🔍 [서버 응답 원본]: {json.dumps(res, ensure_ascii=False)}"
    except Exception as e:
        return False, f"❌ 등록 통신 에러: {str(e)}"

# =======================================================
# 2. 모바일 웹 화면 구성 (Streamlit UI)
# =======================================================
st.set_page_config(page_title="비빈 ERP 자동등록", page_icon="☕", layout="centered")

bean_display_options = ["선택안함", "초콜릿 쿠키 A타입", "초콜릿 쿠키 B타입", "초콜릿 쿠키 C타입", "레몬 마들렌 블렌드", "(2026)에티오피아 싱글오리진", "디카페인"]
bean_key_mapping = {"초콜릿 쿠키 A타입": "A", "초콜릿 쿠키 B타입": "B", "초콜릿 쿠키 C타입": "C", "레몬 마들렌 블렌드": "L", "(2026)에티오피아 싱글오리진": "E", "디카페인": "D"}
default_prices = {"A": 29000, "B": 27000, "C": 22000, "L": 34000, "E": 40000, "D": 38000}

# 세션 상태 초기화
if 'extracted_data' not in st.session_state:
    st.session_state.extracted_data = {}

st.title("☕ 비빈 로스팅팩토리")
st.subheader("모바일 거래처 자동등록 시스템")

st.divider()

# [1단계] 이미지 첨부 (여러 장 첨부 가능하도록 수정)
st.markdown("#### 1. 첨부파일 등록")
st.info("💡 사업자등록증 사진과 카톡 캡처 사진(이메일, 연락처)을 함께 첨부해 보세요!")

# accept_multiple_files=True 옵션 추가
uploaded_files = st.file_uploader("1장 또는 여러 장을 한 번에 선택 가능", type=['jpg', 'jpeg', 'png', 'pdf'], accept_multiple_files=True)

if uploaded_files and not st.session_state.extracted_data:
    if st.button("AI 자동 판독 시작", use_container_width=True, type="primary"):
        with st.spinner(f"AI가 {len(uploaded_files)}장의 이미지를 분석하고 있습니다..."):
            try:
                biz_info = extract_biz_info(uploaded_files)
                st.session_state.extracted_data = biz_info
                st.rerun()
            except Exception as e:
                st.error(f"❌ 이미지 판독 중 오류가 발생했습니다: {str(e)}")

# [2단계] 거래처 정보 확인 및 폼 입력
if st.session_state.extracted_data:
    st.success("✅ 판독이 완료되었습니다. 아래 정보를 확인해 주세요.")
    st.divider()
    st.markdown("#### 2. 거래처 정보 입력")
    
    company_name = st.text_input("상호명", value=st.session_state.extracted_data.get("상호명", ""))
    boss_name = st.text_input("대표자명", value=st.session_state.extracted_data.get("대표자명", ""))
    biz_no = st.text_input("사업자번호", value=st.session_state.extracted_data.get("사업자등록번호", ""))
    addr = st.text_input("사업장주소", value=st.session_state.extracted_data.get("주소", ""))
    uptae = st.text_input("업태", value=st.session_state.extracted_data.get("업태", ""))
    jongmok = st.text_input("종목", value=st.session_state.extracted_data.get("종목", ""))
    
    # AI가 카톡 사진에서 이메일/연락처를 찾았다면 자동으로 채워줌
    email_val = st.session_state.extracted_data.get("이메일", "")
    phone_val = st.session_state.extracted_data.get("연락처", "")
    
    email = st.text_input("이메일 (필수 입력)", value=email_val)
    phone = st.text_input("연락처 (필수 입력)", value=phone_val)
    
    cafe_name = st.text_input("카페명 (검색창내용)", placeholder="상호명과 다를 경우에만 입력하세요")

    st.divider()

    # [3단계] 단가 설정
    st.markdown("#### 3. 단가 입력(부가세포함)")
    
    cb_beans = []
    ent_prices = []
    
    for i in range(3):
        col1, col2 = st.columns([2, 1])
        with col1:
            cb = st.selectbox(f"원두 {i+1}", bean_display_options, index=0, key=f"cb_{i}")
            cb_beans.append(cb)
        with col2:
            ent = st.text_input(f"단가 (원)", key=f"ent_{i}", placeholder="예: 27000")
            ent_prices.append(ent)

    st.divider()

    # [4단계] 실행
    if st.button("🚀 이카운트 시스템 전송", use_container_width=True, type="primary"):
        email_pattern = r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$"
        phone_pattern = r"^\d{2,3}-?\d{3,4}-?\d{4}$"

        if not email or not phone:
            st.warning("⚠️ 이메일과 연락처를 반드시 입력해 주세요.")
        elif not re.match(email_pattern, email):
            st.warning("⚠️ 이메일 형식이 올바르지 않습니다. (예: test@test.com)")
        elif not re.match(phone_pattern, phone):
            st.warning("⚠️ 연락처 형식이 올바르지 않습니다. (예: 010-1234-5678 또는 01012345678)")
        else:
            user_inputs = {}
            has_error = False
            for cb, ent_val in zip(cb_beans, ent_prices):
                price_str = ent_val.strip().replace(",", "")
                if cb != "선택안함" and price_str:
                    try:
                        internal_key = bean_key_mapping.get(cb, cb)
                        user_inputs[internal_key] = int(price_str)
                    except ValueError:
                        st.error("❌ 단가는 숫자만 입력해 주세요.")
                        has_error = True
                        break
            
            if not has_error:
                if not user_inputs:
                    st.warning("⚠️ 최소 1개 이상의 원두와 단가를 설정해 주세요.")
                else:
                    group_code = find_matching_group(user_inputs, default_prices)
                    if not group_code:
                        st.error("❌ 설정되어 있지 않은 단가 조합입니다. 원두와 금액을 확인해 주세요.")
                    else:
                        with st.spinner("🚀 이카운트로 데이터 전송 중..."):
                            st.session_state.extracted_data["상호명"] = company_name
                            st.session_state.extracted_data["대표자명"] = boss_name
                            st.session_state.extracted_data["사업자등록번호"] = biz_no
                            st.session_state.extracted_data["주소"] = addr
                            st.session_state.extracted_data["업태"] = uptae
                            st.session_state.extracted_data["종목"] = jongmok
                            search_keyword = cafe_name if cafe_name.strip() else company_name

                            session_id, login_msg = get_ecount_session()
                            if not session_id:
                                st.error(login_msg)
                            else:
                                success, save_msg = save_customer_to_ecount(
                                    session_id, st.session_state.extracted_data, group_code, email, phone, search_keyword
                                )
                                if success:
                                    st.success(save_msg)
                                    st.balloons()
                                    st.session_state.extracted_data = {}
                                else:
                                    st.error(save_msg)
