import os
import math
from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from fpdf import FPDF

# =========================================================
# V-GEN VPP 수익효과 시뮬레이터
# - Streamlit / pandas / plotly / fpdf2 only
# - NanumGothic.ttf must be located in the same directory as app.py
# =========================================================

st.set_page_config(
    page_title="V-GEN VPP 수익효과 시뮬레이터 v7.0",
    layout="wide",
    initial_sidebar_state="expanded",
)

FONT_FILENAME = "NanumGothic.ttf"
FONT_PATH = os.path.join(os.getcwd(), FONT_FILENAME)
INITIAL_COST_DEFAULT = 3_000_000  # RTU 150만원 + 신자취 150만원
DEFAULT_PROJECT_YEARS = 20

# ---------------------------------------------------------
# 기본 설정값
# 모든 금액 단위는 내부적으로 '원' 또는 '원/kWh'를 사용한다.
# 화면 표시는 '만원' 중심.
# ---------------------------------------------------------
REGION_CONFIG = {
    "호남/육지 (입찰제 확대 모델)": {
        "cp": 11.0,
        "mep": 1.2,
        "map": 0.8,
        "mwp": 0.5,
        "imb": -0.3,
        "dasmp": 120.0,
        "rtsmp": 122.0,
        "cp_unit": 11.0,
        "curtailment_ratio": 0.02,
        "imb_error_ratio": 0.03,
    },
    "제주도 (입찰제 안착 모델)": {
        "cp": 22.0,
        "mep": 1.2,
        "map": 2.5,
        "mwp": 1.0,
        "imb": -0.8,
        "dasmp": 115.0,
        "rtsmp": 120.0,
        "cp_unit": 22.0,
        "curtailment_ratio": 0.08,
        "imb_error_ratio": 0.05,
    },
}

SCENARIO_MULTIPLIERS = {
    "보수": {"cp": 0.75, "mep": 0.6, "map": 0.5, "mwp": 0.5, "imb": 1.5},
    "기준": {"cp": 1.0, "mep": 1.0, "map": 1.0, "mwp": 1.0, "imb": 1.0},
    "낙관": {"cp": 1.25, "mep": 1.3, "map": 1.25, "mwp": 1.2, "imb": 0.7},
}

OPERATION_OPTIONS = {
    "보수 운영 시나리오": {"mep_mult": 0.4, "imb_mult": 2.0, "label": "예측/입찰/제어 역량 낮음"},
    "기준 운영 시나리오": {"mep_mult": 0.8, "imb_mult": 1.2, "label": "일반적인 운영 역량"},
    "브이젠 고도화 운영 시나리오": {"mep_mult": 1.6, "imb_mult": 0.4, "label": "V-GEN 예측·입찰·제어 최적화"},
}

CALC_METHODS = [
    "영업용 환산단가 모델",
    "제도 산식 근사 모델",
]

VIEW_MODES = ["고객용", "내부용"]

# ---------------------------------------------------------
# 유틸 함수
# ---------------------------------------------------------
def won_to_manwon(value: float) -> float:
    return value / 10_000


def fmt_manwon(value: float, digits: int = 0) -> str:
    return f"{won_to_manwon(value):,.{digits}f} 만원"


def fmt_won_per_kwh(value: float, digits: int = 2) -> str:
    return f"{value:,.{digits}f} 원/kWh"


def safe_div(numerator: float, denominator: float, default: float = 0.0) -> float:
    if denominator == 0 or denominator is None:
        return default
    return numerator / denominator


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def pdf_output_to_bytes(pdf: FPDF) -> bytes:
    """fpdf2 버전 차이에 따른 output 반환형(str/bytearray/bytes)을 안전하게 bytes로 변환."""
    raw = pdf.output(dest="S")
    if isinstance(raw, bytes):
        return raw
    if isinstance(raw, bytearray):
        return bytes(raw)
    return raw.encode("latin-1")


# ---------------------------------------------------------
# 계산 함수
# ---------------------------------------------------------
def calc_annual_generation(cap_mw: float, gen_time: float, degradation: float, year: int) -> float:
    base = cap_mw * 1_000 * gen_time * 365
    return base * ((1 - degradation) ** (year - 1))


def apply_scenario(base_value: float, item_key: str, scenario_name: str) -> float:
    return base_value * SCENARIO_MULTIPLIERS[scenario_name][item_key]


