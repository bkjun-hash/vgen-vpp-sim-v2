import os
from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from fpdf import FPDF

# =========================================================
# V-GEN VPP 수익효과 계산기 v8.0
# ---------------------------------------------------------
# 핵심 수정사항
# 1) 기존 고정가격을 SMP 상당분과 REC 상당분으로 분리
# 2) 전력거래 추가효과(MEP)는 기존 총단가가 아니라 기존 SMP 상당분과만 비교
# 3) REC 상당 수익은 사업주가 별도 확보/판매하는 유지 수익으로 분리
# 4) 제도 용어(CP/MEP/MAP/MWP/IMB)를 유지하고, 괄호에 쉬운 설명 병기
# 5) 선수익 상환, 수수료, 20년 현금흐름, PDF 보고서 반영
# =========================================================

st.set_page_config(
    page_title="V-GEN VPP 수익효과 계산기 v8.0",
    layout="wide",
    initial_sidebar_state="expanded",
)

FONT_FILENAME = "NanumGothic.ttf"
FONT_PATH = os.path.join(os.getcwd(), FONT_FILENAME)

INITIAL_COST_DEFAULT = 3_000_000  # RTU 150만원 + 신자취 150만원
DEFAULT_PROJECT_YEARS = 20

# ---------------------------------------------------------
# 기본값
# 금액 단위는 내부 계산에서 원, 원/kWh 사용
# 화면 표시는 만원 중심
# ---------------------------------------------------------
REGION_CONFIG = {
    "호남/육지 입찰제 확대 모델": {
        "capacity_reward": 11.0,      # CP 환산
        "energy_trade_effect": 1.2,   # MEP 환산
        "curtail_reward": 0.8,        # MAP 환산
        "dispatch_reward": 0.5,       # MWP 환산
        "forecast_penalty": -0.3,     # IMB 환산
        "day_ahead_price": 120.0,
        "real_time_price": 122.0,
    },
    "제주도 입찰제 안착 모델": {
        "capacity_reward": 22.0,
        "energy_trade_effect": 1.2,
        "curtail_reward": 2.5,
        "dispatch_reward": 1.0,
        "forecast_penalty": -0.8,
        "day_ahead_price": 115.0,
        "real_time_price": 120.0,
    },
}

SCENARIOS = {
    "보수": {
        "capacity_reward": 0.75,
        "energy_trade_effect": 0.60,
        "curtail_reward": 0.50,
        "dispatch_reward": 0.50,
        "forecast_penalty": 1.50,
    },
    "기준": {
        "capacity_reward": 1.00,
        "energy_trade_effect": 1.00,
        "curtail_reward": 1.00,
        "dispatch_reward": 1.00,
        "forecast_penalty": 1.00,
    },
    "낙관": {
        "capacity_reward": 1.25,
        "energy_trade_effect": 1.30,
        "curtail_reward": 1.25,
        "dispatch_reward": 1.20,
        "forecast_penalty": 0.70,
    },
}

OPERATION_LEVELS = {
    "보수 운영": {
        "energy_mult": 0.4,
        "penalty_mult": 2.0,
        "desc": "예측·입찰·제어 역량이 낮은 경우",
    },
    "일반 운영": {
        "energy_mult": 0.8,
        "penalty_mult": 1.2,
        "desc": "일반적인 VPP 운영 수준",
    },
    "브이젠 고도화 운영": {
        "energy_mult": 1.6,
        "penalty_mult": 0.4,
        "desc": "V-GEN 예측·입찰·제어 최적화 적용",
    },
}

CALC_METHODS = [
    "쉬운 계산 모드",
    "정산규칙 근사 모드",
]

VIEW_MODES = ["고객용", "내부용"]

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


def safe_div(numerator: float, denominator: float, default: float = 0.0) -> float:
    if denominator is None or denominator == 0:
        return default
    return numerator / denominator


def apply_scenario(value: float, key: str, scenario: str) -> float:
    return value * SCENARIOS[scenario][key]


def pdf_to_bytes(pdf: FPDF) -> bytes:
    raw = pdf.output(dest="S")
    if isinstance(raw, bytes):
        return raw
    if isinstance(raw, bytearray):
        return bytes(raw)
    return raw.encode("latin-1")


def annual_generation(cap_mw: float, gen_time: float, degradation: float, year: int) -> float:
    year1 = cap_mw * 1_000 * gen_time * 365
    return year1 * ((1 - degradation) ** (year - 1))


def apply_energy_skill(raw_mep_increment: float, energy_mult: float) -> float:
    """
    전력거래 추가효과 보정.
    - 기존 SMP 대비 시장정산이 유리하면 운영 역량으로 추가효과를 키운다.
    - 불리하면 고도화 운영이 손실을 줄이는 방향으로 처리한다.
    """
    if raw_mep_increment >= 0:
        return raw_mep_increment * energy_mult
    return raw_mep_increment / max(energy_mult, 0.1)


