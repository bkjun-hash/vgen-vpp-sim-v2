import os
from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from fpdf import FPDF

# =========================================================
# V-GEN VPP 수익 비교 계산기 v9.0
# ---------------------------------------------------------
# 목적
# - 기존 수익과 VPP 참여 후 수익을 한눈에 비교
# - 고정가격을 SMP와 REC로 분리
# - MEP는 기존 총단가가 아니라 기존 SMP 상당 단가와만 비교
# - REC는 사업주가 별도로 확보/판매하는 유지 수익으로 반영
# - 기본 구축비는 0원. 필요할 때만 사용자가 입력
# - CP/MEP/MAP/MWP/IMB 제도 용어 유지, 괄호에 쉬운 설명 병기
# =========================================================

st.set_page_config(
    page_title="V-GEN VPP 수익 비교 계산기 v9.0",
    layout="wide",
    initial_sidebar_state="expanded",
)

FONT_FILENAME = "NanumGothic.ttf"
FONT_PATH = os.path.join(os.getcwd(), FONT_FILENAME)
DEFAULT_PROJECT_YEARS = 20

# ---------------------------------------------------------
# 기본값
# ---------------------------------------------------------
REGION_CONFIG = {
    "호남/육지 입찰제 확대 모델": {
        "cp": 11.0,
        "mep": 1.2,
        "map": 0.8,
        "mwp": 0.5,
        "imb": -0.3,
        "dasmp": 120.0,
        "rtsmp": 122.0,
    },
    "제주도 입찰제 안착 모델": {
        "cp": 22.0,
        "mep": 1.2,
        "map": 2.5,
        "mwp": 1.0,
        "imb": -0.8,
        "dasmp": 115.0,
        "rtsmp": 120.0,
    },
}

SCENARIOS = {
    "보수": {"cp": 0.80, "mep": 0.70, "map": 0.60, "mwp": 0.60, "imb": 1.30},
    "기준": {"cp": 1.00, "mep": 1.00, "map": 1.00, "mwp": 1.00, "imb": 1.00},
    "상향": {"cp": 1.20, "mep": 1.30, "map": 1.25, "mwp": 1.20, "imb": 0.70},
}

OPERATION_LEVELS = {
    "일반 운영": {
        "mep_mult": 0.9,
        "imb_mult": 1.1,
        "desc": "일반적인 예측·입찰·제어 운영 수준",
    },
    "브이젠 표준 운영": {
        "mep_mult": 1.3,
        "imb_mult": 0.7,
        "desc": "V-GEN 표준 운영. 전력거래 효과 개선 및 예측오차 페널티 저감",
    },
    "브이젠 고도화 운영": {
        "mep_mult": 1.6,
        "imb_mult": 0.4,
        "desc": "V-GEN 고도화 운영. 예측·입찰·제어 최적화 효과를 크게 반영",
    },
}

CALC_METHODS = ["간편 수익비교", "정산규칙 근사"]
VIEW_MODES = ["고객용", "내부용"]

TERM_LABELS = {
    "cp": "CP (Capacity Payment, 용량보상)",
    "mep": "MEP (Market Energy Payment, 전력거래정산)",
    "map": "MAP (Make-whole Additional Payment, 출력제어 보상)",
    "mwp": "MWP (Make-whole Payment, 급전지시 비용보전)",
    "imb": "IMB (Imbalance Penalty, 예측오차 페널티)",
}

# ---------------------------------------------------------
# CSS
# ---------------------------------------------------------
st.markdown(
    """
<style>
.block-container {padding-top: 1.4rem; padding-bottom: 2.5rem;}
.vgen-hero {
    border-radius: 22px;
    padding: 28px 30px;
    background: linear-gradient(135deg, #0f2a50 0%, #174a7c 52%, #1f7a8c 100%);
    color: white;
    margin-bottom: 18px;
    box-shadow: 0 12px 30px rgba(15, 42, 80, 0.20);
}
.vgen-hero h1 {font-size: 34px; margin: 0 0 8px 0; font-weight: 800;}
.vgen-hero p {font-size: 16px; opacity: 0.94; margin: 0; line-height: 1.55;}
.vgen-card {
    background: white;
    border: 1px solid #e5e7eb;
    border-radius: 18px;
    padding: 20px;
    box-shadow: 0 8px 22px rgba(15, 23, 42, 0.06);
}
.vgen-card h3 {margin-top: 0; margin-bottom: 8px; font-size: 18px;}
.vgen-small {font-size: 13px; color: #64748b; line-height: 1.45;}
.good-box {
    border-left: 6px solid #16a34a;
    background: #f0fdf4;
    border-radius: 14px;
    padding: 14px 18px;
    margin: 12px 0;
}
.warn-box {
    border-left: 6px solid #f59e0b;
    background: #fffbeb;
    border-radius: 14px;
    padding: 14px 18px;
    margin: 12px 0;
}
.big-number {font-size: 30px; font-weight: 900; color: #0f2a50; margin: 4px 0;}
.big-plus {font-size: 34px; font-weight: 900; color: #16a34a; margin: 4px 0;}
.compare-label {font-size: 13px; color: #64748b; font-weight: 700;}
hr {margin-top: 1.3rem; margin-bottom: 1.3rem;}
</style>
""",
    unsafe_allow_html=True,
)