def calc_conversion_model(
    annual_gen: float,
    cp_unit: float,
    mep_unit: float,
    map_unit: float,
    mwp_unit: float,
    imb_unit: float,
    mep_mult: float,
    imb_mult: float,
) -> dict:
    """
    영업용 환산단가 모델.
    각 정산항목을 원/kWh 환산 기대효과로 보고 연간 발전량에 곱한다.
    실제 정산 산식이 아니라, 고객 설명과 민감도 분석용 모델이다.
    """
    adj_mep = mep_unit * mep_mult
    adj_imb = imb_unit * imb_mult

    items_unit = {
        "CP 환산단가": cp_unit,
        "MEP 추가효과 환산단가": adj_mep,
        "MAP 기대효과 환산단가": map_unit,
        "MWP 기대효과 환산단가": mwp_unit,
        "IMB 예상 페널티 환산단가": adj_imb,
    }

    items_amount = {k: annual_gen * v for k, v in items_unit.items()}
    gross_extra = sum(items_amount.values())

    return {
        "items_unit": items_unit,
        "items_amount": items_amount,
        "gross_extra": gross_extra,
        "gross_extra_unit": safe_div(gross_extra, annual_gen),
    }


def calc_formula_model(
    annual_gen: float,
    fixed_price: float,
    dasmp: float,
    rtsmp: float,
    daos_ratio: float,
    rtos_ratio: float,
    mgo_ratio: float,
    mpe_ratio: float,
    cp_unit: float,
    ra_ratio: float,
    elcc_ratio: float,
    map_bid_spread: float,
    mwp_cost_spread: float,
    tolerance: float,
    impf: float,
    mep_efficiency_mult: float,
    imb_defense_mult: float,
) -> dict:
    """
    제도 산식 근사 모델.
    15분 단위 정산자료가 없다는 전제에서 연간 발전량을 기준량으로 환산하여 근사한다.

    MEP = DASMP * DAOS + RTSMP * (MGO - DAOS)
    MAP = max((RTSMP + 기대스프레드) * (DAOS - max(MGO, RTOS) - MPE), 0)
    MWP = max(변동비보전스프레드 * (DAOS - MGO), 0)
    CP  = CP환산단가 * 인정기준량, 인정기준량 = min(RA, MGO, RTOS, ELCC)
    IMB = -RTSMP * max((MGO - RTOS) - RTOS * 허용오차율, 0) * IMPF

    fixed_price 기반 기존 수익과 비교하기 위해 MEP는 전체 정산액이 아니라
    기존 고정가격 수익 대비 증분으로 환산한다.
    """
    daos = annual_gen * daos_ratio
    rtos = annual_gen * rtos_ratio
    mgo = annual_gen * mgo_ratio
    mpe = annual_gen * mpe_ratio
    ra = annual_gen * ra_ratio
    elcc = annual_gen * elcc_ratio

    # 기존 고정가격 기준 매출과 비교한 MEP 증분
    market_energy_payment = dasmp * daos + rtsmp * (mgo - daos)
    base_energy_revenue = fixed_price * mgo
    mep_increment = (market_energy_payment - base_energy_revenue) * mep_efficiency_mult

    # MAP/MWP는 조건부 정산금 성격. 발생 조건을 연간 근사 입력값으로 계산.
    curtailed_quantity_for_map = max(daos - max(mgo, rtos) - mpe, 0)
    map_payment = max((rtsmp + map_bid_spread) * curtailed_quantity_for_map, 0)

    mwp_quantity = max(daos - mgo, 0)
    mwp_payment = max(mwp_cost_spread * mwp_quantity, 0)

    recognized_quantity_for_cp = min(ra, mgo, rtos, elcc)
    cp_payment = cp_unit * recognized_quantity_for_cp

    excess_error = max((mgo - rtos) - (rtos * tolerance), 0)
    imb_penalty = -rtsmp * excess_error * impf * imb_defense_mult

    items_amount = {
        "CP 근사 정산효과": cp_payment,
        "MEP 기존대비 증분": mep_increment,
        "MAP 조건부 기대효과": map_payment,
        "MWP 조건부 보전효과": mwp_payment,
        "IMB 예상 페널티": imb_penalty,
    }
    items_unit = {k: safe_div(v, annual_gen) for k, v in items_amount.items()}
    gross_extra = sum(items_amount.values())

    return {
        "items_unit": items_unit,
        "items_amount": items_amount,
        "gross_extra": gross_extra,
        "gross_extra_unit": safe_div(gross_extra, annual_gen),
        "formula_quantities": {
            "DAOS 하루전계획량(kWh)": daos,
            "RTOS 실시간계획량(kWh)": rtos,
            "MGO 계량값(kWh)": mgo,
            "MPE ESS충전량(kWh)": mpe,
            "RA 공급가능량 환산(kWh)": ra,
            "ELCC/RPCF 인정량 환산(kWh)": elcc,
            "MAP 감발인정량(kWh)": curtailed_quantity_for_map,
            "MWP 보전대상량(kWh)": mwp_quantity,
            "IMB 초과오차량(kWh)": excess_error,
        },
    }


