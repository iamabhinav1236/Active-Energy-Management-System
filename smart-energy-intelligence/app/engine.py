"""Transparent, deterministic multi-agent energy planning engine."""
from dataclasses import dataclass
from typing import Any

AGENTS = [
    {"id":"load", "name":"Load Agent", "focus":"Flexible appliance scheduling", "icon":"↗", "color":"blue"},
    {"id":"solar", "name":"Solar Agent", "focus":"Renewable generation utilization", "icon":"☀", "color":"amber"},
    {"id":"battery", "name":"Battery Agent", "focus":"State of charge and battery health", "icon":"▣", "color":"violet"},
    {"id":"price", "name":"Price Agent", "focus":"Tariff-aware grid purchasing", "icon":"₹", "color":"green"},
    {"id":"weather", "name":"Weather Agent", "focus":"Generation outlook and uncertainty", "icon":"☁", "color":"cyan"},
    {"id":"comfort", "name":"Comfort Agent", "focus":"Occupancy and comfort constraints", "icon":"♡", "color":"rose"},
]

DEFAULTS = {
    "site_name":"Active Home", "site_type":"Household", "tariff_peak":12.5, "tariff_offpeak":6.0,
    "base_load_kw":3.8, "solar_kw":4.2, "battery_capacity_kwh":10.0, "battery_soc":68,
    "comfort_min":22, "comfort_max":25, "occupancy":"Home after 18:00", "carbon_factor":0.72,
    "mode":"recommendation", "budget_inr":250
}