# ---------------------------------------------------------
# 유틸 함수
# ---------------------------------------------------------
def won_to_manwon(value: float) -> float:
    return value / 10_000


def fmt_manwon(value: float, digits: int = 0) -> str:
    return f"{won_to_manwon(value):,.{digits}f} 만원"


def fmt_won(value: float, digits: int = 0) -> str:
    return f"{value:,.{digits}f} 원"


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
    # 플러스 효과는 확대, 마이너스 효과는 손실 축소로 처리
    if raw_value >= 0:
        return raw_value * multiplier
    return raw_value / max(multiplier, 0.1)

# ---------------------------------------------------------
# 계산 함수
# ---------------------------------------------------------
def calc_simple_vpp_effect(
    gen_kwh: float,
    cp_unit: float,
    mep_unit: float,
    map_unit: float,
    mwp_unit: float,
    imb_unit: float,
    mep_mult: float,
    imb_mult: float,
) -> dict:
    units = {
        TERM_LABELS["cp"]: cp_unit,
        TERM_LABELS["mep"]: mep_unit * mep_mult,
        TERM_LABELS["map"]: map_unit,
        TERM_LABELS["mwp"]: mwp_unit,
        TERM_LABELS["imb"]: imb_unit * imb_mult,
    }
    amounts = {k: gen_kwh * v for k, v in units.items()}
    total = sum(amounts.values())
    return {
        "units": units,
        "amounts": amounts,
        "total": total,
        "unit_total": safe_div(total, gen_kwh),
        "detail": {},
    }


def calc_rule_vpp_effect(
    gen_kwh: float,
    base_smp_price: float,
    day_ahead_price: float,
    real_time_price: float,
    da_plan_ratio: float,
    rt_plan_ratio: float,
    actual_ratio: float,
    ess_charge_ratio: float,
    cp_unit: float,
    available_ratio: float,
    recognized_ratio: float,
    map_spread: float,
    mwp_spread: float,
    tolerance_ratio: float,
    penalty_factor: float,
    mep_mult: float,
    imb_mult: float,
) -> dict:
    daos = gen_kwh * da_plan_ratio
    rtos = gen_kwh * rt_plan_ratio
    mgo = gen_kwh * actual_ratio
    mpe = gen_kwh * ess_charge_ratio
    ra = gen_kwh * available_ratio
    recognized = gen_kwh * recognized_ratio

    market_energy_payment = day_ahead_price * daos + real_time_price * (mgo - daos)
    old_smp_revenue = base_smp_price * mgo
    raw_mep = market_energy_payment - old_smp_revenue
    mep = adjust_mep(raw_mep, mep_mult)

    cp_basis = min(ra, mgo, rtos, recognized)
    cp = cp_unit * cp_basis

    map_qty = max(daos - max(mgo, rtos) - mpe, 0)
    map_payment = max((real_time_price + map_spread) * map_qty, 0)

    mwp_qty = max(daos - mgo, 0)
    mwp = max(mwp_spread * mwp_qty, 0)

    excess_error = max((mgo - rtos) - (rtos * tolerance_ratio), 0)
    imb = -real_time_price * excess_error * penalty_factor * imb_mult

    amounts = {
        TERM_LABELS["cp"]: cp,
        TERM_LABELS["mep"]: mep,
        TERM_LABELS["map"]: map_payment,
        TERM_LABELS["mwp"]: mwp,
        TERM_LABELS["imb"]: imb,
    }
    units = {k: safe_div(v, gen_kwh) for k, v in amounts.items()}
    total = sum(amounts.values())

    return {
        "units": units,
        "amounts": amounts,
        "total": total,
        "unit_total": safe_div(total, gen_kwh),
        "detail": {
            "하루전 발전계획량 DAOS(kWh)": daos,
            "실시간 발전계획량 RTOS(kWh)": rtos,
            "실제 발전량 MGO(kWh)": mgo,
            "ESS 충전량 MPE(kWh)": mpe,
            "공급가능량 RA(kWh)": ra,
            "용량 인정량 ELCC/RPCF(kWh)": recognized,
            "CP 인정 기준물량(kWh)": cp_basis,
            "MAP 대상물량(kWh)": map_qty,
            "MWP 대상물량(kWh)": mwp_qty,
            "IMB 초과오차량(kWh)": excess_error,
            "입찰시장 전력정산액(원)": market_energy_payment,
            "기존 SMP 상당 수익(원)": old_smp_revenue,
            "MEP 원증분(원)": raw_mep,
        },
    }