def calc_cashflow(
    cap_mw: float,
    gen_time: float,
    degradation: float,
    fixed_price: float,
    project_years: int,
    initial_cost: float,
    fee_rate: float,
    annual_extra_unit_func,
    om_cost_year1: float,
    om_escalation: float,
) -> pd.DataFrame:
    """
    연도별 현금흐름.
    구축비는 VPP 추가수익에서 우선 상환하고, 상환완료 후에는 수수료를 차감한다.
    상환 중 기존 매출은 유지되는 구조로 표현한다.
    """
    rows = []
    remaining_cost = initial_cost
    cumulative_owner_extra = 0.0
    cumulative_owner_total = 0.0

    for year in range(1, project_years + 1):
        annual_gen_y = calc_annual_generation(cap_mw, gen_time, degradation, year)
        base_revenue = annual_gen_y * fixed_price
        result_y = annual_extra_unit_func(annual_gen_y)
        gross_extra = result_y["gross_extra"]

        repayment = 0.0
        fee = 0.0
        owner_extra = 0.0

        if gross_extra > 0:
            repayment = min(remaining_cost, gross_extra) if remaining_cost > 0 else 0.0
            remaining_cost -= repayment
            fee_base = max(gross_extra - repayment, 0.0)
            fee = fee_base * fee_rate
            owner_extra = gross_extra - repayment - fee
        else:
            # 추가수익이 음수라면 사업주 리스크로 표시한다.
            owner_extra = gross_extra

        om_cost = om_cost_year1 * ((1 + om_escalation) ** (year - 1))
        owner_total_before_om = base_revenue + owner_extra
        owner_total_after_om = owner_total_before_om - om_cost

        cumulative_owner_extra += owner_extra
        cumulative_owner_total += owner_total_after_om

        rows.append({
            "연차": year,
            "연간발전량(kWh)": annual_gen_y,
            "기존수익(원)": base_revenue,
            "VPP추가수익발생액(원)": gross_extra,
            "구축비상환액(원)": repayment,
            "수수료(원)": fee,
            "사업주추가수령액(원)": owner_extra,
            "O&M비용(원)": om_cost,
            "사업주총수령액_O&M차감전(원)": owner_total_before_om,
            "사업주총수령액_O&M차감후(원)": owner_total_after_om,
            "누적추가수령액(원)": cumulative_owner_extra,
            "누적총현금흐름_O&M차감후(원)": cumulative_owner_total,
            "잔여상환액(원)": remaining_cost,
            "VPP추가단가(원/kWh)": safe_div(gross_extra, annual_gen_y),
        })

    return pd.DataFrame(rows)


def calc_payback_months(initial_cost: float, monthly_gross_extra: float):
    if monthly_gross_extra <= 0:
        return None
    return initial_cost / monthly_gross_extra