# ---------------------------------------------------------
# 계산 함수
# ---------------------------------------------------------
def calc_easy_model(
    gen_kwh: float,
    capacity_reward_unit: float,
    energy_trade_unit: float,
    curtail_reward_unit: float,
    dispatch_reward_unit: float,
    forecast_penalty_unit: float,
    energy_mult: float,
    penalty_mult: float,
) -> dict:
    """
    쉬운 계산 모드.
    각 정산효과를 원/kWh 환산단가로 보고 발전량에 곱한다.
    고객 설명과 빠른 민감도 검토용이다.
    """
    adjusted_energy_trade = energy_trade_unit * energy_mult
    adjusted_penalty = forecast_penalty_unit * penalty_mult

    units = {
        "CP (Capacity Payment, 용량보상)": capacity_reward_unit,
        "MEP (Market Energy Payment, 전력거래정산)": adjusted_energy_trade,
        "MAP (Make-whole Additional Payment, 출력제어 보상)": curtail_reward_unit,
        "MWP (Make-whole Payment, 급전지시 비용보전)": dispatch_reward_unit,
        "IMB (Imbalance Penalty, 예측오차 페널티)": adjusted_penalty,
    }

    amounts = {name: gen_kwh * unit for name, unit in units.items()}
    total = sum(amounts.values())

    return {
        "units": units,
        "amounts": amounts,
        "total_extra": total,
        "total_extra_unit": safe_div(total, gen_kwh),
        "detail": {},
    }


def calc_rule_model(
    gen_kwh: float,
    base_smp_price: float,
    day_ahead_price: float,
    real_time_price: float,
    day_ahead_plan_ratio: float,
    real_time_plan_ratio: float,
    actual_gen_ratio: float,
    ess_charge_ratio: float,
    capacity_reward_unit: float,
    available_capacity_ratio: float,
    recognized_capacity_ratio: float,
    curtail_spread: float,
    dispatch_spread: float,
    tolerance_ratio: float,
    penalty_factor: float,
    energy_mult: float,
    penalty_mult: float,
) -> dict:
    """
    정산규칙 근사 모드.
    실제 15분 정산자료가 없다는 전제에서 연간 발전량을 기준으로 근사한다.

    중요한 수정:
    - MEP 비교 기준은 기존 총 판매단가가 아니다.
    - 기존 SMP 상당 수익과만 비교한다.
    - REC 상당 수익은 사업주가 별도 유지하는 수익으로 본다.
    """
    day_ahead_plan = gen_kwh * day_ahead_plan_ratio
    real_time_plan = gen_kwh * real_time_plan_ratio
    actual_gen = gen_kwh * actual_gen_ratio
    ess_charge = gen_kwh * ess_charge_ratio
    available_capacity = gen_kwh * available_capacity_ratio
    recognized_capacity = gen_kwh * recognized_capacity_ratio

    # 1) 전력거래 정산효과(MEP)
    # 하루전 계획량은 하루전 가격, 하루전 계획과 실제 차이는 실시간 가격으로 근사 정산
    market_energy_payment = day_ahead_price * day_ahead_plan + real_time_price * (actual_gen - day_ahead_plan)
    old_smp_revenue = base_smp_price * actual_gen
    raw_energy_increment = market_energy_payment - old_smp_revenue
    energy_increment = apply_energy_skill(raw_energy_increment, energy_mult)

    # 2) 시장참여 용량보상(CP)
    cp_basis_quantity = min(available_capacity, actual_gen, real_time_plan, recognized_capacity)
    capacity_reward = capacity_reward_unit * cp_basis_quantity

    # 3) 출력제어 보상 기대효과(MAP)
    # 실제로 발전할 수 있었지만 급전지시/출력제어로 줄어든 물량을 근사
    curtail_quantity = max(day_ahead_plan - max(actual_gen, real_time_plan) - ess_charge, 0)
    curtail_reward = max((real_time_price + curtail_spread) * curtail_quantity, 0)

    # 4) 급전지시 비용보전 효과(MWP)
    dispatch_quantity = max(day_ahead_plan - actual_gen, 0)
    dispatch_reward = max(dispatch_spread * dispatch_quantity, 0)

    # 5) 예측오차 페널티(IMB)
    excess_error = max((actual_gen - real_time_plan) - (real_time_plan * tolerance_ratio), 0)
    forecast_penalty = -real_time_price * excess_error * penalty_factor * penalty_mult

    amounts = {
        "CP (Capacity Payment, 용량보상)": capacity_reward,
        "MEP (Market Energy Payment, 전력거래정산)": energy_increment,
        "MAP (Make-whole Additional Payment, 출력제어 보상)": curtail_reward,
        "MWP (Make-whole Payment, 급전지시 비용보전)": dispatch_reward,
        "IMB (Imbalance Penalty, 예측오차 페널티)": forecast_penalty,
    }
    units = {name: safe_div(amount, gen_kwh) for name, amount in amounts.items()}
    total = sum(amounts.values())

    detail = {
        "하루전 발전계획량(DAOS)": day_ahead_plan,
        "실시간 발전계획량(RTOS)": real_time_plan,
        "실제 발전량(MGO)": actual_gen,
        "ESS 충전량(MPE)": ess_charge,
        "공급가능량(RA)": available_capacity,
        "용량 인정량(ELCC/RPCF)": recognized_capacity,
        "CP 인정 기준물량": cp_basis_quantity,
        "출력제어 보상 대상물량": curtail_quantity,
        "급전지시 비용보전 대상물량": dispatch_quantity,
        "예측오차 초과물량": excess_error,
        "입찰시장 전력정산액": market_energy_payment,
        "기존 SMP 상당 수익": old_smp_revenue,
        "전력거래 원증분": raw_energy_increment,
    }

    return {
        "units": units,
        "amounts": amounts,
        "total_extra": total,
        "total_extra_unit": safe_div(total, gen_kwh),
        "detail": detail,
    }