def calc_yearly_cashflow(
    years: int,
    cap_mw: float,
    gen_time: float,
    degradation: float,
    total_price: float,
    base_smp_price: float,
    rec_price: float,
    initial_cost: float,
    fee_rate: float,
    om_year1: float,
    om_escalation: float,
    effect_func,
) -> pd.DataFrame:
    rows = []
    remaining = initial_cost
    cumulative_gain = 0.0
    cumulative_before = 0.0
    cumulative_after = 0.0

    for year in range(1, years + 1):
        gen = annual_generation(cap_mw, gen_time, degradation, year)
        old_smp = gen * base_smp_price
        rec = gen * rec_price
        old_total = gen * total_price

        result = effect_func(gen)
        gross_effect = result["total"]

        # 구축비는 기본 0원. 사용자가 입력한 경우에만 VPP 효과에서 우선 차감
        repayment = 0.0
        fee = 0.0
        owner_gain = gross_effect
        if initial_cost > 0 and gross_effect > 0 and remaining > 0:
            repayment = min(remaining, gross_effect)
            remaining -= repayment
            owner_gain = gross_effect - repayment

        if owner_gain > 0:
            fee = owner_gain * fee_rate
            owner_gain_after_fee = owner_gain - fee
        else:
            owner_gain_after_fee = owner_gain

        om = om_year1 * ((1 + om_escalation) ** (year - 1))
        after_total = old_total + owner_gain_after_fee - om
        cumulative_gain += owner_gain_after_fee
        cumulative_before += old_total
        cumulative_after += after_total

        rows.append({
            "연차": year,
            "발전량(kWh)": gen,
            "기존 SMP 수익(원)": old_smp,
            "REC 별도 수익(원)": rec,
            "기존 총수익(원)": old_total,
            "VPP 정산효과 발생액(원)": gross_effect,
            "구축비 차감액(원)": repayment,
            "수수료(원)": fee,
            "VPP 참여 추가수익(원)": owner_gain_after_fee,
            "O&M 비용(원)": om,
            "VPP 참여 후 총수익(원)": after_total,
            "기존 누적수익(원)": cumulative_before,
            "참여 후 누적수익(원)": cumulative_after,
            "누적 추가수익(원)": cumulative_gain,
            "잔여 구축비(원)": remaining,
            "VPP 정산효과 단가(원/kWh)": safe_div(gross_effect, gen),
        })
    return pd.DataFrame(rows)