class EnergyEngine:
    def __init__(self):
        self.settings = DEFAULTS.copy()
        self.feedback_bias = 0.0
        self.current_reading = None

    def dashboard(self) -> dict[str, Any]:
        s=self.settings
        solar = round(s["solar_kw"] * 0.78, 2)
        load = round(s["base_load_kw"] + 0.9, 2)
        battery = round(s["battery_capacity_kwh"] * s["battery_soc"] / 100, 2)
        grid = round(max(0, load - solar), 2)
        cost = round(grid * s["tariff_peak"], 2)
        result={"site":s["site_name"],"site_type":s["site_type"],"load_kw":load,"solar_kw":solar,
                "grid_kw":grid,"battery_kwh":battery,"battery_soc":s["battery_soc"],"cost_per_hour":cost,
                "peak_tariff":s["tariff_peak"],"offpeak_tariff":s["tariff_offpeak"],"comfort":"Within range",
                "mode":s["mode"],"carbon_kg_hour":round(grid*s["carbon_factor"],2),
                "solar_share_pct":round(min(100,solar/max(load,0.1)*100)),"budget_inr":s["budget_inr"]}
        if self.current_reading:
            result.update(self.current_reading)
            result["battery_kwh"]=round(s["battery_capacity_kwh"]*s["battery_soc"]/100,2)
            result["battery_soc"]=s["battery_soc"]
        return result

    def plan(self, overrides: dict | None = None) -> dict[str, Any]:
        s=self.settings.copy()
        if overrides: s.update(overrides)
        # Agent proposals are explicit, inspectable heuristics rather than a black-box claim.
        price_spread=max(0,s["tariff_peak"]-s["tariff_offpeak"])
        solar_surplus=max(0,s["solar_kw"]*0.78-s["base_load_kw"])
        charge_kwh=min(s["battery_capacity_kwh"]*(100-s["battery_soc"])/100, solar_surplus*1.5)
        discharge_kwh=min(s["battery_capacity_kwh"]*s["battery_soc"]/100*0.25, max(0,s["base_load_kw"]-s["solar_kw"]*0.45))
        shiftable_kw=round(min(1.4,max(0.3,s["base_load_kw"]*0.28)) * (1 + self.feedback_bias),2) if price_spread >= 2 else round(0.3 * (1 + self.feedback_bias),2)
        use_solar=s["solar_kw"]>0.5
        actions=[]; conflicts=[]
        if use_solar:
            actions.append({"id":"solar-first","title":"Prioritize on-site solar","detail":"Serve current demand from available solar before importing from the grid.","status":"proposed","agent":"Solar Agent","impact":"Higher renewable self-consumption"})
        if s["battery_soc"] < 90 and charge_kwh > 0.2:
            actions.append({"id":"charge","title":"Charge battery from solar surplus","detail":f"Reserve up to {charge_kwh:.1f} kWh of estimated surplus for storage; do not charge above 95% state of charge.","status":"proposed","agent":"Battery Agent","impact":"Stores renewable energy for later use"})
        if price_spread >= 3:
            actions.append({"id":"shift-load","title":"Move flexible loads to off-peak","detail":f"Shift about {shiftable_kw:.1f} kW of flexible tasks to the lower tariff window; keep essential and comfort loads unchanged.","status":"proposed","agent":"Price + Load Agents","impact":f"Potential tariff spread: ₹{price_spread:.2f}/kWh"})
        if s["battery_soc"] > 25 and s["tariff_peak"] > s["tariff_offpeak"]*1.5:
            actions.append({"id":"discharge","title":"Use battery during expensive peak hours","detail":f"Allow up to {discharge_kwh:.1f} kWh discharge while maintaining a 20% reserve.","status":"proposed","agent":"Battery + Price Agents","impact":"Reduces peak grid purchases"})
        actions.append({"id":"comfort","title":"Protect comfort and essential loads","detail":f"Keep indoor setpoint within {s['comfort_min']}–{s['comfort_max']}°C and do not shift essential loads.","status":"guardrail","agent":"Comfort Agent","impact":"Comfort constraints take priority over savings"})
        if s["battery_soc"] < 20:
            conflicts.append({"topic":"Battery reserve","proposal":"Price Agent requests peak discharge","counterproposal":"Battery Agent requests preserving reserve","resolution":"Discharge blocked; preserve a 20% minimum reserve."})
        if s["comfort_min"] >= s["comfort_max"]:
            conflicts.append({"topic":"Comfort bounds","proposal":"Load Agent requests HVAC scheduling","counterproposal":"Comfort Agent flags invalid range","resolution":"HVAC schedule is not recommended until comfort bounds are corrected."})
        baseline_grid=max(0,s["base_load_kw"]-s["solar_kw"]*0.65)
        baseline_cost=baseline_grid*s["tariff_peak"]
        planned_grid=max(0,baseline_grid-shiftable_kw*0.35-(discharge_kwh/2 if s["battery_soc"]>25 else 0))
        planned_cost=planned_grid*s["tariff_peak"]
        savings=max(0,baseline_cost-planned_cost)
        # Normalize objective scores; weights are visible to the UI.
        scores={"cost":round(min(1,0.55+price_spread/25),2),"comfort":0.95 if s["comfort_min"]<s["comfort_max"] else 0.2,
                "battery_health":0.9 if s["battery_soc"]>=20 else 0.45,"renewable":round(min(1,s["solar_kw"]/max(s["base_load_kw"],0.1)),2)}
        scores["cost"] = round(max(0, min(1, scores["cost"] + self.feedback_bias)), 2)
        return {"plan_id":None,"created_at":None,"status":"pending_approval","mode":s["mode"],"actions":actions,
                "negotiation":{"rounds":2,"agents":len(AGENTS),"consensus":True,"conflicts":conflicts,
                "summary":"The price and load agents favor shifting flexible demand; the solar and battery agents prioritize renewable capture while comfort and reserve rules remain hard constraints.",
                "objective_scores":scores,"weights":{"cost":0.35,"comfort":0.30,"battery_health":0.20,"renewable":0.15}},
                "estimated":{"baseline_cost_per_hour_inr":round(baseline_cost,2),"planned_cost_per_hour_inr":round(planned_cost,2),
                "savings_per_hour_inr":round(savings,2),"savings_pct":round(savings/max(baseline_cost,0.01)*100,1),
                "renewable_share_pct":round(min(100,s["solar_kw"]*0.78/max(s["base_load_kw"],0.1)*100)),"peak_reduction_kw":round(max(0,shiftable_kw*0.35),2)},
                "explanation":"Recommendations are based on the current tariff spread, estimated solar availability, flexible-load share, and battery state of charge. Savings are illustrative estimates, not guaranteed outcomes."}

    def agents_status(self):
        d=self.dashboard(); s=self.settings
        values={"load":f"{d['load_kw']} kW demand forecast","solar":f"{d['solar_kw']} kW estimated generation","battery":f"{d['battery_soc']}% state of charge","price":f"₹{s['tariff_peak']:.2f}/kWh peak tariff","weather":"Forecast confidence: 82% (simulated)","comfort":f"Target {s['comfort_min']}–{s['comfort_max']}°C"}
        return [{**a,"status":"active","observation":values[a['id']],"proposal":"Ready for negotiation"} for a in AGENTS]
