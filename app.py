import os
from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from fpdf import FPDF

# =========================================================
# V-GEN VPP 수익 계산기 v4.0
# ---------------------------------------------------------
# 화면 구분
# 1) 고객용: 사업주 수익 상승 중심
# 2) 영업채널용: 사업주 수익 + 채널 수수료 중심
# 3) 내부용: 비밀번호 입력 후 브이젠 총수익/배분/채널 상세 표시
#
# 케이스 프리셋
# - 제주 1MW, 제주 3MW, 육지 1MW, 육지 3MW, 육지 5MW
# - 직접 입력 가능
#
# 배분 기본 정책
# - CP: 브이젠 귀속
# - IMB/IMBP: 브이젠 부담
# - MEP/MAP/MWP: 사업주 귀속
# - 채널영업 수수료: 브이젠 수익에서 선택 비율 지급
# =========================================================

st.set_page_config(
    page_title="V-GEN VPP 수익 계산기 v4.0",
    layout="wide",
    initial_sidebar_state="expanded",
)

FONT_FILENAME = "NanumGothic.ttf"
FONT_PATH = os.path.join(os.getcwd(), FONT_FILENAME)
INTERNAL_PASSWORD = "1234"
DEFAULT_PROJECT_YEARS = 20

# ---------------------------------------------------------
# 기본 데이터
# ---------------------------------------------------------
REGION_CONFIG = {
    "제주도 입찰제 안착 모델": {
        "cp": 22.0,
        "mep": 1.2,
        "map": 2.5,
        "mwp": 1.0,
        "imb": -0.8,
        "dasmp": 115.0,
        "rtsmp": 120.0,
    },
    "호남/육지 입찰제 확대 모델": {
        "cp": 11.0,
        "mep": 1.2,
        "map": 0.8,
        "mwp": 0.5,
        "imb": -0.3,
        "dasmp": 120.0,
        "rtsmp": 122.0,
    },
}

SCENARIOS = {
    "보수": {"cp": 0.80, "mep": 0.70, "map": 0.60, "mwp": 0.60, "imb": 1.30},
    "기준": {"cp": 1.00, "mep": 1.00, "map": 1.00, "mwp": 1.00, "imb": 1.00},
    "상향": {"cp": 1.20, "mep": 1.30, "map": 1.25, "mwp": 1.20, "imb": 0.70},
}

OPERATION_LEVELS = {
    "일반 운영": {"mep_mult": 0.9, "imb_mult": 1.1, "desc": "일반적인 예측·입찰·제어 운영 수준"},
    "브이젠 표준 운영": {"mep_mult": 1.3, "imb_mult": 0.7, "desc": "V-GEN 표준 운영. 전력거래 효과 개선 및 IMB 리스크 저감"},
    "브이젠 고도화 운영": {"mep_mult": 1.6, "imb_mult": 0.4, "desc": "V-GEN 고도화 운영. 예측·입찰·제어 최적화 효과를 크게 반영"},
}

CHANNEL_PRESETS = {
    "채널 없음": 0,
    "5MW 모집 채널: 브이젠 수익의 20%": 20,
    "10MW 모집 채널: 브이젠 수익의 30%": 30,
    "전략 채널: 브이젠 수익의 50%": 50,
    "직접 입력": None,
}

CALC_METHODS = ["간편 수익비교", "정산규칙 근사"]
ROLE_MODES = ["고객용", "영업채널용", "내부용"]
TERM_LABELS = {
    "cp": "CP (Capacity Payment, 용량보상)",
    "mep": "MEP (Market Energy Payment, 전력거래정산)",
    "map": "MAP (Make-whole Additional Payment, 출력제어 보상)",
    "mwp": "MWP (Make-whole Payment, 급전지시 비용보전)",
    "imb": "IMB/IMBP (Imbalance Penalty, 예측오차 페널티)",
}

CASE_PRESETS = {
    "제주 1MW": {
        "region": "제주도 입찰제 안착 모델",
        "cap_mw": 1.0,
        "gen_time": 3.6,
        "fixed_total_price": 180.0,
        "base_smp_price": 120.0,
        "scenario": "기준",
        "operation": "브이젠 고도화 운영",
        "channel_preset": "채널 없음",
    },
    "제주 3MW": {
        "region": "제주도 입찰제 안착 모델",
        "cap_mw": 3.0,
        "gen_time": 3.6,
        "fixed_total_price": 180.0,
        "base_smp_price": 120.0,
        "scenario": "기준",
        "operation": "브이젠 고도화 운영",
        "channel_preset": "채널 없음",
    },
    "육지 1MW": {
        "region": "호남/육지 입찰제 확대 모델",
        "cap_mw": 1.0,
        "gen_time": 3.6,
        "fixed_total_price": 180.0,
        "base_smp_price": 120.0,
        "scenario": "기준",
        "operation": "브이젠 고도화 운영",
        "channel_preset": "채널 없음",
    },
    "육지 3MW": {
        "region": "호남/육지 입찰제 확대 모델",
        "cap_mw": 3.0,
        "gen_time": 3.6,
        "fixed_total_price": 180.0,
        "base_smp_price": 120.0,
        "scenario": "기준",
        "operation": "브이젠 고도화 운영",
        "channel_preset": "채널 없음",
    },
    "육지 5MW": {
        "region": "호남/육지 입찰제 확대 모델",
        "cap_mw": 5.0,
        "gen_time": 3.6,
        "fixed_total_price": 180.0,
        "base_smp_price": 120.0,
        "scenario": "기준",
        "operation": "브이젠 고도화 운영",
        "channel_preset": "5MW 모집 채널: 브이젠 수익의 20%",
    },
    "직접 입력": {},
}

# ---------------------------------------------------------
# CSS
# ---------------------------------------------------------
st.markdown(
    """
<style>
.block-container {padding-top: 1.2rem; padding-bottom: 2.5rem;}
.hero {
    border-radius: 24px;
    padding: 28px 32px;
    background: linear-gradient(135deg, #0b1f3a 0%, #123e66 48%, #14818c 100%);
    color: white;
    margin-bottom: 18px;
    box-shadow: 0 12px 34px rgba(2, 8, 23, 0.22);
}
.hero h1 {font-size: 34px; margin: 0 0 8px 0; font-weight: 900;}
.hero p {font-size: 16px; opacity: 0.95; margin: 0; line-height: 1.55;}
.card {
    background: white;
    border: 1px solid #e5e7eb;
    border-radius: 18px;
    padding: 20px;
    box-shadow: 0 8px 22px rgba(15, 23, 42, 0.06);
    min-height: 124px;
}
.label {font-size: 13px; color: #64748b; font-weight: 800;}
.big {font-size: 31px; font-weight: 900; color: #0f2a50; margin: 4px 0;}
.plus {font-size: 34px; font-weight: 900; color: #16a34a; margin: 4px 0;}
.red {font-size: 31px; font-weight: 900; color: #dc2626; margin: 4px 0;}
.small {font-size: 13px; color: #64748b; line-height: 1.45;}
.green-box {border-left: 6px solid #16a34a; background: #f0fdf4; border-radius: 14px; padding: 14px 18px; margin: 12px 0;}
.blue-box {border-left: 6px solid #2563eb; background: #eff6ff; border-radius: 14px; padding: 14px 18px; margin: 12px 0;}
.orange-box {border-left: 6px solid #f59e0b; background: #fffbeb; border-radius: 14px; padding: 14px 18px; margin: 12px 0;}
.red-box {border-left: 6px solid #dc2626; background: #fef2f2; border-radius: 14px; padding: 14px 18px; margin: 12px 0;}
.badge {display: inline-block; padding: 4px 10px; border-radius: 999px; font-size: 12px; font-weight: 800; margin-right: 6px;}
.badge-green {background: #dcfce7; color: #166534;}
.badge-blue {background: #dbeafe; color: #1e40af;}
.badge-orange {background: #fef3c7; color: #92400e;}
</style>
""",
    unsafe_allow_html=True,
)