# ---------------------------------------------------------
# 사이드바
# ---------------------------------------------------------
with st.sidebar:
    st.header("1. 기본 설정")
    region = st.selectbox("지역", list(REGION_CONFIG.keys()))
    conf = REGION_CONFIG[region]
    calc_method = st.radio("계산 방식", CALC_METHODS, index=0)
    view_mode = st.radio("화면", VIEW_MODES, index=0, horizontal=True)
    scenario = st.selectbox("수익 시나리오", list(SCENARIOS.keys()), index=1)

    st.header("2. 발전소 정보")
    cap_mw = st.number_input("설비 용량(MW)", min_value=0.01, value=1.0, step=0.1)
    gen_time = st.slider("하루 평균 발전시간", 2.0, 5.5, 3.6, 0.1)
    degradation_pct = st.number_input("연간 발전효율 감소율(%)", min_value=0.0, max_value=3.0, value=0.5, step=0.1)
    years = st.slider("분석 기간(년)", 1, 30, DEFAULT_PROJECT_YEARS)

    st.header("3. 기존 판매단가")
    fixed_total_price = st.number_input(
        "기존 총 판매단가(SMP+REC, 원/kWh)",
        min_value=0.0,
        value=180.0,
        step=1.0,
        help="현재 고객이 받는 전체 단가입니다. 고정가격 계약이면 SMP와 REC가 합쳐진 값으로 입력하세요.",
    )
    base_smp_price = st.number_input(
        "기존 SMP 상당 단가(원/kWh)",
        min_value=0.0,
        value=120.0,
        step=1.0,
        help="MEP 비교 기준입니다. REC까지 포함하면 안 됩니다.",
    )
    rec_price = max(fixed_total_price - base_smp_price, 0.0)
    if fixed_total_price < base_smp_price:
        st.warning("SMP 상당 단가가 총 판매단가보다 큽니다. REC 상당 단가는 0원/kWh로 계산합니다.")
    st.caption(f"REC 상당 단가 자동 계산: {rec_price:,.1f} 원/kWh")

    st.header("4. VPP 정산항목")
    cp_default = apply_scenario(conf["cp"], "cp", scenario)
    mep_default = apply_scenario(conf["mep"], "mep", scenario)
    map_default = apply_scenario(conf["map"], "map", scenario)
    mwp_default = apply_scenario(conf["mwp"], "mwp", scenario)
    imb_default = apply_scenario(conf["imb"], "imb", scenario)

    cp_unit = st.number_input("CP (Capacity Payment, 용량보상, 원/kWh)", value=float(cp_default), step=0.1)
    mep_unit = st.number_input("MEP (Market Energy Payment, 전력거래정산, 원/kWh)", value=float(mep_default), step=0.1)
    map_unit = st.number_input("MAP (Make-whole Additional Payment, 출력제어 보상, 원/kWh)", value=float(map_default), step=0.1)
    mwp_unit = st.number_input("MWP (Make-whole Payment, 급전지시 비용보전, 원/kWh)", value=float(mwp_default), step=0.1)
    imb_unit = st.number_input("IMB (Imbalance Penalty, 예측오차 페널티, 원/kWh)", value=float(imb_default), step=0.1)

    st.header("5. VPP 운영 수준")
    operation = st.radio("운영 수준", list(OPERATION_LEVELS.keys()), index=2)
    op = OPERATION_LEVELS[operation]
    st.caption(op["desc"])

    st.header("6. 선택 비용")
    fee_rate_pct = st.slider("VPP 운영 수수료율(%)", 0, 50, 20)
    initial_cost = st.number_input(
        "구축비 차감액(원, 선택 입력)",
        min_value=0,
        value=0,
        step=100_000,
        help="기본값은 0원입니다. 필요할 때만 RTU/신자취 등 차감할 금액을 입력하세요.",
    )
    om_year1 = st.number_input("연간 O&M/통신/관리비(원, 선택 입력)", min_value=0, value=0, step=100_000)
    om_escalation_pct = st.number_input("O&M 상승률(%/년)", min_value=0.0, max_value=10.0, value=0.0, step=0.1)

    if calc_method == "정산규칙 근사":
        st.header("7. 정산규칙 근사 입력")
        st.caption("기본값 그대로 사용 가능. 내부 검토 시 조정하세요.")
        dasmp = st.number_input("DASMP (Day-ahead SMP, 하루전 전력가격, 원/kWh)", value=float(conf["dasmp"]), step=1.0)
        rtsmp = st.number_input("RTSMP (Real-time SMP, 실시간 전력가격, 원/kWh)", value=float(conf["rtsmp"]), step=1.0)
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
# 계산 실행
# ---------------------------------------------------------
degradation = degradation_pct / 100
fee_rate = fee_rate_pct / 100
om_escalation = om_escalation_pct / 100

gen_y1 = annual_generation(cap_mw, gen_time, degradation, 1)
old_smp_y1 = gen_y1 * base_smp_price
rec_y1 = gen_y1 * rec_price
old_total_y1 = gen_y1 * fixed_total_price


