import re
from datetime import date
from zoneinfo import ZoneInfo

import requests
import streamlit as st


NEIS_BASE_URL = "https://open.neis.go.kr/hub"
KST = ZoneInfo("Asia/Seoul")


def neis_get(endpoint, params):
    """NEIS API를 호출하고 JSON 응답을 반환합니다."""
    response = requests.get(
        f"{NEIS_BASE_URL}/{endpoint}",
        params=params,
        timeout=10,
    )
    response.raise_for_status()
    return response.json()


def get_rows(data, service_name):
    """NEIS 응답에서 row 목록을 꺼냅니다."""
    service = data.get(service_name, [])

    if not service:
        return [], None

    # 첫 번째 상자에서 전체 건수 확인
    head = service[0].get("head", [])
    total_count = None

    for item in head:
        if "list_total_count" in item:
            total_count = item["list_total_count"]
            break

    # 두 번째 상자의 row
    if len(service) >= 2:
        rows = service[1].get("row", [])
        return rows, total_count

    return [], total_count


def is_no_data(data, service_name):
    """NEIS의 INFO-200(조회 데이터 없음)인지 확인합니다."""
    service = data.get(service_name, [])

    for box in service:
        result = box.get("RESULT")
        if result and result.get("CODE") == "INFO-200":
            return True

    return False


def search_schools(school_name):
    """학교 이름으로 학교를 검색합니다."""
    school_name = school_name.strip()

    if not school_name:
        return []

    params = {
        "Type": "json",
        "SCHUL_NM": school_name,
    }

    data = neis_get("schoolInfo", params)

    if is_no_data(data, "schoolInfo"):
        return []

    rows, _ = get_rows(data, "schoolInfo")
    return rows


def expand_school_name(name):
    """
    '수도여고' -> '수도여자고등학교'
    'OO고' -> 'OO고등학교'
    순서로 약칭을 풀어 봅니다.
    """
    name = name.strip()

    # '여고'를 먼저 처리해야 '수도여고'가
    # '수도여자고등학교'로 바뀝니다.
    expanded = name.replace("여고", "여자고등학교")

    # 아직 '고'가 남아 있으면 고등학교로 확장
    if expanded == name:
        expanded = re.sub(r"고$", "고등학교", expanded)

    return expanded


def search_schools_with_fallback(name):
    """원래 검색 후, 결과가 없으면 약칭을 풀어 다시 검색합니다."""
    rows = search_schools(name)

    if rows:
        return rows, name

    expanded = expand_school_name(name)

    if expanded != name:
        rows = search_schools(expanded)
        if rows:
            return rows, expanded

    return [], name


def get_lunch(school, target_date):
    """선택한 학교의 특정 날짜 중식 정보를 조회합니다."""
    ymd = target_date.strftime("%Y%m%d")

    params = {
        "Type": "json",
        "ATPT_OFCDC_SC_CODE": school["ATPT_OFCDC_SC_CODE"],
        "SD_SCHUL_CODE": school["SD_SCHUL_CODE"],
        "MMEAL_SC_CODE": "2",
        "MLSV_FROM_YMD": ymd,
        "MLSV_TO_YMD": ymd,
        "pSize": "1000",
        "pIndex": "1",
    }

    data = neis_get("mealServiceDietInfo", params)

    if is_no_data(data, "mealServiceDietInfo"):
        return None

    rows, _ = get_rows(data, "mealServiceDietInfo")

    for row in rows:
        if row.get("MLSV_YMD") == ymd:
            return row

    return None


# --------------------------------------------------
# Streamlit 화면
# --------------------------------------------------

st.set_page_config(
    page_title="학교 급식 찾아보기",
    page_icon="🍚",
)

st.title("학교 급식 찾아보기")

st.write("학교 이름을 입력하고 학교와 날짜를 선택하면 중식 메뉴를 확인할 수 있습니다.")

school_name = st.text_input(
    "학교 이름",
    placeholder="예: 수도여고",
)

if "schools" not in st.session_state:
    st.session_state.schools = []

if "searched_name" not in st.session_state:
    st.session_state.searched_name = ""


if st.button("학교 찾기", type="primary"):
    if not school_name.strip():
        st.info("학교 이름을 입력해 주세요.")
        st.session_state.schools = []
    else:
        try:
            schools, searched_name = search_schools_with_fallback(school_name)

            st.session_state.schools = schools
            st.session_state.searched_name = searched_name

            if not schools:
                st.info(
                    f"'{school_name.strip()}'에 해당하는 학교를 찾지 못했습니다."
                )
            elif searched_name != school_name.strip():
                st.success(
                    f"'{school_name.strip()}'을(를) '{searched_name}'로 바꾸어 검색했습니다."
                )

        except requests.RequestException:
            st.error("학교 정보를 가져오지 못했습니다. 잠시 후 다시 시도해 주세요.")
        except Exception:
            st.error("학교 정보를 처리하는 중 문제가 발생했습니다.")


schools = st.session_state.schools

if schools:
    # 같은 학교가 중복으로 표시되는 것을 피하면서
    # 학교명과 지역을 함께 보여 줍니다.
    school_options = []

    for school in schools:
        label = (
            f"{school.get('SCHUL_NM', '')} "
            f"({school.get('LCTN_SC_NM', '지역 정보 없음')})"
        )
        school_options.append(label)

    selected_index = st.selectbox(
        "학교 선택",
        range(len(schools)),
        format_func=lambda i: school_options[i],
    )

    selected_school = schools[selected_index]

    target_date = st.date_input(
        "급식 날짜",
        value=date.today().astimezone(KST),
    )

    st.caption(
        f"선택한 학교: {selected_school['SCHUL_NM']} "
        f"· {selected_school.get('LCTN_SC_NM', '')}"
    )

    if st.button("중식 조회", type="primary"):
        try:
            meal = get_lunch(selected_school, target_date)

            if not meal:
                st.info(
                    f"{target_date.strftime('%Y년 %m월 %d일')}에는 "
                    "등록된 중식 급식 정보가 없습니다."
                )
            else:
                st.subheader(
                    f"{target_date.strftime('%Y년 %m월 %d일')} 중식"
                )

                menu = meal.get("DDISH_NM", "")
                calories = meal.get("CAL_INFO", "")

                # NEIS가 메뉴를 <br/>로 구분하므로 HTML 태그를
                # 안전하게 제거하고 줄바꿈으로 표시합니다.
                menu_lines = re.split(r"<br\s*/?>", menu, flags=re.IGNORECASE)

                for item in menu_lines:
                    item = item.strip()
                    if item:
                        st.write(f"- {item}")

                if calories:
                    st.write(f"**칼로리:** {calories}")

        except requests.RequestException:
            st.error("급식 정보를 가져오지 못했습니다. 잠시 후 다시 시도해 주세요.")
        except Exception:
            st.error("급식 정보를 처리하는 중 문제가 발생했습니다.")