# ---------------------------------------------------------
# Sidebar
# ---------------------------------------------------------
with st.sidebar:
    st.header("📍 1. 지역 및 제도 설정")
    selected_region = st.selectbox("지역 선택", list(REGION_CONFIG.keys()))
    conf = REGION_CONFIG[selected_region]
    calc_method = st.radio("계산 방식", CALC_METHODS, index=0)
    view_mode = st.radio("화면 모드", VIEW_MODES, index=0, horizontal=True)
    scenario = st.selectbox("수익 시나리오", list(SCENARIO_MULTIPLIERS.keys()), index=1)

    st.header("🏭 2. 발전소 제원")
    cap_mw = st.number_input("설비 용량 (MW)", min_value=0.01, value=1.0, step=0.1)
    gen_time = st.slider("일평균 발전시간", 2.0, 5.5, 3.6, 0.1)
    degradation_pct = st.number_input("연 효율 저감율 (%)", min_value=0.0, max_value=3.0, value=0.5, step=0.1)
    fixed_price = st.number_input("현재 고정가격/기준 매출단가 (원/kWh)", min_value=0.0, value=180.0, step=1.0)
    project_years = st.slider("분석 기간 (년)", 1, 30, DEFAULT_PROJECT_YEARS)

    st.header("📊 3. 입찰제도 수익효과 입력")
    st.caption("고객용 화면에서는 정산항목을 '환산단가/기대효과'로 표시합니다.")

    base_cp = apply_scenario(conf["cp"], "cp", scenario)
    base_mep = apply_scenario(conf["mep"], "mep", scenario)
    base_map = apply_scenario(conf["map"], "map", scenario)
    base_mwp = apply_scenario(conf["mwp"], "mwp", scenario)
    base_imb = apply_scenario(conf["imb"], "imb", scenario)

    in_cp = st.number_input("CP 환산단가 (원/kWh)", value=float(base_cp), step=0.1)
    in_mep = st.number_input("MEP 추가효과 환산단가 (원/kWh)", value=float(base_mep), step=0.1)
    in_map = st.number_input("MAP 기대효과 환산단가 (원/kWh)", value=float(base_map), step=0.1)
    in_mwp = st.number_input("MWP 기대효과 환산단가 (원/kWh)", value=float(base_mwp), step=0.1)
    in_imb = st.number_input("IMB 예상 페널티 환산단가 (원/kWh)", value=float(base_imb), step=0.1)

    st.header("⚡ 4. VPP 운영 역량 민감도")
    operation_option = st.radio(
        "운영 시나리오 선택",
        options=list(OPERATION_OPTIONS.keys()),
        index=2,
    )
    op_conf = OPERATION_OPTIONS[operation_option]
    st.caption(op_conf["label"])

    st.header("💰 5. 수수료 및 비용")
    fee_rate_pct = st.slider("상환 완료 후 수수료율 (%)", 0, 50, 20)
    initial_cost = st.number_input("초기 구축비: RTU + 신자취 등 (원)", min_value=0, value=INITIAL_COST_DEFAULT, step=100_000)
    om_cost_year1 = st.number_input("연 O&M/통신/관리비 (원)", min_value=0, value=0, step=100_000)
    om_escalation_pct = st.number_input("O&M 상승률 (%/년)", min_value=0.0, max_value=10.0, value=0.0, step=0.1)

    st.info("💡 기본 가정: RTU 150만원 + 신자취 150만원 = 총 300만원. 해당 비용은 VPP 추가수익으로 우선 상환됩니다.")

    if calc_method == "제도 산식 근사 모델":
        st.header("🔬 6. 제도 산식 근사 입력")
        st.caption("15분 정산자료가 없는 경우 연간 발전량 대비 비율로 근사합니다.")
        dasmp = st.number_input("DASMP 하루전시장 평균가격 (원/kWh)", value=float(conf["dasmp"]), step=1.0)
        rtsmp = st.number_input("RTSMP 실시간시장 평균가격 (원/kWh)", value=float(conf["rtsmp"]), step=1.0)
        daos_ratio = st.slider("DAOS / 예상발전량", 0.0, 1.5, 0.95, 0.01)
        rtos_ratio = st.slider("RTOS / 예상발전량", 0.0, 1.5, 0.93, 0.01)
        mgo_ratio = st.slider("MGO / 예상발전량", 0.0, 1.5, 1.00, 0.01)
        mpe_ratio = st.slider("MPE(ESS충전량) / 예상발전량", 0.0, 0.5, 0.00, 0.01)
        ra_ratio = st.slider("RA 공급가능량 / 예상발전량", 0.0, 1.5, 0.95, 0.01)
        elcc_ratio = st.slider("ELCC/RPCF 인정량 / 예상발전량", 0.0, 1.5, 0.75, 0.01)
        map_bid_spread = st.number_input("MAP 기대 스프레드 (원/kWh)", value=0.0, step=0.1)
        mwp_cost_spread = st.number_input("MWP 보전 스프레드 (원/kWh)", value=max(in_mwp, 0.0), step=0.1)
        tolerance_pct = st.number_input("IMB 허용오차율 (%)", min_value=0.0, max_value=30.0, value=8.0, step=0.5)
        impf = st.number_input("IMB 페널티계수(IMPF)", min_value=0.0, value=1.0, step=0.1)
    else:
        dasmp = conf["dasmp"]
        rtsmp = conf["rtsmp"]
        daos_ratio = 0.95
        rtos_ratio = 0.93
        mgo_ratio = 1.00
        mpe_ratio = 0.00
        ra_ratio = 0.95
        elcc_ratio = 0.75
        map_bid_spread = 0.0
        mwp_cost_spread = max(in_mwp, 0.0)
        tolerance_pct = 8.0
        impf = 1.0

# ---------------------------------------------------------
# 핵심 계산
# ---------------------------------------------------------
deg = degradation_pct / 100
fee_rate = fee_rate_pct / 100
om_escalation = om_escalation_pct / 100

annual_gen_year1 = calc_annual_generation(cap_mw, gen_time, deg, 1)
base_revenue_year1 = annual_gen_year1 * fixed_price


def calc_extra_for_generation(annual_gen_value: float) -> dict:
    if calc_method == "영업용 환산단가 모델":
        return calc_conversion_model(
            annual_gen=annual_gen_value,
            cp_unit=in_cp,
            mep_unit=in_mep,
            map_unit=in_map,
            mwp_unit=in_mwp,
            imb_unit=in_imb,
            mep_mult=op_conf["mep_mult"],
            imb_mult=op_conf["imb_mult"],
        )
    return calc_formula_model(
        annual_gen=annual_gen_value,
        fixed_price=fixed_price,
        dasmp=dasmp,
        rtsmp=rtsmp,
        daos_ratio=daos_ratio,
        rtos_ratio=rtos_ratio,
        mgo_ratio=mgo_ratio,
        mpe_ratio=mpe_ratio,
        cp_unit=in_cp,
        ra_ratio=ra_ratio,
        elcc_ratio=elcc_ratio,
        map_bid_spread=map_bid_spread,
        mwp_cost_spread=mwp_cost_spread,
        tolerance=tolerance_pct / 100,
        impf=impf,
        mep_efficiency_mult=op_conf["mep_mult"],
        imb_defense_mult=op_conf["imb_mult"],
    )