def calc_payback_months(initial_cost: float, monthly_extra: float):
    if monthly_extra <= 0:
        return None
    return initial_cost / monthly_extra


def calc_cashflow(
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
    extra_calc_func,
) -> pd.DataFrame:
    rows = []
    remaining_cost = initial_cost
    cumulative_extra_owner = 0.0
    cumulative_total_owner = 0.0

    for year in range(1, years + 1):
        gen = annual_generation(cap_mw, gen_time, degradation, year)

        old_smp_revenue = gen * base_smp_price
        rec_revenue = gen * rec_price
        old_total_revenue = gen * total_price

        result = extra_calc_func(gen)
        gross_extra = result["total_extra"]

        if gross_extra > 0:
            repayment = min(remaining_cost, gross_extra) if remaining_cost > 0 else 0.0
            remaining_cost -= repayment
            fee_base = max(gross_extra - repayment, 0.0)
            fee = fee_base * fee_rate
            owner_extra = gross_extra - repayment - fee
        else:
            repayment = 0.0
            fee = 0.0
            owner_extra = gross_extra

        om_cost = om_year1 * ((1 + om_escalation) ** (year - 1))
        after_vpp_before_om = old_total_revenue + owner_extra
        after_vpp_after_om = after_vpp_before_om - om_cost

        cumulative_extra_owner += owner_extra
        cumulative_total_owner += after_vpp_after_om

        rows.append({
            "연차": year,
            "발전량(kWh)": gen,
            "기존 SMP 상당 수익(원)": old_smp_revenue,
            "REC 상당 수익(원)": rec_revenue,
            "기존 총수익(원)": old_total_revenue,
            "VPP 정산효과 발생액(원)": gross_extra,
            "구축비 상환액(원)": repayment,
            "수수료(원)": fee,
            "사업주 추가수령액(원)": owner_extra,
            "O&M 비용(원)": om_cost,
            "VPP 참여 후 사업주 총수령액(원)": after_vpp_after_om,
            "누적 추가수령액(원)": cumulative_extra_owner,
            "누적 총수령액(원)": cumulative_total_owner,
            "잔여 상환액(원)": remaining_cost,
            "VPP 정산효과 단가(원/kWh)": safe_div(gross_extra, gen),
        })

    return pd.DataFrame(rows)