def effect_func(gen_kwh: float) -> dict:
    if calc_method == "간편 수익비교":
        return calc_simple_vpp_effect(
            gen_kwh=gen_kwh,
            cp_unit=cp_unit,
            mep_unit=mep_unit,
            map_unit=map_unit,
            mwp_unit=mwp_unit,
            imb_unit=imb_unit,
            mep_mult=op["mep_mult"],
            imb_mult=op["imb_mult"],
        )
    return calc_rule_vpp_effect(
        gen_kwh=gen_kwh,
        base_smp_price=base_smp_price,
        day_ahead_price=dasmp,
        real_time_price=rtsmp,
        da_plan_ratio=da_ratio,
        rt_plan_ratio=rt_ratio,
        actual_ratio=actual_ratio,
        ess_charge_ratio=ess_ratio,
        cp_unit=cp_unit,
        available_ratio=available_ratio,
        recognized_ratio=recognized_ratio,
        map_spread=map_spread,
        mwp_spread=mwp_spread,
        tolerance_ratio=tolerance_pct / 100,
        penalty_factor=penalty_factor,
        mep_mult=op["mep_mult"],
        imb_mult=op["imb_mult"],
    )


effect_y1 = effect_func(gen_y1)
gross_vpp_y1 = effect_y1["total"]
gross_vpp_unit_y1 = effect_y1["unit_total"]

# 기본은 구축비 0. 필요 시 차감
repayment_y1 = min(initial_cost, gross_vpp_y1) if initial_cost > 0 and gross_vpp_y1 > 0 else 0.0
owner_gain_before_fee_y1 = gross_vpp_y1 - repayment_y1
fee_y1 = owner_gain_before_fee_y1 * fee_rate if owner_gain_before_fee_y1 > 0 else 0.0
owner_gain_y1 = owner_gain_before_fee_y1 - fee_y1
vpp_total_y1 = old_total_y1 + owner_gain_y1 - om_year1
improvement_rate_y1 = safe_div(owner_gain_y1, old_total_y1) * 100
final_unit_y1 = safe_div(vpp_total_y1, gen_y1)

cashflow_df = calc_yearly_cashflow(
    years=years,
    cap_mw=cap_mw,
    gen_time=gen_time,
    degradation=degradation,
    total_price=fixed_total_price,
    base_smp_price=base_smp_price,
    rec_price=rec_price,
    initial_cost=initial_cost,
    fee_rate=fee_rate,
    om_year1=om_year1,
    om_escalation=om_escalation,
    effect_func=effect_func,
)

sum_old = cashflow_df["기존 총수익(원)"].sum()
sum_after = cashflow_df["VPP 참여 후 총수익(원)"].sum()
sum_gain = cashflow_df["VPP 참여 추가수익(원)"].sum()
sum_improvement_rate = safe_div(sum_gain, sum_old) * 100

# ---------------------------------------------------------
# PDF
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
    pdf.cell(190, 9, "1. 핵심 비교", "B", ln=True)
    pdf.ln(4)
    pdf.set_font("NanumGothic", size=9)

    rows = [
        ("기존 연간 총수익", fmt_manwon(old_total_y1)),
        ("VPP 참여 후 연간 총수익", fmt_manwon(vpp_total_y1)),
        ("연간 추가수익", fmt_manwon(owner_gain_y1)),
        ("연간 개선율", f"{improvement_rate_y1:,.1f}%"),
        (f"{years}년 기존 누적수익", fmt_manwon(sum_old)),
        (f"{years}년 참여 후 누적수익", fmt_manwon(sum_after)),
        (f"{years}년 누적 추가수익", fmt_manwon(sum_gain)),
    ]
    pdf.set_fill_color(240, 245, 255)
    for i, (k, v) in enumerate(rows):
        fill = i % 2 == 0
        pdf.cell(78, 8, k, 1, 0, "C", fill)
        pdf.cell(112, 8, v, 1, 1, "R", fill)

    pdf.ln(6)
    pdf.set_font("NanumGothic", size=14)
    pdf.cell(190, 9, "2. 단가 전제", "B", ln=True)
    pdf.ln(4)
    pdf.set_font("NanumGothic", size=9)
    price_rows = [
        ("기존 총 판매단가(SMP+REC)", fmt_unit(fixed_total_price)),
        ("기존 SMP 상당 단가", fmt_unit(base_smp_price)),
        ("REC 상당 단가", fmt_unit(rec_price)),
        ("VPP 정산효과 단가", fmt_unit(gross_vpp_unit_y1)),
        ("참여 후 실질 단가", fmt_unit(final_unit_y1)),
    ]
    for i, (k, v) in enumerate(price_rows):
        fill = i % 2 == 0
        pdf.cell(78, 8, k, 1, 0, "C", fill)
        pdf.cell(112, 8, v, 1, 1, "R", fill)

    pdf.ln(6)
    pdf.set_font("NanumGothic", size=14)
    pdf.cell(190, 9, "3. VPP 정산항목", "B", ln=True)
    pdf.ln(4)
    pdf.set_font("NanumGothic", size=8)
    pdf.set_fill_color(240, 245, 255)
    pdf.cell(90, 8, "항목", 1, 0, "C", True)
    pdf.cell(45, 8, "단가", 1, 0, "C", True)
    pdf.cell(55, 8, "연간 효과", 1, 1, "C", True)
    for name, amount in effect_y1["amounts"].items():
        pdf.cell(90, 8, name, 1, 0, "C")
        pdf.cell(45, 8, fmt_unit(effect_y1["units"].get(name, 0)), 1, 0, "R")
        pdf.cell(55, 8, fmt_manwon(amount), 1, 1, "R")

    pdf.ln(5)
    pdf.set_font("NanumGothic", size=8)
    pdf.set_text_color(80, 80, 80)
    notice = (
        "본 계산은 입력값 기반의 예상 수익효과입니다. 실제 정산금은 전력거래소 정산 기준, 계량값, "
        "입찰·낙찰 결과, 급전지시 이행 여부, IMB 적용 여부에 따라 달라질 수 있습니다. "
        "MEP 비교 기준은 REC 포함 총단가가 아니라 기존 SMP 상당 단가입니다. REC 상당 수익은 사업주 별도 수익으로 유지합니다. "
        "육지 전역 재생에너지 입찰시장 확대 시행에 따라 기존 예측정산금 제도는 공식 일몰될 예정입니다."
    )
    pdf.multi_cell(190, 5, notice)

    return pdf_to_bytes(pdf)