# ---------------------------------------------------------
# Utility functions
# ---------------------------------------------------------
def won_to_manwon(value: float) -> float:
    return value / 10_000


def fmt_manwon(value: float, digits: int = 0) -> str:
    return f"{won_to_manwon(value):,.{digits}f} 만원"


def fmt_unit(value: float, digits: int = 2) -> str:
    return f"{value:,.{digits}f} 원/kWh"


def safe_div(a: float, b: float, default: float = 0.0) -> float:
    if b is None or b == 0:
        return default
    return a / b


def apply_scenario(value: float, key: str, scenario: str) -> float:
    return value * SCENARIOS[scenario][key]


def annual_generation(cap_mw: float, gen_time: float, degradation: float, year: int) -> float:
    year1 = cap_mw * 1_000 * gen_time * 365
    return year1 * ((1 - degradation) ** (year - 1))


def pdf_to_bytes(pdf: FPDF) -> bytes:
    raw = pdf.output(dest="S")
    if isinstance(raw, bytes):
        return raw
    if isinstance(raw, bytearray):
        return bytes(raw)
    return raw.encode("latin-1")


def adjust_mep(raw_value: float, multiplier: float) -> float:
    if raw_value >= 0:
        return raw_value * multiplier
    return raw_value / max(multiplier, 0.1)


def get_grade(score: int) -> tuple[str, str]:
    if score >= 80:
        return "참여 가능성 높음", "badge-green"
    if score >= 55:
        return "추가 확인 필요", "badge-orange"
    return "사전 조건 보완 필요", "badge-orange"