# ---------------------------------------------------------
# 사이드바 입력
# ---------------------------------------------------------
with st.sidebar:
    st.header("1. 계산 방식")
    selected_region = st.selectbox("지역 선택", list(REGION_CONFIG.keys()))
    calc_method = st.radio("계산 모드", CALC_METHODS, index=0)
    view_mode = st.radio("화면 모드", VIEW_MODES, index=0, horizontal=True)
    scenario = st.selectbox("수익 시나리오", list(SCENARIOS.keys()), index=1)

    conf = REGION_CONFIG[selected_region]

    st.header("2. 발전소 정보")
    cap_mw = st.number_input("설비 용량(MW)", min_value=0.01, value=1.0, step=0.1)
    gen_time = st.slider("하루 평균 발전시간", 2.0, 5.5, 3.6, 0.1)
    degradation_pct = st.number_input("연간 발전효율 감소율(%)", min_value=0.0, max_value=3.0, value=0.5, step=0.1)
    project_years = st.slider("분석 기간(년)", 1, 30, DEFAULT_PROJECT_YEARS)

    st.header("3. 기존 판매단가 분리")
    fixed_total_price = st.number_input(
        "기존 총 판매단가(SMP+REC, 원/kWh)",
        min_value=0.0,
        value=180.0,
        step=1.0,
        help="고정가격 계약 또는 현재 고객이 생각하는 전체 판매단가입니다. 보통 SMP와 REC가 합쳐진 값입니다.",
    )
    base_smp_price = st.number_input(
        "기존 SMP 상당 단가(원/kWh)",
        min_value=0.0,
        value=120.0,
        step=1.0,
        help="전력량 정산과 비교할 기준 단가입니다. MEP는 이 값과 비교해야 하며, REC까지 포함하면 안 됩니다.",
    )
    rec_price = max(fixed_total_price - base_smp_price, 0)
    if fixed_total_price < base_smp_price:
        st.warning("기존 SMP 상당 단가가 총 판매단가보다 큽니다. REC 상당 단가를 0으로 처리합니다.")
    st.caption(f"자동 계산된 REC 상당 단가: {rec_price:,.1f} 원/kWh")
    st.caption("REC 상당 수익은 사업주가 별도로 확보/판매하는 유지 수익으로 보고, MEP 비교에서는 제외합니다.")

    st.header("4. 입찰제도 수익효과")
    base_capacity_reward = apply_scenario(conf["capacity_reward"], "capacity_reward", scenario)
    base_energy_trade = apply_scenario(conf["energy_trade_effect"], "energy_trade_effect", scenario)
    base_curtail = apply_scenario(conf["curtail_reward"], "curtail_reward", scenario)
    base_dispatch = apply_scenario(conf["dispatch_reward"], "dispatch_reward", scenario)
    base_penalty = apply_scenario(conf["forecast_penalty"], "forecast_penalty", scenario)

    capacity_reward_unit = st.number_input("CP (Capacity Payment, 용량보상, 원/kWh)", value=float(base_capacity_reward), step=0.1)
    energy_trade_unit = st.number_input("MEP (Market Energy Payment, 전력거래정산, 원/kWh)", value=float(base_energy_trade), step=0.1)
    curtail_reward_unit = st.number_input("MAP (Make-whole Additional Payment, 출력제어 보상, 원/kWh)", value=float(base_curtail), step=0.1)
    dispatch_reward_unit = st.number_input("MWP (Make-whole Payment, 급전지시 비용보전, 원/kWh)", value=float(base_dispatch), step=0.1)
    forecast_penalty_unit = st.number_input("IMB (Imbalance Penalty, 예측오차 페널티, 원/kWh)", value=float(base_penalty), step=0.1)

    st.header("5. 운영 역량")
    operation_level = st.radio("VPP 운영 수준", list(OPERATION_LEVELS.keys()), index=2)
    op = OPERATION_LEVELS[operation_level]
    st.caption(op["desc"])

    st.header("6. 구축비와 수수료")
    initial_cost = st.number_input("초기 구축비(RTU+신자취 등, 원)", min_value=0, value=INITIAL_COST_DEFAULT, step=100_000)
    fee_rate_pct = st.slider("상환 완료 후 수수료율(%)", 0, 50, 20)
    om_year1 = st.number_input("연간 O&M/통신/관리비(원)", min_value=0, value=0, step=100_000)
    om_escalation_pct = st.number_input("O&M 상승률(%/년)", min_value=0.0, max_value=10.0, value=0.0, step=0.1)

    st.info("기본 가정: RTU 150만원 + 신자취 150만원 = 총 300만원. 해당 비용은 VPP 정산효과로 우선 상환합니다.")

    if calc_method == "정산규칙 근사 모드":
        st.header("7. 정산규칙 근사 입력")
        st.caption("초보자용: 기본값 그대로 두고 사용해도 됩니다. 내부 검토 시에만 조정하세요.")

        day_ahead_price = st.number_input("하루전 전력가격(DASMP, 원/kWh)", value=float(conf["day_ahead_price"]), step=1.0)
        real_time_price = st.number_input("실시간 전력가격(RTSMP, 원/kWh)", value=float(conf["real_time_price"]), step=1.0)
        day_ahead_plan_ratio = st.slider("하루전 발전계획량 비율(DAOS)", 0.0, 1.5, 0.95, 0.01)
        real_time_plan_ratio = st.slider("실시간 발전계획량 비율(RTOS)", 0.0, 1.5, 0.93, 0.01)
        actual_gen_ratio = st.slider("실제 발전량 비율(MGO)", 0.0, 1.5, 1.00, 0.01)
        ess_charge_ratio = st.slider("ESS 충전량 비율(MPE)", 0.0, 0.5, 0.00, 0.01)
        available_capacity_ratio = st.slider("공급가능량 비율(RA)", 0.0, 1.5, 0.95, 0.01)
        recognized_capacity_ratio = st.slider("용량 인정비율(ELCC/RPCF)", 0.0, 1.5, 0.75, 0.01)
        curtail_spread = st.number_input("출력제어 보상 추가단가(원/kWh)", value=0.0, step=0.1)
        dispatch_spread = st.number_input("급전지시 비용보전 단가(원/kWh)", value=max(dispatch_reward_unit, 0.0), step=0.1)
        tolerance_pct = st.number_input("예측오차 허용범위(%)", min_value=0.0, max_value=30.0, value=8.0, step=0.5)
        penalty_factor = st.number_input("예측오차 페널티 계수(IMPF)", min_value=0.0, value=1.0, step=0.1)
    else:
        day_ahead_price = conf["day_ahead_price"]
        real_time_price = conf["real_time_price"]
        day_ahead_plan_ratio = 0.95
        real_time_plan_ratio = 0.93
        actual_gen_ratio = 1.00
        ess_charge_ratio = 0.00
        available_capacity_ratio = 0.95
        recognized_capacity_ratio = 0.75
        curtail_spread = 0.0
        dispatch_spread = max(dispatch_reward_unit, 0.0)
        tolerance_pct = 8.0
        penalty_factor = 1.0

# ---------------------------------------------------------
# 핵심 계산
# ---------------------------------------------------------
deg = degradation_pct / 100
fee_rate = fee_rate_pct / 100
om_escalation = om_escalation_pct / 100

gen_year1 = annual_generation(cap_mw, gen_time, deg, 1)
old_smp_revenue_year1 = gen_year1 * base_smp_price
rec_revenue_year1 = gen_year1 * rec_price
old_total_revenue_year1 = gen_year1 * fixed_total_price