# ---------------------------------------------------------
# 메인 화면
# ---------------------------------------------------------
st.markdown(
    """
<div class="vgen-hero">
  <h1>V-GEN VPP 수익 비교 계산기</h1>
  <p>기존 수익과 VPP 참여 후 수익을 직접 비교합니다. 고정가격은 SMP와 REC로 분리하고, MEP는 기존 SMP 상당 단가와만 비교합니다.</p>
</div>
""",
    unsafe_allow_html=True,
)

# 핵심 비교 카드
col_a, col_b, col_c = st.columns([1, 1, 1.05])
with col_a:
    st.markdown(
        f"""
<div class="vgen-card">
  <div class="compare-label">기존 연간 총수익</div>
  <div class="big-number">{fmt_manwon(old_total_y1)}</div>
  <div class="vgen-small">SMP 상당 수익 {fmt_manwon(old_smp_y1)} + REC 별도 수익 {fmt_manwon(rec_y1)}</div>
</div>
""",
        unsafe_allow_html=True,
    )
with col_b:
    st.markdown(
        f"""
<div class="vgen-card">
  <div class="compare-label">VPP 참여 후 연간 총수익</div>
  <div class="big-number">{fmt_manwon(vpp_total_y1)}</div>
  <div class="vgen-small">기존 총수익 + VPP 추가수익 - 선택비용</div>
</div>
""",
        unsafe_allow_html=True,
    )
with col_c:
    st.markdown(
        f"""
<div class="vgen-card">
  <div class="compare-label">연간 추가수익</div>
  <div class="big-plus">+{fmt_manwon(owner_gain_y1)}</div>
  <div class="vgen-small">기존 대비 개선율 {improvement_rate_y1:,.1f}% / VPP 효과 {fmt_unit(gross_vpp_unit_y1)}</div>
</div>
""",
        unsafe_allow_html=True,
    )

if gross_vpp_y1 > 0:
    st.markdown(
        f"""
<div class="good-box">
  <b>핵심 메시지:</b> 현재 입력값 기준 VPP 참여 시 1년차 기준 <b>{fmt_manwon(owner_gain_y1)}</b>의 추가수익이 예상됩니다. 
  REC는 기존처럼 사업주 별도 수익으로 유지하고, VPP는 CP/MEP/MAP/MWP/IMB 정산효과를 추가로 만드는 구조입니다.
</div>
""",
        unsafe_allow_html=True,
    )
else:
    st.markdown(
        """
<div class="warn-box">
  <b>주의:</b> 현재 입력값 기준 VPP 정산효과가 0 이하입니다. CP/MEP/MAP/MWP 입력값, IMB 페널티, 운영 수준을 다시 확인하세요.
</div>
""",
        unsafe_allow_html=True,
    )