extra_year1 = calc_extra_for_generation(annual_gen_year1)
annual_gross_extra_year1 = extra_year1["gross_extra"]
gross_extra_unit_year1 = extra_year1["gross_extra_unit"]
monthly_gross_extra_year1 = annual_gross_extra_year1 / 12
payback_months = calc_payback_months(initial_cost, monthly_gross_extra_year1)

after_fee_extra_year1 = max(annual_gross_extra_year1, 0) * (1 - fee_rate) if initial_cost == 0 else max(annual_gross_extra_year1 - min(initial_cost, annual_gross_extra_year1), 0) * (1 - fee_rate)
# 상환 완료 후 정상 연간 추가수익은 구축비 상환 없이 수수료만 차감한 값이다.
after_payback_extra_year1 = annual_gross_extra_year1 * (1 - fee_rate)
after_payback_total_revenue_year1 = base_revenue_year1 + after_payback_extra_year1

df_cashflow = calc_cashflow(
    cap_mw=cap_mw,
    gen_time=gen_time,
    degradation=deg,
    fixed_price=fixed_price,
    project_years=project_years,
    initial_cost=initial_cost,
    fee_rate=fee_rate,
    annual_extra_unit_func=calc_extra_for_generation,
    om_cost_year1=om_cost_year1,
    om_escalation=om_escalation,
)

# ---------------------------------------------------------
# PDF 생성
# ---------------------------------------------------------
def generate_report_pdf() -> bytes | None:
    if not os.path.exists(FONT_PATH):
        return None

    pdf = FPDF()
    pdf.add_font("NanumGothic", "", FONT_PATH)
    pdf.set_auto_page_break(auto=True, margin=14)
    pdf.add_page()

    # Header
    pdf.set_fill_color(0, 32, 96)
    pdf.rect(0, 0, 210, 42, "F")
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("NanumGothic", size=19)
    pdf.ln(10)
    pdf.cell(190, 10, "V-GEN VPP 수익효과 시뮬레이션 리포트", ln=True, align="C")
    pdf.set_font("NanumGothic", size=9)
    pdf.cell(190, 8, f"생성일: {datetime.now().strftime('%Y-%m-%d %H:%M')} / 계산방식: {calc_method}", ln=True, align="C")

    pdf.set_text_color(0, 0, 0)
    pdf.ln(18)

    # Summary
    pdf.set_font("NanumGothic", size=14)
    pdf.cell(190, 9, "1. 핵심 결과", "B", ln=True)
    pdf.ln(4)
    pdf.set_font("NanumGothic", size=10)

    summary_rows = [
        ("지역", selected_region),
        ("설비용량", f"{cap_mw:,.2f} MW"),
        ("연간 발전량(1년차)", f"{annual_gen_year1:,.0f} kWh"),
        ("기존 연간 수익", fmt_manwon(base_revenue_year1)),
        ("VPP 추가수익 발생액", fmt_manwon(annual_gross_extra_year1)),
        ("VPP 추가효과 환산단가", fmt_won_per_kwh(gross_extra_unit_year1)),
        ("상환 완료 후 연간 추가수익", fmt_manwon(after_payback_extra_year1)),
        ("상환 완료 후 연간 총수익", fmt_manwon(after_payback_total_revenue_year1)),
        ("예상 상환기간", "상환 불가" if payback_months is None else f"약 {payback_months:.1f}개월"),
    ]

    pdf.set_fill_color(240, 245, 255)
    for i, (k, v) in enumerate(summary_rows):
        fill = i % 2 == 0
        pdf.cell(70, 8, k, 1, 0, "C", fill)
        pdf.cell(120, 8, v, 1, 1, "R", fill)

    # Items
    pdf.ln(6)
    pdf.set_font("NanumGothic", size=14)
    pdf.cell(190, 9, "2. 정산항목별 수익효과", "B", ln=True)
    pdf.ln(4)
    pdf.set_font("NanumGothic", size=9)
    pdf.set_fill_color(240, 245, 255)
    pdf.cell(75, 8, "항목", 1, 0, "C", True)
    pdf.cell(55, 8, "환산단가", 1, 0, "C", True)
    pdf.cell(60, 8, "연간 효과", 1, 1, "C", True)

    for item, amount in extra_year1["items_amount"].items():
        unit = extra_year1["items_unit"].get(item, 0)
        pdf.cell(75, 8, item, 1, 0, "C")
        pdf.cell(55, 8, fmt_won_per_kwh(unit), 1, 0, "R")
        pdf.cell(60, 8, fmt_manwon(amount), 1, 1, "R")

    # Assumptions
    pdf.ln(6)
    pdf.set_font("NanumGothic", size=14)
    pdf.cell(190, 9, "3. 주요 전제조건", "B", ln=True)
    pdf.ln(4)
    pdf.set_font("NanumGothic", size=9)

    assumptions = [
        f"기준 매출단가: {fixed_price:,.1f} 원/kWh",
        f"일평균 발전시간: {gen_time:.1f} h, 연 효율 저감율: {degradation_pct:.2f}%",
        f"운영 시나리오: {operation_option} / 수익 시나리오: {scenario}",
        f"상환 완료 후 수수료율: {fee_rate_pct}%",
        f"초기 구축비: {initial_cost:,.0f} 원",
        f"O&M/통신/관리비: 1년차 {om_cost_year1:,.0f} 원, 상승률 {om_escalation_pct:.2f}%/년",
    ]

    if calc_method == "제도 산식 근사 모델":
        assumptions.extend([
            f"DASMP: {dasmp:,.1f} 원/kWh, RTSMP: {rtsmp:,.1f} 원/kWh",
            f"DAOS: {daos_ratio:.2f}, RTOS: {rtos_ratio:.2f}, MGO: {mgo_ratio:.2f}, MPE: {mpe_ratio:.2f}",
            f"RA: {ra_ratio:.2f}, ELCC/RPCF: {elcc_ratio:.2f}, IMB 허용오차율: {tolerance_pct:.1f}%, IMPF: {impf:.2f}",
        ])

    for text in assumptions:
        pdf.multi_cell(190, 6, f"- {text}")

    # Notice
    pdf.ln(4)
    pdf.set_font("NanumGothic", size=8)
    pdf.set_text_color(80, 80, 80)
    notice = (
        "본 결과는 입력값과 시장가격, 출력제어, 계통운영, 예측오차, 급전지시, 제도 변경에 따라 달라질 수 있는 추정값입니다. "
        "실제 정산금은 전력거래소 정산 기준, 계량값, 입찰·낙찰 결과, 급전지시 이행 여부, 임밸런스 페널티 적용 여부에 따라 확정됩니다. "
        "육지 입찰제도 도입 시 예측정산금 제도는 거래소 발표 방향에 따라 일몰되는 것으로 안내합니다."
    )
    pdf.multi_cell(190, 5, notice)

    return pdf_output_to_bytes(pdf)