def extra_calc(gen_kwh: float) -> dict:
    if calc_method == "쉬운 계산 모드":
        return calc_easy_model(
            gen_kwh=gen_kwh,
            capacity_reward_unit=capacity_reward_unit,
            energy_trade_unit=energy_trade_unit,
            curtail_reward_unit=curtail_reward_unit,
            dispatch_reward_unit=dispatch_reward_unit,
            forecast_penalty_unit=forecast_penalty_unit,
            energy_mult=op["energy_mult"],
            penalty_mult=op["penalty_mult"],
        )
    return calc_rule_model(
        gen_kwh=gen_kwh,
        base_smp_price=base_smp_price,
        day_ahead_price=day_ahead_price,
        real_time_price=real_time_price,
        day_ahead_plan_ratio=day_ahead_plan_ratio,
        real_time_plan_ratio=real_time_plan_ratio,
        actual_gen_ratio=actual_gen_ratio,
        ess_charge_ratio=ess_charge_ratio,
        capacity_reward_unit=capacity_reward_unit,
        available_capacity_ratio=available_capacity_ratio,
        recognized_capacity_ratio=recognized_capacity_ratio,
        curtail_spread=curtail_spread,
        dispatch_spread=dispatch_spread,
        tolerance_ratio=tolerance_pct / 100,
        penalty_factor=penalty_factor,
        energy_mult=op["energy_mult"],
        penalty_mult=op["penalty_mult"],
    )


extra_year1 = extra_calc(gen_year1)
gross_extra_year1 = extra_year1["total_extra"]
gross_extra_unit_year1 = extra_year1["total_extra_unit"]
monthly_extra_year1 = gross_extra_year1 / 12
payback_months = calc_payback_months(initial_cost, monthly_extra_year1)

after_payback_extra_year1 = gross_extra_year1 * (1 - fee_rate)
after_payback_total_year1 = old_total_revenue_year1 + after_payback_extra_year1
final_price_after_fee = fixed_total_price + gross_extra_unit_year1 * (1 - fee_rate)

cashflow_df = calc_cashflow(
    years=project_years,
    cap_mw=cap_mw,
    gen_time=gen_time,
    degradation=deg,
    total_price=fixed_total_price,
    base_smp_price=base_smp_price,
    rec_price=rec_price,
    initial_cost=initial_cost,
    fee_rate=fee_rate,
    om_year1=om_year1,
    om_escalation=om_escalation,
    extra_calc_func=extra_calc,
)