# 누적 비교
st.subheader("1. 기존 vs VPP 참여 후 수익 비교")
compare_df = pd.DataFrame({
    "구분": ["1년차", f"{years}년 누적"],
    "기존 수익(만원)": [won_to_manwon(old_total_y1), won_to_manwon(sum_old)],
    "VPP 참여 후 수익(만원)": [won_to_manwon(vpp_total_y1), won_to_manwon(sum_after)],
    "추가수익(만원)": [won_to_manwon(owner_gain_y1), won_to_manwon(sum_gain)],
})

fig_compare = go.Figure()
fig_compare.add_trace(go.Bar(x=compare_df["구분"], y=compare_df["기존 수익(만원)"], name="기존 수익"))
fig_compare.add_trace(go.Bar(x=compare_df["구분"], y=compare_df["VPP 참여 후 수익(만원)"], name="VPP 참여 후 수익"))
fig_compare.update_layout(
    barmode="group",
    height=430,
    yaxis_title="만원",
    margin=dict(l=20, r=20, t=30, b=40),
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
)
st.plotly_chart(fig_compare, use_container_width=True)

# 단가 구조
st.subheader("2. 단가 구조: 기존 총단가에 VPP 정산효과가 더해지는 구조")
price_parts = pd.DataFrame({
    "항목": ["기존 SMP 상당", "REC 별도 수익", "VPP 정산효과", "수수료/선택비용 반영 후"],
    "단가(원/kWh)": [base_smp_price, rec_price, gross_vpp_unit_y1, final_unit_y1 - fixed_total_price],
})

fig_waterfall = go.Figure(
    go.Waterfall(
        x=["기존 SMP", "REC", "VPP 정산효과", "수수료/비용", "참여 후 실질단가"],
        y=[base_smp_price, rec_price, gross_vpp_unit_y1, final_unit_y1 - fixed_total_price - gross_vpp_unit_y1, 0],
        measure=["relative", "relative", "relative", "relative", "total"],
        text=[
            f"+{base_smp_price:.1f}",
            f"+{rec_price:.1f}",
            f"+{gross_vpp_unit_y1:.1f}",
            f"{final_unit_y1 - fixed_total_price - gross_vpp_unit_y1:.1f}",
            f"{final_unit_y1:.1f}",
        ],
        textposition="outside",
    )
)
fig_waterfall.update_layout(height=430, yaxis_title="원/kWh", margin=dict(l=20, r=20, t=30, b=60))
st.plotly_chart(fig_waterfall, use_container_width=True)

# 정산항목 구성
st.subheader("3. VPP 정산항목별 기여도")
item_df = pd.DataFrame({
    "항목": list(effect_y1["amounts"].keys()),
    "단가(원/kWh)": [effect_y1["units"][k] for k in effect_y1["amounts"].keys()],
    "연간 효과(만원)": [won_to_manwon(v) for v in effect_y1["amounts"].values()],
})

c1, c2 = st.columns([1.2, 1])
with c1:
    fig_items = go.Figure()
    fig_items.add_trace(
        go.Bar(
            x=item_df["항목"],
            y=item_df["연간 효과(만원)"],
            text=[f"{v:,.0f}만원" for v in item_df["연간 효과(만원)"]],
            textposition="outside",
            name="연간 효과",
        )
    )
    fig_items.update_layout(height=440, yaxis_title="만원/년", margin=dict(l=20, r=20, t=30, b=110))
    st.plotly_chart(fig_items, use_container_width=True)
with c2:
    st.dataframe(item_df.round(2), use_container_width=True, hide_index=True)
    st.markdown(
        f"""
<div class="vgen-card">
  <h3>수익 해석</h3>
  <div class="vgen-small">
    <b>CP/MAP/MWP</b>는 VPP 참여로 확보할 수 있는 보상·보전 성격입니다.<br><br>
    <b>MEP</b>는 기존 총단가가 아니라 기존 SMP 상당 단가와 비교합니다.<br><br>
    <b>IMB</b>는 예측오차 페널티이므로 마이너스 항목이며, VPP 운영 역량으로 줄이는 것이 핵심입니다.
  </div>
</div>
""",
        unsafe_allow_html=True,
    )