# ---------------------------------------------------------
# Main UI
# ---------------------------------------------------------
st.title("📑 V-GEN VPP 수익효과 시뮬레이터 v7.0")
st.caption("입찰제도 정산항목별 기대효과를 원/kWh 기준으로 환산하고, 제도 산식 근사·상환·수수료·20년 현금흐름을 함께 검토합니다.")

if calc_method == "영업용 환산단가 모델":
    st.info("현재 모드는 CP/MEP/MAP/MWP/IMB를 원/kWh 환산 기대효과로 계산하는 영업용 민감도 모델입니다. 실제 정산 산식 계산이 필요한 경우 '제도 산식 근사 모델'을 선택하세요.")
else:
    st.info("현재 모드는 DAOS/RTOS/MGO, DASMP/RTSMP, CP 인정량, IMB 허용오차를 반영한 제도 산식 근사 모델입니다. 실제 15분 정산 데이터가 있으면 입력 정확도가 크게 향상됩니다.")

if annual_gross_extra_year1 <= 0:
    st.error("현재 입력값 기준 VPP 추가수익이 0 이하입니다. 상환이 불가능하거나 사업주 수익이 감소할 수 있습니다.")

# 핵심 KPI
m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("기존 연간 수익", fmt_manwon(base_revenue_year1))
m2.metric("VPP 추가수익 발생액", fmt_manwon(annual_gross_extra_year1), fmt_won_per_kwh(gross_extra_unit_year1))
m3.metric("상환 중 사업주 수령액", fmt_manwon(base_revenue_year1), "기존수익 유지 / 추가수익은 구축비 상환")
m4.metric("상환 후 연간 총수익", fmt_manwon(after_payback_total_revenue_year1), f"+{fmt_manwon(after_payback_extra_year1)}")
if payback_months is None:
    m5.metric("예상 상환기간", "상환 불가", "추가수익 부족")
else:
    m5.metric("예상 상환기간", f"약 {payback_months:.1f}개월", f"초기 구축비 {initial_cost/10_000:,.0f}만원")

st.divider()

# 차트 영역
c1, c2 = st.columns([1.35, 1])