# ---------------------------------------------------------
# PDF 보고서
# ---------------------------------------------------------
def make_pdf_report() -> bytes | None:
    if not os.path.exists(FONT_PATH):
        return None

    pdf = FPDF()
    pdf.add_font("NanumGothic", "", FONT_PATH)
    pdf.set_auto_page_break(auto=True, margin=14)
    pdf.add_page()

    pdf.set_fill_color(0, 32, 96)
    pdf.rect(0, 0, 210, 42, "F")
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("NanumGothic", size=18)
    pdf.ln(10)
    pdf.cell(190, 10, "V-GEN VPP 수익효과 계산 리포트", ln=True, align="C")
    pdf.set_font("NanumGothic", size=9)
    pdf.cell(190, 7, f"생성일: {datetime.now().strftime('%Y-%m-%d %H:%M')} / 계산 모드: {calc_method}", ln=True, align="C")

    pdf.set_text_color(0, 0, 0)
    pdf.ln(18)

    pdf.set_font("NanumGothic", size=14)
    pdf.cell(190, 9, "1. 핵심 결과", "B", ln=True)
    pdf.ln(4)
    pdf.set_font("NanumGothic", size=9)

    rows = [
        ("지역", selected_region),
        ("설비 용량", f"{cap_mw:,.2f} MW"),
        ("1년차 발전량", f"{gen_year1:,.0f} kWh"),
        ("기존 총 판매단가", fmt_unit(fixed_total_price)),
        ("기존 SMP 상당 단가", fmt_unit(base_smp_price)),
        ("REC 상당 단가", fmt_unit(rec_price)),
        ("기존 연간 총수익", fmt_manwon(old_total_revenue_year1)),
        ("VPP 정산효과 발생액", fmt_manwon(gross_extra_year1)),
        ("VPP 정산효과 단가", fmt_unit(gross_extra_unit_year1)),
        ("상환 완료 후 연간 추가수익", fmt_manwon(after_payback_extra_year1)),
        ("상환 완료 후 연간 총수익", fmt_manwon(after_payback_total_year1)),
        ("예상 상환기간", "상환 불가" if payback_months is None else f"약 {payback_months:.1f}개월"),
    ]

    pdf.set_fill_color(240, 245, 255)
    for i, (name, value) in enumerate(rows):
        fill = i % 2 == 0
        pdf.cell(72, 8, name, 1, 0, "C", fill)
        pdf.cell(118, 8, value, 1, 1, "R", fill)

    pdf.ln(6)
    pdf.set_font("NanumGothic", size=14)
    pdf.cell(190, 9, "2. 항목별 정산효과", "B", ln=True)
    pdf.ln(4)
    pdf.set_font("NanumGothic", size=9)
    pdf.set_fill_color(240, 245, 255)
    pdf.cell(82, 8, "항목", 1, 0, "C", True)
    pdf.cell(48, 8, "단가", 1, 0, "C", True)
    pdf.cell(60, 8, "연간 효과", 1, 1, "C", True)

    for name, amount in extra_year1["amounts"].items():
        unit = extra_year1["units"].get(name, 0)
        pdf.cell(82, 8, name, 1, 0, "C")
        pdf.cell(48, 8, fmt_unit(unit), 1, 0, "R")
        pdf.cell(60, 8, fmt_manwon(amount), 1, 1, "R")

    pdf.ln(6)
    pdf.set_font("NanumGothic", size=14)
    pdf.cell(190, 9, "3. 계산 전제", "B", ln=True)
    pdf.ln(4)
    pdf.set_font("NanumGothic", size=9)

    assumptions = [
        f"기존 총 판매단가는 SMP와 REC를 합친 단가로 입력했습니다: {fmt_unit(fixed_total_price)}",
        f"전력거래 추가효과(MEP)는 기존 총 판매단가가 아니라 기존 SMP 상당 단가와만 비교했습니다: {fmt_unit(base_smp_price)}",
        f"REC 상당 수익은 사업주가 별도로 확보/판매하는 유지 수익으로 보았습니다: {fmt_unit(rec_price)}",
        f"운영 수준: {operation_level} / 수익 시나리오: {scenario}",
        f"상환 완료 후 수수료율: {fee_rate_pct}%",
        f"초기 구축비: {initial_cost:,.0f}원",
        f"O&M/통신/관리비: 1년차 {om_year1:,.0f}원, 상승률 {om_escalation_pct:.2f}%/년",
    ]

    if calc_method == "정산규칙 근사 모드":
        assumptions.extend([
            f"하루전 전력가격(DASMP): {fmt_unit(day_ahead_price)}, 실시간 전력가격(RTSMP): {fmt_unit(real_time_price)}",
            f"하루전 계획량 비율: {day_ahead_plan_ratio:.2f}, 실시간 계획량 비율: {real_time_plan_ratio:.2f}, 실제 발전량 비율: {actual_gen_ratio:.2f}",
            f"용량 인정비율: {recognized_capacity_ratio:.2f}, 예측오차 허용범위: {tolerance_pct:.1f}%",
        ])

    for text in assumptions:
        pdf.multi_cell(190, 6, f"- {text}")

    pdf.ln(4)
    pdf.set_font("NanumGothic", size=8)
    pdf.set_text_color(80, 80, 80)
    notice = (
        "본 결과는 입력값과 시장가격, 출력제어, 계통운영, 예측오차, 급전지시, 제도 변경에 따라 달라질 수 있는 추정값입니다. "
        "실제 정산금은 전력거래소 정산 기준, 계량값, 입찰·낙찰 결과, 급전지시 이행 여부, 임밸런스 페널티 적용 여부에 따라 확정됩니다. "
        "육지 전역 재생에너지 입찰시장 확대 시행에 따라 기존 예측정산금 제도는 공식 일몰될 예정입니다."
    )
    pdf.multi_cell(190, 5, notice)

    return pdf_to_bytes(pdf)


# ---------------------------------------------------------
# 메인 화면
# ---------------------------------------------------------
st.title("V-GEN VPP 수익효과 계산기 v8.0")
st.caption("고정가격을 SMP와 REC로 분리하고, CP/MEP/MAP/MWP/IMB 정산효과를 계산합니다.")

if calc_method == "쉬운 계산 모드":
    st.info(
        "현재는 쉬운 계산 모드입니다. CP/MEP/MAP/MWP/IMB를 원/kWh 기준의 예상 효과로 넣고 빠르게 계산합니다. "
        "고객 상담, 1차 제안, 민감도 검토에 적합합니다."
    )
else:
    st.info(
        "현재는 정산규칙 근사 모드입니다. 하루전 가격, 실시간 가격, 발전계획량, 실제 발전량, 예측오차를 넣어 더 제도에 가깝게 계산합니다. "
        "단, 실제 15분 정산자료가 아니므로 최종 정산값은 아닙니다."
    )

if gross_extra_year1 <= 0:
    st.error("현재 입력값 기준 VPP 정산효과가 0 이하입니다. 상환이 불가능하거나 사업주 수익이 감소할 수 있습니다.")

# KPI
m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("기존 연간 총수익", fmt_manwon(old_total_revenue_year1))
m2.metric("기존 SMP 수익", fmt_manwon(old_smp_revenue_year1), fmt_unit(base_smp_price))
m3.metric("REC 별도 수익", fmt_manwon(rec_revenue_year1), fmt_unit(rec_price))
m4.metric("VPP 정산효과", fmt_manwon(gross_extra_year1), fmt_unit(gross_extra_unit_year1))
if payback_months is None:
    m5.metric("예상 상환기간", "상환 불가", "추가수익 부족")
else:
    m5.metric("예상 상환기간", f"약 {payback_months:.1f}개월", f"구축비 {initial_cost/10_000:,.0f}만원")

m6, m7, m8 = st.columns(3)
m6.metric("상환 중 사업주 수령", fmt_manwon(old_total_revenue_year1), "기존 수익 유지 / VPP 효과는 구축비 상환")
m7.metric("상환 후 연간 추가수익", fmt_manwon(after_payback_extra_year1), f"수수료 {fee_rate_pct}% 차감")
m8.metric("상환 후 연간 총수익", fmt_manwon(after_payback_total_year1), fmt_unit(final_price_after_fee))