# 연차별 그래프
st.subheader("4. 연차별 누적수익 비교")
fig_line = go.Figure()
fig_line.add_trace(go.Scatter(
    x=cashflow_df["연차"],
    y=cashflow_df["기존 누적수익(원)"].apply(won_to_manwon),
    mode="lines+markers",
    name="기존 누적수익",
))
fig_line.add_trace(go.Scatter(
    x=cashflow_df["연차"],
    y=cashflow_df["참여 후 누적수익(원)"].apply(won_to_manwon),
    mode="lines+markers",
    name="VPP 참여 후 누적수익",
))
fig_line.add_trace(go.Scatter(
    x=cashflow_df["연차"],
    y=cashflow_df["누적 추가수익(원)"].apply(won_to_manwon),
    mode="lines+markers",
    name="누적 추가수익",
))
fig_line.update_layout(height=440, yaxis_title="만원", xaxis_title="연차", margin=dict(l=20, r=20, t=30, b=40))
st.plotly_chart(fig_line, use_container_width=True)

# 표
with st.expander("연차별 상세표 보기", expanded=False):
    show_df = cashflow_df.copy()
    for col in list(show_df.columns):
        if col.endswith("(원)"):
            show_df[col.replace("(원)", "(만원)")] = show_df[col].apply(won_to_manwon)
            show_df.drop(columns=[col], inplace=True)
    for col in show_df.columns:
        if col.endswith("(만원)") or col.endswith("(원/kWh)"):
            show_df[col] = show_df[col].round(2)
        if col == "발전량(kWh)":
            show_df[col] = show_df[col].round(0)

    if view_mode == "고객용":
        cols = [
            "연차",
            "발전량(kWh)",
            "기존 총수익(만원)",
            "VPP 참여 추가수익(만원)",
            "VPP 참여 후 총수익(만원)",
            "누적 추가수익(만원)",
        ]
        show_df = show_df[[c for c in cols if c in show_df.columns]]
    st.dataframe(show_df, use_container_width=True, hide_index=True)

# 안내
st.subheader("5. 안내 문구")
st.warning(
    "육지 전역 재생에너지 입찰시장 확대 시행에 따라 기존 예측정산금 제도는 공식 일몰될 예정입니다. "
    "향후 재생에너지 수익은 CP/MEP/MAP/MWP 확보와 IMB 관리 역량에 따라 달라질 수 있습니다."
)
st.info(
    "본 계산은 입력값 기반 예상 수익효과입니다. 실제 정산금은 전력거래소 정산 기준, 계량값, 입찰·낙찰 결과, "
    "급전지시 이행 여부, IMB 적용 여부에 따라 달라질 수 있습니다. MEP 비교 기준은 REC 포함 총단가가 아니라 기존 SMP 상당 단가입니다."
)

# PDF
st.subheader("PDF 보고서")
pdf_data = make_pdf()
if pdf_data is None:
    st.error("PDF 생성을 위해 app.py와 같은 폴더에 NanumGothic.ttf 파일을 넣어주세요.")
else:
    st.download_button(
        label="VPP 수익 비교 리포트 다운로드",
        data=pdf_data,
        file_name="VGEN_VPP_Profit_Comparison_Report.pdf",
        mime="application/pdf",
        use_container_width=True,
    )

# 내부용
if view_mode == "내부용":
    st.subheader("내부 검증 정보")
    st.write("계산 방식:", calc_method)
    st.write("운영 수준:", operation)
    st.write("수익 시나리오:", scenario)
    if effect_y1["detail"]:
        detail_df = pd.DataFrame({"항목": list(effect_y1["detail"].keys()), "값": list(effect_y1["detail"].values())})
        st.dataframe(detail_df, use_container_width=True, hide_index=True)

    with st.expander("용어 설명", expanded=False):
        st.markdown(
            """
- **CP (Capacity Payment, 용량보상)**: 전력시장에 공급 가능한 자원으로 인정받는 데 따른 보상 효과입니다.
- **MEP (Market Energy Payment, 전력거래정산)**: 입찰시장 전력정산액이 기존 SMP 상당 수익보다 얼마나 유리한지 보는 항목입니다. REC는 비교에서 제외합니다.
- **MAP (Make-whole Additional Payment, 출력제어 보상)**: 발전할 수 있었지만 계통/급전지시로 줄인 물량에 대한 보상 성격입니다.
- **MWP (Make-whole Payment, 급전지시 비용보전)**: 급전지시 때문에 발생할 수 있는 비용 또는 손실을 보전하는 성격입니다.
- **IMB (Imbalance Penalty, 예측오차 페널티)**: 발전계획과 실제 발전량 차이가 커질 때 발생할 수 있는 차감 항목입니다.
- **REC 상당 수익**: 사업주가 별도로 확보하거나 판매하는 수익으로 보며, MEP 비교 기준에 포함하지 않습니다.
            """
        )