with c1:
    st.subheader("📊 정산항목별 수익효과 구성")
    item_names = list(extra_year1["items_amount"].keys())
    item_values_manwon = [won_to_manwon(v) for v in extra_year1["items_amount"].values()]

    fig_bar = go.Figure()
    fig_bar.add_trace(go.Bar(
        x=item_names,
        y=item_values_manwon,
        text=[f"{v:,.0f}만원" for v in item_values_manwon],
        textposition="outside",
        name="연간 수익효과",
    ))
    fig_bar.update_layout(
        height=420,
        yaxis_title="만원/년",
        xaxis_title="정산항목",
        margin=dict(l=20, r=20, t=30, b=80),
    )
    st.plotly_chart(fig_bar, use_container_width=True)

with c2:
    st.subheader("📋 실시간 분석 세부 정보")
    with st.expander("⚡ 운영 시나리오", expanded=True):
        st.write(f"**현재 선택:** {operation_option}")
        st.write(f"- MEP 개선계수: **{op_conf['mep_mult']}배**")
        st.write(f"- IMB 저감계수: **{op_conf['imb_mult']}배**")
        st.caption("계수는 민감도 입력값입니다. 실제 성과는 운영실적, 예측정확도, 급전지시 이행률, 시장가격에 따라 달라집니다.")

    with st.expander("💰 상환 구조", expanded=True):
        if payback_months is None:
            st.error("VPP 추가수익이 부족하여 선수익 상환이 불가능합니다.")
        else:
            st.success(f"예상 상환기간: 약 {payback_months:.1f}개월")
        st.write(f"- 월 평균 VPP 추가수익 발생액: {won_to_manwon(monthly_gross_extra_year1):,.1f} 만원")
        st.write("- 상환 중: 기존 수익은 사업주 유지, VPP 추가수익은 구축비 상환에 우선 사용")
        st.write("- 상환 후: VPP 추가수익에서 약정 수수료 차감 후 사업주 수령")

    if calc_method == "제도 산식 근사 모델" and view_mode == "내부용":
        with st.expander("🔬 제도 산식 기준량", expanded=False):
            qdf = pd.DataFrame([
                {"항목": k, "값": f"{v:,.0f}"} for k, v in extra_year1.get("formula_quantities", {}).items()
            ])
            st.dataframe(qdf, use_container_width=True, hide_index=True)

st.divider()

# Waterfall
st.subheader("🌉 기존 단가 대비 VPP 참여 후 단가 변화")
waterfall_x = ["기존단가"] + list(extra_year1["items_unit"].keys()) + ["수수료", "상환 후 최종단가"]
fee_unit = -gross_extra_unit_year1 * fee_rate
waterfall_y = [fixed_price] + list(extra_year1["items_unit"].values()) + [fee_unit, 0]
waterfall_measure = ["relative"] * (len(waterfall_x) - 1) + ["total"]
final_unit_after_fee = fixed_price + gross_extra_unit_year1 * (1 - fee_rate)
waterfall_text = [
    f"{fixed_price:.1f}",
    *[f"{v:+.2f}" for v in extra_year1["items_unit"].values()],
    f"{fee_unit:.2f}",
    f"{final_unit_after_fee:.2f}",
]

fig_wf = go.Figure(go.Waterfall(
    x=waterfall_x,
    y=waterfall_y,
    measure=waterfall_measure,
    text=waterfall_text,
    textposition="outside",
))
fig_wf.update_layout(height=430, yaxis_title="원/kWh", margin=dict(l=20, r=20, t=30, b=80))
st.plotly_chart(fig_wf, use_container_width=True)

st.divider()

# 20년 현금흐름
st.subheader("📈 연차별 현금흐름 및 상환 시뮬레이션")
show_cols = [
    "연차",
    "연간발전량(kWh)",
    "기존수익(원)",
    "VPP추가수익발생액(원)",
    "구축비상환액(원)",
    "수수료(원)",
    "사업주추가수령액(원)",
    "O&M비용(원)",
    "사업주총수령액_O&M차감후(원)",
    "누적추가수령액(원)",
    "잔여상환액(원)",
]

df_display = df_cashflow[show_cols].copy()
for col in df_display.columns:
    if col.endswith("(원)"):
        df_display[col.replace("(원)", "(만원)")] = df_display[col].apply(won_to_manwon)
        df_display.drop(columns=[col], inplace=True)

df_display["연간발전량(kWh)"] = df_display["연간발전량(kWh)"].round(0)
for col in df_display.columns:
    if col.endswith("(만원)"):
        df_display[col] = df_display[col].round(0)

st.dataframe(df_display, use_container_width=True, hide_index=True)