st.divider()

# 쉬운 설명 박스
st.subheader("계산 구조 쉽게 보기")
st.markdown(
    f"""
1. 기존 총 판매단가 **{fixed_total_price:,.1f}원/kWh**를 두 부분으로 나눕니다.  
   - 기존 SMP 상당 단가: **{base_smp_price:,.1f}원/kWh**  
   - REC 상당 단가: **{rec_price:,.1f}원/kWh**  

2. 입찰제도의 전력거래 추가효과(MEP)는 **기존 총 판매단가와 비교하지 않고, 기존 SMP 상당 단가와만 비교**합니다.  

3. REC 상당 수익은 사업주가 별도로 확보/판매하는 수익으로 보고, VPP 참여 전후 모두 유지되는 수익으로 계산합니다.  

4. VPP 정산효과는 아래 항목을 합산합니다.  
   - CP (Capacity Payment, 용량보상)  
   - MEP (Market Energy Payment, 전력거래정산)  
   - MAP (Make-whole Additional Payment, 출력제어 보상)  
   - MWP (Make-whole Payment, 급전지시 비용보전)  
   - IMB (Imbalance Penalty, 예측오차 페널티)  
"""
)

st.divider()

# 항목별 그래프
c1, c2 = st.columns([1.35, 1])

with c1:
    st.subheader("항목별 VPP 정산효과")
    names = list(extra_year1["amounts"].keys())
    values = [won_to_manwon(v) for v in extra_year1["amounts"].values()]

    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=names,
            y=values,
            text=[f"{v:,.0f}만원" for v in values],
            textposition="outside",
            name="연간 효과",
        )
    )
    fig.update_layout(
        height=430,
        yaxis_title="만원/년",
        xaxis_title="항목",
        margin=dict(l=20, r=20, t=30, b=90),
    )
    st.plotly_chart(fig, use_container_width=True)

with c2:
    st.subheader("선택 조건")
    with st.expander("운영 수준", expanded=True):
        st.write(f"**현재 선택:** {operation_level}")
        st.write(f"- 전력거래 개선계수: **{op['energy_mult']}배**")
        st.write(f"- 예측오차 페널티 계수: **{op['penalty_mult']}배**")
        st.caption(op["desc"])

    with st.expander("선수익 상환 구조", expanded=True):
        if payback_months is None:
            st.error("VPP 정산효과가 부족하여 선수익 상환이 어렵습니다.")
        else:
            st.success(f"예상 상환기간: 약 {payback_months:.1f}개월")
        st.write(f"- 월평균 VPP 정산효과 발생액: {won_to_manwon(monthly_extra_year1):,.1f} 만원")
        st.write("- 상환 중: 기존 수익은 사업주 유지")
        st.write("- VPP 정산효과: 초기 구축비 상환에 우선 사용")
        st.write("- 상환 완료 후: 수수료 차감 후 사업주 수령")

    if calc_method == "정산규칙 근사 모드" and view_mode == "내부용":
        with st.expander("정산규칙 근사 상세값", expanded=False):
            detail_df = pd.DataFrame([
                {"항목": k, "값": v} for k, v in extra_year1["detail"].items()
            ])
            st.dataframe(detail_df, use_container_width=True, hide_index=True)

st.divider()

# 단가 변화 워터폴
st.subheader("기존 단가에서 VPP 참여 후 단가 변화")
fee_unit = -gross_extra_unit_year1 * fee_rate
waterfall_x = ["기존 총단가", "SMP 부분", "REC 부분"] + list(extra_year1["units"].keys()) + ["수수료", "상환 후 단가"]
waterfall_y = [0, base_smp_price, rec_price] + list(extra_year1["units"].values()) + [fee_unit, 0]
waterfall_measure = ["absolute"] + ["relative"] * (len(waterfall_x) - 2) + ["total"]
waterfall_text = [
    f"{fixed_total_price:.1f}",
    f"+{base_smp_price:.1f}",
    f"+{rec_price:.1f}",
    *[f"{v:+.2f}" for v in extra_year1["units"].values()],
    f"{fee_unit:.2f}",
    f"{final_price_after_fee:.2f}",
]

fig_wf = go.Figure(
    go.Waterfall(
        x=waterfall_x,
        y=waterfall_y,
        measure=waterfall_measure,
        text=waterfall_text,
        textposition="outside",
    )
)
fig_wf.update_layout(height=440, yaxis_title="원/kWh", margin=dict(l=20, r=20, t=30, b=100))
st.plotly_chart(fig_wf, use_container_width=True)

st.divider()

# 연차별 현금흐름
st.subheader("연차별 현금흐름")
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

# 고객용에서는 너무 복잡한 열은 숨김
if view_mode == "고객용":
    customer_cols = [
        "연차",
        "발전량(kWh)",
        "기존 총수익(만원)",
        "VPP 정산효과 발생액(만원)",
        "구축비 상환액(만원)",
        "수수료(만원)",
        "사업주 추가수령액(만원)",
        "VPP 참여 후 사업주 총수령액(만원)",
        "누적 추가수령액(만원)",
        "잔여 상환액(만원)",
    ]
    show_df = show_df[[c for c in customer_cols if c in show_df.columns]]