def init_defaults():
    defaults = {
        "role_mode": "고객용",
        "selected_case": "제주 1MW",
        "region": "제주도 입찰제 안착 모델",
        "calc_method": "간편 수익비교",
        "scenario": "기준",
        "cap_mw": 1.0,
        "gen_time": 3.6,
        "degradation_pct": 0.5,
        "years": DEFAULT_PROJECT_YEARS,
        "fixed_total_price": 180.0,
        "base_smp_price": 120.0,
        "operation": "브이젠 고도화 운영",
        "channel_preset": "채널 없음",
        "custom_channel_rate_pct": 20,
        "owner_fee_pct": 0,
        "initial_cost": 0,
        "om_year1": 0,
        "om_escalation_pct": 0.0,
        "has_kpx_meter": "있음",
        "has_control_inv": "있음",
        "has_remote_comm": "가능",
        "site_location_checked": "확인",
        "customer_name": "",
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def apply_case(case_name: str):
    """선택한 케이스 값을 입력 위젯에 반영한다.

    주의: selected_case는 이미 selectbox 위젯으로 생성된 key이므로,
    버튼 클릭 후 같은 실행 흐름에서 st.session_state['selected_case']를 다시 쓰면
    StreamlitAPIException이 발생한다. 따라서 selected_case 자체는 수정하지 않고,
    나머지 입력값만 갱신한다.
    """
    preset = CASE_PRESETS.get(case_name, {})
    if not preset:
        return
    for key, value in preset.items():
        if key != "selected_case":
            st.session_state[key] = value
    st.session_state["degradation_pct"] = st.session_state.get("degradation_pct", 0.5)
    st.session_state["years"] = st.session_state.get("years", DEFAULT_PROJECT_YEARS)

# ---------------------------------------------------------
# Calculation functions
# ---------------------------------------------------------
def calc_simple_effect(gen_kwh, cp_unit, mep_unit, map_unit, mwp_unit, imb_unit, mep_mult, imb_mult):
    units = {
        TERM_LABELS["cp"]: cp_unit,
        TERM_LABELS["mep"]: mep_unit * mep_mult,
        TERM_LABELS["map"]: map_unit,
        TERM_LABELS["mwp"]: mwp_unit,
        TERM_LABELS["imb"]: imb_unit * imb_mult,
    }
    amounts = {k: gen_kwh * v for k, v in units.items()}
    total = sum(amounts.values())
    return {"units": units, "amounts": amounts, "total": total, "unit_total": safe_div(total, gen_kwh), "detail": {}}


def calc_rule_effect(
    gen_kwh,
    base_smp_price,
    dasmp,
    rtsmp,
    da_ratio,
    rt_ratio,
    actual_ratio,
    ess_ratio,
    cp_unit,
    available_ratio,
    recognized_ratio,
    map_spread,
    mwp_spread,
    tolerance_ratio,
    penalty_factor,
    mep_mult,
    imb_mult,
):
    daos = gen_kwh * da_ratio
    rtos = gen_kwh * rt_ratio
    mgo = gen_kwh * actual_ratio
    mpe = gen_kwh * ess_ratio
    ra = gen_kwh * available_ratio
    recognized = gen_kwh * recognized_ratio

    market_energy_payment = dasmp * daos + rtsmp * (mgo - daos)
    old_smp_revenue = base_smp_price * mgo
    raw_mep = market_energy_payment - old_smp_revenue
    mep = adjust_mep(raw_mep, mep_mult)

    cp_basis = min(ra, mgo, rtos, recognized)
    cp = cp_unit * cp_basis

    map_qty = max(daos - max(mgo, rtos) - mpe, 0)
    map_payment = max((rtsmp + map_spread) * map_qty, 0)

    mwp_qty = max(daos - mgo, 0)
    mwp = max(mwp_spread * mwp_qty, 0)

    excess_error = max((mgo - rtos) - (rtos * tolerance_ratio), 0)
    imb = -rtsmp * excess_error * penalty_factor * imb_mult

    amounts = {
        TERM_LABELS["cp"]: cp,
        TERM_LABELS["mep"]: mep,
        TERM_LABELS["map"]: map_payment,
        TERM_LABELS["mwp"]: mwp,
        TERM_LABELS["imb"]: imb,
    }
    units = {k: safe_div(v, gen_kwh) for k, v in amounts.items()}
    detail = {
        "DAOS 하루전 발전계획량(kWh)": daos,
        "RTOS 실시간 발전계획량(kWh)": rtos,
        "MGO 실제 발전량(kWh)": mgo,
        "MPE ESS 충전량(kWh)": mpe,
        "RA 공급가능량(kWh)": ra,
        "ELCC/RPCF 용량 인정량(kWh)": recognized,
        "CP 인정 기준물량(kWh)": cp_basis,
        "MAP 대상물량(kWh)": map_qty,
        "MWP 대상물량(kWh)": mwp_qty,
        "IMB 초과오차량(kWh)": excess_error,
        "입찰시장 전력정산액(원)": market_energy_payment,
        "기존 SMP 상당 수익(원)": old_smp_revenue,
        "MEP 원증분(원)": raw_mep,
    }
    total = sum(amounts.values())
    return {"units": units, "amounts": amounts, "total": total, "unit_total": safe_div(total, gen_kwh), "detail": detail}


def split_revenue(amounts: dict, channel_rate: float) -> dict:
    cp = amounts.get(TERM_LABELS["cp"], 0.0)
    mep = amounts.get(TERM_LABELS["mep"], 0.0)
    map_value = amounts.get(TERM_LABELS["map"], 0.0)
    mwp = amounts.get(TERM_LABELS["mwp"], 0.0)
    imb = amounts.get(TERM_LABELS["imb"], 0.0)

    owner_vpp = mep + map_value + mwp
    vgen_gross_before_imb = cp
    vgen_imb_cost = imb
    vgen_before_channel = vgen_gross_before_imb + vgen_imb_cost
    # 채널영업 수수료는 브이젠의 CP 총수익 기준으로 계산한다.
    # IMB/IMBP는 브이젠이 별도 부담하는 리스크이므로,
    # 채널 수수료 산정 기준에서 제외해야 수수료가 명확히 반영된다.
    channel_fee = max(vgen_gross_before_imb, 0) * channel_rate
    vgen_after_channel = vgen_before_channel - channel_fee

    return {
        "owner_vpp": owner_vpp,
        "vgen_gross_before_imb": vgen_gross_before_imb,
        "vgen_imb_cost": vgen_imb_cost,
        "vgen_before_channel": vgen_before_channel,
        "channel_fee": channel_fee,
        "vgen_after_channel": vgen_after_channel,
        "cp_to_vgen": cp,
        "imb_to_vgen": imb,
        "mep_to_owner": mep,
        "map_to_owner": map_value,
        "mwp_to_owner": mwp,
    }


def calc_cashflow(
    years,
    cap_mw,
    gen_time,
    degradation,
    total_price,
    base_smp_price,
    rec_price,
    channel_rate,
    initial_cost,
    owner_fee_rate,
    om_year1,
    om_escalation,
    effect_func,
):
    rows = []
    remaining_cost = initial_cost
    cum_owner_old = 0.0
    cum_owner_after = 0.0
    cum_owner_gain = 0.0
    cum_vgen_gross_before_imb = 0.0
    cum_vgen_imb_cost = 0.0
    cum_vgen_before_channel = 0.0
    cum_vgen_net = 0.0
    cum_channel = 0.0
    cum_owner_service_fee = 0.0

    for year in range(1, years + 1):
        gen = annual_generation(cap_mw, gen_time, degradation, year)
        old_smp = gen * base_smp_price
        rec = gen * rec_price
        old_total = gen * total_price
        effect = effect_func(gen)
        split = split_revenue(effect["amounts"], channel_rate)

        owner_vpp_before_cost = split["owner_vpp"]
        repayment = 0.0
        if initial_cost > 0 and owner_vpp_before_cost > 0 and remaining_cost > 0:
            repayment = min(remaining_cost, owner_vpp_before_cost)
            remaining_cost -= repayment
        owner_vpp_after_cost = owner_vpp_before_cost - repayment

        owner_service_fee = owner_vpp_after_cost * owner_fee_rate if owner_vpp_after_cost > 0 else 0.0
        owner_vpp_net = owner_vpp_after_cost - owner_service_fee

        om = om_year1 * ((1 + om_escalation) ** (year - 1))
        owner_after_total = old_total + owner_vpp_net - om
        vgen_total_net = split["vgen_after_channel"] + owner_service_fee

        cum_owner_old += old_total
        cum_owner_after += owner_after_total
        cum_owner_gain += owner_vpp_net
        cum_vgen_gross_before_imb += split["vgen_gross_before_imb"]
        cum_vgen_imb_cost += split["vgen_imb_cost"]
        cum_vgen_before_channel += split["vgen_before_channel"]
        cum_vgen_net += vgen_total_net
        cum_channel += split["channel_fee"]
        cum_owner_service_fee += owner_service_fee

        rows.append({
            "연차": year,
            "발전량(kWh)": gen,
            "기존 SMP 수익(원)": old_smp,
            "REC 별도 수익(원)": rec,
            "기존 사업주 총수익(원)": old_total,
            "사업주 VPP 수익(MEP+MAP+MWP)(원)": owner_vpp_before_cost,
            "선택 구축비 차감(원)": repayment,
            "사업주 수수료(원)": owner_service_fee,
            "사업주 VPP 순수익(원)": owner_vpp_net,
            "사업주 참여 후 총수익(원)": owner_after_total,
            "브이젠 CP 총수익(원)": split["vgen_gross_before_imb"],
            "브이젠 IMB 부담(원)": split["vgen_imb_cost"],
            "브이젠 채널 차감 전 수익(원)": split["vgen_before_channel"],
            "채널영업 수수료(원)": split["channel_fee"],
            "브이젠 순수익(원)": vgen_total_net,
            "O&M 비용(원)": om,
            "기존 누적수익(원)": cum_owner_old,
            "참여 후 누적수익(원)": cum_owner_after,
            "누적 사업주 추가수익(원)": cum_owner_gain,
            "누적 브이젠 CP 총수익(원)": cum_vgen_gross_before_imb,
            "누적 브이젠 IMB 부담(원)": cum_vgen_imb_cost,
            "누적 브이젠 채널 차감 전 수익(원)": cum_vgen_before_channel,
            "누적 브이젠 순수익(원)": cum_vgen_net,
            "누적 채널 수수료(원)": cum_channel,
            "누적 사업주 수수료(원)": cum_owner_service_fee,
            "잔여 구축비(원)": remaining_cost,
        })
    return pd.DataFrame(rows)

# ---------------------------------------------------------
# State + Sidebar
# ---------------------------------------------------------
init_defaults()

with st.sidebar:
    st.header("1. 보기 모드")
    role_mode = st.radio("사용 목적", ROLE_MODES, key="role_mode", horizontal=False)
    internal_authenticated = False
    if role_mode == "내부용":
        password = st.text_input("내부용 비밀번호", type="password", placeholder="비밀번호 입력")
        if password == INTERNAL_PASSWORD:
            internal_authenticated = True
            st.success("내부용 화면이 활성화되었습니다.")
        elif password:
            st.error("비밀번호가 맞지 않습니다. 고객용 화면으로 표시됩니다.")
    is_internal = role_mode == "내부용" and internal_authenticated
    is_channel = role_mode == "영업채널용"
    effective_role = "내부용" if is_internal else "영업채널용" if is_channel else "고객용"

    st.header("2. 빠른 케이스")
    case_name = st.selectbox("케이스 선택", list(CASE_PRESETS.keys()), key="selected_case")
    if st.button("케이스 적용", use_container_width=True):
        apply_case(case_name)
        st.rerun()

    st.caption("케이스 적용 후에도 아래 상세 입력에서 값을 직접 수정할 수 있습니다.")

    with st.expander("기본 설정", expanded=False):
        region = st.selectbox("지역", list(REGION_CONFIG.keys()), key="region")
        conf = REGION_CONFIG[region]
        calc_method = st.radio("계산 방식", CALC_METHODS, key="calc_method")
        scenario = st.selectbox("수익 시나리오", list(SCENARIOS.keys()), key="scenario")
        years = st.slider("분석 기간(년)", 1, 30, key="years")

    with st.expander("발전소 정보", expanded=False):
        cap_mw = st.number_input("설비 용량(MW)", min_value=0.01, step=0.1, key="cap_mw")
        gen_time = st.slider("하루 평균 발전시간", 2.0, 5.5, 0.1, key="gen_time")
        degradation_pct = st.number_input("연간 발전효율 감소율(%)", min_value=0.0, max_value=3.0, step=0.1, key="degradation_pct")

    with st.expander("기존 판매단가", expanded=False):
        fixed_total_price = st.number_input("기존 총 판매단가(SMP+REC, 원/kWh)", min_value=0.0, step=1.0, key="fixed_total_price")
        base_smp_price = st.number_input("기존 SMP 상당 단가(원/kWh)", min_value=0.0, step=1.0, key="base_smp_price")
        rec_price = max(fixed_total_price - base_smp_price, 0.0)
        if fixed_total_price < base_smp_price:
            st.warning("SMP 상당 단가가 총 판매단가보다 큽니다. REC 상당 단가는 0원/kWh로 계산합니다.")
        st.caption(f"REC 상당 단가 자동 계산: {rec_price:,.1f} 원/kWh")

    with st.expander("VPP 정산항목", expanded=False):
        cp_unit = st.number_input("CP (Capacity Payment, 용량보상, 원/kWh)", value=float(apply_scenario(conf["cp"], "cp", scenario)), step=0.1)
        mep_unit = st.number_input("MEP (Market Energy Payment, 전력거래정산, 원/kWh)", value=float(apply_scenario(conf["mep"], "mep", scenario)), step=0.1)
        map_unit = st.number_input("MAP (Make-whole Additional Payment, 출력제어 보상, 원/kWh)", value=float(apply_scenario(conf["map"], "map", scenario)), step=0.1)
        mwp_unit = st.number_input("MWP (Make-whole Payment, 급전지시 비용보전, 원/kWh)", value=float(apply_scenario(conf["mwp"], "mwp", scenario)), step=0.1)
        imb_unit = st.number_input("IMB/IMBP (Imbalance Penalty, 예측오차 페널티, 원/kWh)", value=float(apply_scenario(conf["imb"], "imb", scenario)), step=0.1)

    with st.expander("운영 수준", expanded=False):
        operation = st.radio("VPP 운영 수준", list(OPERATION_LEVELS.keys()), key="operation")
        op = OPERATION_LEVELS[operation]
        st.caption(op["desc"])

    if is_channel and st.session_state.get("channel_preset", "채널 없음") == "채널 없음":
        # 영업채널용은 기본 수수료율을 20%로 설정한다.
        # 이후 사용자가 30%, 50%, 직접 입력 등으로 변경 가능하다.
        st.session_state["channel_preset"] = "5MW 모집 채널: 브이젠 수익의 20%"

    if is_internal or is_channel:
        with st.expander("채널/배분 설정", expanded=False):
            channel_preset = st.selectbox("채널영업 수수료율", list(CHANNEL_PRESETS.keys()), key="channel_preset")
            if CHANNEL_PRESETS[channel_preset] is None:
                channel_rate_pct = st.slider("직접 입력 수수료율(%)", 0, 80, key="custom_channel_rate_pct")
            else:
                channel_rate_pct = CHANNEL_PRESETS[channel_preset]
            st.caption(f"채널 수수료율: 브이젠 수익의 {channel_rate_pct}%")
            if is_internal:
                owner_fee_pct = st.slider("사업주 VPP 수익 수수료율(선택, %)", 0, 50, key="owner_fee_pct")
                initial_cost = st.number_input("구축비 차감액(원, 선택 입력)", min_value=0, step=100_000, key="initial_cost")
                om_year1 = st.number_input("연간 O&M/통신/관리비(원, 선택 입력)", min_value=0, step=100_000, key="om_year1")
                om_escalation_pct = st.number_input("O&M 상승률(%/년)", min_value=0.0, max_value=10.0, step=0.1, key="om_escalation_pct")
            else:
                owner_fee_pct = 0
                initial_cost = 0
                om_year1 = 0
                om_escalation_pct = 0.0
    else:
        channel_rate_pct = 0
        owner_fee_pct = 0
        initial_cost = 0
        om_year1 = 0
        om_escalation_pct = 0.0

    with st.expander("참여 가능성 체크", expanded=False):
        has_kpx_meter = st.selectbox("KPX 계량기", ["있음", "없음", "모름"], key="has_kpx_meter")
        has_control_inv = st.selectbox("제어 가능 인버터", ["있음", "없음", "모름"], key="has_control_inv")
        has_remote_comm = st.selectbox("원격 통신 가능", ["가능", "불가", "모름"], key="has_remote_comm")
        site_location_checked = st.selectbox("발전소 위치/계통 확인", ["확인", "미확인", "모름"], key="site_location_checked")
        customer_name = st.text_input("고객명/발전소명(선택)", key="customer_name")

    if calc_method == "정산규칙 근사":
        with st.expander("정산규칙 근사 입력", expanded=False):
            dasmp = st.number_input("DASMP (하루전 전력가격, 원/kWh)", value=float(conf["dasmp"]), step=1.0)
            rtsmp = st.number_input("RTSMP (실시간 전력가격, 원/kWh)", value=float(conf["rtsmp"]), step=1.0)
            da_ratio = st.slider("DAOS (하루전 발전계획량 비율)", 0.0, 1.5, 0.95, 0.01)
            rt_ratio = st.slider("RTOS (실시간 발전계획량 비율)", 0.0, 1.5, 0.93, 0.01)
            actual_ratio = st.slider("MGO (실제 발전량 비율)", 0.0, 1.5, 1.00, 0.01)
            ess_ratio = st.slider("MPE (ESS 충전량 비율)", 0.0, 0.5, 0.00, 0.01)
            available_ratio = st.slider("RA (공급가능량 비율)", 0.0, 1.5, 0.95, 0.01)
            recognized_ratio = st.slider("ELCC/RPCF (용량 인정비율)", 0.0, 1.5, 0.75, 0.01)
            map_spread = st.number_input("MAP 추가 보상단가(원/kWh)", value=0.0, step=0.1)
            mwp_spread = st.number_input("MWP 보전단가(원/kWh)", value=max(mwp_unit, 0.0), step=0.1)
            tolerance_pct = st.number_input("IMB 허용오차율(%)", min_value=0.0, max_value=30.0, value=8.0, step=0.5)
            penalty_factor = st.number_input("IMPF (IMB 페널티 계수)", min_value=0.0, value=1.0, step=0.1)
    else:
        dasmp = conf["dasmp"]
        rtsmp = conf["rtsmp"]
        da_ratio = 0.95
        rt_ratio = 0.93
        actual_ratio = 1.0
        ess_ratio = 0.0
        available_ratio = 0.95
        recognized_ratio = 0.75
        map_spread = 0.0
        mwp_spread = max(mwp_unit, 0.0)
        tolerance_pct = 8.0
        penalty_factor = 1.0

# ---------------------------------------------------------
# Run calculations
# ---------------------------------------------------------
degradation = degradation_pct / 100
channel_rate = channel_rate_pct / 100
owner_fee_rate = owner_fee_pct / 100
om_escalation = om_escalation_pct / 100

gen_y1 = annual_generation(cap_mw, gen_time, degradation, 1)
old_smp_y1 = gen_y1 * base_smp_price
rec_y1 = gen_y1 * rec_price
old_total_y1 = gen_y1 * fixed_total_price


def effect_func(gen_kwh):
    if calc_method == "간편 수익비교":
        return calc_simple_effect(gen_kwh, cp_unit, mep_unit, map_unit, mwp_unit, imb_unit, op["mep_mult"], op["imb_mult"])
    return calc_rule_effect(
        gen_kwh,
        base_smp_price,
        dasmp,
        rtsmp,
        da_ratio,
        rt_ratio,
        actual_ratio,
        ess_ratio,
        cp_unit,
        available_ratio,
        recognized_ratio,
        map_spread,
        mwp_spread,
        tolerance_pct / 100,
        penalty_factor,
        op["mep_mult"],
        op["imb_mult"],
    )


effect_y1 = effect_func(gen_y1)
split_y1 = split_revenue(effect_y1["amounts"], channel_rate)

owner_vpp_before_cost_y1 = split_y1["owner_vpp"]
repayment_y1 = min(initial_cost, owner_vpp_before_cost_y1) if initial_cost > 0 and owner_vpp_before_cost_y1 > 0 else 0.0
owner_vpp_after_cost_y1 = owner_vpp_before_cost_y1 - repayment_y1
owner_service_fee_y1 = owner_vpp_after_cost_y1 * owner_fee_rate if owner_vpp_after_cost_y1 > 0 else 0.0
owner_vpp_net_y1 = owner_vpp_after_cost_y1 - owner_service_fee_y1
owner_after_total_y1 = old_total_y1 + owner_vpp_net_y1 - om_year1
owner_improvement_y1 = safe_div(owner_vpp_net_y1, old_total_y1) * 100

vgen_cp_gross_y1 = split_y1["vgen_gross_before_imb"]
vgen_imb_cost_y1 = split_y1["vgen_imb_cost"]
vgen_before_channel_y1 = split_y1["vgen_before_channel"]
channel_fee_y1 = split_y1["channel_fee"]
vgen_net_y1 = split_y1["vgen_after_channel"] + owner_service_fee_y1

normal_imb_amount = gen_y1 * imb_unit * OPERATION_LEVELS["일반 운영"]["imb_mult"]
selected_imb_amount = effect_y1["amounts"].get(TERM_LABELS["imb"], 0.0)
imb_defense_effect = selected_imb_amount - normal_imb_amount
map_amount = effect_y1["amounts"].get(TERM_LABELS["map"], 0.0)
mwp_amount = effect_y1["amounts"].get(TERM_LABELS["mwp"], 0.0)
curtail_dispatch_effect = map_amount + mwp_amount

cashflow_df = calc_cashflow(
    years,
    cap_mw,
    gen_time,
    degradation,
    fixed_total_price,
    base_smp_price,
    rec_price,
    channel_rate,
    initial_cost,
    owner_fee_rate,
    om_year1,
    om_escalation,
    effect_func,
)

sum_old = cashflow_df["기존 사업주 총수익(원)"].sum()
sum_owner_after = cashflow_df["사업주 참여 후 총수익(원)"].sum()
sum_owner_gain = cashflow_df["사업주 VPP 순수익(원)"].sum()
sum_vgen_cp_gross = cashflow_df["누적 브이젠 CP 총수익(원)"].iloc[-1]
sum_vgen_imb_cost = cashflow_df["누적 브이젠 IMB 부담(원)"].iloc[-1]
sum_vgen_before_channel = cashflow_df["누적 브이젠 채널 차감 전 수익(원)"].iloc[-1]
sum_vgen = cashflow_df["누적 브이젠 순수익(원)"].iloc[-1]
sum_channel = cashflow_df["누적 채널 수수료(원)"].iloc[-1]
sum_owner_service_fee = cashflow_df["누적 사업주 수수료(원)"].iloc[-1]

score = 0
score += 30 if has_kpx_meter == "있음" else 10 if has_kpx_meter == "모름" else 0
score += 30 if has_control_inv == "있음" else 10 if has_control_inv == "모름" else 0
score += 25 if has_remote_comm == "가능" else 10 if has_remote_comm == "모름" else 0
score += 15 if site_location_checked == "확인" else 5 if site_location_checked == "모름" else 0
grade, grade_class = get_grade(score)

# ---------------------------------------------------------
# PDF report
# ---------------------------------------------------------
def make_pdf() -> bytes | None:
    if not os.path.exists(FONT_PATH):
        return None

    pdf = FPDF()
    pdf.add_font("NanumGothic", "", FONT_PATH)
    pdf.set_auto_page_break(auto=True, margin=14)
    pdf.add_page()

    pdf.set_fill_color(15, 42, 80)
    pdf.rect(0, 0, 210, 44, "F")
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("NanumGothic", size=18)
    pdf.ln(10)
    pdf.cell(190, 10, "V-GEN VPP 수익 비교 리포트", ln=True, align="C")
    pdf.set_font("NanumGothic", size=9)
    pdf.cell(190, 7, f"생성일: {datetime.now().strftime('%Y-%m-%d %H:%M')} / {calc_method}", ln=True, align="C")

    pdf.set_text_color(0, 0, 0)
    pdf.ln(18)
    pdf.set_font("NanumGothic", size=14)
    pdf.cell(190, 9, "1. 사업주 수익 비교", "B", ln=True)
    pdf.ln(4)
    pdf.set_font("NanumGothic", size=9)
    rows = [
        ("기존 연간 총수익", fmt_manwon(old_total_y1)),
        ("VPP 참여 후 연간 총수익", fmt_manwon(owner_after_total_y1)),
        ("사업주 연간 추가수익", fmt_manwon(owner_vpp_net_y1)),
        ("개선율", f"{owner_improvement_y1:,.1f}%"),
        (f"{years}년 누적 사업주 추가수익", fmt_manwon(sum_owner_gain)),
    ]
    pdf.set_fill_color(240, 245, 255)
    for i, (k, v) in enumerate(rows):
        fill = i % 2 == 0
        pdf.cell(82, 8, k, 1, 0, "C", fill)
        pdf.cell(108, 8, v, 1, 1, "R", fill)

    if is_internal:
        pdf.ln(6)
        pdf.set_font("NanumGothic", size=14)
        pdf.cell(190, 9, "2. 내부 브이젠 수익", "B", ln=True)
        pdf.ln(4)
        internal_rows = [
            ("브이젠 CP 총수익", fmt_manwon(vgen_cp_gross_y1)),
            ("브이젠 IMB 부담", fmt_manwon(vgen_imb_cost_y1)),
            ("채널 차감 전 브이젠 수익", fmt_manwon(vgen_before_channel_y1)),
            ("채널영업 수수료", fmt_manwon(channel_fee_y1)),
            ("사업주 수수료", fmt_manwon(owner_service_fee_y1)),
            ("브이젠 순수익", fmt_manwon(vgen_net_y1)),
            (f"{years}년 누적 브이젠 순수익", fmt_manwon(sum_vgen)),
        ]
        pdf.set_font("NanumGothic", size=9)
        for i, (k, v) in enumerate(internal_rows):
            fill = i % 2 == 0
            pdf.cell(82, 8, k, 1, 0, "C", fill)
            pdf.cell(108, 8, v, 1, 1, "R", fill)

    pdf.ln(6)
    pdf.set_font("NanumGothic", size=14)
    pdf.cell(190, 9, "참여 가능성", "B", ln=True)
    pdf.ln(4)
    pdf.set_font("NanumGothic", size=9)
    pdf.multi_cell(190, 6, f"참여 가능성: {grade} / 점수: {score}점")
    pdf.multi_cell(190, 6, f"KPX 계량기: {has_kpx_meter}, 제어 가능 인버터: {has_control_inv}, 원격 통신: {has_remote_comm}, 위치/계통 확인: {site_location_checked}")

    pdf.ln(4)
    pdf.set_font("NanumGothic", size=8)
    pdf.set_text_color(80, 80, 80)
    pdf.multi_cell(190, 5, "본 계산은 입력값 기반 예상 수익효과입니다. 실제 정산금은 전력거래소 정산 기준, 계량값, 입찰·낙찰 결과, 급전지시 이행 여부, IMB 적용 여부에 따라 달라질 수 있습니다. MEP 비교 기준은 REC 포함 총단가가 아니라 기존 SMP 상당 단가입니다. REC 상당 수익은 사업주 별도 수익으로 유지합니다.")
    return pdf_to_bytes(pdf)

# ---------------------------------------------------------
# Main UI
# ---------------------------------------------------------
st.markdown(
    """
<div class="hero">
  <h1>V-GEN VPP 수익 계산기</h1>
  <p>고객용·영업채널용·내부용을 구분하고, 제주/육지 주요 케이스를 빠르게 불러와 수익을 비교합니다.</p>
</div>
""",
    unsafe_allow_html=True,
)

if role_mode == "내부용" and not internal_authenticated:
    st.warning("내부용 화면은 비밀번호 입력 후 확인할 수 있습니다. 현재는 고객용 화면으로 표시됩니다.")

st.markdown(
    f"""
<div class="blue-box">
  <b>현재 보기:</b> {effective_role} &nbsp; | &nbsp; <b>선택 케이스:</b> {st.session_state.get('selected_case', '직접 입력')} &nbsp; | &nbsp; <b>지역:</b> {region} &nbsp; | &nbsp; <b>용량:</b> {cap_mw:,.1f}MW
</div>
""",
    unsafe_allow_html=True,
)

# Customer top cards
c1, c2, c3 = st.columns(3)
with c1:
    st.markdown(f"""<div class="card"><div class="label">기존 연간 수익</div><div class="big">{fmt_manwon(old_total_y1)}</div><div class="small">SMP {fmt_manwon(old_smp_y1)} + REC {fmt_manwon(rec_y1)}</div></div>""", unsafe_allow_html=True)
with c2:
    st.markdown(f"""<div class="card"><div class="label">VPP 참여 후 연간 수익</div><div class="big">{fmt_manwon(owner_after_total_y1)}</div><div class="small">기존 수익 + VPP 참여 추가수익</div></div>""", unsafe_allow_html=True)
with c3:
    st.markdown(f"""<div class="card"><div class="label">연간 추가수익</div><div class="plus">+{fmt_manwon(owner_vpp_net_y1)}</div><div class="small">기존 대비 {owner_improvement_y1:,.1f}% 상승</div></div>""", unsafe_allow_html=True)

st.markdown(
    f"""
<div class="green-box">
  <b>핵심 결과:</b> 현재 입력값 기준 VPP 참여 시 사업주는 1년차 기준 <b>{fmt_manwon(owner_vpp_net_y1)}</b>의 추가수익을 기대할 수 있습니다. 기존 SMP/REC 수익은 유지하고, MEP/MAP/MWP 정산효과가 추가되는 구조입니다.
</div>
""",
    unsafe_allow_html=True,
)

# 내부용 핵심 수익은 사업주 수익 카드 바로 아래에서 먼저 확인한다.
if is_internal:
    st.subheader("내부용: 브이젠 총수익 상세")
    st.markdown(
        f"""
<div class="blue-box">
  <b>내부 배분 기준:</b> <span class="badge badge-blue">CP 브이젠 귀속</span> <span class="badge badge-orange">IMB/IMBP 브이젠 부담</span> <span class="badge badge-green">MEP/MAP/MWP 사업주 귀속</span><br>
  채널영업 수수료는 브이젠 CP 총수익의 <b>{channel_rate_pct}%</b>로 계산합니다.
</div>
""",
        unsafe_allow_html=True,
    )
    it1, it2, it3, it4 = st.columns(4)
    with it1:
        st.markdown(f"""<div class="card"><div class="label">브이젠 CP 총수익</div><div class="big">{fmt_manwon(vgen_cp_gross_y1)}</div><div class="small">CP 전체 브이젠 귀속</div></div>""", unsafe_allow_html=True)
    with it2:
        st.markdown(f"""<div class="card"><div class="label">브이젠 IMB 부담</div><div class="red">{fmt_manwon(vgen_imb_cost_y1)}</div><div class="small">IMB/IMBP 브이젠 부담</div></div>""", unsafe_allow_html=True)
    with it3:
        st.markdown(f"""<div class="card"><div class="label">채널영업 수수료</div><div class="big">{fmt_manwon(channel_fee_y1)}</div><div class="small">CP 총수익의 {channel_rate_pct}%</div></div>""", unsafe_allow_html=True)
    with it4:
        st.markdown(f"""<div class="card"><div class="label">브이젠 최종 순수익</div><div class="big">{fmt_manwon(vgen_net_y1)}</div><div class="small">CP + IMB - 채널수수료 + 선택수수료</div></div>""", unsafe_allow_html=True)

    it5, it6, it7, it8 = st.columns(4)
    with it5:
        st.markdown(f"""<div class="card"><div class="label">채널 차감 전 브이젠 수익</div><div class="big">{fmt_manwon(vgen_before_channel_y1)}</div><div class="small">CP + IMB 부담 반영</div></div>""", unsafe_allow_html=True)
    with it6:
        st.markdown(f"""<div class="card"><div class="label">사업주 수수료</div><div class="big">{fmt_manwon(owner_service_fee_y1)}</div><div class="small">선택 입력값 기준</div></div>""", unsafe_allow_html=True)
    with it7:
        st.markdown(f"""<div class="card"><div class="label">{years}년 누적 브이젠 순수익</div><div class="big">{fmt_manwon(sum_vgen)}</div><div class="small">채널수수료 차감 후</div></div>""", unsafe_allow_html=True)
    with it8:
        st.markdown(f"""<div class="card"><div class="label">{years}년 누적 채널 수수료</div><div class="big">{fmt_manwon(sum_channel)}</div><div class="small">채널 파트너 지급액</div></div>""", unsafe_allow_html=True)

# Channel summary for channel mode only
if is_channel:
    st.subheader("영업채널용 요약")
    ch1, ch2, ch3 = st.columns(3)
    with ch1:
        st.markdown(f"""<div class="card"><div class="label">채널영업 연간 수수료</div><div class="big">{fmt_manwon(channel_fee_y1)}</div><div class="small">브이젠 수익의 {channel_rate_pct}% 기준</div></div>""", unsafe_allow_html=True)
    with ch2:
        st.markdown(f"""<div class="card"><div class="label">{years}년 누적 채널 수수료</div><div class="big">{fmt_manwon(sum_channel)}</div><div class="small">선택 케이스 기준</div></div>""", unsafe_allow_html=True)
    with ch3:
        st.markdown(f"""<div class="card"><div class="label">모집 용량</div><div class="big">{cap_mw:,.1f} MW</div><div class="small">{channel_preset}</div></div>""", unsafe_allow_html=True)

# Customer comparison chart
st.subheader("1. 기존 vs VPP 참여 후 사업주 수익")
compare_df = pd.DataFrame({
    "구분": ["1년차", f"{years}년 누적"],
    "기존 수익(만원)": [won_to_manwon(old_total_y1), won_to_manwon(sum_old)],
    "VPP 참여 후 수익(만원)": [won_to_manwon(owner_after_total_y1), won_to_manwon(sum_owner_after)],
    "추가수익(만원)": [won_to_manwon(owner_vpp_net_y1), won_to_manwon(sum_owner_gain)],
})
fig_compare = go.Figure()
fig_compare.add_trace(go.Bar(x=compare_df["구분"], y=compare_df["기존 수익(만원)"], name="기존 수익"))
fig_compare.add_trace(go.Bar(x=compare_df["구분"], y=compare_df["VPP 참여 후 수익(만원)"], name="VPP 참여 후 수익"))
fig_compare.update_layout(barmode="group", height=430, yaxis_title="만원", margin=dict(l=20, r=20, t=30, b=40), legend=dict(orientation="h", y=1.08, x=1, xanchor="right"))
st.plotly_chart(fig_compare, use_container_width=True)

# Customer visible profit composition
st.subheader("2. 사업주 추가수익 구성")
owner_items = pd.DataFrame({
    "항목": [TERM_LABELS["mep"], TERM_LABELS["map"], TERM_LABELS["mwp"]],
    "연간 효과(만원)": [
        won_to_manwon(split_y1["mep_to_owner"]),
        won_to_manwon(split_y1["map_to_owner"]),
        won_to_manwon(split_y1["mwp_to_owner"]),
    ],
})
fig_owner_items = go.Figure()
fig_owner_items.add_trace(go.Bar(x=owner_items["항목"], y=owner_items["연간 효과(만원)"], text=[f"{v:,.0f}만원" for v in owner_items["연간 효과(만원)"]], textposition="outside"))
fig_owner_items.update_layout(height=410, yaxis_title="만원/년", margin=dict(l=20, r=20, t=30, b=110))
st.plotly_chart(fig_owner_items, use_container_width=True)

# Customer cumulative line
st.subheader("3. 연차별 누적수익 비교")
fig_line = go.Figure()
fig_line.add_trace(go.Scatter(x=cashflow_df["연차"], y=cashflow_df["기존 누적수익(원)"].apply(won_to_manwon), mode="lines+markers", name="기존 누적수익"))
fig_line.add_trace(go.Scatter(x=cashflow_df["연차"], y=cashflow_df["참여 후 누적수익(원)"].apply(won_to_manwon), mode="lines+markers", name="VPP 참여 후 누적수익"))
fig_line.add_trace(go.Scatter(x=cashflow_df["연차"], y=cashflow_df["누적 사업주 추가수익(원)"].apply(won_to_manwon), mode="lines+markers", name="누적 추가수익"))
fig_line.update_layout(height=430, yaxis_title="만원", xaxis_title="연차", margin=dict(l=20, r=20, t=30, b=40), legend=dict(orientation="h", y=1.08, x=1, xanchor="right"))
st.plotly_chart(fig_line, use_container_width=True)

# Participation checklist visible to all roles
st.subheader("4. 참여 가능성 진단")
check_cols = st.columns([1, 2])
with check_cols[0]:
    st.markdown(f"""<div class="card"><div class="label">참여 가능성 점수</div><div class="big">{score}점</div><span class="badge {grade_class}">{grade}</span></div>""", unsafe_allow_html=True)
with check_cols[1]:
    next_actions = []
    if has_kpx_meter != "있음":
        next_actions.append("KPX 계량기 설치/보유 여부 확인")
    if has_control_inv != "있음":
        next_actions.append("인버터 제어 가능 여부 및 제조사/모델명 확인")
    if has_remote_comm != "가능":
        next_actions.append("원격 통신 가능 여부 확인")
    if site_location_checked != "확인":
        next_actions.append("발전소 위치 및 계통 조건 확인")
    if not next_actions:
        next_actions.append("참여 가능성이 높습니다. 계약 조건 및 데이터 연동 검토로 진행 가능합니다.")
    st.markdown("**다음 확인사항**")
    for action in next_actions:
        st.write(f"- {action}")

with st.expander("연차별 상세표 보기", expanded=False):
    if is_internal:
        table_df = cashflow_df.copy()
    elif is_channel:
        table_df = cashflow_df[["연차", "발전량(kWh)", "기존 사업주 총수익(원)", "사업주 VPP 순수익(원)", "사업주 참여 후 총수익(원)", "채널영업 수수료(원)", "누적 채널 수수료(원)"]].copy()
    else:
        table_df = cashflow_df[["연차", "발전량(kWh)", "기존 사업주 총수익(원)", "사업주 VPP 순수익(원)", "사업주 참여 후 총수익(원)", "누적 사업주 추가수익(원)"]].copy()
    for col in list(table_df.columns):
        if col.endswith("(원)"):
            table_df[col.replace("(원)", "(만원)")] = table_df[col].apply(won_to_manwon)
            table_df.drop(columns=[col], inplace=True)
    table_df["발전량(kWh)"] = table_df["발전량(kWh)"].round(0)
    for col in table_df.columns:
        if col.endswith("(만원)"):
            table_df[col] = table_df[col].round(1)
    st.dataframe(table_df, use_container_width=True, hide_index=True)

# Internal-only sections
if is_internal:
    st.subheader("5. 내부용: 브이젠 총수익 상세")
    st.markdown(
        f"""
<div class="blue-box">
  <b>내부 배분 기준:</b> <span class="badge badge-blue">CP 브이젠 귀속</span> <span class="badge badge-orange">IMB/IMBP 브이젠 부담</span> <span class="badge badge-green">MEP/MAP/MWP 사업주 귀속</span><br>
  채널영업 수수료는 브이젠 CP 총수익의 <b>{channel_rate_pct}%</b>로 계산합니다.
</div>
""",
        unsafe_allow_html=True,
    )

    i1, i2, i3, i4 = st.columns(4)
    with i1:
        st.markdown(f"""<div class="card"><div class="label">브이젠 CP 총수익</div><div class="big">{fmt_manwon(vgen_cp_gross_y1)}</div><div class="small">CP 전체 브이젠 귀속</div></div>""", unsafe_allow_html=True)
    with i2:
        st.markdown(f"""<div class="card"><div class="label">브이젠 IMB 부담</div><div class="red">{fmt_manwon(vgen_imb_cost_y1)}</div><div class="small">IMB/IMBP 브이젠 부담</div></div>""", unsafe_allow_html=True)
    with i3:
        st.markdown(f"""<div class="card"><div class="label">채널 차감 전 브이젠 수익</div><div class="big">{fmt_manwon(vgen_before_channel_y1)}</div><div class="small">CP + IMB 부담 반영</div></div>""", unsafe_allow_html=True)
    with i4:
        st.markdown(f"""<div class="card"><div class="label">브이젠 최종 순수익</div><div class="big">{fmt_manwon(vgen_net_y1)}</div><div class="small">채널수수료 차감 후</div></div>""", unsafe_allow_html=True)

    j1, j2, j3, j4 = st.columns(4)
    with j1:
        st.markdown(f"""<div class="card"><div class="label">채널영업 연간 수수료</div><div class="big">{fmt_manwon(channel_fee_y1)}</div><div class="small">브이젠 수익의 {channel_rate_pct}%</div></div>""", unsafe_allow_html=True)
    with j2:
        st.markdown(f"""<div class="card"><div class="label">사업주 수수료</div><div class="big">{fmt_manwon(owner_service_fee_y1)}</div><div class="small">선택 입력값 기준</div></div>""", unsafe_allow_html=True)
    with j3:
        st.markdown(f"""<div class="card"><div class="label">{years}년 누적 브이젠 순수익</div><div class="big">{fmt_manwon(sum_vgen)}</div><div class="small">채널수수료 차감 후</div></div>""", unsafe_allow_html=True)
    with j4:
        st.markdown(f"""<div class="card"><div class="label">{years}년 누적 채널 수수료</div><div class="big">{fmt_manwon(sum_channel)}</div><div class="small">채널 파트너 지급액</div></div>""", unsafe_allow_html=True)

    st.subheader("6. 내부용: 브이젠 수익 브릿지")
    bridge_df = pd.DataFrame({
        "항목": ["CP 총수익", "IMB/IMBP 부담", "채널 차감 전 수익", "채널영업 수수료", "사업주 수수료", "브이젠 최종 순수익"],
        "1년차(만원)": [
            won_to_manwon(vgen_cp_gross_y1),
            won_to_manwon(vgen_imb_cost_y1),
            won_to_manwon(vgen_before_channel_y1),
            won_to_manwon(channel_fee_y1),
            won_to_manwon(owner_service_fee_y1),
            won_to_manwon(vgen_net_y1),
        ],
        f"{years}년 누적(만원)": [
            won_to_manwon(sum_vgen_cp_gross),
            won_to_manwon(sum_vgen_imb_cost),
            won_to_manwon(sum_vgen_before_channel),
            won_to_manwon(sum_channel),
            won_to_manwon(sum_owner_service_fee),
            won_to_manwon(sum_vgen),
        ],
    })
    st.dataframe(bridge_df.round(1), use_container_width=True, hide_index=True)

    fig_bridge = go.Figure()
    fig_bridge.add_trace(go.Bar(x=bridge_df["항목"], y=bridge_df["1년차(만원)"], name="1년차"))
    fig_bridge.add_trace(go.Bar(x=bridge_df["항목"], y=bridge_df[f"{years}년 누적(만원)"], name=f"{years}년 누적"))
    fig_bridge.update_layout(barmode="group", height=440, yaxis_title="만원", margin=dict(l=20, r=20, t=30, b=90), legend=dict(orientation="h", y=1.08, x=1, xanchor="right"))
    st.plotly_chart(fig_bridge, use_container_width=True)

    st.subheader("7. 내부용: 사업주 / 브이젠 / 채널 누적 비교")
    split_df = pd.DataFrame({
        "구분": ["사업주 VPP 추가수익", "브이젠 순수익", "채널영업 수수료"],
        "1년차(만원)": [won_to_manwon(owner_vpp_net_y1), won_to_manwon(vgen_net_y1), won_to_manwon(channel_fee_y1)],
        f"{years}년 누적(만원)": [won_to_manwon(sum_owner_gain), won_to_manwon(sum_vgen), won_to_manwon(sum_channel)],
    })
    fig_split = go.Figure()
    fig_split.add_trace(go.Bar(x=split_df["구분"], y=split_df["1년차(만원)"], name="1년차"))
    fig_split.add_trace(go.Bar(x=split_df["구분"], y=split_df[f"{years}년 누적(만원)"], name=f"{years}년 누적"))
    fig_split.update_layout(barmode="group", height=430, yaxis_title="만원", margin=dict(l=20, r=20, t=30, b=60), legend=dict(orientation="h", y=1.08, x=1, xanchor="right"))
    st.plotly_chart(fig_split, use_container_width=True)

    st.subheader("8. 내부용 CP/MEP/MAP/MWP/IMB 상세")
    item_df = pd.DataFrame({
        "항목": list(effect_y1["amounts"].keys()),
        "단가(원/kWh)": [effect_y1["units"][k] for k in effect_y1["amounts"].keys()],
        "연간 효과(만원)": [won_to_manwon(v) for v in effect_y1["amounts"].values()],
        "귀속": ["브이젠", "사업주", "사업주", "사업주", "브이젠 부담"],
    })
    col_i1, col_i2 = st.columns([1.2, 1])
    with col_i1:
        fig_items = go.Figure()
        fig_items.add_trace(
            go.Bar(
                x=item_df["항목"],
                y=item_df["연간 효과(만원)"],
                text=[f"{v:,.0f}만원" for v in item_df["연간 효과(만원)"]],
                textposition="outside",
            )
        )
        fig_items.update_layout(height=440, yaxis_title="만원/년", margin=dict(l=20, r=20, t=30, b=120))
        st.plotly_chart(fig_items, use_container_width=True)
    with col_i2:
        st.dataframe(item_df.round(2), use_container_width=True, hide_index=True)
        st.markdown(f"""<div class="card"><div class="label">IMB 방어 효과</div><div class="big">{fmt_manwon(imb_defense_effect)}</div><div class="small">일반 운영 대비 현재 운영 수준의 IMB 차이입니다.</div></div>""", unsafe_allow_html=True)
        st.markdown(f"""<div class="card"><div class="label">출력제어·급전 대응 효과</div><div class="big">{fmt_manwon(curtail_dispatch_effect)}</div><div class="small">MAP + MWP 합계입니다.</div></div>""", unsafe_allow_html=True)

    st.subheader("9. 내부용 용량별 빠른 비교")
    capacity_list = [0.5, 1, 3, 5, 10, 50, 100]
    quick_rows = []
    for c in capacity_list:
        gen_q = annual_generation(c, gen_time, degradation, 1)
        old_q = gen_q * fixed_total_price
        effect_q = effect_func(gen_q)
        split_q = split_revenue(effect_q["amounts"], channel_rate)
        owner_gross_q = split_q["owner_vpp"]
        owner_fee_q = owner_gross_q * owner_fee_rate if owner_gross_q > 0 else 0
        owner_q = owner_gross_q - owner_fee_q
        vgen_q = split_q["vgen_after_channel"] + owner_fee_q
        quick_rows.append({
            "용량(MW)": c,
            "기존 사업주 수익(만원/년)": won_to_manwon(old_q),
            "사업주 추가수익(만원/년)": won_to_manwon(owner_q),
            "브이젠 CP 총수익(만원/년)": won_to_manwon(split_q["vgen_gross_before_imb"]),
            "브이젠 IMB 부담(만원/년)": won_to_manwon(split_q["vgen_imb_cost"]),
            "브이젠 순수익(만원/년)": won_to_manwon(vgen_q),
            "채널 수수료(만원/년)": won_to_manwon(split_q["channel_fee"]),
        })
    quick_df = pd.DataFrame(quick_rows)
    st.dataframe(quick_df.round(1), use_container_width=True, hide_index=True)

    if effect_y1["detail"]:
        with st.expander("정산규칙 근사 상세값", expanded=False):
            detail_df = pd.DataFrame({"항목": list(effect_y1["detail"].keys()), "값": list(effect_y1["detail"].values())})
            st.dataframe(detail_df, use_container_width=True, hide_index=True)

# Downloads
st.subheader("보고서 다운로드")
lead_df = pd.DataFrame([{
    "생성일": datetime.now().strftime("%Y-%m-%d %H:%M"),
    "보기 모드": effective_role,
    "선택 케이스": st.session_state.get("selected_case", "직접 입력"),
    "고객명/발전소명": customer_name,
    "지역": region,
    "설비용량(MW)": cap_mw,
    "기존 총 판매단가": fixed_total_price,
    "기존 SMP 상당 단가": base_smp_price,
    "REC 상당 단가": rec_price,
    "사업주 연간 추가수익(만원)": won_to_manwon(owner_vpp_net_y1),
    "참여 가능성": grade,
    "점수": score,
}])

if is_channel or is_internal:
    lead_df["채널 연간 수수료(만원)"] = won_to_manwon(channel_fee_y1)
if is_internal:
    lead_df["브이젠 CP 총수익(만원)"] = won_to_manwon(vgen_cp_gross_y1)
    lead_df["브이젠 IMB 부담(만원)"] = won_to_manwon(vgen_imb_cost_y1)
    lead_df["브이젠 연간 순수익(만원)"] = won_to_manwon(vgen_net_y1)

col_d1, col_d2 = st.columns(2)
with col_d1:
    st.download_button("상담 요약 CSV 다운로드", data=lead_df.to_csv(index=False).encode("utf-8-sig"), file_name="vgen_vpp_lead_summary.csv", mime="text/csv", use_container_width=True)
with col_d2:
    download_df = cashflow_df.copy()
    if not is_internal:
        cols = ["연차", "발전량(kWh)", "기존 사업주 총수익(원)", "사업주 VPP 순수익(원)", "사업주 참여 후 총수익(원)", "누적 사업주 추가수익(원)"]
        if is_channel:
            cols += ["채널영업 수수료(원)", "누적 채널 수수료(원)"]
        download_df = download_df[cols]
    st.download_button("연차별 현금흐름 CSV 다운로드", data=download_df.to_csv(index=False).encode("utf-8-sig"), file_name="vgen_vpp_cashflow.csv", mime="text/csv", use_container_width=True)

pdf_data = make_pdf()
if pdf_data is None:
    st.error("PDF 생성을 위해 app.py와 같은 폴더에 NanumGothic.ttf 파일을 넣어주세요.")
else:
    st.download_button("PDF 리포트 다운로드", data=pdf_data, file_name="VGEN_VPP_Report.pdf", mime="application/pdf", use_container_width=True)

st.warning("육지 전역 재생에너지 입찰시장 확대 시행에 따라 기존 예측정산금 제도는 공식 일몰될 예정입니다. 향후 재생에너지 수익은 CP/MEP/MAP/MWP 확보와 IMB 관리 역량에 따라 달라질 수 있습니다.")
st.info("본 계산은 입력값 기반 예상 수익효과입니다. 실제 정산금은 전력거래소 정산 기준, 계량값, 입찰·낙찰 결과, 급전지시 이행 여부, IMB 적용 여부에 따라 달라질 수 있습니다. MEP 비교 기준은 REC 포함 총단가가 아니라 기존 SMP 상당 단가입니다. REC 상당 수익은 사업주 별도 수익으로 유지합니다.")

if is_internal:
    with st.expander("내부용 용어 및 배분 기준", expanded=False):
        st.markdown(
            """
- **CP (Capacity Payment, 용량보상)**: 브이젠 귀속으로 계산합니다.
- **MEP (Market Energy Payment, 전력거래정산)**: 사업주 귀속으로 계산합니다. 기존 총단가가 아니라 기존 SMP 상당 단가와 비교합니다.
- **MAP (Make-whole Additional Payment, 출력제어 보상)**: 사업주 귀속으로 계산합니다.
- **MWP (Make-whole Payment, 급전지시 비용보전)**: 사업주 귀속으로 계산합니다.
- **IMB/IMBP (Imbalance Penalty, 예측오차 페널티)**: 브이젠 부담으로 계산합니다.
- **채널영업 수수료**: 브이젠 CP 총수익에서 선택한 비율만큼 지급하는 것으로 계산합니다.
- **브이젠 최종 순수익**: CP 총수익 + IMB 부담 - 채널영업 수수료 + 선택 입력한 사업주 수수료입니다.
            """
        )