# 누적 그래프
fig_line = go.Figure()
fig_line.add_trace(go.Scatter(
    x=df_cashflow["연차"],
    y=df_cashflow["누적추가수령액(원)"].apply(won_to_manwon),
    mode="lines+markers",
    name="누적 추가수령액",
))
fig_line.add_trace(go.Scatter(
    x=df_cashflow["연차"],
    y=df_cashflow["잔여상환액(원)"].apply(won_to_manwon),
    mode="lines+markers",
    name="잔여 상환액",
))
fig_line.update_layout(height=390, yaxis_title="만원", xaxis_title="연차", margin=dict(l=20, r=20, t=30, b=40))
st.plotly_chart(fig_line, use_container_width=True)

st.divider()

# 고객 안내 문구
st.subheader("🚀 전력시장 패러다임 변화 안내")
st.warning("⚠️ 육지 전역 재생에너지 입찰시장 확대 시행에 따라 기존 예측정산금 제도는 공식 일몰될 예정입니다. 향후 재생에너지 수익은 입찰, 실시간 대응, 임밸런스 관리, 출력제어 대응 역량에 더 크게 좌우됩니다.")

notice_box = """
**유의사항**  
본 계산 결과는 입력값과 시장가격, 출력제어, 계통운영, 예측오차, 급전지시, 제도 변경에 따라 달라질 수 있는 추정값입니다.  
실제 정산금은 전력거래소 정산 기준, 계량값, 입찰·낙찰 결과, 급전지시 이행 여부, 임밸런스 페널티 적용 여부에 따라 확정됩니다.  
고객 제안서에는 본 결과를 확정 수익이 아닌 **입력 가정 기반 예상 수익효과**로 표기하는 것을 권장합니다.
"""
st.info(notice_box)

# 요약 테이블
st.subheader("📌 요약 비교")
summary_df = pd.DataFrame({
    "구분": [
        "연간 발전량(1년차)",
        "기준 매출단가",
        "VPP 추가효과 환산단가",
        "상환 완료 후 최종단가",
        "기존 연간 수익",
        "VPP 추가수익 발생액",
        "상환 완료 후 연간 추가수익",
        "상환 완료 후 연간 총수익",
        "초기 구축비",
        "예상 상환기간",
    ],
    "값": [
        f"{annual_gen_year1:,.0f} kWh",
        fmt_won_per_kwh(fixed_price),
        fmt_won_per_kwh(gross_extra_unit_year1),
        fmt_won_per_kwh(final_unit_after_fee),
        fmt_manwon(base_revenue_year1),
        fmt_manwon(annual_gross_extra_year1),
        fmt_manwon(after_payback_extra_year1),
        fmt_manwon(after_payback_total_revenue_year1),
        f"{initial_cost:,.0f} 원",
        "상환 불가" if payback_months is None else f"약 {payback_months:.1f}개월",
    ],
})
st.table(summary_df)

# PDF 다운로드
st.divider()
st.subheader("📄 분석 결과 보고서 추출")
pdf_bytes = generate_report_pdf()
if pdf_bytes is None:
    st.error("PDF 생성을 위해 app.py와 같은 폴더에 NanumGothic.ttf 파일을 배치해 주세요.")
else:
    st.download_button(
        label="📥 VPP 수익효과 시뮬레이션 리포트 다운로드",
        data=pdf_bytes,
        file_name="VGEN_VPP_Profit_Simulation_Report.pdf",
        mime="application/pdf",
        use_container_width=True,
    )

# 내부용 디버그/검증 정보
if view_mode == "내부용":
    st.divider()
    st.subheader("🧪 내부 검증 정보")
    with st.expander("정산항목별 원/kWh 및 연간 금액", expanded=True):
        detail_df = pd.DataFrame({
            "항목": list(extra_year1["items_unit"].keys()),
            "환산단가(원/kWh)": list(extra_year1["items_unit"].values()),
            "연간효과(만원)": [won_to_manwon(v) for v in extra_year1["items_amount"].values()],
        })
        st.dataframe(detail_df, use_container_width=True, hide_index=True)

    with st.expander("모델 해석", expanded=False):
        st.markdown(
            """
- **영업용 환산단가 모델**: CP/MEP/MAP/MWP/IMB를 과거 실적 또는 내부 가정 기반의 원/kWh 환산단가로 처리합니다. 고객 설명과 민감도 분석에 적합합니다.
- **제도 산식 근사 모델**: DAOS, RTOS, MGO, DASMP, RTSMP, CP 인정량, IMB 허용오차를 연간 기준으로 근사합니다. 15분 단위 데이터가 없을 때 산식 구조를 반영하기 위한 중간 모델입니다.
- 실제 정산 검증을 하려면 15분 단위 DAOS/RTOS/MGO/MPE/DASMP/RTSMP와 자원별 CP/RPCF/ELCC 데이터를 넣는 별도 배치 계산기로 확장하는 것이 바람직합니다.
            """
        )