st.dataframe(show_df, use_container_width=True, hide_index=True)

fig_line = go.Figure()
fig_line.add_trace(
    go.Scatter(
        x=cashflow_df["연차"],
        y=cashflow_df["누적 추가수령액(원)"].apply(won_to_manwon),
        mode="lines+markers",
        name="누적 추가수령액",
    )
)
fig_line.add_trace(
    go.Scatter(
        x=cashflow_df["연차"],
        y=cashflow_df["잔여 상환액(원)"].apply(won_to_manwon),
        mode="lines+markers",
        name="잔여 상환액",
    )
)
fig_line.update_layout(height=390, yaxis_title="만원", xaxis_title="연차", margin=dict(l=20, r=20, t=30, b=40))
st.plotly_chart(fig_line, use_container_width=True)

st.divider()

# 안내 문구
st.subheader("전력시장 변화 안내")
st.warning(
    "육지 전역 재생에너지 입찰시장 확대 시행에 따라 기존 예측정산금 제도는 공식 일몰될 예정입니다. "
    "향후 재생에너지 수익은 단순 예측정산금보다 입찰, 실시간 대응, 예측오차 관리, 출력제어 대응 역량에 더 크게 좌우됩니다."
)

st.info(
    "본 계산 결과는 입력값과 시장가격, 출력제어, 계통운영, 예측오차, 급전지시, 제도 변경에 따라 달라질 수 있는 추정값입니다. "
    "실제 정산금은 전력거래소 정산 기준, 계량값, 입찰·낙찰 결과, 급전지시 이행 여부, 임밸런스 페널티 적용 여부에 따라 확정됩니다. "
    "고객 제안 시에는 확정 수익이 아니라 입력 가정 기반 예상 수익효과로 안내하는 것을 권장합니다."
)

# 요약표
st.subheader("요약 비교")
summary_df = pd.DataFrame({
    "구분": [
        "1년차 발전량",
        "기존 총 판매단가",
        "기존 SMP 상당 단가",
        "REC 상당 단가",
        "기존 연간 총수익",
        "VPP 정산효과 발생액",
        "VPP 정산효과 단가",
        "상환 완료 후 연간 추가수익",
        "상환 완료 후 연간 총수익",
        "초기 구축비",
        "예상 상환기간",
    ],
    "값": [
        f"{gen_year1:,.0f} kWh",
        fmt_unit(fixed_total_price),
        fmt_unit(base_smp_price),
        fmt_unit(rec_price),
        fmt_manwon(old_total_revenue_year1),
        fmt_manwon(gross_extra_year1),
        fmt_unit(gross_extra_unit_year1),
        fmt_manwon(after_payback_extra_year1),
        fmt_manwon(after_payback_total_year1),
        fmt_won(initial_cost),
        "상환 불가" if payback_months is None else f"약 {payback_months:.1f}개월",
    ],
})
st.table(summary_df)

# PDF 다운로드
st.divider()
st.subheader("PDF 보고서 다운로드")
pdf_data = make_pdf_report()
if pdf_data is None:
    st.error("PDF 생성을 위해 app.py와 같은 폴더에 NanumGothic.ttf 파일을 넣어주세요. 파일명도 정확히 NanumGothic.ttf 여야 합니다.")
else:
    st.download_button(
        label="VPP 수익효과 계산 리포트 다운로드",
        data=pdf_data,
        file_name="VGEN_VPP_Profit_Report_v8.pdf",
        mime="application/pdf",
        use_container_width=True,
    )

# 내부 검증 정보
if view_mode == "내부용":
    st.divider()
    st.subheader("내부 검증 정보")

    detail_table = pd.DataFrame({
        "항목": list(extra_year1["units"].keys()),
        "단가(원/kWh)": list(extra_year1["units"].values()),
        "연간 효과(만원)": [won_to_manwon(v) for v in extra_year1["amounts"].values()],
    })
    st.dataframe(detail_table, use_container_width=True, hide_index=True)

    with st.expander("용어 설명", expanded=False):
        st.markdown(
            """
- **CP (Capacity Payment, 용량보상)**: 전력시장에 공급 가능한 자원으로 인정받는 데 따른 보상 효과입니다.
- **MEP (Market Energy Payment, 전력거래정산)**: 입찰시장 전력정산액이 기존 SMP 상당 수익보다 얼마나 유리하거나 불리한지 보는 항목입니다. REC는 비교에서 제외합니다.
- **MAP (Make-whole Additional Payment, 출력제어 보상)**: 발전할 수 있었지만 계통/급전지시로 줄인 물량에 대한 기대 보상 효과입니다.
- **MWP (Make-whole Payment, 급전지시 비용보전)**: 급전지시 때문에 발생할 수 있는 비용 또는 손실을 보전하는 효과입니다.
- **IMB (Imbalance Penalty, 예측오차 페널티)**: 발전계획과 실제 발전량 차이가 커질 때 발생할 수 있는 차감 항목입니다.
- **REC 상당 수익**: 사업주가 별도로 확보하거나 판매하는 수익으로 보며, MEP 비교 기준에 포함하지 않습니다.
            """
        )
